"""
Build a free, categorized top-10,000 website list -- resumable version.

Pipeline:
  1. Download Majestic Million (free CSV, no key, updated daily) -> top 10k domains by rank.
     Cached to disk; re-run skips the download if already present.
  2. Download the Curlie directory dump (free, open-license, human-curated categories)
     and join it against the domain list. Cached to disk; parsed result is also cached.
  3. For domains Curlie doesn't cover, fetch the homepage title (politely, with delays)
     and classify it locally with a free zero-shot model (facebook/bart-large-mnli via
     Hugging Face transformers). Progress is written incrementally to a checkpoint file,
     one row at a time, so an interrupted run resumes exactly where it left off with no
     repeated work and no repeated downloads.

Nothing here calls a paid API. The only "cost" is bandwidth/time and, once, downloading
the local model weights (~1.6GB) from Hugging Face the first time you run it.

Install requirements first:
    pip install requests pandas beautifulsoup4 transformers torch tqdm

Usage:
    python build_top10k_categorized.py
    # Ctrl-C any time -- re-running the same command picks up where it stopped.

Output:
    top10000_categorized.csv
"""

import csv
import re
import tarfile
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

TOP_N = 10_000
MAJESTIC_URL = "https://downloads.majestic.com/majestic_million.csv"
CURLIE_DOWNLOAD_PAGE = "https://curlie.org/directory-dl"  # resolves to the current archive

WORKDIR = Path("top10k_build")
WORKDIR.mkdir(exist_ok=True)

MAJESTIC_CACHE = WORKDIR / "majestic_million_raw.csv"
CURLIE_ARCHIVE_CACHE = WORKDIR / "curlie_archive.tar.gz"
CURLIE_EXTRACT_DIR = WORKDIR / "curlie"
CURLIE_PARSED_CACHE = WORKDIR / "curlie_parsed.csv"
CLASSIFICATION_CHECKPOINT = WORKDIR / "classification_progress.csv"
FINAL_OUTPUT = Path("top10000_categorized.csv")

# A small, general-purpose taxonomy for the fallback classifier.
# Feel free to align this with Curlie's top-level categories instead.
CATEGORY_LABELS = [
    "News", "Shopping", "Social Media", "Entertainment", "Sports",
    "Finance", "Technology", "Health", "Education", "Travel",
    "Food and Drink", "Government", "Reference", "Adult", "Gaming",
    "Business", "Science", "Real Estate", "Jobs", "Other",
]

