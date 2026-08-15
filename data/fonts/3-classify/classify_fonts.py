#!/usr/bin/env python3
"""
font_taxonomy.py

Reduces a CSV of `site,category,font1,font2,font3` rows into a deduplicated
CSV of font metadata, using a tiered lookup:

  1. Generic descriptors    - "Sans Serif" / "Serif" / "Monospace" used as a
                               literal value instead of a real font name.
  2. Curated dictionary     - well-known OS/system fonts and icon-glyph
                               fonts that Google Fonts doesn't carry.
  3. Google Fonts API       - https://developers.google.com/fonts/docs/developer_api
                               covers ~1700+ open-source families and returns
                               real classification, variable-font, and
                               language-subset data.
  4. Error CSV              - anything not resolved by 1-3 (typically
                               proprietary/custom fonts with no public API
                               record) is written to a separate CSV instead
                               of being guessed at.

Usage:
    python font_taxonomy.py input.csv \
        --output fonts_taxonomy.csv \
        --errors fonts_errors.csv \
        --api-key YOUR_GOOGLE_FONTS_API_KEY

    (or set the GOOGLE_FONTS_API_KEY environment variable instead of --api-key)

If no API key is available/reachable, the script still runs using tiers 1-2
and a light keyword heuristic, and is transparent in the `source` column
about how each row was resolved.
"""

import argparse
import csv
import difflib
import os
import re
import sys
import urllib.request
import urllib.error
import json

GOOGLE_FONTS_ENDPOINT = "https://www.googleapis.com/webfonts/v1/webfonts"

# ---------------------------------------------------------------------------
# Tier 1: generic descriptors used in place of an actual font name
# ---------------------------------------------------------------------------
GENERIC_DESCRIPTORS = {
    "sans serif": dict(classification="sans-serif", is_monospace=False),
    "serif": dict(classification="serif", is_monospace=False),
    "monospace": dict(classification="monospace", is_monospace=True),
}

# ---------------------------------------------------------------------------
# Tier 2: curated dictionary for system UI fonts, classic web-safe fonts,
# and icon/glyph fonts that are not (and will never be) on Google Fonts.
# Extend this as you encounter more.
# ---------------------------------------------------------------------------
CURATED_FONTS = {
    # Apple / macOS / iOS system fonts
    "apple system": dict(classification="sans-serif", source="apple-system",
                          is_monospace=False, is_variable=True,
                          notes="San Francisco system UI font"),
    "system ui": dict(classification="sans-serif", source="system-ui",
                       is_monospace=False, is_variable=False,
                       notes="Generic OS-default UI font stack"),
    "sfmono": dict(classification="monospace", source="apple-system",
                    is_monospace=True, is_variable=False,
                    notes="SF Mono, Apple's system monospace font"),
    "menlo": dict(classification="monospace", source="apple-system",
                   is_monospace=True, is_variable=False,
                   notes="Apple monospace coding font"),

    # Microsoft / Windows system fonts
    "segoe ui": dict(classification="sans-serif", source="microsoft-system",
                      is_monospace=False, is_variable=False,
                      notes="Windows system UI font"),
    "consolas": dict(classification="monospace", source="microsoft-system",
                      is_monospace=True, is_variable=False,
                      notes="Microsoft monospace coding font"),
    "tahoma": dict(classification="sans-serif", source="microsoft-system",
                    is_monospace=False, is_variable=False),
    "verdana": dict(classification="sans-serif", source="microsoft-system",
                     is_monospace=False, is_variable=False,
                     notes="Humanist sans, designed for screen legibility"),
    "arial": dict(classification="sans-serif", source="microsoft-system",
                   is_monospace=False, is_variable=False),
    "times new roman": dict(classification="serif", source="microsoft-system",
                             is_monospace=False, is_variable=False),
    "courier new": dict(classification="monospace", source="microsoft-system",
                         is_monospace=True, is_variable=False,
                         notes="Typewriter-style monospace slab serif"),

    # Adobe Fonts / Typekit-distributed commercial families
    "freight text pro": dict(classification="serif", source="adobe-fonts",
                              is_monospace=False, is_variable=False),
    "europa": dict(classification="sans-serif", source="adobe-fonts",
                    is_monospace=False, is_variable=False),
    "neue haas unica": dict(classification="sans-serif", source="adobe-fonts",
                             is_monospace=False, is_variable=False,
                             notes="Modern reworking of Helvetica/Haas Grotesk"),
    "myriad pro": dict(classification="sans-serif", source="adobe-fonts",
                        is_monospace=False, is_variable=False),
    "publico headline": dict(classification="serif", source="adobe-fonts",
                              is_monospace=False, is_variable=False),
    "publico text": dict(classification="serif", source="adobe-fonts",
                          is_monospace=False, is_variable=False),
    "graphik": dict(classification="sans-serif", source="adobe-fonts",
                     is_monospace=False, is_variable=False),
    "frutiger": dict(classification="sans-serif", source="linotype",
                      is_monospace=False, is_variable=False,
                      notes="Humanist sans designed for wayfinding/signage"),
    "century gothic": dict(classification="sans-serif", source="monotype",
                            is_monospace=False, is_variable=False,
                            notes="Geometric sans"),
}

