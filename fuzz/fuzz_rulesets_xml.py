from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    import messpy.rulesets as rulesets
    from scan_profile import run_scan


def fuzz_xml_rulesets(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    num_files = fdp.ConsumeIntInRange(1, 3)

    with TemporaryDirectory() as temporary_directory:
        dir_path = Path(temporary_directory)
        xml_files = []
        for i in range(num_files):
            xml_path = dir_path / f"ruleset_{i}.xml"
            xml_bytes = fdp.ConsumeBytes(fdp.ConsumeIntInRange(10, 500))
            xml_path.write_bytes(xml_bytes)
            xml_files.append(str(xml_path))

        try:
            only = [fdp.ConsumeUnicode(15) for _ in range(fdp.ConsumeIntInRange(0, 2))]
            enable = [fdp.ConsumeUnicode(15) for _ in range(fdp.ConsumeIntInRange(0, 2))]
            disable = [fdp.ConsumeUnicode(15) for _ in range(fdp.ConsumeIntInRange(0, 2))]
            rulesets.select_rules(
                rulesets.RuleSelection(
                    rulesets=tuple(xml_files),
                    only=tuple(only),
                    enable=tuple(enable),
                    disable=tuple(disable),
                    minimum_priority=fdp.ConsumeIntInRange(1, 5),
                    maximum_priority=fdp.ConsumeIntInRange(1, 5),
                )
            )
        except rulesets.RulesetError:
            pass

        # Test cli.run with this ruleset XML file on a simple source file
        run_scan(b"x = 1\n", xml_files[0])


def main() -> None:
    atheris.Setup(sys.argv, fuzz_xml_rulesets)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
