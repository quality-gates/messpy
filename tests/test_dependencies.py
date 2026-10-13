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
    def test_class_keyword_imports_follow_only_normal_if_arms(self) -> None:
        cases = [
            ("if flag:\n    factory=Local\nelse:\n    return", set()),
            ("if flag:\n    factory=Local\nelse:\n    raise ValueError()", set()),
            ("if flag:\n    return\nelse:\n    factory=Local", set()),
            ("if flag:\n    raise ValueError()\nelse:\n    factory=Local", set()),
            ("if flag:\n    factory=Local\n    return\nelse:\n    pass", {"external.Factory"}),
            ("if flag:\n    factory=Local\n    raise ValueError()\nelse:\n    pass", {"external.Factory"}),
            ("if flag:\n    factory=Local\nelse:\n    return\n    from other import Factory as factory", set()),
            ("if flag:\n    if other:\n        return\n    factory=Local\nelse:\n    factory=Local", set()),
            ("if flag:\n    if other:\n        factory=Local\n        return\nelse:\n    raise ValueError()", {"external.Factory"}),
            ("if True:\n    factory=Local\nelse:\n    return", set()),
            ("if flag:\n    return\nelse:\n    raise ValueError()", set()),
            ("def inner():\n    return\nif flag:\n    factory=Local", {"external.Factory"}),
        ]
        for body, expected in cases:
            for header in ("option=factory", "metaclass=factory", "option=(lambda chosen=factory: chosen)"):
                with self.subTest(body=body, header=header):
                    source = (
                        "class Config: pass\nclass Local(type): pass\ndef build(flag, other):\n"
                        "    from external import Factory as factory\n"
                        + "    " + body.replace("\n", "\n    ") + "\n"
                        + f"    class Service(Config, {header}):\n        pass\n    return Service\n"
                    )
                    compile(source, "service.py", "exec", dont_inherit=True)
                    tree = ast.parse(source)
                    node = next(item for item in ast.walk(tree) if isinstance(item, ast.ClassDef) and item.name == "Service")
                    names = Names.build(tree, module=None, path=Path("service.py"))

                    self.assertEqual(
                        frozenset(expected),
                        measure_class_dependencies(_class_info(node), names, {"Config", "Local", "Service"}),
                    )

    def test_class_keyword_imports_override_builtin_spellings(self) -> None:
        cases = [
            ("import custom_meta as type", "type.Factory", {"custom_meta.Factory"}),
            ("from custom_meta import Factory as type", "type", {"custom_meta.Factory"}),
            ("import custom_meta as typing", "typing.Factory", {"custom_meta.Factory"}),
            ("from custom_meta import Factory as list", "list", {"custom_meta.Factory"}),
            ("if flag:\n    import custom_meta as type", "type.Factory", {"custom_meta.Factory"}),
            ("import builtins as type", "type.type", set()),
            ("from typing import Any as type", "type", set()),
            ("from collections.abc import Mapping as type", "type", set()),
            ("", "type", set()),
            ("", "list[int]", set()),
            ("type = object()", "type", set()),
        ]
        for imports, expression, expected in cases:
            with self.subTest(imports=imports, expression=expression):
                tree = ast.parse(f"{imports}\nclass Service(option={expression}):\n    pass\n")
                node = _first_class(tree)
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names))

    def test_class_keyword_reads_precede_future_members(self) -> None:
        cases = [
            ("", "Factory", "Factory = None", {"Factory"}, set()),
            ("", "Factory", "def Factory(self):\n        return None", {"Factory"}, set()),
            ("", "Factory.value", "Factory = None", {"Factory.value"}, set()),
            ("", "factory.value", "factory = None", {"factory.value"}, set()),
            ("class Factory: pass", "Factory", "Factory = None", set(), {"Factory"}),
            ("Factory = object()", "Factory", "Factory = None", set(), set()),
            ("", "Factory", "Factory = None", set(), {"Factory"}),
            ("", "Helper", "Factory = None", set(), {"Helper"}),
            ("", "(lambda: Factory)", "Factory = None", set(), set()),
            ("", "(Factory for item in ())", "Factory = None", set(), set()),
        ]
        for prefix, expression, body, expected, module_names in cases:
            with self.subTest(prefix=prefix, expression=expression, body=body, module_names=module_names):
                source = f"from external import *\n{prefix}\nclass Service(option={expression}):\n    {body}\n"
                tree = ast.parse(source)
                node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(
                    frozenset(expected),
                    measure_class_dependencies(_class_info(node, fields=("Factory", "factory")), names, module_names),
                )

    def test_ordinary_class_masks_keep_while_test_reentry(self) -> None:
        cases = [
            ('class Service:\n    (Bound:=Local())\n    spare=0\n    while spare<2 and Bound.Factory:\n        from external import Bound\n        spare+=1\n    field=LocalFactory', {"Bound.Factory"}),
            ('class Service:\n    (Bound:=Local())\n    spare=0\n    while spare<2 and Bound.Factory:\n        from external import Bound\n        break\n    field=LocalFactory', set()),
            ('class Service:\n    (Bound:=Local())\n    spare=0\n    while spare<2 and Bound.Factory:\n        from external import Bound\n        spare+=1\n        continue\n    field=LocalFactory', {"Bound.Factory"}),
            ('class Service:\n    (Bound:=Local())\n    spare=0\n    while spare<2 and (Bound:=Local()) and Bound.Factory:\n        from external import Bound\n        spare+=1\n    field=LocalFactory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    while (Bound:=Bound.Factory):\n        field=Bound\n        break', {"Bound.Factory"}),
            ('class Service:\n    (Bound:=Local())\n    while False and Bound.Factory:\n        from external import Bound\n    field=Bound.Factory', set()),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass LocalFactory: pass\nclass Local:\n    Factory=LocalFactory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                module_names = {statement.name for statement in tree.body if isinstance(statement, ast.ClassDef)}
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, module_names))

    def test_ordinary_class_masks_keep_target_evaluation_order(self) -> None:
        cases = [
            ('class Context:\n    Factory=LocalFactory\n    def __init__(self,value=None,*,result=None): self.result=result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    with (Bound:=Context()) as holder[Bound.Factory]:\n        field=Bound.Factory', set()),
            ('class Context:\n    Factory=LocalFactory\n    def __init__(self,value=None,*,result=None): self.result=result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    with Context(Bound:=Local()) as holder[Bound.Factory]:\n        field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    holder[Bound.Factory]=(Bound:=Local())\n    field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    for holder[Bound.Factory] in ((Bound:=Local()),):\n        field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    holder[Bound.Factory]: object=(Bound:=Local())\n    field=Bound.Factory', set()),
            ('class Context:\n    Factory=LocalFactory\n    def __init__(self,value=None,*,result=None): self.result=result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    with Context() as holder[(Bound:=Local()).Factory]:\n        field=Bound.Factory', set()),
            ('class Context:\n    Factory=LocalFactory\n    def __init__(self,value=None,*,result=None): self.result=result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    with Context() as holder[(Bound:=Local()).Factory], Context(Bound.Factory):\n        field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    for holder[(Bound:=Local()).Factory] in (None,):\n        field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    holder[(Bound:=Local()).Factory]=holder[Bound.Factory]=None\n    field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    holder[Bound.Factory]=0\n    holder[Bound.Factory]+=(Bound:=0)\n    field=Local.Factory', {"Bound.Factory"}),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    for holder[Bound.Factory] in ((Bound:=Local()),None):\n        field=Local.Factory\n        from external import Bound', {"Bound.Factory"}),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    for holder[(Bound:=Local()).Factory] in ():\n        pass\n    field=Bound.Factory', {"Bound.Factory"}),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    holder={LocalFactory:0}\n    holder[(Bound:=Local()).Factory]+=len([Bound.Factory])\n    field=Bound.Factory', set()),
            ('class Context:\n    Factory=LocalFactory\n    def __init__(self,value=None,*,result=None): self.result=result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    with Context(result=(Local(),None)) as (Bound, holder[Bound.Factory]):\n        field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    for Bound, holder[Bound.Factory] in ((Local(),None),):\n        field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    Bound=holder[Bound.Factory]=Local()\n    field=Bound.Factory', set()),
            ('class Service:\n    (Bound:=Local())\n    from external import Bound\n    holder={}\n    for holder[(Bound:=Bound.Factory)] in (None,):\n        field=Bound', {"Bound.Factory"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass LocalFactory: pass\nclass Local:\n    Factory=LocalFactory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                module_names = {statement.name for statement in tree.body if isinstance(statement, ast.ClassDef)}
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, module_names))
                annotation = next((statement for statement in node.body if isinstance(statement, ast.AnnAssign)), None)
                if annotation is not None:
                    self.assertFalse(names.imported(annotation.target.slice, scope=node))

    def test_ordinary_class_masks_keep_with_targets_and_failed_assertions(self) -> None:
        cases = [
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context() as Bound:\n        field=Bound.Factory\n', set()),
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context() as Bound:\n        pass\n    field=Bound.Factory\n', set()),
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context(result=(Local(),None)) as (Bound, spare):\n        field=Bound.Factory\n', set()),
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass FailedEntry:\n    def __enter__(self): raise ValueError()\n    def __exit__(self,*args): return False\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context() as spare, FailedEntry() as Bound:\n        pass\n    field=Bound.Factory\n', {"Bound.Factory"}),
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context() as (spare, Bound):\n        pass\n    field=Bound.Factory\n', {"Bound.Factory"}),
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass FailedEntry:\n    def __enter__(self): raise ValueError()\n    def __exit__(self,*args): return False\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context() as Bound, FailedEntry() as spare:\n        pass\n    field=Bound.Factory\n', set()),
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context(Bound.Factory) as Bound:\n        field=Bound.Factory\n', {"Bound.Factory"}),
            ('class Context:\n    def __init__(self, ignored=None, *, result=None): self.result=Local() if result is None else result\n    def __enter__(self): return self.result\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context() as Bound, Context(Bound.Factory) as spare:\n        field=Bound.Factory\n', set()),
            ('class Service:\n    (Bound:=Local())\n    try:\n        from external import Bound\n        assert False\n        (Bound:=Local())\n    except AssertionError:\n        field=Bound.Factory\n', {"Bound.Factory"}),
            ('class Service:\n    (Bound:=Local())\n    try:\n        from external import Bound\n        (Bound:=Local())\n        assert False\n    except AssertionError:\n        field=Bound.Factory\n', set()),
            ('class Service:\n    (Bound:=Local())\n    try:\n        from external import Bound\n        assert False, (Bound:=Local())\n    except AssertionError:\n        field=Bound.Factory\n', set()),
            ('class Service:\n    (Bound:=Local())\n    try:\n        from external import Bound\n        assert False, (Bound:=Bound.Factory)\n    except AssertionError:\n        field=Bound\n', {"Bound.Factory"}),
            ('class Context:\n    def __enter__(self): return None\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    with Context():\n        (Bound:=Local())\n    field=Bound.Factory\n', set()),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass LocalFactory: pass\nclass Local:\n    Factory=LocalFactory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                module_names = {statement.name for statement in tree.body if isinstance(statement, ast.ClassDef)}
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, module_names))

    def test_ordinary_class_masks_allow_suppressed_raises(self) -> None:
        cases = [
            ("class Suppress:\n    def __enter__(self):return self\n    def __exit__(self,*args):return True\nclass Service:\n    (Bound:=Local())\n    try:\n        with Suppress():\n            raise ValueError()\n        from external import Bound\n    except ValueError:\n        pass\n    else:\n        field=Bound.Factory\n", {"Bound.Factory"}),
            ("class Suppress:\n    def __enter__(self):return self\n    def __exit__(self,*args):return True\nclass Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        with Suppress():\n            raise ValueError()\n        from external import Bound\n", {"Bound.Factory"}),
            ("class Suppressor:\n    def __enter__(self): return None\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        with Suppressor():\n            from external import Bound\n            raise ValueError()", {"Bound.Factory"}),
            ("class Suppressor:\n    def __enter__(self): return None\n    def __exit__(self,*args): return True\nclass Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        try:\n            with Suppressor():\n                from external import Bound\n                raise ValueError()\n        finally:\n            (Bound:=Local())", set()),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass LocalFactory: pass\nclass Local:\n    Factory=LocalFactory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Local", "LocalFactory", "Suppress", "Suppressor", "Service"}))

    def test_ordinary_class_masks_keep_abrupt_completion_paths(self) -> None:
        cases = [
            ("class Service:\n    (Bound:=Local())\n    try:\n        from external import Bound\n        raise ValueError()\n        (Bound:=Local())\n    except ValueError:\n        field=Bound.Factory", {"Bound.Factory"}),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        from external import Bound\n        break\n        (Bound:=Local())\n    field=Bound.Factory", {"Bound.Factory"}),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        from external import Bound\n        break", set()),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        if spare==0:\n            from external import Bound\n            break\n        (Bound:=Local())\n    field=Bound.Factory", {"Bound.Factory"}),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        from external import Bound\n        continue\n        (Bound:=Local())", {"Bound.Factory"}),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        from external import Bound\n        if spare==0:\n            continue\n        (Bound:=Local())", {"Bound.Factory"}),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        try:\n            field=Bound.Factory\n            from external import Bound\n        finally:\n            break", set()),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        try:\n            field=Bound.Factory\n            from external import Bound\n        finally:\n            continue", {"Bound.Factory"}),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        from external import Bound\n        break\n    else:\n        (Bound:=Local())\n    field=Bound.Factory", {"Bound.Factory"}),
            ("class Service:\n    (Bound:=Local())\n    for spare in (0,1):\n        from external import Bound\n    else:\n        (Bound:=Local())\n    field=Bound.Factory", set()),
            ("class LocalError(ValueError):\n    Factory=LocalFactory\nclass Service:\n    (Bound:=Local())\n    try:\n        from external import Bound\n        raise LocalError()\n    except (Bound:=LocalError):\n        pass\n    finally:\n        field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    from external import Bound\n    if (Bound:=Local()):\n        field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    from external import Bound\n    spare=0\n    while (Bound:=Local()) and spare<1:\n        spare+=1\n    else:\n        field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    from external import Bound\n    try:\n        (Bound:=Local())\n    except ValueError:\n        pass\n    field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    while False:\n        from external import Bound\n    else:\n        field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    for spare in ():\n        from external import Bound\n    else:\n        field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    from external import Bound\n    if flag and (Bound:=Local()):\n        field=Bound.Factory\n    else:\n        field=LocalFactory", set()),
            ("class Service:\n    (Bound:=Local())\n    from external import Bound\n    field=LocalFactory\n    while flag and (Bound:=Local()):\n        field=Bound.Factory\n        flag=False", set()),
            ("class FalsyLocal(Local):\n    def __bool__(self): return False\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    running=flag\n    while running or (Bound:=FalsyLocal()):\n        running=False\n    field=Bound.Factory", set()),
            ("class FalsyLocal(Local):\n    def __bool__(self): return False\nclass Service:\n    (Bound:=Local())\n    from external import Bound\n    running=flag\n    while running or (Bound:=FalsyLocal()):\n        running=False\n    else:\n        field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    from external import Bound\n    while flag or not (Bound:=Local()):\n        flag=False\n    field=Bound.Factory", set()),
            ("class Service:\n    (Bound:=Local())\n    from external import Bound\n    while flag or not (Bound:=Local()):\n        flag=False\n        continue\n    field=Bound.Factory", set()),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass LocalFactory: pass\nclass Local:\n    Factory=LocalFactory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Local", "LocalFactory", "FalsyLocal", "LocalError", "Service"}))

    def test_ordinary_class_masks_keep_ordered_local_renewals(self) -> None:
        cases = [
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n        (Bound := Local())\n    except ValueError:\n        pass\n    else:\n        field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n        (Bound := Local())\n    finally:\n        field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n        (Bound := Local())\n        raise ValueError()\n    except ValueError:\n        field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n    finally:\n        (Bound := Local())\n    field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        from external import Bound\n        (Bound := Local())\n", set()),
            ("class Service:\n    (Bound := Local())\n    spare=0\n    while (Bound := Local()) and spare<2:\n        field=Bound.Factory\n        from external import Bound\n        spare+=1\n", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n    finally:\n        (Bound := Local())\n        field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n        (Bound := Bound.Factory)\n    finally:\n        field=Bound\n", {"Bound.Factory"}),
            ("class LocalError(ValueError):\n    Factory=LocalFactory\nclass Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n        raise LocalError()\n    except (Bound := LocalError):\n        field=Bound.Factory", set()),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass LocalFactory: pass\nclass Local:\n    Factory=LocalFactory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Local", "LocalFactory", "LocalError", "Service"}))

    def test_ordinary_class_masks_follow_exception_and_loop_edges(self) -> None:
        cases = [
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n    except ValueError:\n        pass\n    else:\n        field=Bound.Factory\n", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n    finally:\n        field=Bound.Factory\n", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n        raise ValueError()\n    except ValueError:\n        field=Bound.Factory\n", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    try:\n        raise ValueError()\n    except ValueError as Bound:\n        pass\n    finally:\n        field=Bound.Factory\n", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    try:\n        raise ExceptionGroup(\"errors\",[ValueError(),TypeError()])\n    except* ValueError as Bound:\n        pass\n    except* TypeError:\n        field=Bound.Factory\n", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        from external import Bound\n", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    for spare in ():\n        from external import Bound\n    field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    for spare in []:\n        del Bound\n    field=Bound.Factory\n", set()),
            ("class LocalError(ValueError):\n    Factory=LocalFactory\nclass Service:\n    (Bound := Local())\n    try:\n        from external import Bound\n        raise LocalError()\n    except LocalError as Bound:\n        field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        raise TypeError()\n    except ValueError as Bound:\n        pass\n    except TypeError:\n        field=Bound.Factory\n", set()),
            ("class Service:\n    (Bound := Local())\n    for Bound in (Local(),Local()):\n        field=Bound.Factory\n        from external import Bound\n", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        before=Bound.Factory\n        from external import Bound\n    except ValueError:\n        pass", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        pass\n    except ValueError as Bound:\n        pass\n    else:\n        field=Bound.Factory", set()),
            ("class Service:\n    (Bound := Local())\n    try:\n        pass\n    except ValueError:\n        pass\n    else:\n        from external import Bound\n    finally:\n        field=Bound.Factory", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    for spare in (0,):\n        before=Bound.Factory\n        from external import Bound", set()),
            ("class Service:\n    (Bound := Local())\n    for spare in (0,1):\n        field=Bound.Factory\n        if spare==0:\n            del Bound", {"Bound.Factory"}),
            ("class Service:\n    (Bound := Local())\n    spare=0\n    while spare<2:\n        field=Bound.Factory\n        from external import Bound\n        spare+=1", {"Bound.Factory"}),
            ("class Outer:\n    global Bound\n    if True:\n        (Bound:=Local())\n        class Service(option=Bound.Factory): pass", {"external.Bound"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass LocalFactory: pass\nclass Local:\n    Factory=LocalFactory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Local", "LocalFactory", "LocalError", "Outer", "Service"}))

    def test_ordinary_class_masks_preserve_before_import_and_inactive_paths(self) -> None:
        cases = [
            ("before=Bound.Factory\n    from external import Bound", set()),
            ("if flag:\n        before=Bound.Factory\n        from external import Bound", set()),
            ("if flag:\n        before=Bound.Factory\n        from external import Bound\n    else:\n        before=Bound.Factory", set()),
            ("if False:\n        from external import Bound\n    else:\n        field=Bound.Factory", set()),
            ("while False:\n        from external import Bound\n    field=Bound.Factory", set()),
            ("if flag:\n        while False:\n            from external import Bound\n    field=Bound.Factory", set()),
            ("from external import Other\n    field=Bound.Factory", set()),
            ("del spare\n    field=Bound.Factory", set()),
            ("field=Bound.Factory", set()),
            ("if flag:\n        from external import Bound\n        field=Bound.Factory", {"Bound.Factory"}),
            ("if flag:\n        from external import Bound\n    field=Bound.Factory", {"Bound.Factory"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Bound\nclass Local:\n    Factory=type\nclass Service:\n    spare=0\n    (Bound := Local())\n    " + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Local", "Service"}))

    def test_class_namespace_imports_and_deletes_end_ordinary_expression_masks(self) -> None:
        for revoke in ("from external import Bound", "del Bound"):
            cases = [
                ("class Service:\n    (Bound := Local())\n    " + revoke + "\n    field=Bound.Factory", {"Bound.Factory"}),
                ("class Outer:\n    (Bound := Local())\n    " + revoke + "\n    class Service(Bound.Factory):\n        pass", {"Bound.Factory"}),
                ("class Outer:\n    (Bound := Local())\n    " + revoke + "\n    @Bound.decorate\n    class Service:\n        pass", {"Bound.decorate"}),
            ]
            for body, expected in cases:
                with self.subTest(revoke=revoke, body=body):
                    source = "from external import Bound\nclass Local:\n    Factory=type\n" + body
                    compile(source, "service.py", "exec", dont_inherit=True)
                    tree = ast.parse(source)
                    node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                    names = Names.build(tree, module=None, path=Path("service.py"))
                    self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Local", "Service", "Outer"}))

    def test_eager_keyword_import_query_preserves_unimported_self_roots(self) -> None:
        cases = [
            ("class Service(option=Service if False else None):\n    pass", set()),
            ("class Service(option=lambda value=(Service if False else None): value):\n    pass", set()),
            ("class Service(option=[Service for spare in ()]):\n    pass", set()),
            ("class Service(option=lambda: Service):\n    pass", set()),
            ("from external import Factory as Service\nclass Service(option=Service if False else None):\n    pass", {"external.Factory"}),
            ("if flag:\n    from external import Factory as Service\nclass Service(option=Service if False else None):\n    pass", {"external.Factory"}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Service"}))

    def test_eager_keyword_import_order_and_possible_origins(self) -> None:
        cases = [
            ("from external import Factory as factory\nclass Service(option=factory):\n    pass\nfactory=object()", {"external.Factory"}),
            ("from external import Factory as factory\nfactory=object()\nclass Service(option=factory):\n    pass", set()),
            ("from external import Factory as factory\ndel factory\nfrom genuine import Factory as factory\nclass Service(option=factory):\n    pass", {"genuine.Factory"}),
            ("import external as factory\nclass Service(option=factory.Factory):\n    pass\ndel factory", {"external.Factory"}),
            ("if flag:\n    from external import Factory as factory\nelse:\n    from genuine import Factory as factory\nclass Service(option=factory):\n    pass\nfactory=object()", {"external.Factory", "genuine.Factory"}),
            ("if flag:\n    from external import Factory as factory\nelse:\n    from external import Factory as factory\nfrom external import Factory as alias\nclass Service(first=factory, second=alias):\n    pass\nfactory=object()", {"external.Factory"}),
            ("from external import Factory as factory\nif False:\n    from genuine import Factory as factory\nclass Service(option=factory):\n    pass\nfactory=object()", {"external.Factory"}),
            ("from external import Factory as factory\nif flag:\n    factory=object()\nclass Service(option=factory):\n    pass\nfactory=object()", {"external.Factory"}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Service"}))

    def test_eager_keyword_import_query_declines_unmodeled_loops(self) -> None:
        cases = [
            "while False:\n    from genuine import Factory as factory\nclass Service(option=factory):\n    pass",
            "while flag:\n    from genuine import Factory as factory\n    flag=False\nclass Service(option=factory):\n    pass",
            "while flag:\n    class Service(option=factory):\n        pass\n    flag=False",
        ]
        for body in cases:
            with self.subTest(body=body):
                source = "from external import Factory as factory\n" + body
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertIsNone(names.keyword_binding(node.keywords[0].value))
                self.assertEqual(1, len(measure_class_dependencies(_class_info(node), names, {"Service"})))

    def test_eager_keyword_imports_preserve_nested_and_relative_context(self) -> None:
        cases = [
            ("def build():\n    from external import Factory as factory\n    class Service(option=factory):\n        pass\n    factory=object()", {"external.Factory"}),
            ("class Outer:\n    from external import Factory as factory\n    class Service(option=factory):\n        pass\n    factory=object()", {"external.Factory"}),
            ("from external import Factory as factory\nclass Outer:\n    factory=object()\n    class Service(option=[factory for spare in (1,)]):\n        pass\nfactory=object()", {"external.Factory"}),
            ("from .external import Factory as factory\nclass Service(option=factory):\n    pass\nfactory=object()", {"package.external.Factory"}),
            ("from . import external as factory\nclass Service(option=factory.Factory):\n    pass\nfactory=object()", {"package.external"}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=("package", "service"), path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Service", "Outer"}))

    def test_eager_keyword_import_query_keeps_deferred_reads_on_existing_path(self) -> None:
        cases = [
            ("lambda value=factory: value", {"external.Factory"}),
            ("lambda: factory", set()),
            ("[factory for spare in (1,)]", {"external.Factory"}),
            ("(spare for spare in (factory,))", {"external.Factory"}),
            ("(factory for spare in (1,))", set()),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                source = "from external import Factory as factory\nclass Service(option=" + expression + "):\n    pass\nfactory=object()"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(tree.body[1]), names, {"Service"}))

    def test_keyword_conditional_rhs_stores_are_not_definite_bindings(self) -> None:
        statements = [
            "spare=flag and (Bound := object())",
            "spare=flag or (Bound := object())",
            "spare: object=flag and (Bound := object())",
            "spare=0\n    spare += flag and (Bound := object())",
            "spare=(Bound := object()) if flag else None",
            "spare=(holder := (flag and (Bound := object())))",
        ]
        for statement in statements:
            for root in ("Bound", "Service"):
                with self.subTest(statement=statement, root=root):
                    source = "from external import Factory as " + root + "\nclass Outer:\n    " + statement.replace("Bound", root) + "\n    class Service(option=" + root + ".value):\n        pass\n"
                    compile(source, "service.py", "exec", dont_inherit=True)
                    tree = ast.parse(source)
                    node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                    names = Names.build(tree, module=None, path=Path("service.py"))
                    self.assertEqual(frozenset({"external.Factory"}), measure_class_dependencies(_class_info(node), names, {"Service", "Outer"}))
        for statement in ("Bound=flag and object()", "spare=(Bound := object())", "spare: object=(Bound := object())", "spare=0\n    spare += (Bound := 1)"):
            with self.subTest(statement=statement):
                tree = ast.parse("from external import Factory as Bound\nclass Outer:\n    " + statement + "\n    class Service(option=Bound.value):\n        pass\n")
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(), measure_class_dependencies(_class_info(node), names, {"Service", "Outer"}))

    def test_class_keyword_import_precedes_a_later_alias_store(self) -> None:
        source = (
            "class Config:\n"
            "    def __init_subclass__(cls, **options):\n"
            "        cls.options = options\n"
            "class Local:\n"
            "    value = 1\n"
            "from external import Factory as factory\n"
            "class Service(Config, option=factory):\n"
            "    pass\n"
            "factory=object()\n"
        )
        compile(source, "service.py", "exec", dont_inherit=True)
        tree = ast.parse(source)
        node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Service")
        names = Names.build(tree, module=None, path=Path("service.py"))
        self.assertEqual(frozenset({"external.Factory"}), measure_class_dependencies(_class_info(node), names, {"Config", "Local", "Service"}))

    def test_class_keyword_shared_effects_preserve_generic_name_queries(self) -> None:
        source = "from external import Bound\nclass Local:\n    value=1\nclass Service(first=(flag and (Bound := None)) or (Bound := Local), second=Bound.value):\n    later=Bound.value\n"
        tree = ast.parse(source)
        node = tree.body[-1]
        names = Names.build(tree, module=None, path=Path("service.py"))
        self.assertEqual("external.Bound.value", names.qualified(node.keywords[1].value))
        self.assertIsNone(names.imported(node.keywords[1].value))
        self.assertEqual(("external.Bound", True), names.imported(node.body[0].value))
        self.assertEqual(frozenset({"external.Bound"}), measure_class_dependencies(_class_info(node), names, {"Local", "Service"}))

    def test_class_keyword_completed_expressions_share_definite_effects(self) -> None:
        cases = [
            ("(flag and (Bound := None)) or (Bound := Local)", set()),
            ("(flag or (Bound := True)) and (Bound := Local)", set()),
            ("(flag and (Bound := Local)) or (Bound := Local)", set()),
            ("(flag and (Bound := None)) or ((spare := None) or (Bound := Local))", set()),
            ("(spare := (flag and (Bound := None))) or (Bound := Local)", set()),
            ("((flag and (Bound := None)) or (Bound := Local)) if other else (Bound := Local)", set()),
            ("((Bound := Local) if flag else None) or (Bound := Local)", set()),
            ("(Bound := Local) if flag else (Bound := Local)", set()),
            ("(flag and (Bound := None)) or (Bound := Other)", {"external.Other"}),
            ("(flag and (Bound := Other)) or (Bound := Local)", {"external.Other"}),
            ("flag and (Bound := Local)", {"external.Bound"}),
            ("flag or (Bound := Local)", {"external.Bound"}),
            ("(Bound := Local) if flag else None", {"external.Bound"}),
            ("lambda: (Bound := Local)", {"external.Bound"}),
            ("(Bound.value, (Bound := Local))", {"external.Bound"}),
            ("[(Bound := Local) for spare in ()]", {"external.Bound"}),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                source = "from external import Bound, Other\nclass Local:\n    value=1\nclass Service(first=" + expression + ", second=Bound.value):\n    pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(tree.body[-1]), names, {"Local", "Service"}))

    def test_class_keyword_locals_merge_completed_conditional_branches(self) -> None:
        cases = [
            ("if flag:\n        item=Local()\n    else:\n        item=Local()", set()),
            ("item=Local()\n    if flag:\n        from genuine import Item as item\n        item=Local()\n    else:\n        pass", set()),
            ("item=Local()\n    if flag:\n        del item\n        item=Local()\n    else:\n        pass", set()),
            ("item=Local()\n    if flag:\n        if other:\n            from genuine import Item as item\n            item=Local()\n    else:\n        pass", set()),
            ("item=Local()\n    if flag:\n        from genuine import Item as item\n    else:\n        pass", {"genuine.Item"}),
            ("item=Local()\n    if flag:\n        del item\n    else:\n        pass", {"external.Item"}),
            ("(item := Local())\n    if flag:\n        from genuine import Item as item\n        item=Local()\n    else:\n        pass", set()),
            ("item=Local()\n    flag and (item := Local())\n    if flag:\n        from genuine import Item as item\n        item=Local()\n    else:\n        pass", set()),
            ("if (item := Local()):\n        from genuine import Item as item\n        item=Local()\n    else:\n        pass", set()),
            ("item=Local()\n    if flag and (item := Local()):\n        from genuine import Item as item\n        item=Local()\n    else:\n        pass", set()),
            ("if flag and (item := Local()):\n        from genuine import Item as item\n        item=Local()\n    else:\n        pass", {"external.Item"}),
            ("if flag:\n        if other:\n            item=Local()\n        else:\n            item=Local()\n    else:\n        item=Local()", set()),
            ("if flag:\n        item=Local()\n    elif other:\n        item=Local()\n    else:\n        item=Local()", set()),
            ("if flag:\n        with manager as item:\n            pass\n    else:\n        item=Local()", set()),
            ("if flag:\n        from genuine import Item as item\n        item=Local()\n    else:\n        item=Local()", set()),
            ("if flag:\n        del item\n        item=Local()\n    else:\n        item=Local()", set()),
            ("if flag:\n        item=Local()\n    else:\n        pass", {"external.Item"}),
            ("if flag:\n        item=Local()\n        del item\n    else:\n        item=Local()", {"external.Item"}),
            ("if flag:\n        def configure():\n            item=Local()\n    else:\n        def configure():\n            item=Local()", {"external.Item"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Item as item\nclass Local:\n    value=1\nclass Outer:\n    " + body + "\n    class Service(option=item.value):\n        pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, {"Local", "Outer", "Service"}))

    def test_class_keyword_reads_precede_the_target_name_binding(self) -> None:
        cases = [
            ("import external as Service\nclass Service(metaclass=Service.Factory):\n    pass", {"external.Factory"}),
            ("from external import Meta as Service\nclass Service(metaclass=Service):\n    pass", {"external.Meta"}),
            ("import external as Service\nimport external as Alias\nclass Service(metaclass=Service.Factory, policy=Alias.Factory):\n    pass", {"external.Factory"}),
            ("def build():\n    import external as Service\n    class Service(metaclass=Service.Factory):\n        pass", {"external.Factory"}),
            ("class Outer:\n    import external as Service\n    class Service(metaclass=Service.Factory):\n        pass", {"external.Factory"}),
            ("class Service:\n    Factory=type\nclass Service(metaclass=Service.Factory):\n    pass", set()),
            ("Service=type\nclass Service(metaclass=Service):\n    pass", set()),
            ("def build(Service):\n    class Service(option=Service.value):\n        pass", set()),
            ("class Outer:\n    Service=object()\n    class Service(option=Service.value):\n        pass", set()),
            ("import external as Service\nclass Service(option=lambda: Service.value):\n    pass", {"external.value"}),
            ("import external as Service\nclass Service(option=(lambda: Service.value)()):\n    pass", {"external.value"}),
            ("import external as Service\nclass Service(option=(Service.value for spare in ())):\n    pass", {"external.value"}),
            ("import external as Service\nclass Service(option=(spare for spare in Service.rows)):\n    pass", {"external.rows"}),
            ("import external as Service\nclass Service(metaclass=next(Service.Factory for spare in (1,))):\n    pass", {"external.Factory"}),
            ("import external as Service\nclass Service(metaclass=consume(Service.Factory for spare in (1,))):\n    pass", {"external.Factory"}),
            ("import external as Service\nclass Service(metaclass=consume(lambda: Service.Factory)):\n    pass", {"external.Factory"}),
            ("class Service(option=lambda: Service.value):\n    value=1", set()),
            ("class Service(option=(Service.value for spare in (1,))):\n    value=1", set()),
            ("import external as Service\nclass Service(option=lambda Service=object(): Service.value):\n    pass", set()),
            ("import external as Service\nclass Service(option=(Service.value for Service in rows)):\n    pass", set()),
            ("def build():\n    import external as Service\n    def inner():\n        nonlocal Service\n        class Service(metaclass=Service.Factory):\n            pass\n    Service=Local\n    inner()", set()),
            ("def build():\n    import external as Service\n    def inner():\n        nonlocal Service\n        class Service(metaclass=Service.Factory):\n            pass\n    inner()", {"external.Factory"}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in reversed(list(ast.walk(tree))) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                module_names = {part.name for part in tree.body if isinstance(part, ast.ClassDef)}
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names, module_names))

    def test_class_keyword_boolean_operands_use_reached_path_bindings(self) -> None:
        cases = [
            ("(flag and (Bound := object())) and Bound.value", set()),
            ("(flag or (Bound := object())) or Bound.value", set()),
            ("(not (flag or (Bound := object()))) and Bound.value", set()),
            ("(flag or (Bound := object())) and Bound.value", {"external.Bound"}),
            ("(flag and (Bound := object())) or Bound.value", {"external.Bound"}),
            ("((Bound := Other()) and True) and Bound.value", {"external.Other"}),
            ("((Bound := object()) and flag) and Bound.value", set()),
            ("((flag and (Bound := object())) or False) and Bound.value", set()),
            ("(flag and (Bound := object())) and (Bound.value, Other.value)", {"external.Other"}),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                source = "from external import Bound, Other\nclass Service(option=" + expression + "):\n    pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(_first_class(tree)), names))

    def test_class_keyword_completed_with_proves_only_guaranteed_targets(self) -> None:
        cases = [
            ("with manager as item:\n        pass", set()),
            ("with manager as item:\n        from genuine import Item as item", {"item.value"}),
            ("with manager as item:\n        del item", {"item.value"}),
            ("with manager as (item, spare):\n        pass", {"item.value"}),
            ("with manager as spare, second as item:\n        pass", {"item.value"}),
            ("with manager as item, second as spare:\n        pass", set()),
            ("with manager as spare, (item := second) as other:\n        pass", {"item.value"}),
            ("if True:\n        with manager as item:\n            pass", set()),
            ("if flag:\n        with manager as item:\n            pass", {"item.value"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Item as item\nclass Outer:\n    " + body + "\n    class Service(option=item.value):\n        pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names))

    def test_conditional_path_proofs_preserve_base_and_decorator_contract(self) -> None:
        cases = [
            ("class Service(Bound.Factory if flag and (Bound := local_namespace) else object):\n    pass", {"external.Factory"}),
            ("@(Bound.decorate if flag and (Bound := local_namespace) else identity)\nclass Service:\n    pass", {"external.decorate"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "import external as Bound\n" + body + "\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(_first_class(tree)), names))

    def test_class_keyword_future_eager_bindings_do_not_capture_enclosing_parameters(self) -> None:
        for later in ["def configure(arg=(options := object())):\n            pass", "callback=lambda arg=(options := object()): arg"]:
            with self.subTest(later=later):
                source = "import external as options\ndef build(options):\n    class Outer:\n        class Service(policy=options.factory):\n            pass\n        " + later + "\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset({"options.factory"}), measure_class_dependencies(_class_info(node), names))

    def test_class_keyword_active_blocks_preserve_local_bindings(self) -> None:
        cases = [
            ("for item in rows:\n        class Service(option=item.value):\n            pass", set()),
            ("with manager as item:\n        class Service(option=item.value):\n            pass", set()),
            ("try:\n        raise ValueError\n    except ValueError as item:\n        class Service(option=item.value):\n            pass", set()),
            ("if flag:\n        item = object()\n        class Service(option=item.value):\n            pass", set()),
            ("item=object()\n    if flag:\n        spare=1\n    class Service(option=item.value):\n        pass", set()),
            ("item=object()\n    for spare in rows:\n        pass\n    class Service(option=item.value):\n        pass", set()),
            ("item=object()\n    with manager as spare:\n        pass\n    class Service(option=item.value):\n        pass", set()),
            ("if flag:\n        class Service(option=item.value):\n            pass", {"external.Item"}),
            ("for spare in rows:\n        class Service(option=item.value):\n            pass", {"external.Item"}),
            ("item=object()\n    if flag:\n        from external import Item as item\n    class Service(option=item.value):\n        pass", {"external.Item"}),
            ("for item in rows:\n        from genuine import Item as item\n        class Service(option=item.value):\n            pass", {"item.value"}),
            ("for item in rows:\n        del item\n        class Service(option=item.value):\n            pass", {"item.value"}),
            ("while flag:\n        item=object()\n        class Service(option=item.value):\n            pass", set()),
            ("with first as spare, second as item:\n        if flag:\n            class Service(option=item.value):\n                pass", set()),
            ("if flag:\n        def configure(arg=(item := object())):\n            pass\n        class Service(option=item.value):\n            pass", set()),
            ("if flag:\n        def configure():\n            item=object()\n        class Service(option=item.value):\n            pass", {"external.Item"}),
            ("item=object()\n    if False:\n        del item\n    class Service(option=item.value):\n        pass", set()),
            ("if True:\n        item=object()\n    class Service(option=item.value):\n        pass", set()),
            ("match value:\n        case item:\n            class Service(option=item.value):\n                pass", set()),
            ("for item in rows:\n        class Service(option=lambda: item.value):\n            pass", {"external.Item"}),
            ("for item in rows:\n        class Service(option=[item.value for spare in ()]):\n            pass", {"external.Item"}),
            ("for item in rows:\n        class Service(option=lambda argument=item.value: argument):\n            pass", set()),
            ("item=object()\n    try:\n        from genuine import Item as item\n    finally:\n        class Service(option=item.value):\n            pass", {"item.value"}),
            ("item=object()\n    try:\n        from genuine import Item as item\n        raise ValueError\n    except ValueError:\n        class Service(option=item.value):\n            pass", {"item.value"}),
            ("try:\n        raise ValueError\n    except (item := Error):\n        class Service(option=item.value):\n            pass", set()),
            ("match (item := object()):\n        case _:\n            class Service(option=item.value):\n                pass", set()),
            ("try:\n        item=object()\n    except ValueError:\n        pass\n    else:\n        class Service(option=item.value):\n            pass", set()),
            ("item=object()\n    for spare in rows:\n        class Service(option=item.value):\n            pass\n        from genuine import Item as item", {"item.value"}),
            ("item=object()\n    try:\n        item=object()\n    finally:\n        class Service(option=item.value):\n            pass", set()),
            ("item=object()\n    try:\n        raise ValueError\n    except ValueError as item:\n        pass\n    class Service(option=item.value):\n        pass", {"item.value"}),
            ("item=object()\n    if flag:\n        item=object()\n    class Service(option=item.value):\n        pass", set()),
            ("callback=lambda arg=(item := object()): arg\n    from genuine import Item as item\n    class Service(option=item.value):\n        pass", {"genuine.Item"}),
            ("callback=lambda arg=(item := object()): arg\n    try:\n        from genuine import Item as item\n    finally:\n        class Service(option=item.value):\n            pass", {"genuine.Item"}),
            ("for spare in ((item := object()), 1):\n        class Service(option=item.value):\n            pass\n        from genuine import Item as item", {"item.value"}),
            ("for spare in (item := rows):\n        pass\n    else:\n        class Service(option=item.value):\n            pass", set()),
            ("try:\n        raise TypeError\n    except (item := ValueError):\n        pass\n    except TypeError:\n        class Service(option=item.args):\n            pass", set()),
            ("callback=lambda arg=(item := object()): arg\n    if False:\n        from genuine import Item as item\n    class Service(option=item.value):\n        pass", set()),
            ("callback=lambda arg=(item := object()): arg\n    if False:\n        del item\n    class Service(option=item.value):\n        pass", set()),
            ("for spare in (item := rows):\n        item=object()\n        class Service(option=item.value):\n            pass", set()),
            ("for item in (item := rows):\n        class Service(option=item.value):\n            pass\n        from genuine import Item as item", set()),
            ("for spare in (item := rows):\n        from genuine import Item as item\n    else:\n        class Service(option=item.value):\n            pass", {"item.value"}),
            ("callback=lambda arg=(item := object()): arg\n    if flag:\n        if False:\n            from genuine import Item as item\n    class Service(option=item.value):\n        pass", set()),
            ("try:\n        raise TypeError\n    except (item := ValueError):\n        from genuine import Item as item\n    except TypeError:\n        class Service(option=item.args):\n            pass", set()),
            ("try:\n        raise ExceptionGroup('errors', [ValueError(), TypeError()])\n    except* (item := ValueError):\n        from genuine import Item as item\n    except* TypeError:\n        class Service(option=item.value):\n            pass", {"item.value"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "from external import Item as item\nclass Outer:\n    " + body + "\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names))

    def test_class_keyword_conditional_branches_use_truth_path_bindings(self) -> None:
        cases = [
            ("Bound.value if flag and (Bound := object()) else None", set()),
            ("None if flag or (Bound := object()) else Bound.value", set()),
            ("Bound.value if not (flag or (Bound := object())) else None", set()),
            ("Bound.value if flag or (Bound := object()) else None", {"external.Bound"}),
            ("None if flag and (Bound := object()) else Bound.value", {"external.Bound"}),
            ("Bound.value if flag and (Bound := Other()) else None", {"external.Other"}),
            ("Bound.value if flag else None", {"external.Bound"}),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                source = "from external import Bound, Other\n" + f"class Service(option={expression}):\n    pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(_first_class(tree)), names))

    def test_nested_class_headers_preserve_existing_base_and_decorator_dependencies(self) -> None:
        cases = [
            ("class Service(external.Factory):\n        pass\n    external = object()", {"external.Factory"}),
            ("@external.decorate\n    class Service:\n        pass\n    external = object()", {"external.decorate"}),
            ("external = object()\n    class Service(external.Factory):\n        pass", {"external.Factory"}),
            ("external = object()\n    @external.decorate\n    class Service:\n        pass", {"external.decorate"}),
            ("class Service(option=external.Factory):\n        pass\n    external = object()", {"external.Factory"}),
            ("external = object()\n    class Service(option=external.Factory):\n        pass", set()),
            ("external = object()\n    import genuine as external\n    class Service(option=external.Factory):\n        pass", {"genuine.Factory"}),
            ("if flag:\n        external = object()\n    class Service(option=external.Factory):\n        pass", {"external.Factory"}),
            ("external = object()\n    if flag:\n        import genuine as external\n    class Service(option=external.Factory):\n        pass", {"genuine.Factory"}),
            ("external = object()\n    del external\n    class Service(option=external.Factory):\n        pass", {"external.Factory"}),
            ("external: object\n    class Service(option=external.Factory):\n        pass", {"external.Factory"}),
            ("external = object()\n    spare = object()\n    del spare\n    class Service(option=external.Factory):\n        pass", set()),
            ("external = object()\n    if flag:\n        del external\n    class Service(option=external.Factory):\n        pass", {"external.Factory"}),
            ("external = object()\n    if flag:\n        del external\n        class Service(option=external.Factory):\n            pass", {"external.Factory"}),
            ("external = object()\n    class Inner:\n        class Service(option=external.Factory):\n            pass", {"external.Factory"}),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                source = "import external\nclass Outer:\n    " + body + "\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names))

    def test_class_keywords_include_enclosing_bindings_from_evaluated_definition_headers(self) -> None:
        cases = [
            ("def configure(arg=(Bound := object())):\n        pass", set()),
            ("def configure(*, arg=(Bound := object())):\n        pass", set()),
            ("async def configure(arg=(Bound := object())):\n        pass", set()),
            ("@(Bound := decorate)\n    def configure():\n        pass", set()),
            ("class Configure((Bound := Base)):\n        pass", set()),
            ("class Configure(option=(Bound := object())):\n        pass", set()),
            ("@(Bound := decorate)\n    class Configure:\n        pass", set()),
            ("def configure(arg=(Bound := Other())):\n        pass", set()),
            ("def configure():\n        Bound = object()", {"external.Bound"}),
            ("class Configure:\n        Bound = object()", {"external.Bound"}),
            ("def configure(arg=lambda: (Bound := object())):\n        pass", {"external.Bound"}),
            ("def configure(arg=(lambda value=(Bound := object()): value)):\n        pass", set()),
            ("def configure(arg=(Bound := object())):\n        pass\n    from genuine import Bound", {"genuine.Bound"}),
            ("global Bound\n    def configure(arg=(Bound := object())):\n        pass", {"external.Bound"}),
            ("if False:\n        def configure(arg=(Bound := object())):\n            pass", set()),
        ]
        for definition, expected in cases:
            with self.subTest(definition=definition):
                source = "from external import Bound, Other\ndef build():\n    " + definition + "\n    class Service(option=Bound.value):\n        pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names))

    @unittest.skipIf(sys.version_info >= (3, 14), "assignment expressions in annotations are invalid on Python 3.14")
    def test_class_keyword_bindings_include_eager_annotation_assignments(self) -> None:
        for definition in ["def configure(arg: (Bound := object())):\n        pass", "def configure() -> (Bound := object()):\n        pass", "def configure(arg: (lambda value=(Bound := object()): value)):\n        pass"]:
            with self.subTest(definition=definition):
                source = "from external import Bound\ndef build():\n    " + definition + "\n    class Service(option=Bound.value):\n        pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))
                self.assertEqual(frozenset(), measure_class_dependencies(_class_info(node), names))

    @unittest.skipIf(sys.version_info < (3, 14), "annotation assignment expressions become invalid on Python 3.14")
    def test_annotation_assignments_are_compiler_rejected(self) -> None:
        for source in ["def configure(arg: (Bound := object())): pass", "def configure() -> (Bound := object()): pass", "def configure(arg: (lambda value=(Bound := object()): value)): pass"]:
            with self.subTest(source=source), self.assertRaisesRegex(SyntaxError, "named expression cannot be used within an annotation"):
                compile(source, "service.py", "exec", dont_inherit=True)

    @unittest.skipIf(sys.version_info < (3, 12), "type parameter syntax requires Python 3.12")
    def test_class_keyword_bindings_exclude_lazy_type_expressions(self) -> None:
        cases = [
            ("def configure[T](arg=(Bound := object())):\n        pass", set()),
            ("def configure[T: (lambda: (Bound := object()))]():\n        pass", {"external.Bound"}),
            ("class Configure[T: (lambda: (Bound := object()))]:\n        pass", {"external.Bound"}),
            ("type Alias = (lambda: (Bound := object()))", {"external.Bound"}),
        ]
        for definition, expected in cases:
            with self.subTest(definition=definition):
                source = "from external import Bound\ndef build():\n    " + definition + "\n    class Service(option=Bound.value):\n        pass\n"
                compile(source, "service.py", "exec", dont_inherit=True)
                tree = ast.parse(source)
                node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Service")
                names = Names.build(tree, module=None, path=Path("service.py"))

                self.assertEqual(frozenset(expected), measure_class_dependencies(_class_info(node), names))

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
