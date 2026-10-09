from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    import messpy.rulesets as rulesets
    from scan_profile import FORMATS, RULESETS, run_command, run_scan


def fuzz_public_api(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    mode = fdp.ConsumeIntInRange(0, 3)

    if mode == 0:
        # Fuzz source code analysis with combinations of rulesets, formats, and flags
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

    elif mode == 1:
        # Fuzz XML ruleset loading
        xml_content = fdp.ConsumeBytes(sys.maxsize)
        with TemporaryDirectory() as temporary_directory:
            xml_file = Path(temporary_directory) / "custom_ruleset.xml"
            xml_file.write_bytes(xml_content)
            try:
                rulesets.select_rules(
                    rulesets.RuleSelection(
                        rulesets=(str(xml_file),),
                        minimum_priority=fdp.ConsumeIntInRange(1, 5),
                        maximum_priority=fdp.ConsumeIntInRange(1, 5),
                    )
                )
            except rulesets.RulesetError:
                pass

    elif mode == 2:
        # Fuzz CLI argument parsing and error handling
        arg_count = fdp.ConsumeIntInRange(0, 10)
        args = []
        for _ in range(arg_count):
            args.append(fdp.ConsumeUnicode(30))
        run_command(args)

    elif mode == 3:
        # Fuzz multi-file analysis & directory recursion
        file_count = fdp.ConsumeIntInRange(1, 4)
        report_format = fdp.PickValueInList(FORMATS)
        ruleset = fdp.PickValueInList(RULESETS)
        with TemporaryDirectory() as temporary_directory:
            temp_path = Path(temporary_directory)
            for i in range(file_count):
                sub_file = temp_path / f"file_{i}.py"
                sub_bytes = fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 200))
                sub_file.write_bytes(sub_bytes)
            run_command([str(temp_path), report_format, ruleset])


def main() -> None:
    atheris.Setup(sys.argv, fuzz_public_api)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
