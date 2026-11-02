#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo 'Usage: sh replay.sh /absolute/path/to/messpy /absolute/path/to/scratch' >&2
    exit 1
fi
cli=$1
scratch=$2
mkdir -p "$scratch/src" "$scratch/reports"
cd "$scratch"
printf '%s\n' 'def fetch_customer(customer_identifier):' '    # TODO remove debug' '    return customer_identifier' '' '# messpy-disable-next-line DevelopmentCodeFragment' '# TODO intentional' > src/app.py
printf '%s\n' 'def broken(' > src/broken.py
printf '%s\n' 'def test_example():' '    # TODO test fixture' '    return 1' > src/test_app.py
printf '%s\n' '<ruleset name="team">' '  <rule ref="python"><exclude name="DevelopmentCodeFragment" /></rule>' '  <rule ref="LongVariable"><properties><property name="maximum" value="12" /></properties></rule>' '</ruleset>' > team.xml
run() {
    printf '\n$ messpy'
    printf ' %s' "$@"
    printf '\n'
    status=0
    "$cli" "$@" 2>&1 || status=$?
    printf 'exit=%s\n' "$status"
}
run src text python --ignore-tests
run src text python --ignore-tests --ignore-errors-on-exit --strict
run src text team.xml --ignore-tests --ignore-errors-on-exit
printf '%s\n' '<ruleset><rule ref="NoSuchRule" /></ruleset>' > bad.xml
printf 'sentinel\n' > reports/gate.json
run src json bad.xml --reportfile reports/gate.json
printf 'report after invalid policy: '; head -n 1 reports/gate.json
run src json python --ignore-tests --reportfile reports/gate.json
printf 'saved report after processing error:\n'; python3 -m json.tool reports/gate.json
printf '%s\n' 'def fixed():' '    return 1' > src/broken.py
run src json python --ignore-tests --reportfile reports/gate.json
printf 'saved report after correction:\n'; python3 -m json.tool reports/gate.json
run src text python
printf '%s\n' 'def fetch_customer(customer_identifier):' '    return customer_identifier' '' '# messpy-disable-next-line DevelopmentCodeFragment' '# TODO intentional' > src/app.py
run src text python --ignore-tests
run src text python --ignore-tests --strict
run src json python --ignore-tests --reportfile reports/gate.json
printf 'saved report after removing the finding:\n'; python3 -m json.tool reports/gate.json
printf '%s\n' '<ruleset name="team">' '  <rule ref="python"><exclude name="DevelopmentCodeFragment" /></rule>' '  <rule ref="LongVariable"><properties><property name="maximum" value="30" /></properties></rule>' '</ruleset>' > team.xml
run src text team.xml --ignore-tests
