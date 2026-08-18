#!/usr/bin/env python3
"""
font_taxonomy.py

Reduces a CSV of `site,category,font1,font2,font3` rows into a deduplicated
CSV of font metadata, using a tiered lookup:

  1. Generic descriptors    - "Sans Serif" / "Serif" / "Monospace" used as a
                               literal value instead of a real font name.
  2. Icon/glyph fonts       - Font Awesome, Icomoon, etc. (not text fonts).
  3. Curated dictionary     - well-known OS/system fonts and commercial
                               (Adobe/Typekit/Linotype) fonts that Google
                               Fonts doesn't carry.
  4. Google Fonts API       - https://developers.google.com/fonts/docs/developer_api
                               exact match, then fuzzy match.
  5. Substring heuristic    - if the name itself contains "sans", "serif",
                               "mono", etc., classify off that rather than
                               erroring out.
  6. Error CSV              - anything not resolved by 1-5 (typically
                               proprietary/custom fonts with no public record)
                               is written to a separate CSV instead of being
                               guessed at.

STYLE TAGS (new `style_tags` column):
    There is no free public API that returns subjective style classifications
    (grotesque, geometric, humanist, gothic, etc.) for arbitrary font names -
    Google Fonts' API only returns `category` (serif/sans-serif/display/
    handwriting/monospace), `variants` (available weights/italics), and
    `axes` (variable font axes). So this column is built from two sources,
    both applied automatically, with no manual tagging required per font:

      - API-derived tags: read directly from the Google Fonts response -
        weight extremes ("black-weight-available", "light-weight-available"),
        italic availability, and whether the font is a variable font.
      - Name/curated-derived tags: keyword matches against the font name
        (e.g. "Grotesk" -> grotesque) plus a small curated table of tags for
        well-known fonts not on Google Fonts (e.g. Century Gothic ->
        geometric;gothic). These are best-effort, not authoritative -
        treat them as hints, not ground truth.

Usage:
    python font_taxonomy.py input.csv \
        --output fonts_taxonomy.csv \
        --errors fonts_errors.csv \
        --api-key YOUR_GOOGLE_FONTS_API_KEY \
        --fuzzy-cutoff 0.75

    (or set the GOOGLE_FONTS_API_KEY environment variable instead of --api-key)
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

# substrings that identify icon/glyph fonts (not text-reading fonts)
ICON_FONT_MARKERS = ("font awesome", "icomoon", "material icon", "uxfont")

# ---------------------------------------------------------------------------
# Tier 3: curated dictionary for system UI fonts, classic web-safe fonts,
# and commercial (Adobe/Typekit/Linotype/Monotype) fonts not on Google Fonts.
# `tags` here are curated by name/foundry knowledge, not from an API.
# ---------------------------------------------------------------------------
CURATED_FONTS = {
    # Apple / macOS / iOS system fonts
    "apple system": dict(classification="sans-serif", source="apple-system",
                          is_monospace=False, tags=["humanist", "variable-font"],
                          notes="San Francisco system UI font"),
    "system ui": dict(classification="sans-serif", source="system-ui",
                       is_monospace=False, tags=[],
                       notes="Generic OS-default UI font stack"),
    "sfmono": dict(classification="monospace", source="apple-system",
                    is_monospace=True, tags=["grotesque"],
                    notes="SF Mono, Apple's system monospace font"),
    "menlo": dict(classification="monospace", source="apple-system",
                   is_monospace=True, tags=["slab-serif"],
                   notes="Apple monospace coding font"),

    # Microsoft / Windows system fonts
    "segoe ui": dict(classification="sans-serif", source="microsoft-system",
                      is_monospace=False, tags=["humanist"],
                      notes="Windows system UI font"),
    "consolas": dict(classification="monospace", source="microsoft-system",
                      is_monospace=True, tags=["humanist"],
                      notes="Microsoft monospace coding font"),
    "tahoma": dict(classification="sans-serif", source="microsoft-system",
                    is_monospace=False, tags=["humanist", "grotesque"]),
    "verdana": dict(classification="sans-serif", source="microsoft-system",
                     is_monospace=False, tags=["humanist"],
                     notes="Humanist sans, designed for screen legibility"),
    "arial": dict(classification="sans-serif", source="microsoft-system",
                   is_monospace=False, tags=["grotesque", "neo-grotesque"]),
    "times new roman": dict(classification="serif", source="microsoft-system",
                             is_monospace=False, tags=["transitional", "old-style"]),
    "courier new": dict(classification="monospace", source="microsoft-system",
                         is_monospace=True, tags=["slab-serif", "typewriter"],
                         notes="Typewriter-style monospace slab serif"),

    # Adobe Fonts / Typekit-distributed commercial families
    "freight text pro": dict(classification="serif", source="adobe-fonts",
                              is_monospace=False, tags=["old-style", "transitional"]),
    "europa": dict(classification="sans-serif", source="adobe-fonts",
                    is_monospace=False, tags=["grotesque", "geometric"]),
    "neue haas unica": dict(classification="sans-serif", source="adobe-fonts",
                             is_monospace=False, tags=["grotesque", "neo-grotesque"],
                             notes="Modern reworking of Helvetica/Haas Grotesk"),
    "myriad pro": dict(classification="sans-serif", source="adobe-fonts",
                        is_monospace=False, tags=["humanist"]),
    "publico headline": dict(classification="serif", source="adobe-fonts",
                              is_monospace=False, tags=["transitional"]),
    "publico text": dict(classification="serif", source="adobe-fonts",
                          is_monospace=False, tags=["transitional"]),
    "graphik": dict(classification="sans-serif", source="adobe-fonts",
                     is_monospace=False, tags=["grotesque", "humanist"]),
    "frutiger": dict(classification="sans-serif", source="linotype",
                      is_monospace=False, tags=["humanist"],
                      notes="Humanist sans designed for wayfinding/signage"),
    "century gothic": dict(classification="sans-serif", source="monotype",
                            is_monospace=False, tags=["geometric", "gothic"],
                            notes="Geometric sans"),
}

# ---------------------------------------------------------------------------
# Tier 5: substring-based classification fallback, checked in priority order
# (first match wins). Used only when nothing above resolved the font.
# ---------------------------------------------------------------------------
CLASSIFICATION_KEYWORDS = [
    ("slab", "slab-serif"),
    ("mono", "monospace"),
    ("script", "script"),
    ("hand", "handwriting"),
    ("display", "display"),
    ("sans", "sans-serif"),
    ("grotesk", "sans-serif"),
    ("grotesque", "sans-serif"),
    ("gothic", "sans-serif"),   # American usage: Century/Franklin/Trade Gothic = sans-serif
    ("serif", "serif"),        # checked after "sans" so "Sans Serif"-style names resolve correctly
]

# ---------------------------------------------------------------------------
# Style-tag keyword table (name-derived, not from an API)
# ---------------------------------------------------------------------------
STYLE_KEYWORDS = {
    "grotesque": "grotesque",
    "grotesk": "grotesque",
    "gothic": "gothic",
    "geometric": "geometric",
    "humanist": "humanist",
    "slab": "slab-serif",
    "condensed": "condensed",
    "extended": "extended",
    "expanded": "expanded",
    "rounded": "rounded",
    "narrow": "narrow",
    "compressed": "compressed",
    "typewriter": "typewriter",
    "old style": "old-style",
    "didone": "didone",
    "transitional": "transitional",
    "black": "black-weight",
    "thin": "thin-weight",
    "hairline": "thin-weight",
}


def normalize_key(name: str) -> str:
    """Lowercase, strip non-alphanumerics, for dictionary/API matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _normalize_dict_keys(d: dict) -> dict:
    return {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in d.items()}


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


