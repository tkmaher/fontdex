"""
Crawl a list of domains, extract the fonts actually declared in their CSS,
and split the results into two output CSVs:

  fonts_scraped.csv        -> domain,category,font1,font2,font3
                               (top 3 most-used, non-generic fonts)
  fonts_scraped_error.csv  -> domain,category,error
                               (sites that couldn't be crawled, so they can
                                be retried later)

Input CSV (CLASSIFIED_CSV) must have columns: domain,category

Both output CSVs are written to incrementally, row by row, as each domain
finishes crawling (rather than all at once at the end), so progress is
never lost. On restart, any domain that already has a row in either
output CSV (success or error) is skipped rather than re-crawled - delete
or edit fonts_scraped_error.csv first if you want those specifically
retried.

Every stage that can fail on a single, unpredictable real-world site
(network errors, malformed HTML, malformed/unparseable CSS, blank or
NaN CSV rows) is caught per-domain, logged to scrape_fonts.log, and
recorded as an error row rather than being allowed to crash the whole
run. That log file is the first place to check if the script appears to
"stop" - it will show the domain and traceback for whatever actually
happened.

---------------------------------------------------------------------------
Heuristic for CSS custom-property ("CSS variable") fonts
---------------------------------------------------------------------------
Modern sites frequently set font-family via a variable, e.g.:

    :root { --ds-body-m-font-family: "Segoe UI", sans-serif; }
    p { font-family: var(--ds-body-m-font-family); }

If we naively record the string "var(--ds-body-m-font-family)" as a font,
it pollutes the counts with meaningless variable names instead of the
actual font. The heuristic used here:

  1. Do a first pass over every stylesheet/style block and collect every
     custom property declaration (any property whose name starts with
     "--") into a dict of {var_name: raw_value}. This is scoped to the
     whole page (not just :root), which is a reasonable approximation
     since most sites only ever define these in :root or a small set of
     theme classes, and colliding names are rare.
  2. When a font-family value is (or starts with) var(--name[, fallback]),
     look up --name in that dict and recursively resolve it (a variable's
     value can itself be another var(...) reference, so resolution is
     recursive with a depth cap to avoid infinite loops).
  3. If the variable is defined, use its resolved value. If it is *not*
     defined anywhere on the page (e.g. it comes from a design-system
     stylesheet we didn't fetch, or is set via JS), fall back to the
     explicit fallback value inside the var() call, if one was given
     (var(--foo, Arial) -> "Arial"). If there is no fallback either, the
     declaration is skipped entirely rather than counted as a fake font
     named "var(--foo)".
  4. As with normal font stacks, only the first font in a comma-separated
     list is taken as "the" font for that rule (matches original script's
     behavior), using a parenthesis-aware comma split so we don't break
     apart var(--foo, a, b) style fallbacks.

The only value dropped outright is "inherit" (it doesn't name a font at
all, just "use whatever the parent has"). Generic system-font keywords
like sans-serif, serif, monospace, system-ui, etc. are kept and counted
normally, since a site genuinely relying on system fonts should show up
as such rather than being scrubbed from the results. Font names are
normalized (quotes/whitespace stripped) so '"SF Pro Text"' and
'SF Pro Text' count as the same font.
"""

import csv
import logging
import os
import re
import socket
import traceback
from urllib.parse import urljoin

import cssutils
import pandas as pd
import requests
from bs4 import BeautifulSoup

cssutils.log.setLevel(logging.CRITICAL)

# Belt-and-suspenders against sockets that hang past requests' own timeout
# (e.g. a stalled DNS lookup or TLS handshake on some malformed servers).
socket.setdefaulttimeout(20)

LOG_FILE = "scrape_fonts.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

CLASSIFIED_CSV = "classified.csv"
OUTPUT_CSV = "fonts_scraped.csv"
ERROR_CSV = "fonts_scraped_error.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# "inherit" doesn't name a font at all, so it's the one value dropped
# outright. System-font keywords (sans-serif, monospace, system-ui, ...)
# are intentionally NOT filtered here - a site that relies on the system
# font stack should be recorded as such rather than skipped.
GENERIC_VALUES = {
    "inherit",
    "",
}

VAR_RE = re.compile(r"^var\(\s*(--[\w-]+)\s*(?:,\s*(.*))?\)$", re.IGNORECASE)


def split_top_level(value):
    """Split a comma-separated CSS value list, ignoring commas inside parens."""
    parts = []
    current = ""
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def normalize(name):
    return name.strip().strip("'\"").strip()


