#!/bin/sh
# Replay ElseExpression false positives on a live loop else.
# Usage: MESS=/path/to/messpy ./replay-live-loop-else.sh
set -eu
mess=${MESS:-messpy}
dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp "$dir/j2/src/review/live_else.py" "$work/live_else.py"
cp "$dir/j1/src/billing/async_else.py" "$work/async_else.py"
cd "$work"
echo "=== live_else.py ==="
"$mess" live_else.py text opinionated --only ElseExpression || true
echo "=== async_else.py ==="
"$mess" async_else.py text opinionated --only ElseExpression || true
