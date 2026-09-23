from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.cli import run


class ExplicitnessAcceptanceTests(unittest.TestCase):
    def test_function_that_reads_a_module_variable_has_an_implicit_input(self) -> None:
        status, report, errors = _analyze(
            "total = 0\n"
            "\n"
            "def add_to_total(amount):\n"
            "    return total + amount\n",
            "explicitness",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "4: ImplicitInput [priority 3] The function add_to_total() reads the implicit input total. "
                "Pass it as an argument instead."
            ],
            report,
        )

    def test_local_variable_annotations_are_not_reads(self) -> None:
        status, report, errors = _analyze(
            "Vector = list\n"
            "settings = {}\n"
            "default = []\n"
            "\n"
            "def build():\n"
            "    result: Vector = default\n"
            "    pending: settings\n"
            "    return result\n",
            "explicitness",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "6: ImplicitInput [priority 3] The function build() reads the implicit input default. "
                "Pass it as an argument instead."
            ],
            report,
        )

    def test_function_that_uses_only_arguments_definitions_and_constants_is_explicit(self) -> None:
        status, report, errors = _analyze(
            "import math\n"
            "from typing import Final\n"
            "\n"
            "TAX_RATE = 0.1\n"
            "rounding: Final = 2\n"
            "\n"
            "class Receipt:\n"
            "    pass\n"
            "\n"
            "def helper(value):\n"
            "    return value\n"
            "\n"
            "def calc_tax(amount):\n"
            "    taxed = helper(amount) * TAX_RATE\n"
            "    Receipt()\n"
            "    return round(math.floor(taxed), rounding)\n",
            "explicitness",
        )

        self.assertEqual((0, [], ""), (status, report, errors))

    def test_closure_that_reads_enclosing_variables_has_implicit_inputs(self) -> None:
        status, report, errors = _analyze(
            "def make_counter(start):\n"
            "    step = 2\n"
            "    def helper(value):\n"
            "        return value\n"
            "    def advance(amount):\n"
            "        return helper(start + step + amount)\n"
            "    return advance\n",
            "explicitness",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "6: ImplicitInput [priority 3] The function advance() reads the implicit input start. "
                "Pass it as an argument instead.",
                "6: ImplicitInput [priority 3] The function advance() reads the implicit input step. "
                "Pass it as an argument instead.",
            ],
            report,
        )

    def test_nested_definition_reads_data_when_the_enclosing_function_runs(self) -> None:
        status, report, errors = _analyze(
            "counter = 0\n"
            "registry = []\n"
            "\n"
            "def with_lambda_default():\n"
            "    return lambda extra=counter: extra\n"
            "\n"
            "def with_nested_default():\n"
            "    def inner(*, extra=counter):\n"
            "        return extra\n"
            "    return inner\n"
            "\n"
            "def with_nested_decorator():\n"
            "    @registry.append\n"
            "    def inner():\n"
            "        return 1\n"
            "    return inner\n"
            "\n"
            "def with_class_base():\n"
            "    class Local(registry[0]):\n"
            "        pass\n"
            "    return Local\n",
            "explicitness",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                f"{line}: ImplicitInput [priority 3] The function {function}() reads the implicit input {name}. "
                "Pass it as an argument instead."
                for line, function, name in [
                    (5, "with_lambda_default", "counter"),
                    (8, "with_nested_default", "counter"),
                    (13, "with_nested_decorator", "registry"),
                    (19, "with_class_base", "registry"),
                ]
            ],
            report,
        )

    def test_function_that_reads_the_environment_clock_or_randomness_has_implicit_inputs(self) -> None:
        status, report, errors = _analyze(
            "import os\n"
            "import time as clock\n"
            "from datetime import datetime\n"
            "import random\n"
            "\n"
            "def snapshot(path):\n"
            "    import sys\n"
            "    with open(path) as handle:\n"
            "        body = handle.read()\n"
            "    return {\n"
            "        'at': clock.time(),\n"
            "        'user': os.environ.get('USER'),\n"
            "        'day': datetime.now(),\n"
            "        'seed': random.randint(1, 6),\n"
            "        'args': sys.argv,\n"
            "        'answer': input('?'),\n"
            "        'body': body,\n"
            "    }\n"
            "\n"
            "def shadowed(input, clock):\n"
            "    random = 4\n"
            "    return input(clock.time() + random)\n",
            "ImplicitInput",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                f"{line}: ImplicitInput [priority 3] The function snapshot() reads the implicit input {name}. "
                "Pass it as an argument instead."
                for line, name in [
                    (8, "open"),
                    (11, "time.time"),
                    (12, "os.environ"),
                    (13, "datetime.datetime.now"),
                    (14, "random.randint"),
                    (15, "sys.argv"),
                    (16, "input"),
                ]
            ],
            report,
        )

    def test_function_that_changes_outside_state_or_its_arguments_has_implicit_outputs(self) -> None:
        status, report, errors = _analyze(
            "counter = 0\n"
            "cache = {}\n"
            "REGISTRY = []\n"
            "\n"
            "def record(item, seen, label):\n"
            "    global counter\n"
            "    counter += 1\n"
            "    cache[item] = True\n"
            "    REGISTRY.append(item)\n"
            "    seen.add(item)\n"
            "    del label.text\n"
            "    return item\n"
            "\n"
            "def make_tally():\n"
            "    total = 0\n"
            "    def bump(amount):\n"
            "        nonlocal total\n"
            "        total += amount\n"
            "        return total\n"
            "    return bump\n"
            "\n"
            "class Basket:\n"
            "    def add(self, item):\n"
            "        self.items.append(item)\n"
            "        return self\n"
            "\n"
            "def build(items):\n"
            "    items = list(items)\n"
            "    items.sort()\n"
            "    result = {}\n"
            "    result['count'] = len(items)\n"
            "    return result\n",
            "ImplicitOutput",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                f"{line}: ImplicitOutput [priority 3] The function {function}() writes the implicit output {name}. "
                "Return it instead."
                for line, function, name in [
                    (7, "record", "counter"),
                    (8, "record", "cache"),
                    (9, "record", "REGISTRY"),
                    (10, "record", "seen"),
                    (11, "record", "label.text"),
                    (18, "bump", "total"),
                ]
            ],
            report,
        )

    def test_function_that_prints_logs_or_touches_the_system_has_implicit_outputs(self) -> None:
        status, report, errors = _analyze(
            "import logging\n"
            "import os\n"
            "import shutil\n"
            "import sys\n"
            "from subprocess import run as run_command\n"
            "\n"
            "def publish(path, text):\n"
            "    print(text)\n"
            "    sys.stderr.write(text)\n"
            "    with open(path, mode='a') as handle:\n"
            "        handle.write(text)\n"
            "    logging.info(text)\n"
            "    run_command(['sync'])\n"
            "    os.remove(path)\n"
            "    shutil.rmtree(path)\n"
            "    return text\n"
            "\n"
            "def quiet(print, path):\n"
            "    print(path)\n"
            "    with open(path) as handle:\n"
            "        return handle.read()\n",
            "ImplicitOutput",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                f"{line}: ImplicitOutput [priority 3] The function publish() writes the implicit output {name}. "
                "Return it instead."
                for line, name in [
                    (8, "print"),
                    (9, "sys.stderr"),
                    (10, "open"),
                    (12, "logging.info"),
                    (13, "subprocess.run"),
                    (14, "os.remove"),
                    (15, "shutil.rmtree"),
                ]
            ],
            report,
        )

    def test_common_idioms_that_keep_data_local_are_explicit(self) -> None:
        status, report, errors = _analyze(
            "try:\n"
            "    import _winapi\n"
            "except ImportError:\n"
            "    _winapi = None\n"
            "\n"
            "def close(handle, *args, **kwargs):\n"
            "    kwargs.pop('timeout', None)\n"
            "    return _winapi.CloseHandle(handle)\n"
            "\n"
            "def decorate(label):\n"
            "    def wrapper(*args):\n"
            "        return args\n"
            "    wrapper.cache = {}\n"
            "    return wrapper\n"
            "\n"
            "class Registry(type):\n"
            "    def register(mcls, subclass):\n"
            "        mcls.registry.add(subclass)\n"
            "        return subclass\n"
            "    def __new__(mcls, name, bases, namespace):\n"
            "        mcls.count = 1\n"
            "        return super().__new__(mcls, name, bases, namespace)\n"
            "\n"
            "class Ordered(dict):\n"
            "    def clear(self):\n"
            "        dict.clear(self)\n"
            "        return self\n",
            "explicitness",
        )

        self.assertEqual((0, [], ""), (status, report, errors))

    def test_output_names_the_changed_object_and_ignores_module_constants(self) -> None:
        status, report, errors = _analyze(
            "import subprocess\n"
            "import sys\n"
            "\n"
            "def install(path):\n"
            "    sys.path.insert(0, path)\n"
            "    sys.modules['plugin'] = None\n"
            "    sys.stdout = None\n"
            "    try:\n"
            "        return subprocess.run(['ls'], stdout=subprocess.PIPE, check=True)\n"
            "    except subprocess.CalledProcessError:\n"
            "        return None\n",
            "ImplicitOutput",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                f"{line}: ImplicitOutput [priority 3] The function install() writes the implicit output {name}. "
                "Return it instead."
                for line, name in [(5, "sys.path"), (6, "sys.modules"), (7, "sys.stdout"), (9, "subprocess.run")]
            ],
            report,
        )

    def test_strict_ruleset_treats_instance_and_class_state_as_implicit(self) -> None:
        status, report, errors = _analyze(
            "class Basket:\n"
            "    created = 0\n"
            "    def __init__(self, items):\n"
            "        self.items = list(items)\n"
            "        self.total = 0\n"
            "    def add(self, item):\n"
            "        self.items.append(item)\n"
            "        self.total += item.price\n"
            "        return self.describe()\n"
            "    def describe(self):\n"
            "        return f'{len(self.items)} items'\n"
            "    @classmethod\n"
            "    def empty(cls):\n"
            "        cls.created += 1\n"
            "        return cls([])\n"
            "    @staticmethod\n"
            "    def price(item):\n"
            "        return item.price\n",
            "strictexplicitness",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                f"{line}: {rule} [priority 3] The method Basket.{method}() {message}"
                for line, rule, method, message in [
                    (7, "ImplicitInstanceInput", "add", "reads the implicit input self.items. Pass it as an argument instead."),
                    (7, "ImplicitInstanceOutput", "add", "writes the implicit output self.items. Return it instead."),
                    (8, "ImplicitInstanceInput", "add", "reads the implicit input self.total. Pass it as an argument instead."),
                    (8, "ImplicitInstanceOutput", "add", "writes the implicit output self.total. Return it instead."),
                    (11, "ImplicitInstanceInput", "describe", "reads the implicit input self.items. Pass it as an argument instead."),
                    (14, "ImplicitInstanceInput", "empty", "reads the implicit input cls.created. Pass it as an argument instead."),
                    (14, "ImplicitInstanceOutput", "empty", "writes the implicit output cls.created. Return it instead."),
                ]
            ],
            report,
        )

    def test_strict_ruleset_treats_class_state_changed_in_new_as_an_output(self) -> None:
        status, report, errors = _analyze(
            "class Tracked:\n"
            "    def __new__(cls):\n"
            "        cls.count = 1\n"
            "        instance = super().__new__(cls)\n"
            "        instance.ready = True\n"
            "        return instance\n",
            "ImplicitInstanceOutput",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "3: ImplicitInstanceOutput [priority 3] The method Tracked.__new__() writes the implicit output "
                "cls.count. Return it instead."
            ],
            report,
        )

    def test_default_ruleset_leaves_instance_state_alone(self) -> None:
        status, report, errors = _analyze(
            "counter = 0\n"
            "\n"
            "class Basket:\n"
            "    def add(self, item):\n"
            "        global counter\n"
            "        counter += 1\n"
            "        self.items.append(item)\n"
            "        return self\n",
            "explicitness",
        )

        self.assertEqual((2, ""), (status, errors))
        self.assertEqual(
            [
                "6: ImplicitInput [priority 3] The method Basket.add() reads the implicit input counter. "
                "Pass it as an argument instead.",
                "6: ImplicitOutput [priority 3] The method Basket.add() writes the implicit output counter. "
                "Return it instead.",
            ],
            report,
        )


def _analyze(source: str, ruleset: str) -> tuple[int, list[str], str]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "subject.py"
        path.write_text(source, encoding="utf-8")
        stdout = StringIO()
        stderr = StringIO()
        status = run([str(path), "text", ruleset], stdout, stderr)
    prefix = f"{path.resolve().as_posix()}:"
    report = [line.removeprefix(prefix) for line in stdout.getvalue().splitlines()]
    return status, report, stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