def get_all_styles(url):
    """Fetches all inline/external/internal styles for a URL.

    Returns (styles, error). `error` is None on success (even if 0 styles
    were found), or a short string describing why the page couldn't be
    fetched/parsed at all.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        return [], str(e)

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        all_css_rules = []

        for style_tag in soup.find_all("style"):
            if style_tag.string:
                all_css_rules.append({"css_text": style_tag.string})

        for link_tag in soup.find_all("link", rel="stylesheet"):
            href = link_tag.get("href")
            if not href:
                continue
            css_url = urljoin(url, href)
            try:
                css_response = requests.get(css_url, headers=HEADERS, timeout=5)
                if css_response.status_code == 200:
                    all_css_rules.append({"css_text": css_response.text})
            except requests.RequestException:
                # A single failed external stylesheet isn't fatal for the page.
                continue

        for element in soup.find_all(style=True):
            inline_css = element["style"]
            all_css_rules.append({"css_text": f"inline-element {{ {inline_css} }}"})
    except Exception as e:
        # Malformed HTML or an unexpected parser error shouldn't crash the
        # whole crawl - record it as an error for this domain instead.
        return [], f"Parse error: {e}"

    return all_css_rules, None


def collect_css_variables(styles):
    """First pass: gather every --custom-property declaration on the page."""
    variables = {}
    for style_source in styles:
        try:
            sheet = cssutils.parseString(style_source["css_text"])
        except Exception:
            # Malformed/unparseable CSS on one stylesheet shouldn't kill
            # the whole crawl - just skip variable collection for it.
            continue
        for rule in sheet:
            if rule.type == rule.STYLE_RULE:
                for prop in rule.style:
                    if prop.name.startswith("--"):
                        variables[prop.name] = prop.value.strip()
    return variables


def resolve_font_value(value, variables, depth=0):
    """Resolve a single font-family token, following var() references."""
    if depth > 5:
        return None

    value = value.strip()
    match = VAR_RE.match(value)
    if match:
        var_name, fallback = match.group(1), match.group(2)
        if var_name in variables:
            resolved = variables[var_name]
            first = split_top_level(resolved)[0] if resolved else ""
            return resolve_font_value(first, variables, depth + 1)
        if fallback:
            first_fallback = split_top_level(fallback)[0]
            return resolve_font_value(first_fallback, variables, depth + 1)
        return None  # undefined variable, no fallback -> can't resolve

    return normalize(value)


def parse_styles(styles):
    """Parses raw CSS text for font-family declarations into counts."""
    variables = collect_css_variables(styles)
    fonts = {}

    for style_source in styles:
        try:
            sheet = cssutils.parseString(style_source["css_text"])
        except Exception:
            continue
        for rule in sheet:
            if rule.type == rule.STYLE_RULE:
                for prop in rule.style:
                    if prop.name != "font-family":
                        continue
                    try:
                        primary_raw = split_top_level(prop.value.strip())[0]
                        font = resolve_font_value(primary_raw, variables)
                    except Exception:
                        continue
                    if font is None:
                        continue
                    if font.lower() in GENERIC_VALUES:
                        continue
                    fonts[font] = fonts.get(font, 0) + 1

    return fonts


def top_n_fonts(fonts, n=3):
    ranked = sorted(fonts.items(), key=lambda kv: kv[1], reverse=True)
    top = [name for name, _ in ranked[:n]]
    while len(top) < n:
        top.append("")
    return top


def already_processed_domains(*csv_paths):
    """Domains that already have a row in any of the given CSVs.

    Used on restart so previously-crawled sites (success OR error) are
    skipped rather than re-crawled. If you specifically want to retry
    error sites, delete/clear fonts_scraped_error.csv before rerunning.
    """
    seen = set()
    for path in csv_paths:
        if not os.path.exists(path):
            continue
        try:
            existing = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        if "domain" in existing.columns:
            seen.update(existing["domain"].astype(str))
    return seen


def open_csv_writer(path, fieldnames):
    """Open a CSV for incremental appends, writing the header only if new."""
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
    if not file_exists:
        writer.writeheader()
        f.flush()
    return f, writer


def main():
    df = pd.read_csv(CLASSIFIED_CSV)

    done = already_processed_domains(OUTPUT_CSV, ERROR_CSV)
    logger.info("Loaded %d rows from %s; %d already processed", len(df), CLASSIFIED_CSV, len(done))

    scraped_file, scraped_writer = open_csv_writer(
        OUTPUT_CSV, ["domain", "category", "font1", "font2", "font3"]
    )
    error_file, error_writer = open_csv_writer(
        ERROR_CSV, ["domain", "category", "error"]
    )

    processed_count = 0

    try:
        for _, row in df.iterrows():
            domain = row.get("domain")
            category = row.get("category")

            if pd.isna(domain):
                continue
            domain = str(domain).strip()
            if not domain or domain in done:
                continue

            try:
                url = "https://" + domain
                styles, error = get_all_styles(url)

                if error is not None:
                    error_writer.writerow(
                        {"domain": domain, "category": category, "error": error}
                    )
                    error_file.flush()
                    os.fsync(error_file.fileno())
                else:
                    fonts = parse_styles(styles)
                    font1, font2, font3 = top_n_fonts(fonts, 3)
                    scraped_writer.writerow(
                        {
                            "domain": domain,
                            "category": category,
                            "font1": font1,
                            "font2": font2,
                            "font3": font3,
                        }
                    )
                    scraped_file.flush()
                    os.fsync(scraped_file.fileno())
            except Exception as e:
                # Catch-all: never let one bad domain kill a 10,000-site
                # run. Log the full traceback for debugging and record
                # the domain as an error row so it can be retried later.
                logger.error("Unhandled error on %s:\n%s", domain, traceback.format_exc())
                try:
                    error_writer.writerow(
                        {"domain": domain, "category": category, "error": f"Unhandled: {e}"}
                    )
                    error_file.flush()
                    os.fsync(error_file.fileno())
                except Exception:
                    logger.error("Failed to even write error row for %s", domain)

            done.add(domain)
            processed_count += 1
            if processed_count % 100 == 0:
                logger.info("Processed %d domains so far", processed_count)
    finally:
        scraped_file.close()
        error_file.close()
        logger.info("Run finished/stopped. Processed %d domains this run.", processed_count)


if __name__ == "__main__":
    main()