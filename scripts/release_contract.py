from __future__ import annotations

import re


STABLE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ARCHITECTURES = frozenset({"amd64", "arm64"})