def api_derived_tags(item: dict) -> list:
    """Weight/italic/variable tags read directly from the Google Fonts API response."""
    tags = []
    variants = item.get("variants", [])
    weights = set()
    for v in variants:
        m = re.match(r"(\d{3})", v)
        if m:
            weights.add(int(m.group(1)))
    if weights:
        if min(weights) <= 200:
            tags.append("light-weight-available")
        if max(weights) >= 800:
            tags.append("black-weight-available")
    if any("italic" in v for v in variants):
        tags.append("italic-available")
    if item.get("axes"):
        tags.append("variable-font")
    return tags


def name_derived_tags(name: str) -> list:
    """Keyword-based style tags from the font name itself (best-effort, not authoritative)."""
    lower = name.lower()
    tags = []
    for keyword, tag in STYLE_KEYWORDS.items():
        if keyword in lower and tag not in tags:
            tags.append(tag)
    return tags


def classify_from_google(item: dict, raw_name: str) -> dict:
    """Map a Google Fonts API item to our taxonomy fields."""
    category = item.get("category", "unknown")  # serif/sans-serif/display/handwriting/monospace
    subsets = item.get("subsets", [])
    tags = api_derived_tags(item) + [t for t in name_derived_tags(raw_name)
                                      if t not in api_derived_tags(item)]
    return dict(
        classification=category,
        source="google-fonts",
        is_monospace=(category == "monospace"),
        subsets=";".join(subsets),
        tags=tags,
        notes=f"Google Fonts family '{item.get('family')}'",
    )


