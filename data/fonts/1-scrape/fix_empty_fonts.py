"""
Fix rows in fonts_scraped.csv where font1, font2, and font3 are all blank.

Rows with at least one font already populated are left completely
unchanged. Only fully-blank rows are re-crawled and, if fonts are found,
overwritten in place in fonts_scraped.csv.

---------------------------------------------------------------------------
Why rows came up empty in the first place
---------------------------------------------------------------------------
The original scraper's parse_styles() only looked at top-level STYLE_RULE
objects in each stylesheet. Three common patterns fell through that:

  1. font-family declared inside an @media / @supports / @layer block
     (e.g. `@media (min-width: 768px) { body { font-family: ... } }`),
     which is extremely common for responsive typography. cssutils
     represents these as CSSMediaRule/CSSSupportsRule objects whose own
     .type is NOT STYLE_RULE - the nested rules were never visited.
  2. The `font` shorthand property (e.g. `font: 16px/1.5 Arial, sans-serif;`)
     instead of the longhand `font-family`. Only font-family was checked.
  3. Fonts declared in a stylesheet pulled in via `@import` inside CSS
     (as opposed to a <link rel="stylesheet"> tag in the HTML) - those
     were never fetched at all.

This script fixes all three, then re-crawls just the domains whose
previous result was fully blank.

Sites that are still blank after this (typically JS-rendered
single-page apps that inject styles via JavaScript rather than static
CSS) are a fundamentally different problem - a plain requests/BeautifulSoup
fetch never executes JavaScript, so no amount of CSS-parsing improvement
can recover fonts that only exist in the rendered DOM. Those rows are
left as-is and logged, since we shouldn't fabricate data for them.
---------------------------------------------------------------------------
"""

import csv
import logging
import os
import re
import socket
import traceback
from urllib.parse import urljoin

import certifi
import cssutils
import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

cssutils.log.setLevel(logging.CRITICAL)
socket.setdefaulttimeout(20)

LOG_FILE = "fix_empty_fonts.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

SCRAPED_CSV = "fonts_scraped.csv"
SAVE_EVERY = 20  # rows updated between incremental CSV saves

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

RETRY_CONNECT = 2
RETRY_READ = 1
RETRY_BACKOFF = 1.5
RETRY_STATUS_FORCELIST = (502, 503, 504)


