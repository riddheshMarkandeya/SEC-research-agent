"""
Re-runnable check: does real cached SEC companyconcept data contain any
entry that xbrl_facts.get_metric's entry validation (_entry_defect) would
drop? Offline, reads XBRL_CACHE_DIR only.

Expected result: 0 dropped. A nonzero count means real SEC data has a
shape the validation refuses, which changes which entry get_metric picks
for that ticker/tag, so look at the listed files before trusting answers.
Re-run after adding tickers or refreshing the cache.

Frame files (frame_*.json) and discover_tags' companyfacts files have a
different payload and are skipped. Files, entries and drops are all
reported so a 0 can't come from scanning nothing.

Usage: python tests/manual/verify_xbrl_entry_validation.py
"""

import json
import sys
from collections import Counter

from sec_agent.config import XBRL_CACHE_DIR
from sec_agent.sources.xbrl_facts import _entry_defect


def main() -> int:
    files = sorted(
        p for p in XBRL_CACHE_DIR.glob("*.json")
        if not p.name.startswith("frame_") and not p.name.endswith("_companyfacts.json")
    )
    scanned_entries = 0
    reasons: Counter[str] = Counter()
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("units", {}).get("USD", [])
        scanned_entries += len(entries)
        file_reasons = Counter(d for d in map(_entry_defect, entries) if d is not None)
        if file_reasons:
            print(f"[DROP] {path.name}: {dict(file_reasons)}")
        reasons.update(file_reasons)

    dropped = sum(reasons.values())
    print(f"\nfiles={len(files)} entries={scanned_entries} dropped={dropped} reasons={dict(reasons)}")
    if not files or not scanned_entries:
        print("[FAIL] nothing scanned -- is the XBRL cache populated?")
        return 1
    print("[OK] every cached entry is usable" if dropped == 0 else "[CHECK] real data has dropped entries")
    return 0 if dropped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
