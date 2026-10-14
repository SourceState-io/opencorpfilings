"""Run the one-filing workflow over a declared issuer sample and label each outcome.

Example:
    python benchmarks/qualify.py benchmarks/qualification_sample_v2.json --out qualify.jsonl

`qualification_sample.json` is the 2026-10-08 sample as run; it names national routes
retired since, so rerunning it is not that run.

The sample file names, per route, the issuers and forms to run. Each issuer and
form runs `provider_workflow.py` in its own process with a timeout, so one hung
source cannot stall the run. Routes run in parallel, except routes that share a
source host (`host` in the sample), which run one after another. Issuers within
a route always run sequentially to respect source pacing.

The labels are deterministic; deciding a route's tier from them is a reviewed
judgement recorded in BENCHMARKS.md, not something this script asserts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from datetime import date
from pathlib import Path

WORKFLOW = Path(__file__).with_name("provider_workflow.py")
SOURCE_OUTAGE = {"SourceUnavailableError", "RateLimitError"}
TEXT_BEARING = {"text/html", "application/xhtml+xml", "application/zip"}


# Pre-registered 2026-10-09 (BENCHMARKS.md, "Route qualification v2").
MIN_REPORT_CHARACTERS = 20_000
MIN_PRINTABLE_RATIO = 0.9
# Interim: a half-year report can be ~365 + 60 days old (v2 found 304 too tight, 2026-10-09).
MAX_PERIOD_AGE_DAYS = {"annual": 548, "interim": 425, "quarterly": 213}


def label(record: dict, *, today: date | None = None) -> str:
    """One outcome per row: pass, no_filing, source_unavailable, a content failure, or fail_<stage>."""
    if record.get("status") == "error":
        if record.get("error_type") == "FilingNotFoundError":
            return "no_filing"
        if record.get("error_type") in SOURCE_OUTAGE:
            return "source_unavailable"
        return f"fail_{record.get('failed_stage', 'unknown')}"
    if record.get("status") != "ok":
        return "fail_unknown"
    if not record.get("provenance") or not record.get("original_bytes"):
        return "fail_provenance"
    if record.get("amendment") is True and record.get("form") in MAX_PERIOD_AGE_DAYS:
        return "amendment_selected"
    if record.get("role") not in (None, "report"):
        return "wrong_document"
    text_bearing = record.get("media_type") in TEXT_BEARING
    if text_bearing and record.get("text_status") != "available":
        return "text_gap"
    if record.get("printable_ratio") is not None and record["printable_ratio"] < MIN_PRINTABLE_RATIO:
        return "unreadable_text"
    if text_bearing and (record.get("text_characters") or 0) < MIN_REPORT_CHARACTERS and "text_characters" in record:
        return "text_small"
    limit = MAX_PERIOD_AGE_DAYS.get(record.get("form"))
    if today is not None and limit is not None and record.get("period_end"):
        if (today - date.fromisoformat(record["period_end"])).days > limit:
            return "stale"
    return "pass"


def run_one(route: dict, issuer: dict, form: str, *, start: str | None, timeout: int) -> dict:
    command = [sys.executable, str(WORKFLOW), route["market"], issuer["id"], "--form", form, "--facts"]
    if route.get("source"):
        command += ["--source", route["source"]]
    if start:
        command += ["--start", start]
    base = {"route": route["route"], "issuer": issuer["id"], "issuer_class": issuer.get("class"), "form": form}
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {**base, "status": "error", "failed_stage": "timeout", "error_type": "Timeout",
                "outcome": "fail_timeout"}
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if not lines:
        record = {"status": "error", "failed_stage": "program", "error_type": "ProgramError",
                  "error": done.stderr.strip().splitlines()[-1][:300] if done.stderr.strip() else ""}
    else:
        record = json.loads(lines[-1])
    record = {**base, **record}
    record["outcome"] = label(record, today=date.today())
    return record


def run_route(route: dict, *, start: str | None, timeout: int, emit) -> list[dict]:
    rows = []
    for issuer in route["issuers"]:
        for form in route.get("forms", ["annual"]):
            row = run_one(route, issuer, form, start=route.get("start", start), timeout=timeout)
            emit(row)
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="JSONL file for every row")
    parser.add_argument("--routes", help="comma-separated subset of route names")
    parser.add_argument("--timeout", type=int, default=300, help="seconds per issuer and form")
    parser.add_argument("--workers", type=int, default=6, help="source hosts run in parallel")
    args = parser.parse_args()

    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    routes = sample["routes"]
    if args.routes:
        wanted = {name.strip() for name in args.routes.split(",")}
        routes = [route for route in routes if route["route"] in wanted]
    by_host: dict[str, list[dict]] = defaultdict(list)
    for route in routes:
        by_host[route.get("host", route["route"])].append(route)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    lock = Lock()
    with args.out.open("w", encoding="utf-8") as out:
        def emit(row: dict) -> None:
            with lock:
                _write(out, row)

        def _write(out, row: dict) -> None:
            out.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
            out.flush()
            print(f"{row['route']:>6} {row['issuer']:<28} {row['form']:<8} {row['outcome']}", flush=True)

        def run_host(host_routes: list[dict]) -> list[dict]:
            return [row for route in host_routes
                    for row in run_route(route, start=sample.get("start"), timeout=args.timeout, emit=emit)]

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = [row for host_rows in pool.map(run_host, by_host.values()) for row in host_rows]

    summary: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        summary[f"{row['route']}:{row['form']}"][row["outcome"]] += 1
    for key in sorted(summary):
        print(json.dumps({"summary": key, **summary[key]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