def classify_by_substring(raw_name: str) -> str | None:
    """Last-resort classification: does the name itself say what it is?"""
    lower = raw_name.lower()
    for keyword, classification in CLASSIFICATION_KEYWORDS:
        if keyword in lower:
            return classification
    return None


def resolve_font(raw_name: str, google_index: dict, fuzzy_cutoff: float) -> dict | None:
    """
    Try, in order: generic descriptor -> icon font -> curated dictionary ->
    Google Fonts exact match -> Google Fonts fuzzy match -> substring
    heuristic. Returns a dict of taxonomy fields, or None if unresolved.
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
            subsets="",
            tags=[],
            notes="Value was a generic style descriptor, not a font name",
        )

    # Tier 2: icon fonts
    if any(marker in lower for marker in ICON_FONT_MARKERS):
        return dict(
            classification="icon-font",
            source="icon-library",
            is_monospace=False,
            subsets="",
            tags=[],
            notes="Glyph/icon font, not a text-reading font",
        )

    # Tier 3: curated dictionary
    if key in CURATED_FONTS_NORMALIZED:
        base = CURATED_FONTS_NORMALIZED[key]
        return dict(
            classification=base["classification"],
            source=base["source"],
            is_monospace=base["is_monospace"],
            subsets="",
            tags=list(base.get("tags", [])),
            notes=base.get("notes", ""),
        )

    # Tier 4a: Google Fonts exact match
    if key in google_index:
        return classify_from_google(google_index[key], raw_name)

    # Tier 4b: Google Fonts fuzzy match (handles spacing/casing/minor typo
    # deviations, e.g. "Noto Sans Jp" vs. official "Noto Sans JP")
    if google_index:
        close = difflib.get_close_matches(key, google_index.keys(), n=1, cutoff=fuzzy_cutoff)
        if close:
            return classify_from_google(google_index[close[0]], raw_name)

    # Tier 5: substring heuristic - still not "found", so source stays
    # transparent about the fact this is a guess, not a lookup.
    guess = classify_by_substring(raw_name)
    if guess:
        return dict(
            classification=guess,
            source="substring-heuristic",
            is_monospace=(guess == "monospace"),
            subsets="",
            tags=name_derived_tags(raw_name),
            notes="Not found in any lookup tier; classified from keywords in the name itself",
        )

    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input_csv", default="../2-sanitize/fonts_clean.csv", help="Path to site/category/font1/font2/font3 CSV (no header)")
    parser.add_argument("--output", default="fonts_classified.csv",
                         help="Path to write resolved font taxonomy CSV")
    parser.add_argument("--errors", default="fonts_errors.csv",
                         help="Path to write unresolved/unfindable fonts CSV")
    parser.add_argument("--api-key", default=os.environ.get("GOOGLE_FONTS_API_KEY", ""),
                         help="Google Fonts API key (or set GOOGLE_FONTS_API_KEY env var)")
    parser.add_argument("--fuzzy-cutoff", type=float, default=0.9,
                         help="difflib similarity threshold (0-1) for fuzzy-matching "
                              "font names against the Google Fonts catalog. Lower = "
                              "more permissive. Default 0.9.")
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
    fieldnames = ["font", "classification", "style_tags", "source",
                  "is_monospace", "is_icon_font", "subsets", "notes"]

    for name in ordered_fonts:
        result = resolve_font(name, google_index, args.fuzzy_cutoff)
        if result is None:
            error_rows.append({"font": name, "reason": "No match in generic "
                                "descriptors, icon fonts, curated dictionary, "
                                "Google Fonts API, or substring heuristic"})
            continue
        resolved_rows.append({
            "font": name,
            "classification": result["classification"],
            "style_tags": ";".join(result.get("tags", [])),
            "source": result["source"],
            "is_monospace": result["is_monospace"],
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