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


def fuzz_cli_options(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)

    with TemporaryDirectory() as temporary_directory:
        source_file = Path(temporary_directory) / "test.py"
        source_file.write_text("def foo(x):\n    return x + 1\n", encoding="utf-8")

        arg_count = fdp.ConsumeIntInRange(0, 12)
        args = []
        for _ in range(arg_count):
            choice = fdp.ConsumeIntInRange(0, 5)
            if choice == 0:
                args.append(str(source_file))
            elif choice == 1:
                args.append(fdp.PickValueInList(["text", "xml", "json", "html", "ansi", "github", "gitlab", "checkstyle", "sarif", "invalid_fmt"]))
            elif choice == 2:
                args.append(fdp.PickValueInList(["codesize", "naming", "unusedcode", "cleancode", "design", "controversial", "opinionated", "python", "bogus"]))
            elif choice == 3:
                opt = fdp.PickValueInList([
                    "--strict", "--verbose", "--ignore-tests", "--ignore-errors-on-exit", "--ignore-violations-on-exit",
                    "--help", "--version", "-h", "-v",
                    "--color=auto", "--color=always", "--color=never", "--color=invalid",
                    "--minimum-priority=1", "--minimum-priority=5", "--minimum-priority=0", "--minimum-priority=6", "--minimum-priority=abc",
                    "--maximum-priority=1", "--maximum-priority=5", "--maximum-priority=0", "--maximum-priority=6", "--maximum-priority=xyz",
                    "--only=ShortClassName", "--enable=LongClassName", "--disable=ShortVariable",
                    "--suffixes=.py,.pyi", "--suffixes=py,pyi", "--suffixes=",
                    "--exclude=foo,bar", "--exclude=",
                ])
                args.append(opt)
            else:
                args.append(fdp.ConsumeUnicode(25))

        stdout = StringIO()
        stderr = StringIO()
        try:
            status = cli.run(args, stdout, stderr)
            if status not in NORMAL_EXIT_STATUSES:
                raise AssertionError(f"Unexpected exit status {status} for CLI args: {args}")
        except (cli.CliError, rulesets.RulesetError):
            pass


def main() -> None:
    atheris.Setup(sys.argv, fuzz_cli_options)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
