from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_accumulator_copies.py"


class AccumulatorCopyCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "src" / "messpy"
        self.package.mkdir(parents=True)
        for source in (ROOT / "src" / "messpy").glob("*.py"):
            (self.package / source.name).write_text("", encoding="utf-8")

    def run_check(self, root: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--source-root", str(root or self.root)],
            capture_output=True, text=True, check=False,
        )

    def test_repository_passes_the_same_command_as_ci(self) -> None:
        result = self.run_check(ROOT)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)

    def test_historical_copy_shapes_name_the_existing_replacement(self) -> None:
        cases = (
            ("onion.py", "class _ActionPath:\n    def phrase(self):\n        seen = seen | {1}\n", "update the search collections"),
            ("analyzer.py", "def _with_naming_target(state, target):\n    return replace(state, targets=(*state.targets, target))\n", "_Cons"),
            ("analyzer.py", "def _with_naming_target(state, target):\n    return replace(state, target_names=state.target_names | {target})\n", "_Cons"),
            ("analyzer.py", "def _naming_function(node, state):\n    return replace(state, callables=state.callables + (node,))\n", "_Cons"),
            ("ownership.py", "def _allocated(node, value, state, context):\n    heap = {**state.heap, node: value}\n    return replace(state, heap=heap)\n", "_with_entry"),
            ("ownership.py", "class _State:\n    def remember(self, node, value):\n        return replace(self, evaluated={**self.evaluated, node: value})\n", "_with_entry"),
            ("ownership.py", "class _CallMemo:\n    def replay(self, call, state):\n        return replace(state, heap={**state.heap, **self.heap})\n", "_with_entries"),
            ("ownership.py", "class _ObservationReplay:\n    def descend(self, trace):\n        return Replay((*self.pending, trace))\n", "_TraceFrame.previous"),
            ("ownership.py", "class _ComprehensionFrame:\n    def result(self, trace):\n        return replace(self, traces=(*self.traces, trace))\n", "_then"),
            ("captures.py", "class _CaptureWalk:\n    def advance(self):\n        return self.frames[:-1]\n", "_CaptureFrame.previous"),
            ("effects.py", "class _EffectReports:\n    def claim(self, identity):\n        return Reports(self.identities | {identity})\n", "_EffectReports.collect"),
            ("names.py", "class _NameLookup:\n    def advance(self, names):\n        return Lookup(self.name, self.scopes[1:])\n", "advance position"),
            ("names.py", "class _NameLookup:\n    def advance(self, names):\n        self.scopes += (names,)\n", "advance position"),
            ("callgraph.py", "def _register_callable(state):\n    return {**state.nodes}\n", "owned dictionaries"),
            ("callgraph.py", "def _define_function(state):\n    return {**state.enclosing}\n", "owned dictionaries"),
            ("callgraph.py", "def _bind_name(state):\n    return {**state.bindings}\n", "owned dictionaries"),
            ("callgraph.py", "def _shadow(state):\n    return {**state.shadows}\n", "owned dictionaries"),
            ("callgraph.py", "class _CallableLookup:\n    def advance(self, index):\n        return Lookup(self.name, self.scopes[1:])\n", "advance position"),
        )
        for module, source, fix in cases:
            with self.subTest(module=module, source=source):
                path = self.package / module
                path.write_text(source, encoding="utf-8")
                result = self.run_check()
                self.assertEqual(1, result.returncode)
                self.assertIn(f"src/messpy/{module}:", result.stderr.replace("\\", "/"))
                self.assertIn("copies accumulated", result.stderr)
                self.assertIn(fix, result.stderr)
                path.write_text("", encoding="utf-8")

    def test_sharing_and_mutable_collection_operations_pass(self) -> None:
        sources = {
            "analyzer.py": "def _naming_function(node, state):\n    return replace(state, callables=_Cons(node, state.callables))\n",
            "ownership.py": "def _allocated(node, value, state, context):\n    return replace(state, heap=_with_entry(state.heap, node, value))\n",
            "captures.py": "class _CaptureWalk:\n    def descend(self, nodes):\n        return replace(self, frame=_CaptureFrame(nodes, previous=self.frame))\n",
            "effects.py": "class _EffectReports:\n    def collect(self, identity):\n        self.identities.add(identity)\n",
            "names.py": "class _NameLookup:\n    def advance(self, names):\n        return Lookup(self.name, self.scopes, self.position + 1)\n",
        }
        for module, source in sources.items():
            (self.package / module).write_text(source, encoding="utf-8")
        result = self.run_check()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_other_owners_and_modules_are_outside_the_narrow_policy(self) -> None:
        (self.package / "analyzer.py").write_text(
            "def unrelated(state):\n    return (*state.targets, 1)\n", encoding="utf-8",
        )
        (self.package / "unrelated.py").write_text(
            "class _CaptureWalk:\n    def advance(self):\n        return self.frames[:-1]\n", encoding="utf-8",
        )
        result = self.run_check()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_fixed_prefix_and_tail_slices_pass(self) -> None:
        for selection in ("[-1:]", "[:1]", "[1:3]", "[-3:-1]", "[-3::2]", "[:0]",
                          "[-1:limit]", "[start:1]", "[-1:limit:2]", "[start:1:2]"):
            with self.subTest(selection=selection):
                (self.package / "names.py").write_text(
                    f"class _NameLookup:\n    def advance(self, names):\n        return self.scopes{selection}\n",
                    encoding="utf-8",
                )
                result = self.run_check()
                self.assertEqual(0, result.returncode, result.stderr)

    def test_growing_or_dynamic_slices_fail(self) -> None:
        for selection in ("[1:]", "[:-1]", "[-1::-1]", "[:limit]", "[start:]", "[start:limit]",
                          "[:1:step]", "[-1:limit:step]"):
            with self.subTest(selection=selection):
                (self.package / "names.py").write_text(
                    f"class _NameLookup:\n    def advance(self, names):\n        return self.scopes{selection}\n",
                    encoding="utf-8",
                )
                result = self.run_check()
                self.assertEqual(1, result.returncode)
                self.assertIn("advance position", result.stderr)

    def test_missing_protected_source_fails_instead_of_skipping_the_check(self) -> None:
        (self.package / "captures.py").unlink()
        result = self.run_check()
        self.assertEqual(2, result.returncode)
        self.assertIn("captures.py", result.stderr)

    def test_invalid_protected_source_fails_instead_of_skipping_the_check(self) -> None:
        (self.package / "captures.py").write_text("class invalid", encoding="utf-8")
        result = self.run_check()
        self.assertEqual(2, result.returncode)
        self.assertIn("captures.py", result.stderr)
