#!/usr/bin/env python3
"""
ai_classify_fonts.py

Takes the leftover *unresolved* fonts from fonts_errors.csv (fonts that
generic descriptors, the curated dictionary, the Google Fonts API, and the
substring heuristic all failed to identify) and classifies them using a
locally-running LLM via Ollama - fully offline, no API key, no per-request
cost, no rate limit.

WHY THIS IS A LAST RESORT, NOT A LOOKUP:
This is model recall, not a database query. A local model will correctly
classify well-known fonts it saw during training ("Rajdhani is a geometric
sans-serif") but will honestly not know truly obscure/custom/in-house fonts
("Gdsherpa", "Sv D Ester Blenda") - and unlike a real lookup, a model can
also confidently hallucinate. To manage that:
  - Every row gets a `confidence` (high/medium/low) from the model itself.
  - The model is explicitly instructed to answer "unknown" rather than guess
    when it doesn't recognize a font.
  - Every AI row is tagged `source=ollama-llm:<model>` in the output, so it
    stays visibly distinct from verified API/dictionary rows in the merged
    taxonomy - treat `high`/`medium` as decent-but-unverified, and spot-check
    a sample before trusting `low` rows at all.

SETUP:
    1. Install Ollama: https://ollama.com/download
    2. Pull a SMALL model - this matters a lot if RAM is tight:
           ollama pull qwen2.5:1.5b     # ~1.5GB RAM, fits on almost any laptop
           ollama pull llama3.2:1b      # ~1.3GB RAM, even lighter, slightly less accurate
           ollama pull phi3:mini        # ~2.5GB RAM, a step up in accuracy if you can spare it
       Avoid 7b/8b-class models unless you have 16GB+ RAM free - on a tight
       laptop they'll swap to disk and every request will crawl or time out,
       which is almost certainly what happened with llama3.1:8b.
    3. Make sure the Ollama server is running (it starts automatically on
       most installs; otherwise `ollama serve`).
    4. Optional but recommended on a tight machine: run `ollama run <model>`
       once by hand first and leave it loaded (`--keep-alive` below keeps it
       resident between batches so you're not paying model-load time on
       every single request).

IF YOU'RE STILL HITTING TIMEOUTS:
This script now splits a batch in half and retries automatically whenever a
batch times out or fails to parse, all the way down to batch size 1 if
needed - so a single slow/oversized request won't sink your whole run. If
even single-font requests are timing out, the model itself doesn't fit in
available RAM; step down to a smaller model rather than raising --timeout
further.

USAGE:
    python ai_classify_fonts.py fonts_errors.csv \
        --output fonts_ai_classified.csv \
        --still-unresolved fonts_still_unresolved.csv \
        --model qwen2.5:1.5b \
        --batch-size 8

Then merge fonts_ai_classified.csv into fonts_taxonomy.csv (see the
`merge_into_taxonomy.py` helper printed at the end of this file's docstring,
or just concatenate the CSVs with pandas - they share the same columns plus
one extra `confidence` column).
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
import urllib.error

OLLAMA_ENDPOINT = "http://localhost:11434/api/chat"

# Keep this in sync with font_taxonomy.py's vocabulary so AI rows slot
# cleanly into the same taxonomy.
CLASSIFICATION_VOCAB = [
    "serif", "sans-serif", "monospace", "slab-serif", "script",
    "display", "handwriting", "icon-font", "system-ui", "unknown",
]
STYLE_TAG_VOCAB = [
    "grotesque", "neo-grotesque", "geometric", "humanist", "gothic",
    "old-style", "transitional", "didone", "slab-serif", "condensed",
    "extended", "expanded", "rounded", "compressed", "typewriter",
    "black-weight", "thin-weight", "variable-font",
]

SYSTEM_PROMPT = f"""You are a typography expert helping classify web fonts.

For each font name given, respond with your best knowledge of that specific
named typeface. Allowed values for "classification" (pick exactly one):
{", ".join(CLASSIFICATION_VOCAB)}

