from __future__ import annotations

from configparser import ConfigParser
from email.parser import Parser
from pathlib import Path
import re
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
    configuration = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]
    version_path = Path(configuration["tool"]["hatch"]["version"]["path"])
    version_match = re.search(
        r'^__version__\s*=\s*["\u0027]([^"\u0027]+)["\u0027]',
        version_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if version_match is None:
        raise AssertionError("version source does not define __version__")
    expected_version = version_match.group(1)
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
        _single_name(names, ".dist-info/licenses/LICENSE")
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        if metadata["Name"] != project["name"] or metadata["Version"] != expected_version:
            raise AssertionError("wheel metadata has the wrong project identity")
        if metadata["Requires-Python"] != project["requires-python"]:
            raise AssertionError("wheel metadata has the wrong Python requirement")
        entry_points = ConfigParser()
        entry_points.read_string(archive.read(entry_points_name).decode("utf-8"))
        if entry_points.get("console_scripts", "messpy") != "messpy.cli:main":
            raise AssertionError("wheel does not expose the messpy command")

    with tarfile.open(source_distributions[0], "r:gz") as archive:
        archive_names = set(archive.getnames())
        names = {name.split("/", 1)[1] for name in archive_names if "/" in name}
        expected = {"LICENSE", "pyproject.toml", *(f"src/{name}" for name in PACKAGE_FILES)}
        missing = expected - names
        if missing:
            raise AssertionError(f"source distribution is missing files: {sorted(missing)}")
        package_info_name = _single_name(archive_names, "/PKG-INFO")
        package_info_file = archive.extractfile(package_info_name)
        if package_info_file is None:
            raise AssertionError("source distribution PKG-INFO cannot be read")
        package_info = Parser().parsestr(package_info_file.read().decode("utf-8"))
        if package_info["Name"] != project["name"] or package_info["Version"] != expected_version:
            raise AssertionError("source distribution metadata has the wrong project identity")


def _single_name(names: set[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one wheel member ending in {suffix}")
    return matches[0]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect_distribution.py DIST_DIRECTORY")
    inspect(Path(sys.argv[1]))
