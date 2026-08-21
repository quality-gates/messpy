from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    import messpy.cli as cli

RULESETS = [
    "codesize",
    "naming",
    "unusedcode",
    "cleancode",
    "design",
    "controversial",
    "opinionated",
    "python",
    "codesize,naming,unusedcode,cleancode,design,controversial,opinionated",
]

FORMATS = [
    "text",
    "xml",
    "json",
    "html",
    "ansi",
    "github",
    "gitlab",
    "checkstyle",
    "sarif",
]

NORMAL_EXIT_STATUSES = frozenset({0, 1, 2})


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

    source_bytes = fdp.ConsumeBytes(sys.maxsize)

    with TemporaryDirectory() as temporary_directory:
        source_file = Path(temporary_directory) / "source.py"
        source_file.write_bytes(source_bytes)
        stdout = StringIO()
        stderr = StringIO()
        try:
            status = cli.run([str(source_file), report_format, ruleset, *flags], stdout, stderr)
            if status not in NORMAL_EXIT_STATUSES:
                raise AssertionError(
                    f"Unexpected MessPy exit status: {status}\n"
                    f"Format: {report_format}, Ruleset: {ruleset}, Flags: {flags}\n"
                    f"Stderr: {stderr.getvalue()}"
                )
        except Exception as error:
            # Any uncaught exception escaping cli.run is a bug!
            raise


def main() -> None:
    atheris.Setup(sys.argv, fuzz_source_analysis)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