# substrings that identify icon/glyph fonts (not text-reading fonts)
ICON_FONT_MARKERS = ("font awesome", "icomoon", "material icon", "uxfont")


def _normalize_dict_keys(d: dict) -> dict:
    return {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in d.items()}


def normalize_key(name: str) -> str:
    """Lowercase, strip non-alphanumerics, for dictionary/API matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


CURATED_FONTS_NORMALIZED = _normalize_dict_keys(CURATED_FONTS)


def display_name(name: str) -> str:
    """Clean up whitespace/casing for the output CSV without inventing data."""
    return re.sub(r"\s+", " ", name.strip())


def fetch_google_fonts(api_key: str) -> dict:
    """
    Fetch the full Google Fonts catalog once and index it by normalized
    family name. Returns {} on any network/auth failure so the rest of the
    pipeline degrades gracefully instead of crashing.
    """
    if not api_key:
        print("[info] No Google Fonts API key provided - skipping API tier.",
              file=sys.stderr)
        return {}

    url = f"{GOOGLE_FONTS_ENDPOINT}?key={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError) as exc:
        print(f"[warn] Google Fonts API unreachable ({exc}); "
              f"continuing with curated dictionary only.", file=sys.stderr)
        return {}

    index = {}
    for item in data.get("items", []):
        key = normalize_key(item["family"])
        index[key] = item
    print(f"[info] Loaded {len(index)} families from Google Fonts API.",
          file=sys.stderr)
    return index


def classify_from_google(item: dict) -> dict:
    """Map a Google Fonts API item to our taxonomy fields."""
    category = item.get("category", "unknown")  # serif/sans-serif/display/handwriting/monospace
    axes = item.get("axes")  # present only for variable fonts
    subsets = item.get("subsets", [])
    return dict(
        classification=category,
        source="google-fonts",
        is_monospace=(category == "monospace"),
        is_variable=bool(axes),
        subsets=";".join(subsets),
        notes=f"Google Fonts family '{item.get('family')}'",
    )


def resolve_font(raw_name: str, google_index: dict) -> dict | None:
    """
    Try, in order: generic descriptor -> curated dictionary -> Google Fonts
    exact match -> Google Fonts close/fuzzy match.
    Returns a dict of taxonomy fields, or None if unresolved.
    """
    key = normalize_key(raw_name)
    lower = raw_name.lower().strip()

    # Tier 1: generic descriptor
    if lower in GENERIC_DESCRIPTORS:
        base = GENERIC_DESCRIPTORS[lower]
        return dict(
            classification=base["classification"],
            source="generic-descriptor",
            is_monospace=base["is_monospace"],
            is_variable=False,
            subsets="",
            notes="Value was a generic style descriptor, not a font name",
        )

    # Icon fonts (checked before dictionary/API since they're a special case)
    if any(marker in lower for marker in ICON_FONT_MARKERS):
        return dict(
            classification="icon-font",
            source="icon-library",
            is_monospace=False,
            is_variable=False,
            subsets="",
            notes="Glyph/icon font, not a text-reading font",
        )

    # Tier 2: curated dictionary (keys are normalized the same way as input)
    if key in CURATED_FONTS_NORMALIZED:
        base = CURATED_FONTS_NORMALIZED[key]
        return dict(
            classification=base["classification"],
            source=base["source"],
            is_monospace=base["is_monospace"],
            is_variable=base.get("is_variable", False),
            subsets="",
            notes=base.get("notes", ""),
        )

    # Tier 3: Google Fonts exact match
    if key in google_index:
        return classify_from_google(google_index[key])

    # Tier 3b: Google Fonts fuzzy match (handles things like "Noto Sans Jp"
    # vs. official "Noto Sans JP")
    if google_index:
        close = difflib.get_close_matches(key, google_index.keys(), n=1, cutoff=0.9)
        if close:
            return classify_from_google(google_index[close[0]])

    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_csv", help="Path to site/category/font1/font2/font3 CSV (no header)")
    parser.add_argument("--output", default="fonts_taxonomy.csv",
                         help="Path to write resolved font taxonomy CSV")
    parser.add_argument("--errors", default="fonts_errors.csv",
                         help="Path to write unresolved/unfindable fonts CSV")
    parser.add_argument("--api-key", default=os.environ.get("GOOGLE_FONTS_API_KEY", ""),
                         help="Google Fonts API key (or set GOOGLE_FONTS_API_KEY env var)")
    args = parser.parse_args()

    # --- 1. Read input, collect unique font names -------------------------
    seen = set()
    ordered_fonts = []
    with open(args.input_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            # columns: site, category, font1, font2, font3 (font columns may be short/empty)
            for raw in row[2:]:
                raw = raw.strip()
                if not raw:
                    continue
                name = display_name(raw)
                key = normalize_key(name)
                if key not in seen:
                    seen.add(key)
                    ordered_fonts.append(name)

    print(f"[info] Found {len(ordered_fonts)} unique font values in input.",
          file=sys.stderr)

    # --- 2. Load Google Fonts catalog (single API call) -------------------
    google_index = fetch_google_fonts(args.api_key)

    # --- 3. Resolve each font ----------------------------------------------
    resolved_rows = []
    error_rows = []
    fieldnames = ["font", "classification", "source", "is_monospace",
                  "is_variable", "is_icon_font", "subsets", "notes"]

    for name in ordered_fonts:
        result = resolve_font(name, google_index)
        if result is None:
            error_rows.append({"font": name, "reason": "No match in generic "
                                "descriptors, curated dictionary, or Google Fonts API"})
            continue
        resolved_rows.append({
            "font": name,
            "classification": result["classification"],
            "source": result["source"],
            "is_monospace": result["is_monospace"],
            "is_variable": result["is_variable"],
            "is_icon_font": result["classification"] == "icon-font",
            "subsets": result.get("subsets", ""),
            "notes": result.get("notes", ""),
        })

    # --- 4. Write outputs ----------------------------------------------
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(resolved_rows)

    with open(args.errors, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["font", "reason"])
        writer.writeheader()
        writer.writerows(error_rows)

    print(f"[done] Resolved {len(resolved_rows)} fonts -> {args.output}",
          file=sys.stderr)
    print(f"[done] {len(error_rows)} unresolved fonts -> {args.errors}",
          file=sys.stderr)


if __name__ == "__main__":
    main()