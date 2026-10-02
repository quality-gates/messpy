from __future__ import annotations

import sys
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    from scan_profile import FORMATS, RULESETS, run_scan


def fuzz_source_analysis(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    ruleset = fdp.PickValueInList(RULESETS)
    report_format = fdp.PickValueInList(FORMATS)

    flags = []
    if fdp.ConsumeBool():
        flags.append("--strict")
    if fdp.ConsumeBool():
        flags.append("--verbose")
    if fdp.ConsumeBool():
        flags.append(f"--color={fdp.PickValueInList(['auto', 'always', 'never'])}")
    if fdp.ConsumeBool():
        min_p = fdp.ConsumeIntInRange(1, 5)
        max_p = fdp.ConsumeIntInRange(min_p, 5)
        flags.append(f"--minimum-priority={min_p}")
        flags.append(f"--maximum-priority={max_p}")
    if fdp.ConsumeBool():
        flags.append("--ignore-tests")
    if fdp.ConsumeBool():
        flags.append("--ignore-errors-on-exit")
    if fdp.ConsumeBool():
        flags.append("--ignore-violations-on-exit")

    run_scan(fdp.ConsumeBytes(sys.maxsize), ruleset, report_format, flags)


def main() -> None:
    atheris.Setup(sys.argv, fuzz_source_analysis)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
