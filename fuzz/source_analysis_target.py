from __future__ import annotations

from scan_profile import RULESETS, run_scan


def run_source_analysis(source_bytes: bytes) -> dict[str, int]:
    return {ruleset: run_scan(source_bytes, ruleset) for ruleset in RULESETS}
