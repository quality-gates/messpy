from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    import messpy.cli as cli
    import messpy.rulesets as rulesets

NORMAL_EXIT_STATUSES = frozenset({0, 1, 2})


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

        # Test load_rulesets directly
        try:
            loaded = rulesets.load_rulesets(xml_files)
            if loaded:
                only = [fdp.ConsumeUnicode(15) for _ in range(fdp.ConsumeIntInRange(0, 2))]
                enable = [fdp.ConsumeUnicode(15) for _ in range(fdp.ConsumeIntInRange(0, 2))]
                disable = [fdp.ConsumeUnicode(15) for _ in range(fdp.ConsumeIntInRange(0, 2))]
                try:
                    rulesets.filter_rules(
                        loaded,
                        only=only,
                        enable=enable,
                        disable=disable,
                        minimum_priority=fdp.ConsumeIntInRange(1, 5),
                        maximum_priority=fdp.ConsumeIntInRange(1, 5),
                    )
                except rulesets.RulesetError:
                    pass
        except rulesets.RulesetError:
            pass

        # Test cli.run with this ruleset XML file on a simple source file
        source_file = dir_path / "sample.py"
        source_file.write_text("x = 1\n", encoding="utf-8")
        stdout = StringIO()
        stderr = StringIO()
        try:
            status = cli.run([str(source_file), "text", xml_files[0]], stdout, stderr)
            if status not in NORMAL_EXIT_STATUSES:
                raise AssertionError(f"Unexpected exit status {status} for XML ruleset run")
        except (cli.CliError, rulesets.RulesetError):
            pass


def main() -> None:
    atheris.Setup(sys.argv, fuzz_xml_rulesets)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
