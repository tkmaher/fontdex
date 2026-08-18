#!/usr/bin/env python3
"""
gemini_enrich_classified.py

Runs the same Gemini-based enrichment as gemini_classify_fonts.py, but on
the fonts that are ALREADY classified (fonts_taxonomy.csv) instead of the
error list. Many of those rows - especially ones resolved via the generic-
descriptor, curated-dictionary, or Google Fonts tiers - have a correct
`classification` but thin or empty `style_tags`/`notes`. This script asks
Gemini to add richer style tags and a real description for each one.

IMPORTANT: this does NOT let the model re-decide `classification`. That
field came from a verified source (Google Fonts API, curated dictionary,
or a literal generic descriptor) and is more trustworthy than model
recall - overwriting it with an LLM guess would be a downgrade, not an
enrichment. The model is given the existing classification as context and
asked only to add style_tags and a description; classification passes
through unchanged.

After enriching, this script merges the result with fonts_ai_classified.csv
(the fonts previously resolved via Gemini from the error list) into one
combined CSV, so you end up with a single file covering both the originally
classified fonts and the AI-resolved ones, all with consistent detail.

SETUP: same as gemini_classify_fonts.py
    export GEMINI_API_KEY=your_key_here   (free key: https://aistudio.google.com/apikey)

USAGE:
    python gemini_enrich_classified.py \
        fonts_taxonomy.csv fonts_ai_classified.csv \
        --enriched-output fonts_taxonomy_enriched.csv \
        --merged-output fonts_ai_classified.csv \
        --model gemini-3.1-flash-lite --batch-size 30

If gemini-3.1-flash-lite errors out by the time you run this, check
https://ai.google.dev/gemini-api/docs/models for the current free-tier
model list and pass --model to override.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

STYLE_TAG_VOCAB = [
    "grotesque", "neo-grotesque", "geometric", "humanist", "gothic",
    "old-style", "transitional", "didone", "slab-serif", "condensed",
    "extended", "expanded", "rounded", "compressed", "typewriter",
    "black-weight", "thin-weight", "variable-font",
]

SYSTEM_PROMPT = f"""You are a typography expert enriching an existing font
database with more detail.

For each font you are given its name AND its already-verified
`classification` (e.g. serif, sans-serif, monospace) - this classification
is correct and already confirmed; do NOT change it or second-guess it.

Your only job is to ADD detail:
- "style_tags": a list of specific style descriptors beyond the base
  classification. Suggested (not exhaustive) vocabulary:
  {", ".join(STYLE_TAG_VOCAB)}
  Use any that genuinely apply, or a short lowercase-hyphenated tag of your
  own if none fit. Return an empty list if you don't know the font well
  enough to add real detail - do not pad with generic/uninformative tags.
- "description": one or two sentences of real detail - foundry, designer,
  release era, notable usage, or distinguishing visual characteristics.
  If you don't specifically recognize this font, say so plainly (e.g.
  "Not a widely documented typeface; no further detail available.")
  rather than inventing plausible-sounding facts.
