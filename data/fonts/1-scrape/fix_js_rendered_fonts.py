"""
Second-pass fixer for fonts_scraped.csv rows that are STILL blank after
fix_empty_fonts.py. These are (almost always) JS-rendered sites: React/
Vue/etc. apps, CSS-in-JS libraries (styled-components, emotion, ...) that
inject <style> tags at runtime, or sites that load their CSS via a JS
chunk loader. requests + BeautifulSoup can never see any of that because
it never executes JavaScript - this script uses a real headless browser
via Playwright instead, so the page actually runs, and the DOM/
stylesheets we inspect afterward are the real, rendered ones.

Setup (run once):
    pip install playwright pandas requests certifi cssutils
    playwright install chromium

Usage:
    python fix_js_rendered_fonts.py

Behavior mirrors fix_empty_fonts.py: only rows in fonts_scraped.csv
where font1/font2/font3 are ALL still blank are touched; everything
else is left exactly as-is. Progress is saved incrementally, and a log
of what happened per-domain goes to fix_js_rendered_fonts.log.

Two extraction strategies, in order:
  1. Stylesheet-based (same parser as fix_empty_fonts.py): after the
     page has fully rendered, read every <style> tag's content (this
     now includes JS-injected style tags, since the DOM has actually
     been built), every <link rel=stylesheet> href, inline style=""
     attributes, and one level of @import - then run them through the
     same recursive @media/@supports-aware, var()-resolving CSS parser.
  2. Computed-style fallback: if #1 finds nothing (e.g. fonts are set
     via inline JS style manipulation with no discoverable stylesheet
     rule), ask the real browser what font it actually rendered body
     text, headings, paragraphs, links, and buttons in via
     getComputedStyle(). This is a weaker signal (the resolved/
     inherited font actually painted, not "a declared rule") but is
     far better than nothing for these harder sites.

Caveats:
  - This is much slower than the static scraper (a real page load per
    domain, ~5-20s each). 573 domains sequentially could take a few
    hours - consider splitting the blank rows into chunks and running
    several in parallel (separate processes, each with its own browser)
    if you want it faster.
  - Sites behind a JS bot-challenge (Cloudflare Turnstile, etc.) can
    still fail even with a real browser - those remain blank and are
    logged, same as before.
"""

import logging
import os
import re
import traceback
from urllib.parse import urljoin

import certifi
import cssutils
import pandas as pd
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

cssutils.log.setLevel(logging.CRITICAL)

LOG_FILE = "fix_js_rendered_fonts.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

SCRAPED_CSV = "fonts_scraped.csv"
SAVE_EVERY = 10
PAGE_TIMEOUT_MS = 25000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

SESSION = requests.Session()
VERIFY = certifi.where()

GENERIC_VALUES = {"inherit", ""}
VAR_RE = re.compile(r"^var\(\s*(--[\w-]+)\s*(?:,\s*(.*))?\)$", re.IGNORECASE)
IMPORT_RE = re.compile(
    r'@import\s+(?:url\(\s*)?[\'"]?([^\'")\s;]+)[\'"]?\s*\)?[^;]*;', re.IGNORECASE
)
FONT_SIZE_RE = re.compile(
    r"(?:\d+(?:\.\d+)?(?:px|em|rem|%|pt|vw|vh|vmin|vmax)|"
    r"xx-small|x-small|small|medium|large|x-large|xx-large|larger|smaller)"
    r"(?:\s*/\s*[\w.%-]+)?\s+(.*)$",
    re.IGNORECASE,
)


def split_top_level(value):
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
    extra = []
    for m in IMPORT_RE.finditer(css_text):
        if len(seen_urls) >= max_imports:
            break
        import_url = urljoin(base_url, m.group(1))
        if import_url in seen_urls:
            continue
        seen_urls.add(import_url)
        try:
            resp = SESSION.get(import_url, headers=HEADERS, timeout=8, verify=VERIFY)
            if resp.status_code == 200:
                extra.append({"css_text": resp.text})
        except requests.RequestException:
            continue
    return extra


def iter_style_rules(rules, depth=0):
    if depth > 5:
        return
    for rule in rules:
        if rule.type == rule.STYLE_RULE:
            yield rule
        elif hasattr(rule, "cssRules"):
            yield from iter_style_rules(rule.cssRules, depth + 1)


def collect_css_variables(styles):
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
    m = FONT_SIZE_RE.search(value)
    return m.group(1).strip() if m else None


def parse_styles(styles):
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
                if font is None or font.lower() in GENERIC_VALUES:
                    continue
                fonts[font] = fonts.get(font, 0) + 1
    return fonts


def top_fonts_from_computed(computed):
    """Fallback signal: what the browser actually painted, by selector."""
    fonts = {}
    for priority, sel in enumerate(["body", "p", "h1", "h2", "a", "button"]):
        value = computed.get(sel)
        if not value:
            continue
        first = split_top_level(value)[0] if value else ""
        font = normalize(first)
        if not font or font.lower() in GENERIC_VALUES:
            continue
        weight = 6 - priority  # body/p text weighted higher than nav/buttons
        fonts[font] = fonts.get(font, 0) + weight
    return fonts


