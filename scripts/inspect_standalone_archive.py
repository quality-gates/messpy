from __future__ import annotations

import argparse
from pathlib import Path
import tarfile

from release_contract import ARCHITECTURES, STABLE_VERSION


EXPECTED_MEMBERS = {"LICENSE": 0o644, "messpy": 0o755}


def inspect(archive_path: Path, version: str, architecture: str) -> None:
    if STABLE_VERSION.fullmatch(version) is None:
        raise AssertionError("version must match MAJOR.MINOR.PATCH")
    if architecture not in ARCHITECTURES:
        raise AssertionError(f"unsupported architecture: {architecture}")
    expected_name = f"messpy_{version}_darwin_{architecture}.tar.gz"
    if archive_path.name != expected_name:
        raise AssertionError(f"archive must be named {expected_name}")

    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise AssertionError("archive contains duplicate member names")
        if set(names) != set(EXPECTED_MEMBERS):
            raise AssertionError(f"archive members must be {sorted(EXPECTED_MEMBERS)}")
        for member in members:
            if not member.isfile():
                raise AssertionError(f"archive member is not a regular file: {member.name}")
            if member.mode != EXPECTED_MEMBERS[member.name]:
                raise AssertionError(f"archive member has the wrong mode: {member.name}")
            if member.uid != 0 or member.gid != 0:
                raise AssertionError(f"archive member has a non-root owner: {member.name}")
            if member.size == 0:
                raise AssertionError(f"archive member is empty: {member.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("version")
    parser.add_argument("architecture")
    arguments = parser.parse_args()
    try:
        inspect(arguments.archive, arguments.version, arguments.architecture)
    except (AssertionError, OSError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
