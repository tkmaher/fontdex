import pandas as pd
import os
import csv
import string
import re

SCRAPED_CSV = "fonts_scraped.csv"
OUTPUT_CSV = "fonts_clean.csv"

def open_csv_writer(path, fieldnames):
    """Open a CSV for incremental appends, writing the header only if new."""
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
    if not file_exists:
        writer.writeheader()
        f.flush()
    return f, writer

qualifiers = [
    "light", "regular", "medium", "wide", "semibold", "bold", "extrabold", "black", "demibold", "extralight", "thin", "ultralight", "heavy", "book", "italic", "oblique", "condensed", "narrow", "tight", "free", "web", "semi"
]

def sanitize(font):
    if (font is None) or (not isinstance(font, str)) or (font.strip() == ''):
        return ''
    if 'icon' in font.lower() or 'px' in font.lower():
        return '' # Ignore icon fonts or styles
    if ';' in font or '/' in font or ':' in font or '(' in font or ')' in font or '<' in font or 'É' in font or 'é' in font:
        return '' # Ignore fonts with style-like chars
    font = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', font) # Add space before capital letters
    font = font.replace('_', ' ') # Eliminate underscores
    font = font.replace('-', ' ') # Eliminate hyphens
    font = font.replace('\\', '') # Eliminate backslashes
    font = font.replace('"', '') # Eliminate quotes
    font = string.capwords(font) # Capitalize each word

    for qualifier in qualifiers:
        pattern = r'\b' + re.escape(qualifier) + r'\b'
        font = re.sub(pattern, '', font, flags=re.IGNORECASE).strip()
        font = font.replace(qualifier, '').strip() # Remove qualifiers

    font = re.sub(r'\s+', ' ', font) # Remove extra spaces
    return font

def main():
    df = pd.read_csv(SCRAPED_CSV)
    clean_file, clean_writer = open_csv_writer(
        OUTPUT_CSV, ["domain", "category", "font1", "font2", "font3"]
    )

    for index, row in df.iterrows():
        try:
            fontArr = [
                sanitize(row.get("font1")),
                sanitize(row.get("font2")),
                sanitize(row.get("font3")),
            ]
            filtered = list(dict.fromkeys([x for x in fontArr if x != '']))
            padding_count = 3 - len(filtered)
            final = filtered + [''] * padding_count
            clean_writer.writerow(
                {
                    "domain": row.get("domain"),
                    "category": row.get("category"),
                    "font1": final[0],
                    "font2": final[1],
                    "font3": final[2],
                }
            )
            clean_file.flush()
            os.fsync(clean_file.fileno())
        except Exception as e:
            print(f"Error processing row {index}: {e}")

if __name__ == "__main__":
    main()