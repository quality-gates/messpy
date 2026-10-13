from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from messpy.dependencies import ClassInfo, measure_class_dependencies
from messpy.names import Names


def _first_class(tree: ast.Module) -> ast.ClassDef:
    return next(node for node in tree.body if isinstance(node, ast.ClassDef))


def _class_info(
    node: ast.ClassDef,
    *,
    fields: tuple[str, ...] = (),
    is_ast_visitor: bool = False,
) -> ClassInfo:
    methods = tuple(
        statement
        for statement in node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return ClassInfo(
        node=node,
        name=node.name,
        fields=fields,
        methods=methods,
        is_ast_visitor=is_ast_visitor,
    )


class ClassDependencyTests(unittest.TestCase):
    def test_class_with_no_references_has_empty_dependencies(self) -> None:
        tree = ast.parse("class Widget:\n    pass\n")
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("widget.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset(), dependencies)

    def test_class_inheriting_from_external_base_records_base(self) -> None:
        tree = ast.parse("class Widget(BaseWidget):\n    pass\n")
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("widget.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset({"BaseWidget"}), dependencies)

    def test_class_with_imported_decorator_records_dependency(self) -> None:
        tree = ast.parse("from dataclasses import dataclass\n\n@dataclass\nclass Widget:\n    pass\n")
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("widget.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset({"dataclasses.dataclass"}), dependencies)

    def test_class_keyword_records_imported_metaclass_dependency(self) -> None:
        cases = [
            ("from custom_meta import CustomMeta", "CustomMeta"),
            ("from custom_meta import CustomMeta as Meta", "Meta"),
            ("import custom_meta as meta", "meta.CustomMeta"),
        ]
        for imports, expression in cases:
            with self.subTest(expression=expression):
                tree = ast.parse(f"{imports}\nclass Service(metaclass={expression}):\n    pass\n")
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                dependencies = measure_class_dependencies(_class_info(class_node), names)

                self.assertEqual(frozenset({"custom_meta.CustomMeta"}), dependencies)

    def test_class_keyword_expressions_record_external_dependencies(self) -> None:
        cases = [
            ("policy=choose(CustomMeta)", {"factories.choose", "custom_meta.CustomMeta"}),
            ("policy=[CustomMeta, meta.OtherMeta]", {"custom_meta.CustomMeta", "custom_meta.OtherMeta"}),
            ("**{'metaclass': CustomMeta}", {"custom_meta.CustomMeta"}),
            ("**meta.options", {"custom_meta.options"}),
        ]
        for keywords, expected in cases:
            with self.subTest(keywords=keywords):
                tree = ast.parse(
                    "from factories import choose\n"
                    "from custom_meta import CustomMeta\n"
                    "import custom_meta as meta\n"
                    f"class Service({keywords}):\n    pass\n"
                )
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                dependencies = measure_class_dependencies(_class_info(class_node), names)

                self.assertEqual(frozenset(expected), dependencies)

    def test_class_keyword_comprehension_targets_are_local_dependencies(self) -> None:
        expressions = [
            "[item.value for item in ()]",
            "{item.value for item in ()}",
            "{item.key: item.value for item in ()}",
            "(item.value for item in ())",
            "[Item for Item in ()]",
            "[item.value for item in () if item.enabled]",
            "[(key.value, item.value) for key, *item in ()]",
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                tree = ast.parse(
                    "from external import Item\n"
                    "import external as item\n"
                    f"class Service(options={expression}):\n    pass\n"
                )
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                dependencies = measure_class_dependencies(_class_info(class_node), names)

                self.assertEqual(frozenset(), dependencies)

    def test_class_keyword_comprehensions_keep_outer_dependencies(self) -> None:
        cases = [
            ("[item.value for item in item.records]", {"external.records"}),
            ("[Item.value for Item in Item.records]", {"external.Item"}),
            ("[item.value for item in () if Checker(item)]", {"checks.Checker"}),
            ("[(item.value, other.value) for item in () for other in Other.records]", {"external.Other"}),
            ("[[item.value for item in item.children] for item in ()]", set()),
            ("([item.value for item in ()], item.records)", {"external.records"}),
            ("[Item.value for Item in ()] + [Item.value for other in ()]", {"external.Item"}),
            ("[Unknown.value for item in ()]", {"Unknown.value"}),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                tree = ast.parse(
                    "import external as item\n"
                    "from external import Item, Other\n"
                    "from checks import Checker\n"
                    f"class Service(options={expression}):\n    pass\n"
                )
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                dependencies = measure_class_dependencies(_class_info(class_node), names)

                self.assertEqual(frozenset(expected), dependencies)

    def test_class_keywords_preserve_dependency_exclusions(self) -> None:
        tree = ast.parse(
            "from typing import TypedDict as Record\n"
            "from collections.abc import Sequence as Items\n"
            "from builtins import type as Meta\n"
            "class Service(Record, metaclass=Meta, total=False, label='CustomMeta', "
            "count=1, empty=None, policy=list[int], items=Items, helper=Helper):\n"
            "    pass\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("service.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names, {"Helper"})

        self.assertEqual(frozenset(), dependencies)

    def test_class_keyword_dependencies_deduplicate_with_other_references(self) -> None:
        tree = ast.parse(
            "from custom_meta import CustomMeta\n"
            "@CustomMeta\n"
            "class Service(CustomMeta, metaclass=CustomMeta, policy=CustomMeta):\n"
            "    value: CustomMeta\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("service.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset({"custom_meta.CustomMeta"}), dependencies)

    def test_nested_class_keywords_belong_to_the_nested_class(self) -> None:
        tree = ast.parse(
            "from custom_meta import CustomMeta\n"
            "class Outer:\n"
            "    class Inner(metaclass=CustomMeta):\n"
            "        pass\n"
        )
        outer = _first_class(tree)
        inner = outer.body[0]
        self.assertIsInstance(inner, ast.ClassDef)
        names = Names.build(tree, module=None, path=Path("service.py"))

        self.assertEqual(frozenset(), measure_class_dependencies(_class_info(outer), names))
        self.assertEqual(
            frozenset({"custom_meta.CustomMeta"}),
            measure_class_dependencies(_class_info(inner), names),
        )

    def test_class_with_uppercase_unimported_decorator_records_dependency(self) -> None:
        tree = ast.parse("@CustomDecorator\nclass Widget:\n    pass\n")
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("widget.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset({"CustomDecorator"}), dependencies)

    def test_method_annotations_and_body_record_dependencies(self) -> None:
        tree = ast.parse(
            "class Service:\n"
            "    def handle(self, request: Request) -> Response:\n"
            "        return Client.send(request)\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("service.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset({"Request", "Response", "Client.send"}), dependencies)

    def test_forward_reference_string_annotations_are_parsed(self) -> None:
        tree = ast.parse(
            "class Service:\n"
            "    def handle(self, request: 'Request') -> 'Response':\n"
            "        ...\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("service.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset({"Request", "Response"}), dependencies)

    def test_invalid_string_annotations_are_safely_ignored(self) -> None:
        tree = ast.parse(
            "class Service:\n"
            "    def handle(self, request: '???invalid syntax???') -> None:\n"
            "        ...\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("service.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset(), dependencies)

    def test_class_name_methods_and_parameters_are_excluded_from_dependencies(self) -> None:
        tree = ast.parse(
            "class Pipeline:\n"
            "    def step(self, value):\n"
            "        result = Pipeline()\n"
            "        return self.step(value)\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("pipeline.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset(), dependencies)

    def test_class_fields_are_excluded_from_dependencies(self) -> None:
        tree = ast.parse(
            "class Container:\n"
            "    Item = None\n"
            "    def get_item(self):\n"
            "        return Item\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("container.py"))

        dependencies = measure_class_dependencies(_class_info(class_node, fields=("Item",)), names)

        self.assertEqual(frozenset(), dependencies)

    def test_module_names_are_excluded_from_dependencies(self) -> None:
        tree = ast.parse(
            "class Worker:\n"
            "    def run(self):\n"
            "        return Helper()\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("worker.py"))

        dependencies = measure_class_dependencies(
            _class_info(class_node), names, module_names={"Helper"}
        )

        self.assertEqual(frozenset(), dependencies)

    def test_builtins_typing_and_collections_abc_are_excluded(self) -> None:
        tree = ast.parse(
            "import typing\n"
            "from typing import Optional, List\n"
            "from collections.abc import Sequence\n"
            "\n"
            "class Model:\n"
            "    def parse(self, text: str, items: Sequence[int], opt: typing.Optional[dict]) -> Optional[List[int]]:\n"
            "        return None\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("model.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset(), dependencies)

    def test_imported_symbol_and_in_function_import_are_resolved(self) -> None:
        tree = ast.parse(
            "from app.services import Service\n"
            "\n"
            "class Controller:\n"
            "    def __init__(self, svc: Service) -> None:\n"
            "        from app.clients import HttpClient\n"
            "        self.client = HttpClient()\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("controller.py"))

        dependencies = measure_class_dependencies(_class_info(class_node), names)

        self.assertEqual(frozenset({"app.services.Service", "app.clients.HttpClient"}), dependencies)

    def test_ast_visitor_class_excludes_ast_module_dependencies(self) -> None:
        tree = ast.parse(
            "import ast\n"
            "\n"
            "class MyVisitor(ast.NodeVisitor):\n"
            "    def visit_Name(self, node: ast.Name) -> None:\n"
            "        ExternalHandler.process(node)\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("visitor.py"))

        visitor_info = _class_info(class_node, is_ast_visitor=True)
        visitor_deps = measure_class_dependencies(visitor_info, names)
        self.assertEqual(frozenset({"ExternalHandler.process"}), visitor_deps)

        non_visitor_info = _class_info(class_node, is_ast_visitor=False)
        non_visitor_deps = measure_class_dependencies(non_visitor_info, names)
        self.assertEqual(frozenset({"ast.NodeVisitor", "ast.Name", "ExternalHandler.process"}), non_visitor_deps)
