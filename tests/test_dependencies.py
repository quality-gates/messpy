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
    def test_class_keywords_resolve_enclosing_function_bindings(self) -> None:
        cases = [
            ("def build(options):\n    class Service(policy=options.factory):\n        pass", set()),
            ("def build():\n    options = object()\n    class Service(policy=options.factory):\n        pass", set()),
            ("def outer(options):\n    def build():\n        class Service(policy=options.factory):\n            pass", set()),
            ("def outer(options):\n    def build():\n        nonlocal options\n        class Service(policy=options.factory):\n            pass", set()),
            ("def build():\n    global options\n    class Service(policy=options.factory):\n        pass", {"external.factory"}),
            ("def build():\n    from external import Options as options\n    class Service(policy=options.factory):\n        pass", {"external.Options"}),
            ("def build(options):\n    class Service(policy=(options.factory, Other)):\n        pass", {"external.Other"}),
            ("class Outer:\n    options = object()\n    class Service(policy=options.factory):\n        pass", set()),
            ("class Outer:\n    options = object()\n    class Service(policy=lambda: options.factory):\n        pass", {"external.factory"}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                source = "import external as options\nfrom external import Other\n" + source + "\n"
                compile(source, "service.py", "exec")
                tree = ast.parse(source)
                class_node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(class_node), names))

    @unittest.skipIf(sys.version_info < (3, 12), "type parameter syntax requires Python 3.12")
    def test_generic_class_keywords_use_annotation_scope_bindings(self) -> None:
        cases = [
            ("class Service[T](option=T):\n    pass", set()),
            ("class Service[T](option=lambda: T):\n    pass", set()),
            ("class Service[T](option=[T for value in ()]):\n    pass", set()),
            ("class Service[*Ts](option=Ts):\n    pass", set()),
            ("class Service[**P](option=P):\n    pass", set()),
            ("class Service[T](option=(T, Other)):\n    pass", {"external.Other"}),
            ("@T\nclass Service[T](option=T):\n    pass", {"external.T"}),
            ("class Service[T](option=T):\n    def method(self):\n        return T", set()),
            ("class Service[T](option=T):\n    def method(self):\n        from external import T\n        return T", {"external.T"}),
            ("class Outer[T]:\n    class Service(option=T):\n        pass", set()),
            ("def build[T]():\n    class Service(option=T):\n        pass", set()),
            ("class Service[T](option=T):\n    def method(self):\n        global T\n        return T", {"external.T"}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                source = "from external import T, Ts, P, Other\n" + source + "\n"
                compile(source, "service.py", "exec")
                tree = ast.parse(source)
                class_node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(class_node), names))

    @unittest.skipIf(sys.version_info < (3, 12), "type parameter syntax requires Python 3.12")
    def test_annotation_scopes_keep_function_defaults_and_decorators_enclosing(self) -> None:
        source = (
            "from external import T, Other\n"
            "@T\n"
            "def build[T](argument: T = T) -> T:\n"
            "    return T\n"
            "type Alias[T] = tuple[T, Other]\n"
        )
        compile(source, "service.py", "exec")
        tree = ast.parse(source)
        names = Names.build(tree, module=None, path=Path("service.py"))
        function = tree.body[1]
        self.assertIsInstance(function, ast.FunctionDef)

        for node in [function.decorator_list[0], function.args.defaults[0]]:
            self.assertEqual(("external.T", True), names.imported(node))
            self.assertFalse(names.is_local(node))
        for node in [function.args.args[0].annotation, function.returns, function.body[0].value]:
            self.assertIsNone(names.imported(node))
            self.assertTrue(names.is_local(node))
        alias_references = [node for node in ast.walk(tree.body[2].value) if isinstance(node, ast.Name)]
        for node in alias_references:
            with self.subTest(name=node.id):
                if node.id == "T":
                    self.assertIsNone(names.imported(node))
                    self.assertTrue(names.is_local(node))
                if node.id == "Other":
                    self.assertEqual(("external.Other", True), names.imported(node))
                    self.assertFalse(names.is_local(node))

    def test_class_keyword_comprehensions_resolve_walrus_bindings_in_order(self) -> None:
        cases = [
            ("[Bound.value for x in rows if (Bound := Local())]", set()),
            ("{Bound.value for x in rows if (Bound := Local())}", set()),
            ("(Bound.value for x in rows if (Bound := Local()))", set()),
            ("{x: Bound.value for x in rows if (Bound := Local())}", set()),
            ("[Bound.value for x in rows if (Bound := Other())]", {"external.Other"}),
            ("[Bound.value for x in rows if (Bound := Bound.factory())]", {"external.Bound"}),
            ("[Bound.value for x in rows if Bound.ready if (Bound := Local())]", {"external.Bound"}),
            ("[Bound.value for x in rows if (Bound := Local()) if Bound.ready]", set()),
            ("[Bound.value for x in rows if (Bound := Local()) for y in Bound.children]", set()),
            ("{(Bound := Local()): Bound.value for x in rows}", set()),
            ("{Bound.value: (Bound := Local()) for x in rows}", {"external.Bound"}),
            ("{(Bound := Other()): Bound.value for x in rows}", {"external.Other"}),
            ("[Bound.value for x in rows if flag and (Bound := Local())]", set()),
            ("[Bound.value for x in rows if flag or (Bound := Local())]", {"external.Bound"}),
            ("[Bound.value for x in rows if (flag and (Bound := Local())) or (other and (Bound := Local()))]", set()),
            ("[Bound.value for x in rows if not (flag or not (Bound := Local()))]", set()),
            ("[Bound.value for x in rows if ((Bound := Local()) if flag else (Bound := Local()))]", set()),
            ("[Bound.value for x in rows if ((Bound := Local()) if flag else True)]", {"external.Bound"}),
            ("[Bound.value for x in rows if 0 < 1 < (Bound := Local(2))]", set()),
            ("[Bound.value for x in rows if 0 < 1 < (Bound := Other())]", {"external.Other"}),
            ("[Bound.value for x in rows if 0 < 1 < (Bound := Bound.factory())]", {"external.Bound"}),
            ("[Bound.value for x in rows if not (x < 1 < (Bound := Local(2)))]", {"external.Bound"}),
            ("[Bound.value for x in rows if -3 < -2 < (Bound := Local(0))]", set()),
            ("[Bound.value for x in rows if -3 < -2 < (flag and (Bound := Local(0)))]", {"external.Bound"}),
            ("([Bound.value for x in rows if (Bound := Local())], Bound.value)", {"external.Bound"}),
            ("[([Bound.value for y in rows if (Bound := Local())], Bound.value) for x in rows]", {"external.Bound"}),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                source = (
                    "from external import Bound, Other\n"
                    "class Local(int):\n    value = 1\n"
                    "rows = ()\n"
                    f"class Service(option={expression}):\n    pass\n"
                )
                compile(source, "service.py", "exec")
                tree = ast.parse(source)
                class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(class_node), names, {"Local"}))

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

    def test_class_keyword_lambda_arguments_are_local_dependencies(self) -> None:
        expressions = [
            "lambda item: item.value",
            "lambda Item: Item",
            "lambda Item, /: Item.value",
            "lambda *, Item: Item.value",
            "lambda *Items: Items[0].value",
            "lambda **Items: Items['key'].value",
            "lambda Item, /, Other=None, *Items, Key=None, **Options: (Item, Other, Items, Key, Options)",
            "lambda: ((Item := object()), Item.value)",
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                tree = ast.parse(
                    "import external as item\n"
                    "from external import Item, Other, Items, Key, Options\n"
                    f"class Service(option={expression}):\n    pass\n"
                )
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                dependencies = measure_class_dependencies(_class_info(class_node), names)

                self.assertEqual(frozenset(), dependencies)

    def test_class_keyword_lambda_defaults_and_nested_bindings_preserve_outer_dependencies(self) -> None:
        cases = [
            ("lambda item=item.value: item.value", {"external.value"}),
            ("lambda Item=Item.factory(): Item.value", {"external.Item"}),
            ("lambda *, Item=Other.factory(): Item.value", {"external.Other"}),
            ("lambda Item=Other.factory(), *Items, Key=Item.factory(), **Options: (Item, Items, Key, Options)", {"external.Item", "external.Other"}),
            ("lambda item: Other.value", {"external.Other"}),
            ("lambda Item: lambda: Item.value", set()),
            ("lambda Item: lambda Item=Item.value: Item.value", set()),
            ("lambda: lambda Item=Item.factory(): Item.value", {"external.Item"}),
            ("[(lambda item=item.value: item.value) for item in ()]", set()),
            ("[(lambda Item=Other.factory(): Item.value) for Item in ()]", {"external.Other"}),
            ("lambda Item=[Item.value for Item in Other.records]: Item.value", {"external.Other"}),
            ("lambda item: [other.value for other in item.records]", set()),
            ("lambda item: [item.value for item in Other.records]", {"external.Other"}),
            ("lambda: ((Item := Other()), Item.value)", {"external.Other"}),
            ("lambda Item: (lambda: [Other.value for Other in Item.records])", set()),
            ("(lambda Item: Item.value, Item.value)", {"external.Item"}),
            ("(lambda Item: Item.value)(Other())", {"external.Other"}),
            ("lambda: ((Nested := lambda Item: Item.value), Nested())", set()),
            ("lambda: (lambda Item=(Bound := object()): Bound.value)", set()),
            ("lambda: (lambda Item=(Bound := Other()): Bound.value)", {"external.Other"}),
            ("lambda: ((lambda Item=(Bound := Other()): Item.value), Bound.value)", {"external.Other"}),
            ("lambda: ([(lambda: Item.value) for Item in ()], Item.value)", {"external.Item"}),
            ("lambda: [(Item := Other()) for item in ()]", {"external.Other"}),
            ("lambda Item=(lambda Other: Other.value): Item.value", set()),
            ("lambda Item=(lambda Other=Other.factory(): Other.value): Item.value", {"external.Other"}),
            ("lambda: Unknown.value", {"Unknown.value"}),
            ("lambda arg=(Bound := object()): Bound.value", set()),
            ("lambda *, arg=(Bound := object()): Bound.value", set()),
            ("lambda arg=(Bound := Other()): Bound.value", {"external.Other"}),
            ("lambda arg=(Bound := Bound.factory()): Bound.value", {"external.Bound"}),
            ("lambda first=(Bound := Other()), second=Bound: Bound.value", {"external.Other"}),
            ("lambda first=(Bound := Other()), *, second=Bound: Bound.value", {"external.Other"}),
            ("lambda arg=(False and (Bound := object())): Bound.value", {"external.Bound"}),
            ("lambda arg=(True and (Bound := object())): Bound.value", set()),
            ("lambda arg=((Bound := object()) if True else None): Bound.value", set()),
            ("lambda arg=((Bound := object()) if False else None): Bound.value", {"external.Bound"}),
            ("lambda arg=((Bound := object()) if flag else (Bound := object())): Bound.value", set()),
            ("lambda arg=((Bound := object()) if flag else None): Bound.value", {"external.Bound"}),
            ("lambda arg=[(Bound := object()) for value in ()]: Bound.value", {"external.Bound"}),
            ("lambda arg=((Bound := object()) for value in ()): Bound.value", {"external.Bound"}),
            ("((lambda arg=(Bound := object()): arg), Bound.value)", set()),
            ("(Bound.value, (lambda arg=(Bound := object()): Bound.value))", {"external.Bound"}),
            ("[(lambda arg=(Bound := object()): arg), Bound.value]", set()),
            ("{(lambda arg=(Bound := object()): arg): Bound.value}", set()),
            ("{Bound.value: (lambda arg=(Bound := object()): Bound.value)}", {"external.Bound"}),
            ("Other(lambda arg=(Bound := object()): arg, Bound.value)", {"external.Other"}),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                tree = ast.parse(
                    "import external as item\n"
                    "from external import Item, Other, Items, Key, Options, Bound, Nested\n"
                    f"class Service(option={expression}):\n    pass\n"
                )
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                dependencies = measure_class_dependencies(_class_info(class_node), names)

                self.assertEqual(frozenset(expected), dependencies)

    def test_class_keyword_default_bindings_reach_later_keywords(self) -> None:
        tree = ast.parse(
            "from external import Bound\n"
            "class Service(first=lambda arg=(Bound := object()): arg, second=Bound.value):\n"
            "    pass\n"
        )
        class_node = _first_class(tree)
        names = Names.build(tree, module=None, path=Path("service.py"))

        self.assertEqual(frozenset(), measure_class_dependencies(_class_info(class_node), names))

    def test_class_namespace_bindings_do_not_hide_lambda_or_comprehension_globals(self) -> None:
        cases = [
            ("option=lambda arg=(Bound := object()): Bound.value", {"external.Bound"}),
            ("option=lambda arg=(Bound := Other()): Bound.value", {"external.Bound", "external.Other"}),
            ("option=lambda first=(Bound := object()), second=Bound: Bound.value", {"external.Bound"}),
            ("first=lambda arg=(Bound := object()): arg, second=lambda: Bound.value", {"external.Bound"}),
            ("first=lambda arg=(Bound := object()): arg, second=[Bound.value for item in ()]", {"external.Bound"}),
            ("first=lambda arg=(Bound := object()): arg, second=lambda arg=Bound: arg", set()),
            ("first=lambda arg=(Bound := object()): arg, second=[item.value for item in Bound.records]", set()),
            ("option=[(lambda: item.value) for item in ()]", set()),
            ("option=lambda arg=(Bound := object()): ((Bound := object()), Bound.value)", set()),
            ("option=lambda arg=(Bound := object()): lambda: Bound.value", {"external.Bound"}),
        ]
        for header, expected in cases:
            with self.subTest(header=header):
                tree = ast.parse(
                    "from external import Bound, Other\n"
                    "class Outer:\n"
                    f"    class Service({header}):\n        pass\n"
                )
                class_node = _first_class(tree).body[0]
                self.assertIsInstance(class_node, ast.ClassDef)
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(class_node), names))

    def test_class_body_lambda_defaults_preserve_global_dependencies(self) -> None:
        cases = [
            ("lambda arg=(Bound := object()): Bound.value", {"external.Bound"}),
            ("(lambda arg=(Bound := object()): arg, lambda: Bound.value)", {"external.Bound"}),
            ("(lambda arg=(Bound := object()): arg, [Bound.value for item in ()])", {"external.Bound"}),
            ("[(lambda: item.value) for item in ()]", set()),
            ("lambda: (lambda arg=(Bound := object()): Bound.value)", set()),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                tree = ast.parse(
                    "from external import Bound\n"
                    f"class Service:\n    callback = {expression}\n"
                )
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(class_node), names))

    def test_class_default_initializers_preserve_imports_and_later_rebinding(self) -> None:
        cases = [
            ("callback = lambda arg=(Bound := Bound.factory()): Bound.value\n    later = Bound.value", {"external.Bound"}),
            ("callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", set()),
            ("callback = lambda arg=(Bound := object()): arg\n    def method(arg=Bound.value):\n        pass", set()),
            ("callback = lambda arg=(Bound := object()): arg\n    def method(self):\n        return Bound.value", {"external.Bound"}),
            ("def method(self):\n        Bound = object()\n    later = Bound.value", {"external.Bound"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                tree = ast.parse("from external import Bound\n" + f"class Service:\n    {body}\n")
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(class_node), names))

    def test_conditional_class_default_bindings_keep_possible_outer_dependencies(self) -> None:
        cases = [
            ("if False:\n        callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", {"external.Bound"}),
            ("if flag:\n        callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", {"external.Bound"}),
            ("for value in ():\n        callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", {"external.Bound"}),
            ("while False:\n        callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", {"external.Bound"}),
            ("if True:\n        callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", set()),
            ("if flag:\n        callback = lambda arg=(Bound := object()): arg\n    else:\n        callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", set()),
            ("if (Bound := object()):\n        pass\n    later = Bound.value", set()),
            ("try:\n        raise ValueError\n        callback = lambda arg=(Bound := object()): arg\n    except ValueError:\n        pass\n    later = Bound.value", {"external.Bound"}),
            ("with manager:\n        if flag:\n            callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", {"external.Bound"}),
            ("match value:\n        case 1:\n            callback = lambda arg=(Bound := object()): arg\n    later = Bound.value", {"external.Bound"}),
            ("assert flag, (lambda arg=(Bound := object()): arg)\n    later = Bound.value", {"external.Bound"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                tree = ast.parse("from external import Bound\n" + f"class Service:\n    {body}\n")
                class_node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(class_node), names))

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
