"""
Second-pass fixer for fonts_scraped.csv rows that are STILL blank after
fix_empty_fonts.py: JS-rendered sites where fonts only exist after
JavaScript runs. Requires font_worker.py in the same directory.

Setup (run once):
    pip install playwright pandas requests certifi cssutils
    playwright install chromium

Usage:
    python fix_js_rendered_fonts.py

---------------------------------------------------------------------------
Why this runs each domain as a subprocess instead of one shared browser
---------------------------------------------------------------------------
Earlier versions kept one long-lived browser/page in-process and relied on
Playwright's own goto() timeout to bound each domain. In practice a
domain occasionally hangs past that timeout anyway - typically a
network-level condition (e.g. a firewall/proxy silently dropping packets
instead of cleanly refusing the connection) that doesn't produce an
error for Playwright to catch and time out on. When that happens
in-process, there is no way to recover except killing the whole script.

This version runs font_worker.py - which handles exactly ONE domain and
always exits - as a subprocess per domain, with a hard wall-clock
timeout enforced by the OS (SIGKILL on the whole process group, so any
Chromium child processes die too, not just the Python wrapper). If a
domain hangs, only that subprocess dies; the driver moves on to the next
domain immediately. This is strictly slower (each domain pays Chromium's
~1-2s startup cost, since we can't cheaply share a browser across
subprocess boundaries) but it's the only way to guarantee the run itself
can never get stuck.

Behavior mirrors fix_empty_fonts.py: only rows where font1/font2/font3
are ALL still blank are touched; everything else is left exactly as-is.
Progress is saved incrementally, log goes to fix_js_rendered_fonts.log,
and per-domain status is also printed live to the console.
---------------------------------------------------------------------------
"""

import json
import logging
import os
import random
import signal
import subprocess
import sys
import time

import pandas as pd

LOG_FILE = "fix_js_rendered_fonts.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

SCRAPED_CSV = "fonts_scraped.csv"
SAVE_EVERY = 10
HARD_TIMEOUT_SEC = 45  # wall-clock cap per domain; worker's own soft
                        # timeouts (see font_worker.py) stay well under this
INTER_DOMAIN_DELAY_RANGE = (0.4, 1.2)

WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "font_worker.py")


def run_worker(domain):
    """Run font_worker.py for a single domain with a hard kill timeout.

    Returns (result_dict_or_None, error_string_or_None).
    """
    kwargs = dict(
        args=[sys.executable, WORKER_SCRIPT, domain],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # POSIX: put the worker in its own process group so a timeout kill
    # takes down any Chromium child processes it spawned too, not just
    # the Python wrapper (Chromium would otherwise be left as an orphan).
    if os.name == "posix":
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(**kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=HARD_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return None, f"Hard timeout - killed after {HARD_TIMEOUT_SEC}s"

    if proc.returncode != 0:
        return None, f"Worker exited {proc.returncode}: {stderr.strip()[:200]}"

    try:
        last_line = stdout.strip().splitlines()[-1]
        return json.loads(last_line), None
    except Exception as e:
        return None, f"Bad worker output: {e} (stdout: {stdout[:200]!r})"


def is_blank_row(row):
    return not (row.get("font1") or row.get("font2") or row.get("font3"))


def main():
    if not os.path.exists(SCRAPED_CSV):
        raise SystemExit(f"{SCRAPED_CSV} not found in the current directory.")
    if not os.path.exists(WORKER_SCRIPT):
        raise SystemExit(f"font_worker.py not found next to this script ({WORKER_SCRIPT}).")

    df = pd.read_csv(SCRAPED_CSV, dtype=str, keep_default_na=False)
    for col in ("font1", "font2", "font3"):
        if col not in df.columns:
            df[col] = ""

    blank_mask = df.apply(is_blank_row, axis=1)
    blank_indices = df.index[blank_mask].tolist()
    total = len(blank_indices)
    logger.info("%d rows still blank; retrying with a headless browser (subprocess mode)", total)
    print(f"{total} rows still blank; retrying with a headless browser (subprocess mode)", flush=True)

    updated = 0
    still_blank = 0

    for i, idx in enumerate(blank_indices):
        domain = str(df.at[idx, "domain"]).strip()
        if not domain:
            continue

        print(f"[{i+1}/{total}] {domain} ...", end=" ", flush=True)
        result, run_error = run_worker(domain)

        if run_error is not None:
            print(f"FAILED ({run_error[:80]})", flush=True)
            logger.info("Still failing for %s: %s", domain, run_error)
            still_blank += 1
        elif result.get("error"):
            print(f"FAILED ({str(result['error'])[:80]})", flush=True)
            logger.info("Still failing for %s: %s", domain, result["error"])
            still_blank += 1
        else:
            font1, font2, font3 = result["font1"], result["font2"], result["font3"]
            df.at[idx, "font1"] = font1
            df.at[idx, "font2"] = font2
            df.at[idx, "font3"] = font3
            updated += 1
            print(f"fixed -> {font1} | {font2} | {font3}", flush=True)
            logger.info("Fixed %s -> %s | %s | %s", domain, font1, font2, font3)

        if updated and updated % SAVE_EVERY == 0:
            df.to_csv(SCRAPED_CSV, index=False)
            logger.info("Progress saved (%d updated so far)", updated)

        time.sleep(random.uniform(*INTER_DOMAIN_DELAY_RANGE))

    df.to_csv(SCRAPED_CSV, index=False)
    logger.info(
        "Done. Fixed %d rows, %d still blank, out of %d retried.",
        updated, still_blank, total,
    )
    print(
        f"\nDone. Fixed {updated} rows, {still_blank} still blank "
        f"(see {LOG_FILE} for details).",
        flush=True,
    )


if __name__ == "__main__":
    main()