Suggested (not exhaustive) vocabulary for "style_tags" - use any that apply,
or invent a short lowercase-hyphenated tag if none fit well:
{", ".join(STYLE_TAG_VOCAB)}

Rules:
- If you do not specifically recognize this font (i.e. you'd be guessing
  purely from the name), set "classification" to "unknown", "style_tags" to
  an empty list, and "confidence" to "low". Do NOT invent plausible-sounding
  facts about a font you don't actually know.
- "confidence" must be "high" (you know this specific font and its
  foundry/designer), "medium" (you recognize the family/likely style but
  are not fully certain of specifics), or "low" (you are guessing or do not
  recognize it).
- "is_monospace" is true only if you know the font has fixed-width glyphs.
- "notes" should be one short sentence: foundry/designer/notable use if
  known, or why you're unsure.

Respond with ONLY a JSON array, one object per font, in this exact shape,
and nothing else - no markdown fences, no commentary:
[
  {{"font": "<echo the exact name given>", "classification": "...",
    "style_tags": ["...", "..."], "is_monospace": true,
    "confidence": "high", "notes": "..."}}
]
"""


def normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def read_error_fonts(path: str) -> list:
    fonts = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("font", "").strip()
            if name:
                fonts.append(name)
    return fonts


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def call_ollama(model: str, font_batch: list, timeout: int, num_ctx: int,
                 keep_alive: str) -> list:
    user_prompt = "Classify these fonts:\n" + json.dumps(font_batch)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",  # ask Ollama to constrain to valid JSON where the model supports it
        "keep_alive": keep_alive,  # keep the model resident between batches; avoids reload cost
        "options": {
            "temperature": 0.1,
            "num_ctx": num_ctx,  # cap context window - lower = less RAM per request
        },
    }
    req = urllib.request.Request(
        OLLAMA_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    content = body.get("message", {}).get("content", "")
    content = strip_code_fences(content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Some models wrap the array in an object like {"fonts": [...]}
        # or add stray text around it - try to salvage the array.
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            parsed = next(iter(parsed.values()))

    if isinstance(parsed, dict):
        parsed = parsed.get("fonts") or parsed.get("results") or list(parsed.values())[0]

    return parsed


def classify_batch_adaptive(model, batch, timeout, num_ctx, keep_alive,
                             retries, depth=0):
    """
    Try to classify a batch; on timeout/failure, retry a couple times, and
    if it still fails, split the batch in half and recurse. This means a
    single oversized/slow request degrades gracefully into several smaller
    ones instead of losing the whole batch - important on constrained RAM
    where request time is unpredictable.

    Returns (classified_items, failed_font_names_with_reason).
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            result = call_ollama(model, batch, timeout, num_ctx, keep_alive)
            return result, []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                ConnectionError) as exc:
            last_exc = exc
            print(f"[warn] {'  ' * depth}batch of {len(batch)} attempt "
                  f"{attempt + 1} failed: {exc}", file=sys.stderr)
            time.sleep(1.0)

    if len(batch) == 1:
        return [], [(batch[0], f"Failed even at batch size 1: {last_exc}")]

    mid = len(batch) // 2
    print(f"[info] {'  ' * depth}splitting batch of {len(batch)} into "
          f"{mid} + {len(batch) - mid} and retrying...", file=sys.stderr)
    left_items, left_failed = classify_batch_adaptive(
        model, batch[:mid], timeout, num_ctx, keep_alive, retries, depth + 1)
    right_items, right_failed = classify_batch_adaptive(
        model, batch[mid:], timeout, num_ctx, keep_alive, retries, depth + 1)
    return left_items + right_items, left_failed + right_failed


