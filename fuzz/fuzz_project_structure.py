from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import atheris

with atheris.instrument_imports(include=["messpy"], enable_loader_override=False):
    import messpy.cli as cli
    import messpy.rulesets as rulesets

RULESETS = [
    "codesize",
    "naming",
    "unusedcode",
    "cleancode",
    "design",
    "controversial",
    "opinionated",
    "python",
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


def fuzz_project_structure(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)

    with TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory) / "project"
        project_root.mkdir()

        # Generate complex directory structure
        num_dirs = fdp.ConsumeIntInRange(1, 5)
        dirs = [project_root]
        for i in range(num_dirs):
            dname = fdp.PickValueInList(["src", "tests", "test", "pkg", ".venv", "__pycache__", "build", "dist", "deep/nested/pkg"])
            dpath = project_root / dname
            dpath.mkdir(parents=True, exist_ok=True)
            dirs.append(dpath)

        # Generate files in dirs
        num_files = fdp.ConsumeIntInRange(1, 8)
        for i in range(num_files):
            target_dir = fdp.PickValueInList(dirs)
            fname = fdp.PickValueInList(["module.py", "test_app.py", "app_test.py", "types.pyi", "data.txt", "empty.py", "weird.PY", "deep.py"])
            fpath = target_dir / fname
            content_type = fdp.ConsumeIntInRange(0, 3)
            if content_type == 0:
                fpath.write_text("x = 1\n", encoding="utf-8")
            elif content_type == 1:
                fpath.write_bytes(fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 200)))
            elif content_type == 2:
                fpath.write_text("def long_function():\n" + "    pass\n" * 150, encoding="utf-8")
            else:
                fpath.touch()

        # Symlinks if supported
        if fdp.ConsumeBool():
            symlink_path = project_root / "link_dir"
            target = fdp.PickValueInList(dirs)
            try:
                symlink_path.symlink_to(target, target_is_directory=True)
            except OSError:
                pass

        # Build CLI arguments
        report_format = fdp.PickValueInList(FORMATS)
        ruleset = fdp.PickValueInList(RULESETS)
        flags = []
        if fdp.ConsumeBool():
            flags.append("--ignore-tests")
        if fdp.ConsumeBool():
            flags.append("--strict")
        if fdp.ConsumeBool():
            flags.append("--verbose")
        if fdp.ConsumeBool():
            flags.append(f"--suffixes={fdp.PickValueInList(['.py', '.py,.pyi', 'py,pyi', '.py,.txt'])}")
        if fdp.ConsumeBool():
            flags.append(f"--exclude={fdp.PickValueInList(['pkg', 'test', 'dist', 'src/deep'])}")
        if fdp.ConsumeBool():
            report_file = project_root / "out_report.txt"
            flags.append(f"--reportfile={report_file}")

        stdout = StringIO()
        stderr = StringIO()
        try:
            status = cli.run([str(project_root), report_format, ruleset, *flags], stdout, stderr)
            if status not in NORMAL_EXIT_STATUSES:
                raise AssertionError(f"Unexpected exit status {status} for project scan")
        except (cli.CliError, rulesets.RulesetError):
            pass


def main() -> None:
    atheris.Setup(sys.argv, fuzz_project_structure)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
