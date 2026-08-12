from __future__ import annotations

import gzip
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).parent.parent


class StandaloneArchiveAcceptanceTests(unittest.TestCase):
    def test_packager_creates_reproducible_safe_release_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            executable = temporary / "source-messpy"
            license_file = temporary / "source-license"
            first_output = temporary / "first"
            second_output = temporary / "second"
            executable.write_bytes(b"#!/bin/sh\necho 1.2.3\n")
            license_file.write_text("Example license\n", encoding="utf-8")
            command = [
                sys.executable,
                str(ROOT / "scripts" / "package_standalone.py"),
                str(executable),
                str(license_file),
            ]
            for output in [first_output, second_output]:
                result = subprocess.run(
                    [*command, str(output), "1.2.3", "arm64", "1700000000"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
            archive = first_output / "messpy_1.2.3_darwin_arm64.tar.gz"
            inspection = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "inspect_standalone_archive.py"),
                    str(archive),
                    "1.2.3",
                    "arm64",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            second_archive = second_output / archive.name

            self.assertEqual(0, inspection.returncode, inspection.stderr)
            self.assertEqual(archive.read_bytes(), second_archive.read_bytes())
            with tarfile.open(archive, "r:gz") as packaged:
                members = {member.name: member for member in packaged.getmembers()}
                executable_member = packaged.extractfile("messpy")
                license_member = packaged.extractfile("LICENSE")
                self.assertIsNotNone(executable_member)
                self.assertIsNotNone(license_member)
                self.assertEqual(0o755, members["messpy"].mode)
                self.assertEqual(0o644, members["LICENSE"].mode)
                self.assertEqual(executable.read_bytes(), executable_member.read())
                self.assertEqual(license_file.read_bytes(), license_member.read())

    def test_inspector_rejects_a_link_in_place_of_the_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = Path(temporary_directory) / "messpy_1.2.3_darwin_amd64.tar.gz"
            with archive.open("wb") as raw_archive:
                with gzip.GzipFile(fileobj=raw_archive, mode="wb", mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w") as packaged:
                        license_member = tarfile.TarInfo("LICENSE")
                        license_member.size = 1
                        license_member.mode = 0o644
                        packaged.addfile(license_member, _BytesReader(b"x"))
                        executable_member = tarfile.TarInfo("messpy")
                        executable_member.type = tarfile.SYMTYPE
                        executable_member.linkname = "/usr/bin/python3"
                        executable_member.mode = 0o755
                        packaged.addfile(executable_member)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "inspect_standalone_archive.py"),
                    str(archive),
                    "1.2.3",
                    "amd64",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("not a regular file", result.stderr)


class ReleaseWorkflowContractTests(unittest.TestCase):
    def test_standalone_release_and_homebrew_contract_is_explicit(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        expected_contract = [
            "validate-source-release@92b635fe61fb926a5b13c7c59f163c3cec3ca756",
            "publish-source-release@92b635fe61fb926a5b13c7c59f163c3cec3ca756",
            "git merge-base --is-ancestor",
            "python -m unittest discover -s tests",
            "pyinstaller-requirements-macos.txt",
            "--require-hashes",
            "macos-15-intel",
            "macos-15",
            "environment: homebrew",
            "tool: messpy",
        ]
        for required_text in expected_contract:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, workflow)
        unpinned_actions = re.findall(r"uses:\s+[^\s@]+@(v\d+|main|master)\b", workflow)
        self.assertEqual([], unpinned_actions)

    def test_pypi_publication_remains_oidc_protected(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("environment:\n      name: pypi", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("pypa/gh-action-pypi-publish@", workflow)
        self.assertNotIn("password:", workflow)


class _BytesReader:
    def __init__(self, contents: bytes) -> None:
        self._contents = contents
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._contents) - self._offset
        result = self._contents[self._offset : self._offset + size]
        self._offset += len(result)
        return result


if __name__ == "__main__":
    unittest.main()
