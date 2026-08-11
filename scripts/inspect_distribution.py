from __future__ import annotations

from configparser import ConfigParser
from email.parser import Parser
from pathlib import Path
import sys
import tarfile
import tomllib
import zipfile


PACKAGE_FILES = {
    "messpy/__init__.py",
    "messpy/cli.py",
    "messpy/rulesets.py",
    "messpy/py.typed",
}


def inspect(directory: Path) -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    wheels = sorted(directory.glob("messpy-*.whl"))
    source_distributions = sorted(directory.glob("messpy-*.tar.gz"))
    if len(wheels) != 1 or len(source_distributions) != 1:
        raise AssertionError("expected exactly one messpy wheel and one source distribution")

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        missing = PACKAGE_FILES - names
        if missing:
            raise AssertionError(f"wheel is missing package files: {sorted(missing)}")
        metadata_name = _single_name(names, ".dist-info/METADATA")
        entry_points_name = _single_name(names, ".dist-info/entry_points.txt")
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        if metadata["Name"] != project["name"] or metadata["Version"] != project["version"]:
            raise AssertionError("wheel metadata has the wrong project identity")
        if metadata["Requires-Python"] != project["requires-python"]:
            raise AssertionError("wheel metadata has the wrong Python requirement")
        entry_points = ConfigParser()
        entry_points.read_string(archive.read(entry_points_name).decode("utf-8"))
        if entry_points.get("console_scripts", "messpy") != "messpy.cli:main":
            raise AssertionError("wheel does not expose the messpy command")

    with tarfile.open(source_distributions[0], "r:gz") as archive:
        names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
        expected = {"pyproject.toml", *(f"src/{name}" for name in PACKAGE_FILES)}
        missing = expected - names
        if missing:
            raise AssertionError(f"source distribution is missing files: {sorted(missing)}")


def _single_name(names: set[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one wheel member ending in {suffix}")
    return matches[0]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect_distribution.py DIST_DIRECTORY")
    inspect(Path(sys.argv[1]))
