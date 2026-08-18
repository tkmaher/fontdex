"""
Single-domain worker for fix_js_rendered_fonts.py.

Launches its own headless browser, navigates to exactly one domain,
extracts fonts, prints a single line of JSON to stdout, and exits.
Deliberately a short-lived, one-shot process rather than part of a
long-lived loop: the driver script (fix_js_rendered_fonts.py) runs this
as a subprocess with a hard wall-clock timeout and force-kills the whole
process tree if it doesn't finish in time. That's the only reliable
defense against a domain that hangs past Playwright's own in-process
timeout (which can happen with certain network-level packet-drop
conditions that don't produce a clean connection error for Playwright to
catch and time out on cleanly).

Not meant to be run standalone for real use, but you can smoke-test it
directly:
    python font_worker.py adobe.com
"""

import json
import re
import sys
from urllib.parse import urljoin

import certifi
import cssutils
import logging
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

cssutils.log.setLevel(logging.CRITICAL)

PAGE_TIMEOUT_MS = 12000  # kept comfortably under the driver's hard kill timeout
POST_LOAD_SETTLE_MS = 1500
NAV_MAX_ATTEMPTS = 2
NAV_RETRY_BACKOFF = 1.0

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
TRANSIENT_NET_ERR_RE = re.compile(
    r"net::ERR_(HTTP2_PROTOCOL_ERROR|CONNECTION_RESET|CONNECTION_CLOSED|"
    r"NETWORK_CHANGED|TIMED_OUT|EMPTY_RESPONSE|SOCKET_NOT_CONNECTED|"
    r"QUIC_PROTOCOL_ERROR)"
)


def split_top_level(value):
    parts, current, depth = [], "", 0
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
            resp = SESSION.get(import_url, headers=HEADERS, timeout=6, verify=VERIFY)
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
    fonts = {}
    for priority, sel in enumerate(["body", "p", "h1", "h2", "a", "button"]):
        value = computed.get(sel)
        if not value:
            continue
        first = split_top_level(value)[0] if value else ""
        font = normalize(first)
        if not font or font.lower() in GENERIC_VALUES:
            continue
        weight = 6 - priority
        fonts[font] = fonts.get(font, 0) + weight
    return fonts


def top_n_fonts(fonts, n=3):
    ranked = sorted(fonts.items(), key=lambda kv: kv[1], reverse=True)
    top = [name for name, _ in ranked[:n]]
    while len(top) < n:
        top.append("")
    return top


def get_rendered_styles(context, url):
    page = context.new_page()
    page.set_default_timeout(PAGE_TIMEOUT_MS)
    page.on("dialog", lambda dialog: dialog.dismiss())

    try:
        goto_error = None
        for attempt in range(NAV_MAX_ATTEMPTS):
            try:
                page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="load")
                goto_error = None
                break
            except PWTimeoutError:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=4000)
                    goto_error = None
                except Exception as e:
                    goto_error = str(e)
                break
            except Exception as e:
                msg = str(e)
                if TRANSIENT_NET_ERR_RE.search(msg) and attempt < NAV_MAX_ATTEMPTS - 1:
                    import time
                    time.sleep(NAV_RETRY_BACKOFF * (attempt + 1))
                    continue
                goto_error = msg
                break

        if goto_error is not None:
            return [], None, goto_error

        if page.url.startswith("chrome-error:"):
            return [], None, f"Navigation failed (landed on {page.url})"

        page.wait_for_timeout(POST_LOAD_SETTLE_MS)

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
    finally:
        try:
            page.close()
        except Exception:
            pass

    styles = []
    for css_text in data["styleTags"]:
        if css_text.strip():
            styles.append({"css_text": css_text})
    for inline_css in data["inline"]:
        styles.append({"css_text": f"inline-element {{ {inline_css} }}"})
    for href in data["linkHrefs"]:
        css_url = urljoin(url, href)
        try:
            resp = SESSION.get(css_url, headers=HEADERS, timeout=6, verify=VERIFY)
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


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: font_worker.py <domain>"}))
        sys.exit(1)

    domain = sys.argv[1]
    result = {"domain": domain, "font1": "", "font2": "", "font3": "", "error": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-http2",
                ],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1366, "height": 900},
                accept_downloads=True,
            )
            try:
                styles, computed, error = get_rendered_styles(context, "https://" + domain)
                if error is not None:
                    result["error"] = error
                else:
                    fonts = parse_styles(styles)
                    if not fonts and computed:
                        fonts = top_fonts_from_computed(computed)
                    font1, font2, font3 = top_n_fonts(fonts, 3)
                    if not any([font1, font2, font3]):
                        result["error"] = "No fonts found even with a real browser"
                    else:
                        result["font1"], result["font2"], result["font3"] = font1, font2, font3
            finally:
                context.close()
                browser.close()
    except Exception as e:
        result["error"] = f"Worker crash: {e}"

    # Exactly one line of JSON on stdout - the driver parses the LAST
    # stdout line, so nothing else should print to stdout here.
    print(json.dumps(result))


if __name__ == "__main__":
    main()