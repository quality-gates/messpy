from __future__ import annotations

import ast
import gc
from pathlib import Path
import symtable
import sys
import tempfile
import unittest
import weakref
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy import analyzer
from messpy.analyzer import Finding, ProcessingError, analyze, analyze_source
from messpy.rulesets import load_rulesets


def _findings(source: str, ruleset: str, rule_name: str) -> tuple[Finding, ...]:
    rules = [rule for rule in load_rulesets([ruleset]) if rule.name == rule_name]
    result = analyze_source(source, rules=rules, filename="state.py")
    if result.errors:
        raise AssertionError(result.errors)
    return result.findings


class AnalyzerTransitionTests(unittest.TestCase):
    def test_file_decode_failure_does_not_prevent_later_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            broken = directory / "a.py"
            valid = directory / "b.py"
            broken.write_bytes(b"# coding: no-such-encoding\n")
            valid.write_text("def compute():\n    unused = 1\n", encoding="utf-8")
            result = analyze([directory], rules=load_rulesets(["unusedcode"]))
        self.assertEqual([broken.resolve()], [error.path for error in result.errors])
        self.assertEqual([("UnusedLocalVariable", 2)], [(finding.rule_name, finding.line) for finding in result.findings])

    def test_overlapping_roots_keep_first_discovery_error_and_one_source(self) -> None:
        path = Path("same.py")
        first = ProcessingError(path, 1, "first")
        later = ProcessingError(path, 2, "later")
        with mock.patch.object(analyzer, "_source_files_under", side_effect=[({path}, [first]), ({path}, [later])]):
            files, errors = analyzer._source_files([Path("a"), Path("b")], {".py"}, [], False)
        self.assertEqual([path], files)
        self.assertEqual([first], errors)

    def test_discovery_releases_prior_root_results_as_it_scans_duplicate_roots(self) -> None:
        path = Path("same.py")
        root_results: list[weakref.ReferenceType[set[Path]]] = []
        peak_live_results = 0

        def discover(*args, **kwargs):
            nonlocal peak_live_results
            gc.collect()
            found = {path}
            root_results.append(weakref.ref(found))
            peak_live_results = max(peak_live_results, sum(result() is not None for result in root_results))
            return found, []

        roots = [Path("root")] * 8
        with mock.patch.object(analyzer, "_source_files_under", side_effect=discover):
            files, errors = analyzer._source_files(roots, {".py"}, [], False)
        self.assertEqual([path], files)
        self.assertEqual([], errors)
        self.assertLessEqual(peak_live_results, 2)

    def test_comprehension_iterable_reads_precede_rebinding_and_stop_at_shadow(self) -> None:
        source = "[item for item in values for item in item]"
        node = ast.parse(source, mode="eval").body
        self.assertTrue(analyzer._comprehension_target_is_used(node, 0, "item"))
        source = "[item for item in values for item in others]"
        node = ast.parse(source, mode="eval").body
        self.assertFalse(analyzer._comprehension_target_is_used(node, 0, "item"))
        self.assertTrue(analyzer._comprehension_target_is_used(node, 1, "item"))

    def test_same_line_symbol_tables_are_consumed_by_matching_parameters(self) -> None:
        source = "left = lambda first: first; right = lambda second: 0\n"
        scopes = analyzer._function_scopes(source, ast.parse(source))
        self.assertEqual(
            [(('first',), frozenset({'first'})), (('second',), frozenset())],
            [(table.get_parameters(), used) for _, table, used in scopes],
        )
        self.assertIsNot(scopes[0][1], scopes[1][1])

    def test_nested_region_depth_and_same_line_directives(self) -> None:
        source = (
            "# messpy-enable Example\n"
            "value = 1 # messpy-disable Example\n"
            "# messpy-disable Example\n"
            "value = 2\n"
            "# messpy-enable Example\n"
            "value = 3\n"
            "# messpy-enable Example\n"
            "value = 4\n"
        )
        findings = [Finding(Path("state.py"), line, "Example", 1, "example") for line in (2, 4, 6, 8)]
        result = analyzer._apply_suppressions(source, ast.parse(source), findings)
        self.assertEqual([False, True, True, False], [finding.suppressed for finding in result])

    def test_scheduled_suppression_skips_unrelated_comment_findings_and_wraps_header(self) -> None:
        source = (
            "# messpy-disable-next-line Example\n"
            "# unrelated\n"
            "@decorate\n"
            "def compute(\n"
            "    value,\n"
            "):\n"
            "    pass\n"
        )
        findings = [Finding(Path("state.py"), line, rule, 1, "example") for line, rule in ((2, "Other"), (4, "Example"), (5, "Example"), (7, "Example"))]
        result = analyzer._apply_suppressions(source, ast.parse(source), findings)
        self.assertEqual([False, True, True, False], [finding.suppressed for finding in result])

    def test_global_first_binding_identity_and_final_status_survive_later_writes(self) -> None:
        findings = _findings(
            "from typing import Final\n"
            "unchanged = []\n"
            "changed = []\n"
            "changed = []\n"
            "fixed: Final = []\n"
            "fixed.append(1)\n"
            "def local():\n"
            "    unchanged = []\n"
            "    unchanged.append(1)\n"
            "def mutate():\n"
            "    global changed\n"
            "    changed = []\n",
            "design", "GlobalVariable",
        )
        self.assertEqual([("changed", 3)], [(finding.context, finding.line) for finding in findings])

    def test_lexical_shadow_lookup_uses_class_bindings_only_in_class_body(self) -> None:
        quiet = _findings(
            "shared = []\n"
            "class Holder:\n    shared = []\n    shared.append(1)\n",
            "design", "GlobalVariable",
        )
        noisy = _findings(
            "shared = []\n"
            "class Holder:\n    shared = []\n"
            "    def update(self):\n        shared.append(1)\n",
            "design", "GlobalVariable",
        )
        self.assertEqual((), quiet)
        self.assertEqual([("shared", 1)], [(finding.context, finding.line) for finding in noisy])

    def test_unknown_private_access_and_exports_never_recover_precision(self) -> None:
        for uncertain in ("getattr(object(), field_name)\n", "__all__ = discover()\n__all__ = ['Other']\n"):
            with self.subTest(uncertain=uncertain):
                findings = _findings(
                    uncertain + "class Holder:\n    def __init__(self):\n        self._unused = 1\n",
                    "unusedcode", "UnusedPrivateField",
                )
                self.assertEqual((), findings)
        findings = _findings(
            "class Holder:\n"
            "    def __init__(self):\n        self._unused = 1\n        self._unused = 2\n",
            "unusedcode", "UnusedPrivateField",
        )
        self.assertEqual([3], [finding.line for finding in findings])

    def test_boolean_suffix_is_shared_by_both_branches_but_not_nested_definitions(self) -> None:
        for source, expected in (
            ("if condition:\n    return True\nreturn False", True),
            ("if condition:\n    return True", False),
            ("if condition:\n    pass\nelse:\n    return False\nreturn True", True),
            ("def nested():\n    return 0\nreturn True", True),
            ("while condition:\n    return True\nreturn False", False),
        ):
            with self.subTest(source=source):
                self.assertEqual(expected, analyzer._all_paths_return_boolean(ast.parse(source).body))

    def test_visitor_inheritance_converges_when_descendants_appear_first(self) -> None:
        source = (
            "import ast\n"
            "class Root(ast.NodeVisitor):\n    pass\n"
            "class Middle(Root):\n    pass\n"
            "class Leaf(Middle):\n    pass\n"
            "class Separate:\n    pass\n"
        )
        tree = ast.parse(source)
        nodes = [node for node in reversed(tree.body) if isinstance(node, ast.ClassDef)]
        qualified, classes = analyzer._qualified_class_index(tree)
        root = next(node for node in nodes if node.name == "Root")
        known = analyzer._inherited_ast_visitor_class_ids(nodes, qualified, classes, {id(root)})
        self.assertEqual({"Leaf", "Middle"}, {node.name for node in nodes if id(node) in known})

    def test_dictionary_collisions_keep_the_first_equal_key_witness(self) -> None:
        findings = _findings("mapping = {\n    1: 'first',\n    True: 'second',\n    1.0: 'third',\n}\n", "cleancode", "DuplicatedArrayKey")
        self.assertEqual([3, 4], [finding.line for finding in findings])
        self.assertTrue(all("first declared at line 2" in finding.message for finding in findings))

    def test_scope_usage_propagates_free_names_and_reuses_completed_children(self) -> None:
        table = symtable.symtable("def outer(value):\n    def middle():\n        def inner():\n            return value\n        return inner\n    return middle\n", "state.py", "exec")
        table = next(child for child in table.get_children() if child.get_name() == "outer")
        usage, memo = analyzer._scope_usage(table)
        self.assertIn("value", usage.used_names)
        self.assertNotIn("value", usage.free_names)
        child = next(child for child in table.get_children() if child.get_name() == "middle")
        child_usage, reused = analyzer._scope_usage(child, memo)
        self.assertIs(memo, reused)
        self.assertIs(memo[id(child)], child_usage)
        self.assertEqual(frozenset({"value"}), child_usage.free_names)

    def test_emission_deduplication_keeps_first_binding_and_first_exit_per_scope(self) -> None:
        locals_found = _findings("def compute():\n    unused = 1\n    unused = 2\n", "unusedcode", "UnusedLocalVariable")
        self.assertEqual([2], [finding.line for finding in locals_found])
        exits = _findings("def compute():\n    exit()\n    exit()\ndef other():\n    exit()\n", "design", "ExitExpression")
        self.assertEqual([2, 5], [finding.line for finding in exits])

    def test_repeated_bindings_and_exits_construct_only_emitted_findings(self) -> None:
        cases = (
            ("def compute():\n" + "    unused = 1\n" * 1000, "unusedcode", "UnusedLocalVariable"),
            ("def compute():\n" + "    exit()\n" * 1000, "design", "ExitExpression"),
            ("[0 for unused in values for unused in values]\n", "unusedcode", "UnusedLocalVariable"),
        )
        for source, ruleset, rule_name in cases:
            with self.subTest(rule=rule_name, source=source[:40]):
                with mock.patch.object(analyzer, "Finding", wraps=Finding) as construct:
                    findings = _findings(source, ruleset, rule_name)
                self.assertEqual(1, len(findings))
                self.assertEqual(1 if source.startswith("[") else 2, findings[0].line)
                self.assertEqual(1, construct.call_count)

    def test_class_graph_cycles_and_diamonds_finish_without_losing_reachable_classes(self) -> None:
        nodes = [ast.ClassDef(name=name, bases=[], keywords=[], body=[], decorator_list=[]) for name in ("A", "B", "C", "D")]
        a, b, c, d = nodes
        links = {id(a): [b, c], id(b): [d], id(c): [d], id(d): [a]}
        self.assertEqual(set(nodes), analyzer._linked_classes(a, links))


if __name__ == "__main__":
    unittest.main()
