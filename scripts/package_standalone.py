from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import re
import tarfile


STABLE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ARCHITECTURES = {"amd64", "arm64"}


def package(executable: Path, license_file: Path, output: Path, epoch: int) -> None:
    if not executable.is_file() or not license_file.is_file():
        raise ValueError("the executable and LICENSE must be regular files")
    if epoch < 0:
        raise ValueError("the source date must not be negative")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw_archive:
        with gzip.GzipFile(fileobj=raw_archive, mode="wb", filename="", mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive:
                _add_file(archive, license_file, "LICENSE", 0o644, epoch)
                _add_file(archive, executable, "messpy", 0o755, epoch)


def _add_file(
    archive: tarfile.TarFile, source: Path, name: str, mode: int, epoch: int
) -> None:
    information = tarfile.TarInfo(name)
    information.size = source.stat().st_size
    information.mode = mode
    information.uid = 0
    information.gid = 0
    information.mtime = epoch
    with source.open("rb") as contents:
        archive.addfile(information, contents)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("license", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("version")
    parser.add_argument("architecture", choices=sorted(ARCHITECTURES))
    parser.add_argument("source_date_epoch", type=int)
    arguments = parser.parse_args()
    if STABLE_VERSION.fullmatch(arguments.version) is None:
        parser.error("version must match MAJOR.MINOR.PATCH")
    output = arguments.output_directory / (
        f"messpy_{arguments.version}_darwin_{arguments.architecture}.tar.gz"
    )
    package(arguments.executable, arguments.license, output, arguments.source_date_epoch)


if __name__ == "__main__":
    main()
