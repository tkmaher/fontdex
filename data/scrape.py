"""
Categorize a list of domains into a fixed, custom taxonomy (<=20 categories)
using a domain categorization API (default: Webshrinker-style auth).

Usage:
    1. pip install requests
    2. Set WEBSHRINKER_ACCESS_KEY / WEBSHRINKER_SECRET_KEY env vars (or hardcode below)
    3. Put your domain list in cl_top20000.csv (one column: "domain")
    4. python categorize_domains.py

Output: categorized_domains.csv (domain, raw_category, mapped_category, confidence)
Resumable: already-processed domains are skipped on re-run.
"""

import csv
import os
import time
import base64
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "cl_top20000.csv"
OUTPUT_FILE = "categorized_domains.csv"
MAX_WORKERS = 5          
RETRY_LIMIT = 3
RETRY_BACKOFF_SEC = 2

ACCESS_KEY = os.environ.get("WEBSHRINKER_ACCESS_KEY", "YOUR_ACCESS_KEY")
SECRET_KEY = os.environ.get("WEBSHRINKER_SECRET_KEY", "YOUR_SECRET_KEY")


def fetch_category(domain: str):
    """Call the categorization API for a single domain. Returns (raw_category, confidence)."""
    url = f"https://api.webshrinker.com/categories/v3/{base64.b64encode(domain.encode()).decode()}"
    params = {"taxonomy": "webshrinker"}  # or "iab" for the detailed taxonomy

    for attempt in range(RETRY_LIMIT):
        try:
            resp = requests.get(url, params=params, auth=(ACCESS_KEY, SECRET_KEY), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                cats = data.get("data", [{}])[0].get("categories", [])
                if cats:
                    top = cats[0]
                    return top.get("name", "Unknown"), top.get("confidence", 0)
                return "Unknown", 0
            elif resp.status_code == 429:
                time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
            else:
                return f"Error_{resp.status_code}", 0
        except requests.RequestException:
            time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    return "Error_timeout", 0


def load_already_done():
    if not os.path.exists(OUTPUT_FILE):
        return set()
    with open(OUTPUT_FILE, newline="") as f:
        return {row["domain"] for row in csv.DictReader(f)}


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
            writer.writerow(["domain", "raw_category", "mapped_category", "confidence"])

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(fetch_category, d): d for d in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                domain = futures[fut]
                raw_cat, confidence = fut.result()
                mapped = map_to_custom_category(raw_cat)
                writer.writerow([domain, raw_cat, mapped, confidence])
                out_f.flush()
                if i % 100 == 0:
                    print(f"Processed {i}/{len(todo)}")

    print("Done.")


if __name__ == "__main__":
    main()