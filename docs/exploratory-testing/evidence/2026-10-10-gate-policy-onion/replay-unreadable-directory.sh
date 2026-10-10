#!/bin/sh
# Replay the unreadable-directory failure from this evidence directory.
# Restores permissions before exiting.
set -u
MESS="${MESS:-messpy}"
cd "$(dirname "$0")/j1"
mkdir -p runs
restore() {
    chmod 755 mixed/secret 2>/dev/null || true
    chmod 644 src/billing/locked-file.py 2>/dev/null || true
}
trap restore EXIT
restore

capture() {
    name="$1"
    shift
    set +e
    "$@" >"runs/$name.stdout.txt" 2>"runs/$name.stderr.txt"
    status=$?
    set -e
    printf '%s\n' "$status" >"runs/$name.status.txt"
    printf '%s status=%s\n' "$name" "$status"
}

echo '=== baseline: both directories readable ==='
capture baseline "$MESS" mixed text python

echo '=== locked child directory ==='
chmod 000 mixed/secret
capture locked "$MESS" mixed text python
capture locked-ignore "$MESS" mixed text python --ignore-errors-on-exit --reportfile runs/locked-ignore.json
capture two-paths "$MESS" "mixed/ok/visible.py,mixed/secret" text python
chmod 755 mixed/secret

echo '=== replay 2 ==='
capture baseline-2 "$MESS" mixed text python
chmod 000 mixed/secret
capture locked-2 "$MESS" mixed text python
chmod 755 mixed/secret

echo '=== contrast: unreadable file still reports the sibling ==='
chmod 000 src/billing/locked-file.py
capture file-contrast "$MESS" "mixed/ok/visible.py,src/billing/locked-file.py" text python
chmod 644 src/billing/locked-file.py

echo '=== captures ==='
for name in baseline locked locked-ignore two-paths baseline-2 locked-2 file-contrast; do
    printf '\n--- %s status=%s ---\n' "$name" "$(cat "runs/$name.status.txt")"
    echo 'stdout:'
    cat "runs/$name.stdout.txt"
    echo 'stderr:'
    cat "runs/$name.stderr.txt"
done
if [ -f runs/locked-ignore.json ]; then
    echo 'locked-ignore.json exists'
else
    echo 'locked-ignore.json absent'
fi