def top_n_fonts(fonts, n=3):
    ranked = sorted(fonts.items(), key=lambda kv: kv[1], reverse=True)
    top = [name for name, _ in ranked[:n]]
    while len(top) < n:
        top.append("")
    return top


def get_rendered_styles(page, url):
    """Navigate with a real browser and pull styles from the fully
    rendered DOM. Returns (styles, computed_fonts, error)."""
    try:
        try:
            page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="networkidle")
        except PWTimeoutError:
            # networkidle never settles on some long-poll/websocket-heavy
            # sites - fall back to the plain load event instead of
            # failing the domain outright.
            page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="load")
    except Exception as e:
        return [], None, str(e)

    try:
        data = page.evaluate(
            """() => {
                const styleTags = Array.from(document.querySelectorAll('style'))
                    .map(s => s.textContent || '');
                const linkHrefs = Array.from(
                    document.querySelectorAll('link[rel="stylesheet"]')
                ).map(l => l.href).filter(Boolean);
                const inline = Array.from(document.querySelectorAll('[style]'))
                    .map(e => e.getAttribute('style'))
                    .filter(Boolean);
                const computed = {};
                for (const sel of ['body', 'h1', 'h2', 'p', 'a', 'button']) {
                    const el = document.querySelector(sel);
                    if (el) computed[sel] = getComputedStyle(el).fontFamily;
                }
                return {styleTags, linkHrefs, inline, computed};
            }"""
        )
    except Exception as e:
        return [], None, f"Evaluate error: {e}"

    styles = []
    for css_text in data["styleTags"]:
        if css_text.strip():
            styles.append({"css_text": css_text})
    for inline_css in data["inline"]:
        styles.append({"css_text": f"inline-element {{ {inline_css} }}"})
    for href in data["linkHrefs"]:
        css_url = urljoin(url, href)
        try:
            resp = SESSION.get(css_url, headers=HEADERS, timeout=8, verify=VERIFY)
            if resp.status_code == 200:
                styles.append({"css_text": resp.text})
        except requests.RequestException:
            continue

    seen_urls = set()
    import_extra = []
    for style_source in list(styles):
        import_extra.extend(fetch_imports(style_source["css_text"], url, seen_urls))
    styles.extend(import_extra)

    return styles, data["computed"], None


def is_blank_row(row):
    return not (row.get("font1") or row.get("font2") or row.get("font3"))


def main():
    if not os.path.exists(SCRAPED_CSV):
        raise SystemExit(f"{SCRAPED_CSV} not found in the current directory.")

    df = pd.read_csv(SCRAPED_CSV, dtype=str, keep_default_na=False)
    for col in ("font1", "font2", "font3"):
        if col not in df.columns:
            df[col] = ""

    blank_mask = df.apply(is_blank_row, axis=1)
    blank_indices = df.index[blank_mask].tolist()
    logger.info("%d rows still blank; retrying with a headless browser", len(blank_indices))

    updated = 0
    still_blank = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()

        try:
            for idx in blank_indices:
                domain = str(df.at[idx, "domain"]).strip()
                if not domain:
                    continue

                try:
                    url = "https://" + domain
                    styles, computed, error = get_rendered_styles(page, url)

                    if error is not None:
                        logger.info("Still failing for %s: %s", domain, error)
                        still_blank += 1
                        continue

                    fonts = parse_styles(styles)
                    if not fonts and computed:
                        fonts = top_fonts_from_computed(computed)

                    font1, font2, font3 = top_n_fonts(fonts, 3)
                    if not any([font1, font2, font3]):
                        logger.info("No fonts found for %s even with a real browser", domain)
                        still_blank += 1
                        continue

                    df.at[idx, "font1"] = font1
                    df.at[idx, "font2"] = font2
                    df.at[idx, "font3"] = font3
                    updated += 1
                    logger.info("Fixed %s -> %s | %s | %s", domain, font1, font2, font3)

                except Exception:
                    logger.error(
                        "Unhandled error re-crawling %s:\n%s", domain, traceback.format_exc()
                    )
                    still_blank += 1
                    continue

                if updated and updated % SAVE_EVERY == 0:
                    df.to_csv(SCRAPED_CSV, index=False)
                    logger.info("Progress saved (%d updated so far)", updated)
        finally:
            browser.close()
            df.to_csv(SCRAPED_CSV, index=False)
            logger.info(
                "Done. Fixed %d rows, %d still blank, out of %d retried.",
                updated, still_blank, len(blank_indices),
            )
            print(
                f"Fixed {updated} rows via headless browser. {still_blank} remain blank "
                f"(see {LOG_FILE} - likely bot-challenge-protected sites)."
            )


if __name__ == "__main__":
    main()