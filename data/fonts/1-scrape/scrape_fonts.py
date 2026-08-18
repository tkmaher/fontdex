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

Transient failures (DNS resolver hiccups, brief connect timeouts, and
502/503/504 responses) are retried a couple of times with backoff at the
transport layer before being recorded as an error - on a long crawl a
meaningful chunk of "errors" are really just the local network/resolver
hiccuping under sustained load against otherwise perfectly reachable
sites, and those should now resolve on retry rather than needing a
second full run. Genuinely broken sites (bot-blocking WAFs returning
403, sites with actually misconfigured/expired/self-signed certificates,
truly dead domains) will still end up in the error CSV, since those
aren't things a retry fixes.

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
import ssl
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

# Domains where the bare apex genuinely never serves a real page - it's
# not a network/TLS problem, there is no content to fetch. No retry ladder
# fixes this, so these are skipped immediately rather than wasting a
# request + timeout on every single crawl attempt:
#   - CDN/infra roots: real content lives at random-id.cloudfront.net etc,
#     never at the bare "cloudfront.net" apex itself.
#   - URL shorteners / redirect-only domains: they 400 on a bare request
#     because they require a specific short-code path to route anywhere.
#   - Hosting-platform roots (wixsite.com, etc): real sites live at
#     <user>.wixsite.com, the bare root has nothing.
#   - iframe-embed-only domains (youtube-nocookie.com): used as an iframe
#     src for specific video paths, no general front page at the apex.
# This list is inherently incomplete - add to it as you spot more
# obviously-infrastructure domains showing up in the error CSV.
SKIP_DOMAIN_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^(www\.)?(cloudfront\.net|amazonaws\.com|googleusercontent\.com"
        r"|akamaized\.net|akamaihd\.net|fastly\.net|azureedge\.net"
        r"|edgekey\.net|edgesuite\.net|cloudflare\.net|herokuapp\.com)$",
        r"^(www\.)?(goo\.gl|forms\.gle|maps\.app\.goo\.gl|bit\.ly"
        r"|tinyurl\.com|t\.co|is\.gd|buff\.ly|ow\.ly|lnks\.gd|cvent\.me"
        r"|subscribepage\.io|b23\.tv|rebrand\.ly|cutt\.ly)$",
        r"^(www\.)?wixsite\.com$",
        r"^(www\.)?youtube-nocookie\.com$",
    ]
]


def skip_reason(domain):
    """Returns a reason string if `domain` should be skipped without ever
    attempting a request, or None if it should be crawled normally."""
    for pattern in SKIP_DOMAIN_PATTERNS:
        if pattern.match(domain):
            return f"Skipped: known non-content/infrastructure domain ({domain})"
    return None

# A realistic browser header set. The bare User-Agent-only header set from
# the original script is itself a bot-detection signal for many WAFs
# (Cloudflare/Akamai etc.) - a fuller, ordinary-browser-shaped header set
# clears some of those checks, though JS-challenge-based WAFs can't be
# beaten by plain `requests` regardless of headers.
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

# Transient network hiccups (DNS resolver hiccups, brief connect timeouts,
# 502/503/504/429) are retried automatically at the transport layer before
# being counted as a real error - see the DNS-resolution-failure note in
# already_processed_domains/get_session below. 429 is included because
# requests/urllib3 honors a Retry-After header when present, so a genuine
# rate limit gets a proper backoff instead of an immediate permanent error.
RETRY_CONNECT = 2
RETRY_READ = 1
RETRY_BACKOFF = 1.5
RETRY_STATUS_FORCELIST = (429, 502, 503, 504)

# A hard cap on redirect hops. Without this, a misbehaving server/proxy that
# rewrites the Location header incorrectly on each hop (seen in practice:
# a URL that re-appended "www.lyon.fr" onto itself on every redirect until
# it was tens of thousands of characters long before finally erroring) can
# waste a huge amount of time and memory on a single domain before the
# default 30-redirect ceiling kicks in.
MAX_REDIRECTS = 5