- "confidence": "high" (you know this specific font well), "medium" (you
  recognize the general family/style but aren't certain of specifics), or
  "low" (you don't really recognize it and have little to add).

Respond with a JSON array, one object per font, in this exact shape:
[
  {{"font": "<echo the exact name given>", "style_tags": ["...", "..."],
    "description": "...", "confidence": "high"}}
]
"""


def normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def read_rows(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def call_gemini(api_key: str, model: str, batch_payload: list, timeout: int) -> list:
    url = f"{GEMINI_ENDPOINT_TEMPLATE.format(model=model)}?key={api_key}"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{
            "parts": [{"text": "Enrich these fonts:\n" + json.dumps(batch_payload)}]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            raise RuntimeError(
                f"HTTP 404: model '{model}' not found or no longer available. "
                f"Check https://ai.google.dev/gemini-api/docs/models and pass --model "
                f"to override. Detail: {detail[:200]}") from exc
        raise RuntimeError(f"HTTP {exc.code}: {detail[:300]}") from exc

    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected response shape: {json.dumps(body)[:300]}") from exc

    text = strip_code_fences(text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))

    if isinstance(parsed, dict):
        parsed = parsed.get("fonts") or parsed.get("results") or list(parsed.values())[0]

    return parsed


def merge_tags(existing: str, new_tags: list) -> str:
    existing_set = [t.strip() for t in (existing or "").split(";") if t.strip()]
    seen = {t.lower() for t in existing_set}
    for tag in new_tags:
        tag = tag.strip()
        if tag and tag.lower() not in seen:
            existing_set.append(tag)
            seen.add(tag.lower())
    return ";".join(existing_set)


def merge_notes(existing: str, description: str) -> str:
    existing = (existing or "").strip()
    description = (description or "").strip()
    if not description or description.lower() in existing.lower():
        return existing
    if not existing:
        return description
    return f"{existing} {description}"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("taxonomy_csv", help="Path to fonts_taxonomy.csv (already classified)")
    parser.add_argument("ai_classified_csv", help="Path to fonts_ai_classified.csv, to merge with when done")
    parser.add_argument("--enriched-output", default="fonts_taxonomy_enriched.csv",
                         help="Where to write the enriched (but not yet merged) taxonomy")
    parser.add_argument("--merged-output", default="fonts_classified_merged.csv",
                         help="Where to write the final merged file (default overwrites "
                              "fonts_ai_classified.csv with the union of both lists)")
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY", ""))
    parser.add_argument("--model", default="gemini-3.1-flash-lite")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--rpm", type=float, default=14)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("[error] No API key. Get a free one at https://aistudio.google.com/apikey "
                  "and pass --api-key or set GEMINI_API_KEY.")

    taxonomy_fields, taxonomy_rows = read_rows(args.taxonomy_csv)
    if "font" not in taxonomy_fields or "classification" not in taxonomy_fields:
        sys.exit("[error] taxonomy CSV needs at least 'font' and 'classification' columns")

    print(f"[info] Enriching {len(taxonomy_rows)} already-classified fonts with {args.model}",
          file=sys.stderr)

    batches = list(chunked(taxonomy_rows, args.batch_size))
    print(f"[info] {len(batches)} requests planned at {args.rpm} RPM "
          f"(~{len(batches) / args.rpm:.1f} min)", file=sys.stderr)

    min_interval = 60.0 / args.rpm
    last_call = 0.0
    enrichment_by_key = {}  # normalized font -> {style_tags, description, confidence}

    for i, batch in enumerate(batches, 1):
        elapsed = time.time() - last_call
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        print(f"[info] Batch {i}/{len(batches)} ({len(batch)} fonts)...", file=sys.stderr)

        batch_payload = [
            {"font": row["font"], "classification": row.get("classification", "")}
            for row in batch
        ]

        result = None
        last_exc = None
        backoff = 5.0
        for attempt in range(args.retries + 1):
            try:
                last_call = time.time()
                result = call_gemini(args.api_key, args.model, batch_payload, args.timeout)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = backoff if "429" in str(exc) else 2.0
                print(f"[warn] Batch {i} attempt {attempt + 1} failed: {exc} "
                      f"(retrying in {wait:.0f}s)", file=sys.stderr)
                time.sleep(wait)
                backoff *= 2

        if result is None:
            print(f"[error] Batch {i} failed after retries ({last_exc}); "
                  f"those rows keep their original values, unenriched.", file=sys.stderr)
            continue

        for item in result:
            if not isinstance(item, dict):
                continue
            key = normalize_key(item.get("font", ""))
            if key:
                enrichment_by_key[key] = item

    # --- apply enrichment on top of the original rows, in place -----------
    enriched_fields = taxonomy_fields if "confidence" in taxonomy_fields else taxonomy_fields + ["confidence"]
    enriched_rows = []
    enriched_count = 0

    for row in taxonomy_rows:
        new_row = {k: row.get(k, "") for k in enriched_fields}
        item = enrichment_by_key.get(normalize_key(row["font"]))

        if item is None:
            new_row.setdefault("confidence", "verified")
            enriched_rows.append(new_row)
            continue

        tags = item.get("style_tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(";") if t.strip()]
        description = item.get("description", "")
        model_confidence = item.get("confidence", "low")

        new_row["style_tags"] = merge_tags(row.get("style_tags", ""), tags)
        new_row["notes"] = merge_notes(row.get("notes", ""), description)
        # classification is untouched - it stays whatever the verified source said
        existing_source = row.get("source", "")
        if f"ai-enriched:{args.model}" not in existing_source:
            new_row["source"] = (existing_source + f";ai-enriched:{args.model}").lstrip(";")
        # confidence reflects trust in the ENRICHMENT (tags/notes), not the
        # underlying classification, which remains verified regardless
        new_row["confidence"] = f"verified-classification;enrichment-{model_confidence}"

        if tags or (description and model_confidence != "low"):
            enriched_count += 1
        enriched_rows.append(new_row)

    with open(args.enriched_output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=enriched_fields)
        writer.writeheader()
        writer.writerows(enriched_rows)

    print(f"[done] Enriched {enriched_count}/{len(taxonomy_rows)} rows with new "
          f"detail -> {args.enriched_output}", file=sys.stderr)

    # --- merge with fonts_ai_classified.csv --------------------------------
    ai_fields, ai_rows = read_rows(args.ai_classified_csv)
    merged_fields = ["font", "classification", "style_tags", "source",
                      "is_monospace", "is_icon_font", "subsets", "notes", "confidence"]

    merged_rows = []
    for row in enriched_rows:
        merged_rows.append({k: row.get(k, "") for k in merged_fields})
    for row in ai_rows:
        merged_rows.append({k: row.get(k, "") for k in merged_fields})

    with open(args.merged_output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=merged_fields)
        writer.writeheader()
        writer.writerows(merged_rows)

    print(f"[done] Merged {len(enriched_rows)} enriched + {len(ai_rows)} AI-classified "
          f"= {len(merged_rows)} total rows -> {args.merged_output}", file=sys.stderr)


if __name__ == "__main__":
    main()