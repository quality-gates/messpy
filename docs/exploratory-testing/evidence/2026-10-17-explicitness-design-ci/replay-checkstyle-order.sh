#!/bin/sh
# Replay checkstyle placing a processing error between findings.
# Usage: MESS=/path/to/messpy ./replay-checkstyle-order.sh
set -eu
mess=${MESS:-messpy}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/src"
printf '%s\n' '# TODO: marker' > "$work/src/a_ok.py"
printf '%s\n' 'def broken(' > "$work/src/m_broken.py"
printf '%s\n' '# TODO: later' > "$work/src/z_ok.py"
cd "$work"
"$mess" src checkstyle python || true
