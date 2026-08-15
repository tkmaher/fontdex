"""
Sanitize the DomScan output by removing domains that failed to be categorized.
Usage:
    1. Put categorized domains in categorized_domains.csv
    2. python clean_categorized.py

Output: categorized_domains_sanitized.csv (domain, primary_category, primary_category_id,
         mapped_category, primary_category_confidence, adult_content, title,
         language, cached) and categorized_domains_error.csv (domain, error)
"""

import csv
import os

INPUT_FILE = "categorized_domains.csv"
OUTPUT_FILE = "categorized_domains_sanitized.csv"
ERROR_FILE = "categorized_domains_error.csv"

error_strings = {
    "UNSAFE_TARGET_URL", 
    "Website content could not be observed", 
    "Error_400", 
    "This operation was aborted", 
    "fetch failed",
    ""
}

def main():
    with open(INPUT_FILE, newline="") as f:
        domains = [row for row in csv.DictReader(f)]

    file_exists = os.path.exists(OUTPUT_FILE)
    errorfile_exists = os.path.exists(ERROR_FILE)

    with open(OUTPUT_FILE, "a", newline="") as out_f:
        writer = csv.writer(out_f)
        if not file_exists:
            writer.writerow([
                "domain", "primary_category", "primary_category_id", "mapped_category",
                "primary_category_confidence", "adult_content", "title", "language", "cached",
            ])
        with open(ERROR_FILE, "a", newline="") as err_f:
            err_writer = csv.writer(err_f)
            if not errorfile_exists:
                err_writer.writerow([
                    "domain", "error"
                ])

            for domain in domains:
                if domain.get("primary_category") in error_strings:
                    err_writer.writerow([domain.get("domain"), domain.get("primary_category")])
                    err_f.flush()
                else:
                    writer.writerow([
                        domain.get("domain"), domain.get("primary_category"), domain.get("primary_category_id"),
                        domain.get("mapped_category"), domain.get("primary_category_confidence"),
                        domain.get("adult_content"), domain.get("title"), domain.get("language"),
                        domain.get("cached")
                    ])
                    out_f.flush()
            

    print("Done.")


if __name__ == "__main__":
    main()