def get_session():
    session = requests.Session()
    retry = Retry(
        total=RETRY_CONNECT + RETRY_READ,
        connect=RETRY_CONNECT,
        read=RETRY_READ,
        status_forcelist=RETRY_STATUS_FORCELIST,
        backoff_factor=RETRY_BACKOFF,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = get_session()
VERIFY = certifi.where()

GENERIC_VALUES = {"inherit", ""}
VAR_RE = re.compile(r"^var\(\s*(--[\w-]+)\s*(?:,\s*(.*))?\)$", re.IGNORECASE)
IMPORT_RE = re.compile(
    r'@import\s+(?:url\(\s*)?[\'"]?([^\'")\s;]+)[\'"]?\s*\)?[^;]*;', re.IGNORECASE
)
# Matches a CSS font-size token (unit-based or keyword), optionally followed
# by /line-height, then captures everything after it as the family list -
# used to pull the family portion out of the `font` shorthand property.
FONT_SIZE_RE = re.compile(
    r"(?:\d+(?:\.\d+)?(?:px|em|rem|%|pt|vw|vh|vmin|vmax)|"
    r"xx-small|x-small|small|medium|large|x-large|xx-large|larger|smaller)"
    r"(?:\s*/\s*[\w.%-]+)?\s+(.*)$",
    re.IGNORECASE,
)


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


def fetch_imports(css_text, base_url, seen_urls, max_imports=10):
    """Fetch stylesheets pulled in via @import inside a piece of CSS.

    One level deep only (imports-of-imports aren't followed), and capped
    at max_imports total per page to keep this bounded.
    """
    extra = []
    for m in IMPORT_RE.finditer(css_text):
        if len(seen_urls) >= max_imports:
            break
        href = m.group(1)
        import_url = urljoin(base_url, href)
        if import_url in seen_urls:
            continue
        seen_urls.add(import_url)
        try:
            resp = SESSION.get(import_url, headers=HEADERS, timeout=5, verify=VERIFY)
            if resp.status_code == 200:
                extra.append({"css_text": resp.text})
        except requests.RequestException:
            continue
    return extra


def get_all_styles(url):
    """Fetches all inline/external/internal/@import styles for a URL.

    Returns (styles, error). `error` is None on success (even if 0 styles
    were found), or a short string describing why the page couldn't be
    fetched/parsed at all.
    """
    try:
        response = SESSION.get(url, headers=HEADERS, timeout=10, verify=VERIFY)
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
                css_response = SESSION.get(
                    css_url, headers=HEADERS, timeout=5, verify=VERIFY
                )
                if css_response.status_code == 200:
                    all_css_rules.append({"css_text": css_response.text})
            except requests.RequestException:
                continue

        for element in soup.find_all(style=True):
            inline_css = element["style"]
            all_css_rules.append({"css_text": f"inline-element {{ {inline_css} }}"})

        # Follow @import statements inside whatever CSS we already have -
        # fonts declared only in an imported stylesheet were previously
        # never fetched at all.
        seen_urls = set()
        import_extra = []
        for style_source in list(all_css_rules):
            import_extra.extend(
                fetch_imports(style_source["css_text"], url, seen_urls)
            )
        all_css_rules.extend(import_extra)

    except Exception as e:
        return [], f"Parse error: {e}"

    return all_css_rules, None


def iter_style_rules(rules, depth=0):
    """Recursively yield STYLE_RULE objects, descending into @media,
    @supports, @layer, and any other rule type that nests child rules.
    This is the core fix: the original script only looked at top-level
    rules, so font-family/font declarations inside @media etc. were
    invisible to it.
    """
    if depth > 5:
        return
    for rule in rules:
        if rule.type == rule.STYLE_RULE:
            yield rule
        elif hasattr(rule, "cssRules"):
            yield from iter_style_rules(rule.cssRules, depth + 1)


def collect_css_variables(styles):
    """First pass: gather every --custom-property declaration on the page."""
    variables = {}
    for style_source in styles:
        try:
            sheet = cssutils.parseString(style_source["css_text"])
        except Exception:
            continue
        for rule in iter_style_rules(sheet):
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
        return None

    return normalize(value)


def extract_family_from_font_shorthand(value):
    """Pull the family-list portion out of a `font:` shorthand value,
    e.g. 'italic bold 16px/1.4 "Helvetica Neue", Arial' -> '"Helvetica Neue", Arial'.
    Returns None if no size token (and therefore no reliable family
    boundary) is found.
    """
    m = FONT_SIZE_RE.search(value)
    if m:
        return m.group(1).strip()
    return None


def parse_styles(styles):
    """Parses raw CSS text for font-family (and font shorthand) declarations."""
    variables = collect_css_variables(styles)
    fonts = {}

    for style_source in styles:
        try:
            sheet = cssutils.parseString(style_source["css_text"])
        except Exception:
            continue
        for rule in iter_style_rules(sheet):
            for prop in rule.style:
                raw_value = None
                if prop.name == "font-family":
                    raw_value = prop.value.strip()
                elif prop.name == "font":
                    raw_value = extract_family_from_font_shorthand(prop.value.strip())

                if not raw_value:
                    continue

                try:
                    primary_raw = split_top_level(raw_value)[0]
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


def is_blank_row(row):
    return not (row.get("font1") or row.get("font2") or row.get("font3"))


def main():
    if not os.path.exists(SCRAPED_CSV):
        raise SystemExit(f"{SCRAPED_CSV} not found in the current directory.")

    # dtype=str + keep_default_na=False so blank cells read back as "" and
    # not NaN/float, and so nothing gets silently type-coerced.
    df = pd.read_csv(SCRAPED_CSV, dtype=str, keep_default_na=False)
    for col in ("font1", "font2", "font3"):
        if col not in df.columns:
            df[col] = ""

    blank_mask = df.apply(is_blank_row, axis=1)
    blank_indices = df.index[blank_mask].tolist()
    logger.info(
        "%d of %d rows have all fonts blank; re-crawling those",
        len(blank_indices), len(df),
    )

    updated = 0
    still_blank = 0

    try:
        for i, idx in enumerate(blank_indices, start=1):
            domain = str(df.at[idx, "domain"]).strip()
            if not domain:
                continue

            try:
                url = "https://" + domain
                styles, error = get_all_styles(url)

                if error is not None:
                    logger.info("Still failing for %s: %s", domain, error)
                    still_blank += 1
                    continue

                fonts = parse_styles(styles)
                font1, font2, font3 = top_n_fonts(fonts, 3)

                if not any([font1, font2, font3]):
                    logger.info(
                        "No fonts found for %s even with the improved parser "
                        "(likely JS-rendered styles)", domain,
                    )
                    still_blank += 1
                    continue

                df.at[idx, "font1"] = font1
                df.at[idx, "font2"] = font2
                df.at[idx, "font3"] = font3
                updated += 1
                logger.info(
                    "Fixed %s -> %s | %s | %s", domain, font1, font2, font3
                )

            except Exception:
                logger.error(
                    "Unhandled error re-crawling %s:\n%s",
                    domain, traceback.format_exc(),
                )
                still_blank += 1
                continue

            if updated and updated % SAVE_EVERY == 0:
                df.to_csv(SCRAPED_CSV, index=False, quoting=csv.QUOTE_MINIMAL)
                logger.info("Progress saved (%d updated so far)", updated)
    finally:
        df.to_csv(SCRAPED_CSV, index=False, quoting=csv.QUOTE_MINIMAL)
        logger.info(
            "Done. Fixed %d rows, %d still blank (likely JS-rendered sites), "
            "out of %d originally blank.",
            updated, still_blank, len(blank_indices),
        )
        print(
            f"Fixed {updated} rows. {still_blank} remain blank "
            f"(see {LOG_FILE} for details - these are likely JS-rendered "
            f"sites that no static-HTML scraper can recover fonts from)."
        )


if __name__ == "__main__":
    main()