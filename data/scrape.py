"""
Categorize a list of domains into a fixed, custom taxonomy (<=20 categories)
using the DomScan bulk categorization API.

Usage:
    1. pip install requests
    2. Set DOMSCAN_API_KEY env var (or hardcode below)
    3. Put your domain list in cl_top20000.csv (one column: "domain")
    4. python categorize_domains.py

Output: categorized_domains.csv (domain, primary_category, primary_category_id,
         primary_category_confidence, adult_content, title, language, cached)
Resumable: already-processed domains are skipped on re-run.
"""

import csv
import os
import time
import requests

INPUT_FILE = "cl_top20000.csv"
OUTPUT_FILE = "categorized_domains.csv"
BATCH_SIZE = 100
RETRY_LIMIT = 3
RETRY_BACKOFF_SEC = 2

API_KEY = os.environ.get("DOMSCAN_API_KEY", "YOUR_API_KEY")
API_URL = "https://domscan.net/v1/categorize/bulk"


def map_to_custom_category(raw_category: str) -> str:
    """TODO: map DomScan's category taxonomy onto your own custom taxonomy (<=20 categories)."""
    return raw_category


def fetch_category_batch(domains: list[str]):
    """
    Call the DomScan bulk categorization API for a batch of domains (<=100).
    Returns a dict mapping domain -> result dict from the API response
    (or an error placeholder if the domain wasn't returned / the call failed).
    """
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY,
    }
    payload = {"urls": domains}

    for attempt in range(RETRY_LIMIT):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                by_domain = {}
                for r in results:
                    # API may echo back full URLs (e.g. "https://example.com"); normalize to bare domain
                    returned_url = r.get("url", "")
                    key = returned_url.replace("https://", "").replace("http://", "").rstrip("/")
                    by_domain[key] = r

                out = {}
                for d in domains:
                    if d in by_domain:
                        out[d] = by_domain[d]
                    else:
                        out[d] = {"error": "missing_from_response"}
                return out
            elif resp.status_code == 429:
                time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
            else:
                return {d: {"error": f"Error_{resp.status_code}"} for d in domains}
        except requests.RequestException:
            time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))

    return {d: {"error": "Error_timeout"} for d in domains}


def load_already_done():
    if not os.path.exists(OUTPUT_FILE):
        return set()
    with open(OUTPUT_FILE, newline="") as f:
        return {row["domain"] for row in csv.DictReader(f)}


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def main():
    with open(INPUT_FILE, newline="") as f:
        domains = [row["domain"].strip() for row in csv.DictReader(f) if row["domain"].strip()]

    done = load_already_done()
    todo = [d for d in domains if d not in done]
    print(f"{len(todo)} domains left to process out of {len(domains)}")

    file_exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="") as out_f:
        writer = csv.writer(out_f)
        if not file_exists:
            writer.writerow([
                "domain",
                "primary_category",
                "primary_category_id",
                "mapped_category",
                "primary_category_confidence",
                "adult_content",
                "title",
                "language",
                "cached",
            ])

        processed = 0
        for batch in chunked(todo, BATCH_SIZE):
            results = fetch_category_batch(batch)
            for domain in batch:
                r = results.get(domain, {"error": "unknown"})
                if "error" in r:
                    writer.writerow([domain, r["error"], "", "", "", "", "", "", ""])
                else:
                    raw_cat = r.get("primary_category", "Unknown")
                    writer.writerow([
                        domain,
                        raw_cat,
                        r.get("primary_category_id", ""),
                        map_to_custom_category(raw_cat),
                        r.get("primary_category_confidence", ""),
                        r.get("adult_content", ""),
                        r.get("title", ""),
                        r.get("language", ""),
                        r.get("cached", ""),
                    ])
            out_f.flush()
            processed += len(batch)
            print(f"Processed {processed}/{len(todo)}")

    print("Done.")


if __name__ == "__main__":
    main()