def main():
    global OLLAMA_ENDPOINT
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("errors_csv", help="Path to fonts_errors.csv from font_taxonomy.py")
    parser.add_argument("--output", default="fonts_ai_classified.csv",
                         help="Where to write AI-classified rows")
    parser.add_argument("--still-unresolved", default="fonts_still_unresolved.csv",
                         help="Where to write fonts the model also couldn't identify")
    parser.add_argument("--model", default="qwen2.5:1.5b",
                         help="Ollama model tag (must already be pulled). Default is a small "
                              "~1.5GB model that runs on constrained RAM; use llama3.1:8b+ "
                              "only if you have 16GB+ RAM free.")
    parser.add_argument("--batch-size", type=int, default=8,
                         help="Fonts per request. Kept small by default for low-RAM machines; "
                              "batches auto-split further on failure regardless.")
    parser.add_argument("--endpoint", default=OLLAMA_ENDPOINT,
                         help="Ollama chat endpoint (change if not running on localhost:11434)")
    parser.add_argument("--timeout", type=int, default=120,
                         help="Per-request timeout in seconds")
    parser.add_argument("--num-ctx", type=int, default=2048,
                         help="Context window cap passed to Ollama. Lower uses less RAM per "
                              "request; raise only if batches get truncated/malformed.")
    parser.add_argument("--keep-alive", default="10m",
                         help="How long Ollama keeps the model loaded between requests "
                              "(avoids reload cost per batch). Use '0' to unload immediately "
                              "if RAM is needed elsewhere between runs.")
    parser.add_argument("--retries", type=int, default=1,
                         help="Retries per batch before splitting it in half and recursing")
    args = parser.parse_args()
    OLLAMA_ENDPOINT = args.endpoint

    fonts = read_error_fonts(args.errors_csv)
    print(f"[info] {len(fonts)} unresolved fonts to classify with {args.model}", file=sys.stderr)

    ai_fieldnames = ["font", "classification", "style_tags", "source",
                      "is_monospace", "is_icon_font", "subsets", "notes", "confidence"]
    classified_rows = []
    unresolved_rows = []

    batches = list(chunked(fonts, args.batch_size))
    for i, batch in enumerate(batches, 1):
        print(f"[info] Batch {i}/{len(batches)} ({len(batch)} fonts)...", file=sys.stderr)

        result, failed = classify_batch_adaptive(
            args.model, batch, args.timeout, args.num_ctx, args.keep_alive, args.retries)

        failed_names = set()
        for name, reason in failed:
            unresolved_rows.append({"font": name, "reason": reason})
            failed_names.add(normalize_key(name))

        if not result:
            continue

        returned = {normalize_key(item.get("font", "")): item for item in result
                    if isinstance(item, dict)}

        for name in batch:
            if normalize_key(name) in failed_names:
                continue  # already recorded via adaptive splitting
            item = returned.get(normalize_key(name))
            if item is None:
                unresolved_rows.append({"font": name,
                                         "reason": "Model response did not include this font"})
                continue

            classification = item.get("classification", "unknown")
            confidence = item.get("confidence", "low")

            if classification == "unknown" or not classification:
                unresolved_rows.append({"font": name,
                                         "reason": "Model did not recognize this font"})
                continue

            tags = item.get("style_tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(";") if t.strip()]

            classified_rows.append({
                "font": name,
                "classification": classification,
                "style_tags": ";".join(tags),
                "source": f"ollama-llm:{args.model}",
                "is_monospace": bool(item.get("is_monospace", classification == "monospace")),
                "is_icon_font": classification == "icon-font",
                "subsets": "",
                "notes": item.get("notes", ""),
                "confidence": confidence,
            })

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ai_fieldnames)
        writer.writeheader()
        writer.writerows(classified_rows)

    with open(args.still_unresolved, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["font", "reason"])
        writer.writeheader()
        writer.writerows(unresolved_rows)

    print(f"[done] AI-classified {len(classified_rows)} fonts -> {args.output}", file=sys.stderr)
    print(f"[done] {len(unresolved_rows)} still unresolved -> {args.still_unresolved}", file=sys.stderr)
    if classified_rows:
        low_conf = sum(1 for r in classified_rows if r["confidence"] == "low")
        print(f"[info] {low_conf}/{len(classified_rows)} classified rows are 'low' confidence - "
              f"treat those as rough guesses, worth spot-checking.", file=sys.stderr)


if __name__ == "__main__":
    main()