from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from pathlib import Path
import os
import tempfile
import unittest

ROOT = Path(__file__).parent.parent
import sys

sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


DOMAIN_PATTERN = " */myapp/domain/* "
OUTER_LAYERS = "myapp.infra, requests"


def _ruleset(domain: str = DOMAIN_PATTERN, outer_layers: str | None = OUTER_LAYERS) -> str:
    properties = [f'            <property name="domain" value="{domain}" />']
    if outer_layers is not None:
        properties.append(f'            <property name="outer-layers" value="{outer_layers}" />')
    body = "\n".join(properties)
    return (
        '<ruleset name="team">\n'
        '    <rule ref="onion">\n'
        "        <properties>\n"
        f"{body}\n"
        "        </properties>\n"
        "    </rule>\n"
        "</ruleset>\n"
    )


class OnionAcceptanceTests(unittest.TestCase):
    def test_onion_without_domain_fails(self) -> None:
        status, report, errors = _analyze_source("def checkout():\n    return 1\n", _ruleset(domain=" , "))

        self.assertEqual((1, []), (status, report))
        self.assertEqual(
            "Error: DomainAction property 'domain' must name at least one path pattern.\n",
            errors,
        )

    def test_outer_import_rule_without_outer_layers_fails(self) -> None:
        status, report, errors = _analyze_source("def checkout():\n    return 1\n", _ruleset(outer_layers=None))

        self.assertEqual((1, []), (status, report))
        self.assertEqual(
            "Error: DomainOuterImport property 'outer-layers' must name at least one module.\n",
            errors,
        )

    def test_domain_function_that_reads_implicit_inputs_is_an_action(self) -> None:
        status, report, errors = _analyze_source(
            "import os\n"
            "import time as clock\n"
            "from datetime import datetime\n"
            "import random\n"
            "\n"
            "total = 0\n"
            "\n"
            "def add_to_total(amount):\n"
            "    return total + amount\n"
            "\n"
            "def snapshot(path):\n"
            "    with open(path) as handle:\n"
            "        body = handle.read()\n"
            "    return {\n"
            "        'at': clock.time(),\n"
            "        'user': os.environ.get('USER'),\n"
            "        'day': datetime.now(),\n"
            "        'seed': random.randint(1, 6),\n"
            "        'answer': input('?'),\n"
            "        'body': body,\n"
            "    }\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "9: DomainAction [priority 2] The function add_to_total() reads the implicit input total. "
                "Pass it as an argument instead.",
                "12: DomainAction [priority 2] The function snapshot() reads the implicit input open. "
                "Pass it as an argument instead.",
                "15: DomainAction [priority 2] The function snapshot() reads the implicit input time.time. "
                "Pass it as an argument instead.",
                "16: DomainAction [priority 2] The function snapshot() reads the implicit input os.environ. "
                "Pass it as an argument instead.",
                "17: DomainAction [priority 2] The function snapshot() reads the implicit input datetime.datetime.now. "
                "Pass it as an argument instead.",
                "18: DomainAction [priority 2] The function snapshot() reads the implicit input random.randint. "
                "Pass it as an argument instead.",
                "19: DomainAction [priority 2] The function snapshot() reads the implicit input input. "
                "Pass it as an argument instead.",
            ],
            report,
        )

    def test_domain_function_that_writes_implicit_outputs_is_an_action(self) -> None:
        status, report, errors = _analyze_source(
            "import logging\n"
            "import os\n"
            "from subprocess import run as run_command\n"
            "\n"
            "counter = 0\n"
            "\n"
            "def publish(path, text, items):\n"
            "    global counter\n"
            "    counter += 1\n"
            "    items.append(text)\n"
            "    print(text)\n"
            "    logging.info(text)\n"
            "    with open(path, mode='w') as handle:\n"
            "        handle.write(text)\n"
            "    run_command(['sync'])\n"
            "    os.remove(path)\n"
            "    return text\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "9: DomainAction [priority 2] The function publish() reads the implicit input counter. "
                "Pass it as an argument instead.",
                "9: DomainAction [priority 2] The function publish() writes the implicit output counter. "
                "Return it instead.",
                "10: DomainAction [priority 2] The function publish() writes the implicit output items. "
                "Return it instead.",
                "11: DomainAction [priority 2] The function publish() writes the implicit output print. "
                "Return it instead.",
                "12: DomainAction [priority 2] The function publish() writes the implicit output logging.info. "
                "Return it instead.",
                "13: DomainAction [priority 2] The function publish() writes the implicit output open. "
                "Return it instead.",
                "15: DomainAction [priority 2] The function publish() writes the implicit output subprocess.run. "
                "Return it instead.",
                "16: DomainAction [priority 2] The function publish() writes the implicit output os.remove. "
                "Return it instead.",
            ],
            report,
        )

    def test_argument_calls_follow_implicit_output_semantics(self) -> None:
        status, report, errors = _analyze_source(
            "def checkout(order, notify, repo):\n"
            "    notify(order)\n"
            "    repo.save(order)\n"
            "    repo.add(order)\n"
            "    return order\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "4: DomainAction [priority 2] The function checkout() writes the implicit output repo. "
                "Return it instead."
            ],
            report,
        )

    def test_self_reads_stay_quiet_and_self_writes_outside_constructors_are_actions(self) -> None:
        status, report, errors = _analyze_source(
            "class Basket:\n"
            "    def __init__(self, items):\n"
            "        self.items = list(items)\n"
            "    def __post_init__(self):\n"
            "        self.ready = True\n"
            "    def add(self, item):\n"
            "        self.items.append(item)\n"
            "        return len(self.items)\n"
            "    @classmethod\n"
            "    def empty(cls):\n"
            "        cls.created = 1\n"
            "        return cls([])\n"
            "\n"
            "class Tracked:\n"
            "    def __new__(cls):\n"
            "        cls.count = 1\n"
            "        return super().__new__(cls)\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "7: DomainAction [priority 2] The method Basket.add() writes the implicit output self.items. "
                "Return it instead.",
                "11: DomainAction [priority 2] The method Basket.empty() writes the implicit output cls.created. "
                "Return it instead.",
                "16: DomainAction [priority 2] The method Tracked.__new__() writes the implicit output cls.count. "
                "Return it instead.",
            ],
            report,
        )

    def test_the_same_action_outside_the_domain_layer_stays_quiet(self) -> None:
        source = "def checkout():\n    print('saved')\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            domain = _write(project / "src/myapp/domain/orders.py", source)
            outside = _write(project / "src/myapp/web/app.py", source)
            ruleset = _write_ruleset(project)
            status, stdout, errors = _run([str(project), "text", str(ruleset)])

        self.assertEqual((2, ""), (status, errors))
        self.assertIn("DomainAction", stdout)
        self.assertIn(domain.resolve().as_posix(), stdout)
        self.assertNotIn(outside.resolve().as_posix(), stdout)

    def test_import_time_io_is_an_action_and_plain_definitions_stay_quiet(self) -> None:
        status, report, errors = _analyze_source(
            "import json\n"
            "from typing import TypeAlias\n"
            "\n"
            "RATE = 0.2\n"
            "OrderId: TypeAlias = str\n"
            "\n"
            "class Order:\n"
            "    pass\n"
            "\n"
            "def checkout(amount):\n"
            "    return amount * RATE\n"
            "\n"
            "CONFIG = json.load(open('config.json'))\n"
            "print('boot')\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "13: DomainAction [priority 2] The module reads the implicit input open at import time. "
                "Move the action to the interaction layer.",
                "14: DomainAction [priority 2] The module writes the implicit output print at import time. "
                "Move the action to the interaction layer.",
            ],
            report,
        )

    def test_actions_spread_through_same_module_helpers_and_name_the_chain(self) -> None:
        status, report, errors = _analyze_source(
            "def save_report():\n"
            "    print('saved')\n"
            "\n"
            "def prepare():\n"
            "    save_report()\n"
            "\n"
            "def checkout():\n"
            "    prepare()\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "2: DomainAction [priority 2] The function save_report() writes the implicit output print. "
                "Return it instead.",
                "5: DomainAction [priority 2] The function prepare() calls save_report(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
                "8: DomainAction [priority 2] The function checkout() calls prepare(), "
                "which calls save_report(), which writes the implicit output print. "
                "Move the action to the interaction layer.",
            ],
            report,
        )

    def test_a_helper_called_several_times_is_reported_once_at_the_first_call(self) -> None:
        status, report, errors = _analyze_source(
            "def save_report():\n"
            "    print('saved')\n"
            "\n"
            "def checkout():\n"
            "    save_report()\n"
            "    save_report()\n"
            "    save_report()\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "2: DomainAction [priority 2] The function save_report() writes the implicit output print. "
                "Return it instead.",
                "5: DomainAction [priority 2] The function checkout() calls save_report(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
            ],
            report,
        )

    def test_self_method_calls_spread_inside_the_class(self) -> None:
        status, report, errors = _analyze_source(
            "class Order:\n"
            "    def save(self):\n"
            "        print('saved')\n"
            "    def checkout(self):\n"
            "        self.save()\n"
            "        self.save()\n"
            "    @classmethod\n"
            "    def load(cls):\n"
            "        print('loaded')\n"
            "    @classmethod\n"
            "    def fetch(cls):\n"
            "        cls.load()\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "3: DomainAction [priority 2] The method Order.save() writes the implicit output print. "
                "Return it instead.",
                "5: DomainAction [priority 2] The method Order.checkout() calls save(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
                "9: DomainAction [priority 2] The method Order.load() writes the implicit output print. "
                "Return it instead.",
                "12: DomainAction [priority 2] The method Order.fetch() calls load(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
            ],
            report,
        )

    def test_recursion_terminates_without_duplicate_findings(self) -> None:
        status, report, errors = _analyze_source(
            "def walk(node):\n"
            "    if node is None:\n"
            "        return 0\n"
            "    return walk(node.left) + node.value\n"
            "\n"
            "def descend(node):\n"
            "    print(node)\n"
            "    if node is not None:\n"
            "        descend(node.child)\n"
            "\n"
            "def left(value):\n"
            "    return right(value)\n"
            "\n"
            "def right(value):\n"
            "    print(value)\n"
            "    return left(value)\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "7: DomainAction [priority 2] The function descend() writes the implicit output print. "
                "Return it instead.",
                "9: DomainAction [priority 2] The function descend() calls descend(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
                "12: DomainAction [priority 2] The function left() calls right(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
                "15: DomainAction [priority 2] The function right() writes the implicit output print. "
                "Return it instead.",
                "16: DomainAction [priority 2] The function right() calls left(), which calls right(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
            ],
            report,
        )

    def test_lambdas_and_nested_functions_spread_actions(self) -> None:
        status, report, errors = _analyze_source(
            "def checkout():\n"
            "    def save_report():\n"
            "        print('saved')\n"
            "    action = lambda: save_report()\n"
            "    action()\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "3: DomainAction [priority 2] The function save_report() writes the implicit output print. "
                "Return it instead.",
                "4: DomainAction [priority 2] The function <lambda>() calls save_report(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
                "5: DomainAction [priority 2] The function checkout() calls action(), "
                "which calls save_report(), which writes the implicit output print. "
                "Move the action to the interaction layer.",
            ],
            report,
        )

    def test_a_comprehension_target_does_not_spread_to_the_outer_function(self) -> None:
        status, report, errors = _analyze_source(
            "def save_report():\n"
            "    print('saved')\n"
            "\n"
            "def checkout(items):\n"
            "    save_report()\n"
            "    return [save_report() for save_report in items]\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "2: DomainAction [priority 2] The function save_report() writes the implicit output print. "
                "Return it instead.",
                "5: DomainAction [priority 2] The function checkout() calls save_report(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
            ],
            report,
        )

    def test_one_import_statement_reports_each_outer_layer(self) -> None:
        status, report, errors = _analyze_source(
            "import requests, sqlalchemy\n"
            "from myapp import infra\n",
            _ruleset(outer_layers="myapp.infra, requests, sqlalchemy"),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "1: DomainOuterImport [priority 2] The module imports requests, which belongs to the outer layer "
                "requests. The domain layer must not know about the interaction layer.",
                "1: DomainOuterImport [priority 2] The module imports sqlalchemy, which belongs to the outer layer "
                "sqlalchemy. The domain layer must not know about the interaction layer.",
            ],
            report,
        )

    def test_unresolved_and_imported_calls_do_not_spread(self) -> None:
        status, report, errors = _analyze_source(
            "from myapp.pricing import save\n"
            "\n"
            "def checkout():\n"
            "    save()\n"
            "    missing()\n",
            _ruleset(),
        )

        self.assertEqual((0, [], ""), (status, report, errors))

    def test_domain_module_imports_of_outer_layers_are_reported(self) -> None:
        source = (
            "import requests\n"
            "from requests import get\n"
            "import myapp.infra.db as database\n"
            "\n"
            "def checkout():\n"
            "    import requests.sessions\n"
            "    return get\n"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            domain = _write(project / "src/myapp/domain/orders.py", source)
            outside = _write(project / "src/myapp/web/app.py", "import requests\n")
            ruleset = _write_ruleset(project)
            status, stdout, errors = _run([str(project), "text", str(ruleset)])

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "1: DomainOuterImport [priority 2] The module imports requests, which belongs to the outer layer "
                "requests. The domain layer must not know about the interaction layer.",
                "2: DomainOuterImport [priority 2] The module imports requests, which belongs to the outer layer "
                "requests. The domain layer must not know about the interaction layer.",
                "3: DomainOuterImport [priority 2] The module imports myapp.infra.db, which belongs to the outer "
                "layer myapp.infra. The domain layer must not know about the interaction layer.",
                "6: DomainOuterImport [priority 2] The module imports requests.sessions, which belongs to the "
                "outer layer requests. The domain layer must not know about the interaction layer.",
            ],
            _finding_lines(stdout, domain),
        )
        self.assertNotIn(outside.resolve().as_posix(), stdout)

    def test_relative_imports_use_the_package_and_stay_quiet_outside_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            _write(project / "src/myapp/__init__.py", "")
            _write(project / "src/myapp/domain/__init__.py", "")
            _write(project / "src/myapp/infra/__init__.py", "")
            packaged = _write(
                project / "src/myapp/domain/orders.py",
                "from ..infra import db\nfrom ..infra.db import connect\n",
            )
            loose = _write(
                project / "src/myapp/domain/loose.py",
                "from .helpers import tax\n",
            )
            unpackaged = _write(
                project / "pkg/myapp/domain/script.py",
                "from ..infra import db\n",
            )
            beyond = _write(
                project / "src/myapp/domain/beyond.py",
                "from ...infra import db\n",
            )
            ruleset = _write_ruleset(project)
            status, stdout, errors = _run([str(project), "text", str(ruleset)])

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "1: DomainOuterImport [priority 2] The module imports myapp.infra, which belongs to the outer "
                "layer myapp.infra. The domain layer must not know about the interaction layer.",
                "2: DomainOuterImport [priority 2] The module imports myapp.infra.db, which belongs to the outer "
                "layer myapp.infra. The domain layer must not know about the interaction layer.",
            ],
            _finding_lines(stdout, packaged),
        )
        self.assertNotIn(loose.resolve().as_posix(), stdout)
        self.assertNotIn(unpackaged.resolve().as_posix(), stdout)
        self.assertNotIn(beyond.resolve().as_posix(), stdout)

    def test_type_checking_imports_count(self) -> None:
        status, report, errors = _analyze_source(
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from myapp.infra.db import Session\n",
            _ruleset(),
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "4: DomainOuterImport [priority 2] The module imports myapp.infra.db, which belongs to the outer "
                "layer myapp.infra. The domain layer must not know about the interaction layer."
            ],
            report,
        )

    def test_findings_do_not_depend_on_the_scan_root_or_working_directory(self) -> None:
        source = "def checkout():\n    print('saved')\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            _write(project / "src/myapp/domain/orders.py", source)
            _write(project / "src/myapp/web/app.py", source)
            ruleset = _write_ruleset(project)
            from_root = _absolute_findings(*_run_in(project, [".", "text", str(ruleset)]), project)
            from_src = _absolute_findings(*_run_in(project, ["src", "text", str(ruleset)]), project)
            from_subdir = _absolute_findings(
                *_run_in(project / "src" / "myapp", [str(project), "text", str(ruleset)]),
                project / "src" / "myapp",
            )

        self.assertEqual(from_root, from_src)
        self.assertEqual(from_root, from_subdir)
        self.assertEqual(1, len(from_root[2]))
        self.assertIn("DomainAction", from_root[2][0])

    def test_suppression_waives_the_line_and_still_spreads(self) -> None:
        source = (
            "def save_report():\n"
            "    # messpy-disable-next-line DomainAction\n"
            "    print('saved')\n"
            "\n"
            "# messpy-disable DomainAction\n"
            "def hidden():\n"
            "    print('hidden')\n"
            "# messpy-enable DomainAction\n"
            "\n"
            "def checkout():\n"
            "    save_report()\n"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            path = _write(project / "src/myapp/domain/orders.py", source)
            ruleset = _write_ruleset(project)
            status, stdout, errors = _run([str(path), "text", str(ruleset)])
            strict_status, strict_stdout, strict_errors = _run(
                [str(path), "text", str(ruleset), "--strict"]
            )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "11: DomainAction [priority 2] The function checkout() calls save_report(), "
                "which writes the implicit output print. Move the action to the interaction layer."
            ],
            _finding_lines(stdout, path),
        )
        self.assertEqual((2, ""), (strict_status, strict_errors))
        self.assertEqual(
            [
                "3: DomainAction [priority 2] [suppressed] The function save_report() writes the implicit output "
                "print. Return it instead.",
                "7: DomainAction [priority 2] [suppressed] The function hidden() writes the implicit output print. "
                "Return it instead.",
                "11: DomainAction [priority 2] The function checkout() calls save_report(), "
                "which writes the implicit output print. Move the action to the interaction layer.",
            ],
            _finding_lines(strict_stdout, path),
        )

    def test_rule_filters_select_each_onion_rule(self) -> None:
        source = "import requests\n\ndef checkout():\n    print('saved')\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            path = _write(project / "src/myapp/domain/orders.py", source)
            ruleset = _write_ruleset(project)
            disabled = _run([str(path), "text", str(ruleset), "--disable", "DomainOuterImport"])
            only_action = _run([str(path), "text", str(ruleset), "--only", "DomainAction"])
            enabled_import = _run([str(path), "text", str(ruleset), "--enable", "DomainOuterImport"])
            above = _run([str(path), "text", str(ruleset), "--minimumpriority", "3"])

        self.assertEqual(2, disabled[0])
        self.assertIn("DomainAction", disabled[1])
        self.assertNotIn("DomainOuterImport", disabled[1])
        self.assertEqual(2, only_action[0])
        self.assertIn("DomainAction", only_action[1])
        self.assertNotIn("DomainOuterImport", only_action[1])
        self.assertEqual(2, enabled_import[0])
        self.assertIn("DomainOuterImport", enabled_import[1])
        self.assertNotIn("DomainAction", enabled_import[1])
        self.assertEqual((0, "", ""), above)

    def test_every_report_format_includes_the_finding(self) -> None:
        source = "def checkout():\n    print('saved')\n"
        formats = ["text", "json", "xml", "html", "sarif", "checkstyle", "github", "gitlab"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            path = _write(project / "src/myapp/domain/orders.py", source)
            ruleset = _write_ruleset(project)
            results = {
                report_format: _run([str(path), report_format, str(ruleset)])
                for report_format in formats
            }

        for report_format, (status, stdout, errors) in results.items():
            with self.subTest(report_format=report_format):
                self.assertEqual(2, status)
                self.assertEqual("", errors)
                self.assertIn("DomainAction", stdout)


def _analyze_source(source: str, ruleset_text: str) -> tuple[int, list[str], str]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        project = Path(temporary_directory)
        path = _write(project / "src/myapp/domain/orders.py", source)
        ruleset = _write(project / "team.xml", ruleset_text)
        status, stdout, errors = _run([str(path), "text", str(ruleset)])
    return status, _finding_lines(stdout, path), errors


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _write_ruleset(project: Path) -> Path:
    return _write(project / "team.xml", _ruleset())


def _run(arguments: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    status = run(arguments, stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def _run_in(directory: Path, arguments: list[str]) -> tuple[int, str, str]:
    with _working_directory(directory):
        return _run(arguments)


@contextmanager
def _working_directory(directory: Path):
    previous = Path.cwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous)


def _finding_lines(report: str, path: Path) -> list[str]:
    prefix = f"{path.resolve().as_posix()}:"
    return [line.removeprefix(prefix) for line in report.splitlines() if line.startswith(prefix)]


def _absolute_findings(status: int, report: str, errors: str, cwd: Path) -> tuple[int, str, list[str]]:
    findings = []
    for line in report.splitlines():
        location, _separator, message = line.partition(": ")
        file_text, line_number = location.rsplit(":", 1)
        file_path = Path(file_text)
        if not file_path.is_absolute():
            file_path = cwd / file_path
        findings.append(f"{file_path.resolve().as_posix()}:{line_number}: {message}")
    return status, errors, findings


if __name__ == "__main__":
    unittest.main()
