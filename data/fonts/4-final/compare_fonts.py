#!/usr/bin/env python3
"""
compare_fonts.py

Compares fonts referenced in websites_clean_out.csv (font1, font2, font3 columns)
against the canonical list of fonts in fonts_classified_out.csv (font column).

Usage:
    python3 compare_fonts.py fonts_classified_out.csv websites_clean_out.csv

Outputs:
    - Prints a summary to stdout
    - Writes fonts_missing_from_classification.csv
        (fonts used on websites but not present in fonts_classified_out.csv)
    - Writes fonts_never_used_on_websites.csv
        (fonts present in fonts_classified_out.csv but never referenced in font1/font2/font3)
"""

import csv
import sys
from collections import Counter


def normalize(font_name: str) -> str:
    """Normalize a font name for comparison: strip whitespace, collapse
    internal whitespace, and lowercase. Adjust here if you want case-sensitive
    or punctuation-sensitive matching instead."""
    if font_name is None:
        return ""
    return " ".join(font_name.strip().split()).lower()


def load_classified_fonts(path: str):
    """Returns dict: normalized_name -> original_name (first seen), and a
    Counter of how many times each normalized name appears (to flag dupes)."""
    fonts = {}
    dupe_counter = Counter()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if "font" not in reader.fieldnames:
            sys.exit(
                f"ERROR: '{path}' has no 'font' column. "
                f"Found columns: {reader.fieldnames}"
            )
        for row in reader:
            raw = row["font"]
            if raw is None or raw.strip() == "":
                continue
            norm = normalize(raw)
            dupe_counter[norm] += 1
            if norm not in fonts:
                fonts[norm] = raw.strip()
    return fonts, dupe_counter


def load_site_fonts(path: str):
    """Returns:
        used_fonts: dict normalized_name -> original_name (first seen)
        usage_counter: Counter normalized_name -> number of (domain, column) references
        rows_with_font: dict normalized_name -> list of (domain, column) sample refs (capped)
    """
    used_fonts = {}
    usage_counter = Counter()
    rows_with_font = {}
    font_cols = ["font1", "font2", "font3"]

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing_cols = [c for c in font_cols if c not in reader.fieldnames]
        if missing_cols or "domain" not in reader.fieldnames:
            sys.exit(
                f"ERROR: '{path}' is missing expected columns {missing_cols + (['domain'] if 'domain' not in reader.fieldnames else [])}. "
                f"Found columns: {reader.fieldnames}"
            )
        for row in reader:
            domain = row.get("domain", "")
            for col in font_cols:
                raw = row.get(col)
                if raw is None or raw.strip() == "":
                    continue
                norm = normalize(raw)
                usage_counter[norm] += 1
                if norm not in used_fonts:
                    used_fonts[norm] = raw.strip()
                rows_with_font.setdefault(norm, [])
                if len(rows_with_font[norm]) < 5:  # cap sample refs
                    rows_with_font[norm].append(f"{domain}:{col}")

    return used_fonts, usage_counter, rows_with_font


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 compare_fonts.py fonts_classified_out.csv websites_clean_out.csv"
        )
        sys.exit(1)

    classified_path, sites_path = sys.argv[1], sys.argv[2]

    classified_fonts, classified_dupes = load_classified_fonts(classified_path)
    site_fonts, usage_counter, rows_with_font = load_site_fonts(sites_path)

    classified_set = set(classified_fonts.keys())
    site_set = set(site_fonts.keys())

    # Fonts used on websites but missing from the classification table
    missing_from_classification = sorted(site_set - classified_set)

    # Fonts classified but never referenced on any website
    never_used = sorted(classified_set - site_set)

    # Report duplicate entries in the classification file (same font listed twice)
    dupes = {k: v for k, v in classified_dupes.items() if v > 1}

    print("=" * 70)
    print("FONT COMPARISON SUMMARY")
    print("=" * 70)
    print(f"Classified fonts (fonts_classified_out.csv): {len(classified_set)}")
    print(f"Distinct fonts referenced on websites:        {len(site_set)}")
    print()
    print(f"Fonts used on sites but NOT classified:  {len(missing_from_classification)}")
    print(f"Classified fonts NEVER used on any site: {len(never_used)}")
    if dupes:
        print(f"\nWARNING: {len(dupes)} font name(s) appear more than once in "
              f"fonts_classified_out.csv (possible duplicate rows).")
    print("=" * 70)

    # Write missing-from-classification CSV
    out1 = "fonts_missing_from_classification.csv"
    with open(out1, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["font", "usage_count", "sample_references"])
        for norm in missing_from_classification:
            writer.writerow([
                site_fonts[norm],
                usage_counter[norm],
                "; ".join(rows_with_font.get(norm, [])),
            ])
    print(f"\nWrote {len(missing_from_classification)} rows -> {out1}")

    # Write never-used CSV
    out2 = "fonts_never_used_on_websites.csv"
    with open(out2, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["font"])
        for norm in never_used:
            writer.writerow([classified_fonts[norm]])
    print(f"Wrote {len(never_used)} rows -> {out2}")

    # Optional: duplicates report
    if dupes:
        out3 = "fonts_classified_duplicates.csv"
        with open(out3, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["font", "occurrences"])
            for norm, count in sorted(dupes.items(), key=lambda x: -x[1]):
                writer.writerow([classified_fonts[norm], count])
        print(f"Wrote {len(dupes)} rows -> {out3}")


if __name__ == "__main__":
    main()