def get_session():
    """A requests Session that retries transient connect/DNS/5xx/429 failures."""
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    retry = Retry(
        total=RETRY_CONNECT + RETRY_READ,
        connect=RETRY_CONNECT,
        read=RETRY_READ,
        status_forcelist=RETRY_STATUS_FORCELIST,
        backoff_factor=RETRY_BACKOFF,
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = get_session()

# Use certifi's CA bundle explicitly rather than whatever the system/venv
# happens to have. "unable to get local issuer certificate" errors against
# otherwise-unrelated, legitimate sites are almost always a stale/missing
# local CA bundle rather than a real problem with those sites - pinning to
# certifi (and keeping the `certifi` package updated: `pip install -U
# certifi`) clears most of those.
VERIFY = certifi.where()


class LegacyTLSAdapter(HTTPAdapter):
    """An adapter that relaxes TLS negotiation for old/misconfigured servers.

    A meaningful slice of SSL errors on a large, real-world domain list
    aren't "the site is broken" - they're OpenSSL 3.x's stricter defaults
    (SECLEVEL 2, no legacy renegotiation) refusing to talk to older servers
    that still work fine in a normal browser. This is common on smaller
    enterprise/government/legacy sites. This adapter lowers the security
    level and allows legacy renegotiation, while still validating the
    certificate against the same certifi bundle - it relaxes *cryptographic
    compatibility*, not certificate trust.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context(cafile=VERIFY)
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def get_legacy_session():
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    retry = Retry(
        total=RETRY_CONNECT + RETRY_READ,
        connect=RETRY_CONNECT,
        read=RETRY_READ,
        status_forcelist=RETRY_STATUS_FORCELIST,
        backoff_factor=RETRY_BACKOFF,
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = LegacyTLSAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


LEGACY_SESSION = get_legacy_session()

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


def fetch_root_page(domain):
    """Fetch a domain's root page, trying a couple of cheap fallbacks.

    Returns (response, final_url, error). error is None on success.

    Fallback ladder:
      1. https://<domain> on the normal session.
      2. If that failed with a connection-level error (DNS/connect
         timeout/refused - NOT an HTTP error like 403/404, and NOT an SSL
         error, which is handled separately below): retry once against
         https://www.<domain>. Some domains only have DNS/vhost records
         for the www subdomain, not the bare apex.
      3. If either attempt failed with an SSLError: retry the *original*
         URL once on the legacy-TLS session (relaxed cipher/negotiation
         settings for old servers, still verifying certs against certifi -
         see LegacyTLSAdapter). This is tried after the www attempt so a
         www redirect target gets a chance first, but falls back to the
         apex domain if www itself doesn't exist.
    """
    url = "https://" + domain
    try:
        response = SESSION.get(url, headers=HEADERS, timeout=10, verify=VERIFY)
        response.raise_for_status()
        return response, url, None
    except requests.exceptions.SSLError as e:
        first_error = str(e)
        first_url = url
    except requests.exceptions.ConnectionError as e:
        # Not an SSLError (that's caught above first, since it's a more
        # specific subclass) - DNS failure, connection refused, connect
        # timeout, etc. Try the www. subdomain once before giving up.
        if not domain.startswith("www."):
            www_url = "https://www." + domain
            try:
                response = SESSION.get(
                    www_url, headers=HEADERS, timeout=10, verify=VERIFY
                )
                response.raise_for_status()
                return response, www_url, None
            except requests.exceptions.SSLError as e2:
                first_error = str(e2)
                first_url = www_url
            except requests.RequestException as e2:
                return [], url, f"{e} (www. fallback also failed: {e2})"
        else:
            return [], url, str(e)
    except requests.RequestException as e:
        # HTTPError (403/404/etc.), Timeout, etc. - a real response came
        # back or the failure isn't connection/SSL-shaped; no fallback
        # ladder makes sense here.
        return [], url, str(e)

    # Reaching here means an SSLError happened somewhere above - retry
    # that same URL once with relaxed legacy-TLS negotiation.
    try:
        response = LEGACY_SESSION.get(
            first_url, headers=HEADERS, timeout=10, verify=VERIFY
        )
        response.raise_for_status()
        return response, first_url, None
    except requests.RequestException as e2:
        return [], url, f"{first_error} (legacy-TLS fallback also failed: {e2})"


def get_all_styles(domain):
    """Fetches all inline/external/internal styles for a domain.

    Returns (styles, error). `error` is None on success (even if 0 styles
    were found), or a short string describing why the page couldn't be
    fetched/parsed at all.
    """
    response, url, error = fetch_root_page(domain)
    if error is not None:
        return [], error

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

            reason = skip_reason(domain)
            if reason is not None:
                error_writer.writerow(
                    {"domain": domain, "category": category, "error": reason}
                )
                error_file.flush()
                os.fsync(error_file.fileno())
                done.add(domain)
                processed_count += 1
                continue

            try:
                styles, error = get_all_styles(domain)

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