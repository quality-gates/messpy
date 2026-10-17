#!/bin/sh
# Replay checkout-dependent GitLab fingerprints for one syntax error.
# Usage: MESS=/path/to/messpy ./replay-gitlab-fingerprint.sh
set -eu
mess=${MESS:-messpy}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/left/pkg" "$work/right/pkg"
printf '%s\n' 'def broken(' > "$work/left/pkg/broken.py"
cp "$work/left/pkg/broken.py" "$work/right/pkg/broken.py"
(cd "$work/left" && "$mess" pkg gitlab python > gitlab.json || true)
(cd "$work/right" && "$mess" pkg gitlab python > gitlab.json || true)
python3 - "$work" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
left = json.loads((root / "left" / "gitlab.json").read_text())
right = json.loads((root / "right" / "gitlab.json").read_text())
print("equal", left[0]["fingerprint"] == right[0]["fingerprint"])
print("left", left[0]["description"])
print("right", right[0]["description"])
PY