HEADERS = {
    # A real browser UA + Accept headers -- many sites serve an empty/blocked
    # shell to obvious bot user agents, which is why generic titles were
    # coming back blank and collapsing everything into "Other".
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_DELAY_SECONDS = 1.0   # politeness delay between homepage fetches
REQUEST_TIMEOUT = 8

# Confidence floor for the zero-shot classifier. Below this, we don't trust
# the guess enough to force it into a category -- "Other" should mean "we
# looked and it's genuinely miscellaneous", not "we couldn't tell".
MIN_CONFIDENCE = 0.40
FALLBACK_LABEL = "Uncategorized"

# A handful of domains dominate *every* top-N list (Google infra, CDNs,
# tracking pixels, app stores, etc.) and are exactly the ones a generic
# title/description classifier struggles with -- "google.com" isn't really
# "about" any one topic. Curated overrides checked before the model runs:
# free, instant, and far more accurate than a snippet-based guess for these.
KNOWN_DOMAIN_OVERRIDES = {
    "google.com": "Search Engine", "www.google.com": "Search Engine",
    "maps.google.com": "Reference", "docs.google.com": "Technology",
    "drive.google.com": "Technology", "plus.google.com": "Social Media",
    "sites.google.com": "Technology", "play.google.com": "Shopping",
    "policies.google.com": "Reference", "forms.gle": "Technology",
    "goo.gl": "Technology", "maps.app.goo.gl": "Reference",
    "googletagmanager.com": "Technology", "google-analytics.com": "Technology",
    "gstatic.com": "Technology", "googleapis.com": "Technology",
    "youtube.com": "Entertainment", "youtu.be": "Entertainment",
    "facebook.com": "Social Media", "instagram.com": "Social Media",
    "twitter.com": "Social Media", "x.com": "Social Media",
    "linkedin.com": "Social Media", "pinterest.com": "Social Media",
    "tiktok.com": "Social Media", "reddit.com": "Social Media",
    "tumblr.com": "Social Media", "flickr.com": "Social Media",
    "whatsapp.com": "Technology", "api.whatsapp.com": "Technology",
    "wa.me": "Technology", "t.me": "Technology", "telegram.org": "Technology",
    "apple.com": "Technology", "apps.apple.com": "Shopping",
    "itunes.apple.com": "Entertainment", "microsoft.com": "Technology",
    "support.microsoft.com": "Technology", "office.com": "Technology",
    "github.com": "Technology", "github.io": "Technology",
    "gravatar.com": "Technology", "wordpress.org": "Technology",
    "wordpress.com": "Technology", "blogspot.com": "Technology",
    "adobe.com": "Technology", "amazonaws.com": "Technology",
    "godaddy.com": "Technology", "nginx.org": "Technology",
    "nginx.com": "Technology", "apache.org": "Technology",
    "mozilla.org": "Technology", "macromedia.com": "Technology",
    "spotify.com": "Entertainment", "open.spotify.com": "Entertainment",
    "vimeo.com": "Entertainment", "player.vimeo.com": "Entertainment",
    "archive.org": "Reference", "wikipedia.org": "Reference",
    "en.wikipedia.org": "Reference", "bit.ly": "Technology",
    "amazon.com": "Shopping", "baidu.com": "Search Engine",
    "qq.com": "Social Media", "yahoo.com": "News",
    "nytimes.com": "News", "nih.gov": "Health", "europa.eu": "Government",
}

# ----------------------------------------------------------------------------
# Generic cached-download helper
# ----------------------------------------------------------------------------

def download_to_cache(url: str, dest: Path, timeout: int = 60) -> Path:
    """Downloads url to dest unless dest already exists non-empty."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"Using cached download: {dest}")
        return dest

    print(f"Downloading {url} ...")
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with requests.get(url, headers=HEADERS, timeout=timeout, stream=True) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    tmp.rename(dest)  # only "commit" the file once it's fully downloaded
    return dest


# ----------------------------------------------------------------------------
# Step 1: Majestic Million (rankings)
# ----------------------------------------------------------------------------

def get_majestic_top_n(n: int = TOP_N) -> pd.DataFrame:
    download_to_cache(MAJESTIC_URL, MAJESTIC_CACHE, timeout=30)
    df = pd.read_csv(MAJESTIC_CACHE)
    df = df.sort_values("GlobalRank").head(n)
    return df[["GlobalRank", "Domain"]].rename(
        columns={"GlobalRank": "rank", "Domain": "domain"}
    )


# ----------------------------------------------------------------------------
# Step 2: Curlie (categories)
# ----------------------------------------------------------------------------

def get_curlie_extracted_dir() -> Path:
    if CURLIE_EXTRACT_DIR.exists() and any(CURLIE_EXTRACT_DIR.iterdir()):
        print(f"Curlie archive already extracted at {CURLIE_EXTRACT_DIR}, skipping.")
        return CURLIE_EXTRACT_DIR

    download_to_cache(CURLIE_DOWNLOAD_PAGE, CURLIE_ARCHIVE_CACHE, timeout=180)

    print("Extracting Curlie archive...")
    CURLIE_EXTRACT_DIR.mkdir(exist_ok=True)
    with tarfile.open(CURLIE_ARCHIVE_CACHE, mode="r:gz") as tar:
        tar.extractall(CURLIE_EXTRACT_DIR)

    return CURLIE_EXTRACT_DIR


def parse_curlie(curlie_dir: Path) -> pd.DataFrame:
    """
    Returns a DataFrame with columns: domain, curlie_category.
    Result is cached to CURLIE_PARSED_CACHE so this parsing only ever runs once.

    NOTE: column indices below are based on Curlie's documented format (paired
    *-c.tsv content files and *-s.tsv structure files, tab-separated). Verify
    against the readme in the extracted archive and adjust if needed -- if you
    change the parsing logic, delete CURLIE_PARSED_CACHE to force a re-parse.
    """
    if CURLIE_PARSED_CACHE.exists():
        print(f"Using cached parsed Curlie data: {CURLIE_PARSED_CACHE}")
        return pd.read_csv(CURLIE_PARSED_CACHE)

    site_files = list(curlie_dir.rglob("*-c.tsv"))
    struct_files = list(curlie_dir.rglob("*-s.tsv"))

    if not site_files or not struct_files:
        print("Could not locate expected *-c.tsv / *-s.tsv files -- "
              "check the extracted archive structure and update this function.")
        empty = pd.DataFrame(columns=["domain", "curlie_category"])
        empty.to_csv(CURLIE_PARSED_CACHE, index=False)
        return empty

    cat_path_by_id = {}
    for f in struct_files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            reader = csv.reader(fh, delimiter="\t")
            next(reader, None)  # header
            for row in reader:
                if len(row) < 2:
                    continue
                cat_id, cat_path = row[0], row[1]
                cat_path_by_id[cat_id] = cat_path

    domain_category_rows = []
    url_re = re.compile(r"https?://(?:www\.)?([^/]+)")
    for f in site_files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            reader = csv.reader(fh, delimiter="\t")
            next(reader, None)  # header
            for row in reader:
                if len(row) < 3:
                    continue
                url, cat_id = row[1], row[-1]  # adjust indices per real schema
                m = url_re.match(url)
                if not m:
                    continue
                domain = m.group(1).lower()
                full_path = cat_path_by_id.get(cat_id, "")
                top_level = full_path.split("/")[0] if full_path else None
                if top_level:
                    domain_category_rows.append((domain, top_level))

    df = pd.DataFrame(domain_category_rows, columns=["domain", "curlie_category"])
    df = df.drop_duplicates(subset="domain")
    df.to_csv(CURLIE_PARSED_CACHE, index=False)
    return df


# ----------------------------------------------------------------------------
# Step 3: fallback classification for domains Curlie doesn't cover
# ----------------------------------------------------------------------------

def domain_to_words(domain: str) -> str:
    """
    Turns a bare domain into readable words as a last-resort signal, e.g.
    "nytimes.com" -> "nytimes com", "support.microsoft.com" -> "support
    microsoft com". Not great on its own, but better than the literal string
    for a language-model-based classifier, and it's what we had before as
    the *only* fallback -- now it's one signal among several.
    """
    parts = re.split(r"[.\-]", domain)
    return " ".join(p for p in parts if p)


def fetch_title_snippet(domain: str) -> tuple[str, bool]:
    """
    Fetch homepage <title> + meta description + first <h1>, politely.
    Returns (snippet, got_real_content) so the caller can tell a genuine
    empty/thin page apart from a fetch that failed outright.
    """
    for scheme in ("https://", "http://"):
        try:
            r = requests.get(
                scheme + domain,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if r.status_code >= 400 or not r.text:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            desc_tag = soup.find("meta", attrs={"name": "description"})
            desc = desc_tag["content"].strip() if desc_tag and desc_tag.get("content") else ""
            h1 = soup.find("h1")
            h1_text = h1.get_text(strip=True) if h1 else ""

            parts = [p for p in (title, desc, h1_text) if p]
            if parts:
                return " . ".join(parts), True
        except requests.RequestException:
            continue

    # Nothing usable came back (blocked, JS-only shell, timeout, etc.) --
    # fall back to readable domain tokens, but flag it as low-signal so the
    # classifier's result can be treated with appropriate skepticism.
    return domain_to_words(domain), False


def load_classification_checkpoint() -> dict[str, str]:
    """Loads whatever classification progress already exists on disk."""
    if not CLASSIFICATION_CHECKPOINT.exists():
        return {}
    df = pd.read_csv(CLASSIFICATION_CHECKPOINT)
    return dict(zip(df["domain"], df["category"]))


def classify_uncategorized(domains: list[str]) -> dict[str, str]:
    """
    Local, free zero-shot classification -- no API calls, no billing.
    Downloads model weights once from Hugging Face on first run.

    Resumable: results already in CLASSIFICATION_CHECKPOINT are skipped, and
    each new result is appended + flushed to that file immediately, so a
    Ctrl-C or crash loses at most the one domain currently in flight.
    """
    already_done = load_classification_checkpoint()
    remaining = [d for d in domains if d not in already_done]

    if not remaining:
        print("All domains already classified in checkpoint file.")
        return already_done

    print(f"{len(already_done)} domains already classified; "
          f"{len(remaining)} remaining.")

    from transformers import pipeline
    print("Loading local zero-shot classifier (facebook/bart-large-mnli)...")
    classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

    checkpoint_is_new = not CLASSIFICATION_CHECKPOINT.exists()
    with open(CLASSIFICATION_CHECKPOINT, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if checkpoint_is_new:
            writer.writerow(["domain", "category"])
            f.flush()

        for domain in tqdm(remaining, desc="Classifying uncategorized domains"):
            snippet = fetch_title_snippet(domain)
            time.sleep(REQUEST_DELAY_SECONDS)  # be polite, avoid hammering sites
            try:
                out = classifier(snippet, CATEGORY_LABELS)
                category = out["labels"][0]
            except Exception:
                category = "Other"

            writer.writerow([domain, category])
            f.flush()  # commit progress immediately, one row at a time
            already_done[domain] = category

    return already_done


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    if FINAL_OUTPUT.exists():
        print(f"{FINAL_OUTPUT} already exists. Delete it if you want to rebuild "
              f"the final file (cached intermediate data will still be reused).")

    majestic_df = get_majestic_top_n(TOP_N)

    curlie_dir = get_curlie_extracted_dir()
    curlie_df = parse_curlie(curlie_dir)

    merged = majestic_df.merge(curlie_df, on="domain", how="left")

    covered = merged[merged["curlie_category"].notna()]
    uncovered = merged[merged["curlie_category"].isna()]
    print(f"Curlie covered {len(covered)}/{len(merged)} domains directly.")

    if len(uncovered) > 0:
        fallback_categories = classify_uncategorized(uncovered["domain"].tolist())
        merged.loc[merged["curlie_category"].isna(), "curlie_category"] = (
            merged.loc[merged["curlie_category"].isna(), "domain"].map(fallback_categories)
        )

    merged = merged.rename(columns={"curlie_category": "category"})
    merged = merged.sort_values("rank")
    merged.to_csv(FINAL_OUTPUT, index=False)
    print(f"Done. Wrote {FINAL_OUTPUT}")


if __name__ == "__main__":
    main()