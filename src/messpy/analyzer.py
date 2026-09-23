from __future__ import annotations

import ast
from bisect import bisect_right
import builtins
from collections import defaultdict
from collections.abc import Sequence, Set as AbstractSet
from dataclasses import dataclass, replace
import keyword
import re
import symtable
import token
import tokenize
from io import StringIO
from pathlib import Path

from .rulesets import LoadedRule, RulesetError

__all__ = ["DEFAULT_SUFFIXES", "Analysis", "Finding", "ProcessingError", "analyze"]

DEFAULT_SUFFIXES = frozenset({".py", ".pyi"})


@dataclass(frozen=True)
class Analysis:
    findings: tuple[Finding, ...]
    errors: tuple[ProcessingError, ...]


def analyze(
    paths: Sequence[Path | str],
    *,
    rules: Sequence[LoadedRule],
    suffixes: AbstractSet[str] = DEFAULT_SUFFIXES,
    exclusions: Sequence[str] = (),
    ignore_tests: bool = False,
) -> Analysis:
    from .onion import validate_onion_rules

    validate_onion_rules(rules)
    input_paths = [Path(value).resolve() for value in paths]
    source_files = _source_files(input_paths, suffixes, exclusions, ignore_tests)
    findings, processing_errors = _analyze(source_files, rules)
    return Analysis(findings=tuple(findings), errors=tuple(processing_errors))


METHOD_LENGTH_RULE_NAME = "ExcessiveMethodLength"


CYCLOMATIC_COMPLEXITY_RULE_NAME = "CyclomaticComplexity"


NPATH_COMPLEXITY_RULE_NAME = "NPathComplexity"


EXCESSIVE_PARAMETER_LIST_RULE_NAME = "ExcessiveParameterList"


EXCESSIVE_CLASS_LENGTH_RULE_NAME = "ExcessiveClassLength"


EXCESSIVE_PUBLIC_COUNT_RULE_NAME = "ExcessivePublicCount"


TOO_MANY_FIELDS_RULE_NAME = "TooManyFields"


TOO_MANY_METHODS_RULE_NAME = "TooManyMethods"


TOO_MANY_PUBLIC_METHODS_RULE_NAME = "TooManyPublicMethods"


EXCESSIVE_CLASS_COMPLEXITY_RULE_NAME = "ExcessiveClassComplexity"


SHORT_CLASS_NAME_RULE_NAME = "ShortClassName"


LONG_CLASS_NAME_RULE_NAME = "LongClassName"


SHORT_VARIABLE_RULE_NAME = "ShortVariable"


LONG_VARIABLE_RULE_NAME = "LongVariable"


SHORT_METHOD_NAME_RULE_NAME = "ShortMethodName"


CONSTANT_NAMING_CONVENTIONS_RULE_NAME = "ConstantNamingConventions"


BOOLEAN_GET_METHOD_NAME_RULE_NAME = "BooleanGetMethodName"


UNUSED_LOCAL_VARIABLE_RULE_NAME = "UnusedLocalVariable"


UNUSED_FORMAL_PARAMETER_RULE_NAME = "UnusedFormalParameter"


UNUSED_PRIVATE_FIELD_RULE_NAME = "UnusedPrivateField"


UNUSED_PRIVATE_METHOD_RULE_NAME = "UnusedPrivateMethod"


BOOLEAN_ARGUMENT_FLAG_RULE_NAME = "BooleanArgumentFlag"


ELSE_EXPRESSION_RULE_NAME = "ElseExpression"


STATIC_ACCESS_RULE_NAME = "StaticAccess"


IF_STATEMENT_ASSIGNMENT_RULE_NAME = "IfStatementAssignment"


DUPLICATED_ARRAY_KEY_RULE_NAME = "DuplicatedArrayKey"


EXIT_EXPRESSION_RULE_NAME = "ExitExpression"


EXIT_CALL_NAMES = frozenset(
    {"sys.exit", "os._exit", "builtins.exit", "builtins.quit", "exit", "quit"}
)


COUNT_IN_LOOP_EXPRESSION_RULE_NAME = "CountInLoopExpression"


DEVELOPMENT_CODE_FRAGMENT_RULE_NAME = "DevelopmentCodeFragment"


DEVELOPMENT_CALL_NAMES = frozenset({"breakpoint", "builtins.breakpoint", "pdb.set_trace"})


EMPTY_CATCH_BLOCK_RULE_NAME = "EmptyCatchBlock"


COUPLING_BETWEEN_OBJECTS_RULE_NAME = "CouplingBetweenObjects"


GLOBAL_VARIABLE_RULE_NAME = "GlobalVariable"


LACK_OF_COHESION_RULE_NAME = "LackOfCohesionOfMethods"


CAMEL_CASE_CLASS_RULE_NAME = "CamelCaseClassName"


CAMEL_CASE_METHOD_RULE_NAME = "CamelCaseMethodName"


CAMEL_CASE_PROPERTY_RULE_NAME = "CamelCasePropertyName"


CAMEL_CASE_PARAMETER_RULE_NAME = "CamelCaseParameterName"


CAMEL_CASE_VARIABLE_RULE_NAME = "CamelCaseVariableName"
IMPLICIT_INPUT_RULE_NAME = "ImplicitInput"
IMPLICIT_OUTPUT_RULE_NAME = "ImplicitOutput"
IMPLICIT_INSTANCE_INPUT_RULE_NAME = "ImplicitInstanceInput"
IMPLICIT_INSTANCE_OUTPUT_RULE_NAME = "ImplicitInstanceOutput"


DEFAULT_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "cache",
        "coverage",
        "dist",
        "env",
        "generated",
        "htmlcov",
        "out",
        "output",
        "site-packages",
        "tmp",
        "venv",
    }
)


TEST_DIRECTORY_NAMES = frozenset({"test", "tests", "__test__", "__tests__"})


DIRECTIVE_PATTERN = re.compile(
    r"^messpy-(disable-next-line|disable|enable)(?:\s+(.+?))?$", re.IGNORECASE
)


RULE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


CODE_SIZE_RULE_NAMES = frozenset(
    {
        CYCLOMATIC_COMPLEXITY_RULE_NAME,
        NPATH_COMPLEXITY_RULE_NAME,
        METHOD_LENGTH_RULE_NAME,
        EXCESSIVE_PARAMETER_LIST_RULE_NAME,
        EXCESSIVE_CLASS_LENGTH_RULE_NAME,
        EXCESSIVE_PUBLIC_COUNT_RULE_NAME,
        TOO_MANY_FIELDS_RULE_NAME,
        TOO_MANY_METHODS_RULE_NAME,
        TOO_MANY_PUBLIC_METHODS_RULE_NAME,
        EXCESSIVE_CLASS_COMPLEXITY_RULE_NAME,
    }
)


CLASS_CODE_SIZE_RULE_NAMES = frozenset(
    {
        EXCESSIVE_CLASS_LENGTH_RULE_NAME,
        EXCESSIVE_PUBLIC_COUNT_RULE_NAME,
        TOO_MANY_FIELDS_RULE_NAME,
        TOO_MANY_METHODS_RULE_NAME,
        TOO_MANY_PUBLIC_METHODS_RULE_NAME,
        EXCESSIVE_CLASS_COMPLEXITY_RULE_NAME,
    }
)


NAMING_RULE_NAMES = frozenset(
    {
        SHORT_CLASS_NAME_RULE_NAME,
        LONG_CLASS_NAME_RULE_NAME,
        SHORT_VARIABLE_RULE_NAME,
        LONG_VARIABLE_RULE_NAME,
        SHORT_METHOD_NAME_RULE_NAME,
        CONSTANT_NAMING_CONVENTIONS_RULE_NAME,
        BOOLEAN_GET_METHOD_NAME_RULE_NAME,
        CAMEL_CASE_CLASS_RULE_NAME,
        CAMEL_CASE_METHOD_RULE_NAME,
        CAMEL_CASE_PROPERTY_RULE_NAME,
        CAMEL_CASE_PARAMETER_RULE_NAME,
        CAMEL_CASE_VARIABLE_RULE_NAME,
    }
)


UNUSED_CODE_RULE_NAMES = frozenset(
    {
        UNUSED_LOCAL_VARIABLE_RULE_NAME,
        UNUSED_FORMAL_PARAMETER_RULE_NAME,
        UNUSED_PRIVATE_FIELD_RULE_NAME,
        UNUSED_PRIVATE_METHOD_RULE_NAME,
    }
)


CLEAN_CODE_RULE_NAMES = frozenset(
    {
        BOOLEAN_ARGUMENT_FLAG_RULE_NAME,
        ELSE_EXPRESSION_RULE_NAME,
        STATIC_ACCESS_RULE_NAME,
        IF_STATEMENT_ASSIGNMENT_RULE_NAME,
        DUPLICATED_ARRAY_KEY_RULE_NAME,
    }
)


DESIGN_RULE_NAMES = frozenset(
    {
        EXIT_EXPRESSION_RULE_NAME,
        COUNT_IN_LOOP_EXPRESSION_RULE_NAME,
        DEVELOPMENT_CODE_FRAGMENT_RULE_NAME,
        EMPTY_CATCH_BLOCK_RULE_NAME,
        COUPLING_BETWEEN_OBJECTS_RULE_NAME,
        GLOBAL_VARIABLE_RULE_NAME,
        LACK_OF_COHESION_RULE_NAME,
    }
)
EXPLICITNESS_RULE_NAMES = frozenset(
    {
        IMPLICIT_INPUT_RULE_NAME,
        IMPLICIT_OUTPUT_RULE_NAME,
        IMPLICIT_INSTANCE_INPUT_RULE_NAME,
        IMPLICIT_INSTANCE_OUTPUT_RULE_NAME,
    }
)
# __new__ is not in this set. Its receiver is the class, so a write in __new__ changes shared state.
CONSTRUCTOR_METHOD_NAMES = frozenset({"__init__", "__post_init__"})
MUTATOR_METHOD_NAMES = frozenset(
    {"add", "append", "clear", "discard", "extend", "insert", "pop", "remove", "reverse", "sort", "update"}
)
BUILTIN_ATTRIBUTE_MUTATORS = frozenset({"builtins.setattr", "builtins.delattr"})
IMPLICIT_INPUT_NAMES = frozenset(
    {
        "builtins.input",
        "datetime.date.today",
        "datetime.datetime.now",
        "datetime.datetime.today",
        "datetime.datetime.utcnow",
        "os.environ",
        "os.getcwd",
        "os.getenv",
        "os.listdir",
        "os.urandom",
        "random.choice",
        "random.choices",
        "random.gauss",
        "random.getrandbits",
        "random.randint",
        "random.random",
        "random.randrange",
        "random.sample",
        "random.shuffle",
        "random.uniform",
        "secrets.choice",
        "secrets.randbelow",
        "secrets.randbits",
        "secrets.token_bytes",
        "secrets.token_hex",
        "secrets.token_urlsafe",
        "sys.argv",
        "sys.stdin",
        "time.monotonic",
        "time.perf_counter",
        "time.time",
        "time.time_ns",
        "uuid.uuid1",
        "uuid.uuid4",
    }
)
IMPLICIT_OUTPUT_NAMES = frozenset(
    {
        "builtins.print",
        "logging.critical",
        "logging.debug",
        "logging.error",
        "logging.exception",
        "logging.info",
        "logging.log",
        "logging.warning",
        "os.makedirs",
        "os.mkdir",
        "os.putenv",
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.system",
        "os.unlink",
        "os.unsetenv",
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "subprocess.run",
        "sys.stderr",
        "sys.stdout",
    }
)
OPEN_CALL_NAMES = frozenset({"builtins.open", "io.open"})


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    rule_name: str
    priority: int
    message: str
    suppressed: bool = False
    context: str = ""


@dataclass(frozen=True)
class ProcessingError:
    path: Path
    line: int
    message: str


@dataclass(frozen=True)
class CallableInfo:
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    name: str
    kind: str
    parameter_count: int


@dataclass(frozen=True)
class ClassInfo:
    node: ast.ClassDef
    name: str
    fields: tuple[str, ...]
    methods: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]
    is_ast_visitor: bool
    has_unresolved_base: bool


@dataclass(frozen=True)
class NamingTarget:
    name: str
    line: int
    role: str
    contract: bool = False


@dataclass(frozen=True)
class NamingCallable:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    role: str


@dataclass(frozen=True)
class ScopeUsage:
    used_names: frozenset[str]
    free_names: frozenset[str]


@dataclass(frozen=True)
class PrivateMemberUsage:
    accessed_names: frozenset[str]
    exported_names: frozenset[str]
    requires_conservative_handling: bool


@dataclass(frozen=True)
class CleanCodeCallable:
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    owner_name: str | None


def _analyze(
    source_files: Sequence[Path], rules: Sequence[LoadedRule]
) -> tuple[list[Finding], list[ProcessingError]]:
    findings: list[Finding] = []
    processing_errors: list[ProcessingError] = []
    for source_file in source_files:
        try:
            with tokenize.open(source_file) as source_handle:
                source = source_handle.read()
            tree = ast.parse(source, filename=str(source_file))
        except SyntaxError as error:
            line = error.lineno or 1
            processing_errors.append(
                ProcessingError(source_file, line, f"Could not parse {source_file}: {error.msg}")
            )
            continue
        except (RecursionError, MemoryError, OSError, UnicodeError) as error:
            processing_errors.append(ProcessingError(source_file, 1, f"Could not process {source_file}: {error}"))
            continue
        try:
            findings.extend(_apply_suppressions(source, tree, _findings(source_file, source, tree, rules)))
        except SyntaxError as error:
            # ast.parse() above accepts some sources (e.g. duplicate parameter
            # names) that symtable.symtable() rejects; rules that build symbol
            # tables can hit this second, stricter parse.
            line = error.lineno or 1
            processing_errors.append(
                ProcessingError(source_file, line, f"Could not analyze {source_file}: {error.msg}")
            )
        except (RecursionError, MemoryError, tokenize.TokenError, ValueError, OSError, UnicodeError) as error:
            processing_errors.append(
                ProcessingError(source_file, 1, f"Could not process {source_file}: {error}")
            )
    return findings, processing_errors


def _findings(path: Path, source: str, tree: ast.Module, rules: Sequence[LoadedRule]) -> list[Finding]:
    from .onion import onion_findings

    rule_names = frozenset(rule.name for rule in rules)
    classes = _selected_classes(tree, rule_names)
    callables = _selected_callables(tree, rule_names)
    function_scopes = _selected_function_scopes(source, tree, rule_names)
    protocol_method_ids = _selected_protocol_method_ids(tree, rule_names)
    comprehension_scopes = _selected_comprehension_scopes(source, tree, rule_names)
    private_member_usage = _selected_private_member_usage(tree, rule_names)
    clean_code_callables = _selected_clean_code_callables(tree, rule_names)
    return [
        *_cyclomatic_complexity_findings(path, callables, rules),
        *_npath_complexity_findings(path, callables, rules),
        *_excessive_method_length_findings(path, callables, rules),
        *_excessive_parameter_list_findings(path, callables, rules),
        *_selected_class_findings(path, source, classes, rules, rule_names),
        *_selected_naming_findings(path, tree, rules, rule_names),
        *_unused_local_variable_findings(path, rules, function_scopes, comprehension_scopes, protocol_method_ids),
        *_unused_formal_parameter_findings(path, tree, rules, function_scopes, protocol_method_ids),
        *_unused_private_field_findings(path, tree, classes, rules, private_member_usage),
        *_unused_private_method_findings(path, classes, rules, private_member_usage),
        *_selected_clean_code_findings(path, source, tree, rules, rule_names, clean_code_callables),
        *_selected_design_findings(path, source, tree, classes, rules, rule_names, clean_code_callables),
        *_selected_explicitness_findings(path, tree, rules, rule_names),
        *onion_findings(path, tree, rules),
    ]


def _selected_classes(tree: ast.Module, rule_names: AbstractSet[str]) -> list[ClassInfo]:
    class_rules = CLASS_CODE_SIZE_RULE_NAMES | {
        UNUSED_PRIVATE_FIELD_RULE_NAME,
        UNUSED_PRIVATE_METHOD_RULE_NAME,
        COUPLING_BETWEEN_OBJECTS_RULE_NAME,
        LACK_OF_COHESION_RULE_NAME,
    }
    if not _has_any_rule(rule_names, class_rules):
        return []
    return _classes(tree)


def _selected_callables(tree: ast.Module, rule_names: AbstractSet[str]) -> list[CallableInfo]:
    callable_rules = {
        CYCLOMATIC_COMPLEXITY_RULE_NAME,
        NPATH_COMPLEXITY_RULE_NAME,
        METHOD_LENGTH_RULE_NAME,
        EXCESSIVE_PARAMETER_LIST_RULE_NAME,
    }
    if not _has_any_rule(rule_names, callable_rules):
        return []
    return _callables(tree)


def _selected_function_scopes(
    source: str, tree: ast.Module, rule_names: AbstractSet[str]
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, symtable.SymbolTable, frozenset[str]]]:
    if not _has_any_rule(rule_names, {UNUSED_LOCAL_VARIABLE_RULE_NAME, UNUSED_FORMAL_PARAMETER_RULE_NAME}):
        return []
    return _function_scopes(source, tree)


def _selected_protocol_method_ids(tree: ast.Module, rule_names: AbstractSet[str]) -> set[int]:
    if not _has_any_rule(rule_names, {UNUSED_LOCAL_VARIABLE_RULE_NAME, UNUSED_FORMAL_PARAMETER_RULE_NAME}):
        return set()
    return _protocol_method_ids(tree)


def _selected_comprehension_scopes(
    source: str, tree: ast.Module, rule_names: AbstractSet[str]
) -> list[
    tuple[
        ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        symtable.SymbolTable | None,
    ]
]:
    if UNUSED_LOCAL_VARIABLE_RULE_NAME not in rule_names:
        return []
    return _comprehension_scopes(source, tree)


def _selected_private_member_usage(
    tree: ast.Module, rule_names: AbstractSet[str]
) -> PrivateMemberUsage | None:
    private_member_rules = {UNUSED_PRIVATE_FIELD_RULE_NAME, UNUSED_PRIVATE_METHOD_RULE_NAME}
    if not _has_any_rule(rule_names, private_member_rules):
        return None
    return _private_member_usage(tree)


def _selected_clean_code_callables(
    tree: ast.Module, rule_names: AbstractSet[str]
) -> list[CleanCodeCallable]:
    callable_rules = {
        BOOLEAN_ARGUMENT_FLAG_RULE_NAME,
        ELSE_EXPRESSION_RULE_NAME,
        STATIC_ACCESS_RULE_NAME,
        EXIT_EXPRESSION_RULE_NAME,
        COUNT_IN_LOOP_EXPRESSION_RULE_NAME,
        DEVELOPMENT_CODE_FRAGMENT_RULE_NAME,
        EMPTY_CATCH_BLOCK_RULE_NAME,
    }
    if not _has_any_rule(rule_names, callable_rules):
        return []
    return _clean_code_callables(tree)


def _selected_class_findings(
    path: Path,
    source: str,
    classes: Sequence[ClassInfo],
    rules: Sequence[LoadedRule],
    rule_names: AbstractSet[str],
) -> list[Finding]:
    if not _has_any_rule(rule_names, CLASS_CODE_SIZE_RULE_NAMES):
        return []
    return _class_findings(path, source.splitlines(), classes, rules)


def _selected_naming_findings(
    path: Path,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    rule_names: AbstractSet[str],
) -> list[Finding]:
    if not _has_any_rule(rule_names, NAMING_RULE_NAMES):
        return []
    return _naming_findings(path, tree, rules)


def _selected_clean_code_findings(
    path: Path,
    source: str,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    rule_names: AbstractSet[str],
    clean_code_callables: Sequence[CleanCodeCallable],
) -> list[Finding]:
    if not _has_any_rule(rule_names, CLEAN_CODE_RULE_NAMES):
        return []
    return _clean_code_findings(path, source, tree, rules, clean_code_callables)


def _selected_design_findings(
    path: Path,
    source: str,
    tree: ast.Module,
    classes: Sequence[ClassInfo],
    rules: Sequence[LoadedRule],
    rule_names: AbstractSet[str],
    clean_code_callables: Sequence[CleanCodeCallable],
) -> list[Finding]:
    if not _has_any_rule(rule_names, DESIGN_RULE_NAMES):
        return []
    return _design_findings(path, source, tree, classes, rules, rule_names, clean_code_callables)


def _design_findings(
    path: Path,
    source: str,
    tree: ast.Module,
    classes: Sequence[ClassInfo],
    rules: Sequence[LoadedRule],
    rule_names: AbstractSet[str],
    clean_code_callables: Sequence[CleanCodeCallable],
) -> list[Finding]:
    parents = _selected_design_parents(tree, rule_names)
    contexts = _selected_design_contexts(clean_code_callables, rule_names)
    bindings = _selected_design_bindings(tree, rule_names)
    resolved_calls = (
        _resolved_call_names(tree, bindings)
        if _has_any_rule(rule_names, {EXIT_EXPRESSION_RULE_NAME, DEVELOPMENT_CODE_FRAGMENT_RULE_NAME})
        else {}
    )
    return [
        *_exit_expression_findings(path, tree, rules, parents, contexts, resolved_calls),
        *_count_in_loop_findings(path, tree, rules, parents, contexts, bindings),
        *_development_fragment_findings(path, source, tree, rules, parents, contexts, resolved_calls),
        *_empty_catch_findings(path, tree, rules, parents, contexts),
        *_coupling_findings(path, tree, classes, rules),
        *_global_variable_findings(path, tree, rules, parents, bindings),
        *_cohesion_findings(path, classes, rules),
    ]


def _selected_design_parents(tree: ast.Module, rule_names: AbstractSet[str]) -> dict[int, ast.AST]:
    parent_rules = {
        EXIT_EXPRESSION_RULE_NAME,
        COUNT_IN_LOOP_EXPRESSION_RULE_NAME,
        DEVELOPMENT_CODE_FRAGMENT_RULE_NAME,
        EMPTY_CATCH_BLOCK_RULE_NAME,
        GLOBAL_VARIABLE_RULE_NAME,
    }
    if not _has_any_rule(rule_names, parent_rules):
        return {}
    return {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _selected_design_contexts(
    clean_code_callables: Sequence[CleanCodeCallable], rule_names: AbstractSet[str]
) -> dict[int, str]:
    context_rules = {
        EXIT_EXPRESSION_RULE_NAME,
        COUNT_IN_LOOP_EXPRESSION_RULE_NAME,
        DEVELOPMENT_CODE_FRAGMENT_RULE_NAME,
        EMPTY_CATCH_BLOCK_RULE_NAME,
    }
    if not _has_any_rule(rule_names, context_rules):
        return {}
    return {
        id(callable_info.node): _clean_code_context(callable_info)
        for callable_info in clean_code_callables
    }


def _selected_design_bindings(tree: ast.Module, rule_names: AbstractSet[str]) -> dict[int, set[str]]:
    binding_rules = {
        EXIT_EXPRESSION_RULE_NAME,
        COUNT_IN_LOOP_EXPRESSION_RULE_NAME,
        DEVELOPMENT_CODE_FRAGMENT_RULE_NAME,
        GLOBAL_VARIABLE_RULE_NAME,
    }
    if not _has_any_rule(rule_names, binding_rules):
        return {}
    return _scope_bindings(tree)


_BindingScope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef


@dataclass(frozen=True)
class _ScopeCallImports:
    """The call-relevant imports and the other name bindings of one scope."""

    call_modules: dict[str, str]
    rebound: set[str]


def _exit_expression_findings(
    path: Path,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    parents: dict[int, ast.AST],
    contexts: dict[int, str],
    resolved_calls: dict[int, str],
) -> list[Finding]:
    rule = _rule(rules, EXIT_EXPRESSION_RULE_NAME)
    if rule is None:
        return []
    reported_scopes: set[int] = set()
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_exit_call(node, resolved_calls):
            continue
        scope, context = _design_scope(node, parents, contexts)
        if id(scope) in reported_scopes:
            continue
        reported_scopes.add(id(scope))
        findings.append(
            Finding(
                path,
                node.lineno,
                rule.name,
                rule.priority,
                f"The {context} contains an exit expression.",
                context=context,
            )
        )
    return findings


def _is_exit_call(
    node: ast.Call, resolved_calls: dict[int, str]
) -> bool:
    return resolved_calls.get(id(node), "") in EXIT_CALL_NAMES


def _resolved_call_names(
    tree: ast.Module,
    bindings: dict[int, set[str]],
) -> dict[int, str]:
    aliases = _imported_call_aliases(tree)
    resolved_calls: dict[int, str] = {}
    active_names, changes = _call_scope_entered({}, [], tree, aliases, bindings)
    pending: list[tuple[ast.AST, bool]] = [(tree, False)]
    while pending:
        node, leaving_scope = pending.pop()
        if leaving_scope:
            active_names, changes = _call_scope_left(active_names, changes)
            continue
        if isinstance(node, ast.Call):
            resolved_calls[id(node)] = _resolve_call_name(_dotted_name(node.func), active_names)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            active_names, changes = _call_scope_entered(active_names, changes, node, aliases, bindings)
            pending.append((node, True))
        children = list(ast.iter_child_nodes(node))
        pending.extend((child, False) for child in reversed(children))
    return resolved_calls


def _call_scope_entered(
    active_names: dict[str, str],
    changes: list[list[tuple[str, str | None]]],
    scope: _BindingScope,
    aliases: dict[int, _ScopeCallImports],
    bindings: dict[int, set[str]],
) -> tuple[dict[str, str], list[list[tuple[str, str | None]]]]:
    imports = aliases[id(scope)]
    scope_bindings = bindings[id(scope)]
    recorded: list[tuple[str, str | None]] = []
    updated = dict(active_names)
    for name in imports.rebound | set(imports.call_modules) | scope_bindings:
        recorded.append((name, active_names.get(name)))
        if name in imports.rebound or name not in imports.call_modules:
            updated[name] = ""
        else:
            updated[name] = imports.call_modules[name]
    return updated, [*changes, recorded]


def _call_scope_left(
    active_names: dict[str, str],
    changes: list[list[tuple[str, str | None]]],
) -> tuple[dict[str, str], list[list[tuple[str, str | None]]]]:
    updated = dict(active_names)
    for name, previous in reversed(changes[-1]):
        if previous is None:
            updated.pop(name, None)
        else:
            updated[name] = previous
    return updated, changes[:-1]


def _resolve_call_name(
    original_name: str,
    active_names: dict[str, str],
) -> str:
    root_name = original_name.split(".", 1)[0]
    attributes = original_name[len(root_name):]
    resolved_name = active_names.get(root_name)
    if resolved_name is None:
        return original_name
    if not resolved_name:
        return ""
    return f"{resolved_name}{attributes}"


def _count_in_loop_findings(
    path: Path,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    parents: dict[int, ast.AST],
    contexts: dict[int, str],
    bindings: dict[int, set[str]],
) -> list[Finding]:
    rule = _rule(rules, COUNT_IN_LOOP_EXPRESSION_RULE_NAME)
    if rule is None:
        return []
    findings: list[Finding] = []
    for loop in ast.walk(tree):
        if not isinstance(loop, ast.While):
            continue
        calls = _expression_calls(loop.test)
        length_call = next(
            (call for call in calls if isinstance(call.func, ast.Name) and call.func.id == "len"),
            None,
        )
        if length_call is None or _is_shadowed("len", length_call, tree, parents, bindings):
            continue
        _, context = _design_scope(loop, parents, contexts)
        findings.append(
            Finding(
                path,
                length_call.lineno,
                rule.name,
                rule.priority,
                "Avoid using len() in while loops.",
                context=context,
            )
        )
    return findings


def _development_fragment_findings(
    path: Path,
    source: str,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    parents: dict[int, ast.AST],
    contexts: dict[int, str],
    resolved_calls: dict[int, str],
) -> list[Finding]:
    rule = _rule(rules, DEVELOPMENT_CODE_FRAGMENT_RULE_NAME)
    if rule is None:
        return []
    unwanted = DEVELOPMENT_CALL_NAMES | {
        name.strip()
        for name in rule.properties.get("unwanted-functions", "").split(",")
        if name.strip()
    }
    findings = _development_call_findings(path, tree, rule, unwanted, parents, contexts, resolved_calls)
    findings.extend(_development_marker_findings(path, source, rule))
    return findings


def _development_call_findings(
    path: Path,
    tree: ast.Module,
    rule: LoadedRule,
    unwanted: set[str],
    parents: dict[int, ast.AST],
    contexts: dict[int, str],
    resolved_calls: dict[int, str],
) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        resolved = resolved_calls.get(id(node), "")
        if resolved in DEVELOPMENT_CALL_NAMES:
            name = resolved
        elif name not in unwanted or name == "breakpoint":
            # A bare `breakpoint` that resolution could not pin on the builtins
            # module is a user-defined or rebound name, so it stays quiet.
            continue
        _, context = _design_scope(node, parents, contexts)
        subject = "The module" if context == "module" else f"The {context}"
        findings.append(
            Finding(
                path,
                node.lineno,
                rule.name,
                rule.priority,
                f"{subject} calls the typical debug function {name}() which is mostly only used during development.",
                context=context,
            )
        )
    return findings


def _development_marker_findings(path: Path, source: str, rule: LoadedRule) -> list[Finding]:
    markers = [
        marker.strip().casefold()
        for marker in rule.properties.get("markers", "TODO,FIXME,HACK").split(",")
        if marker.strip()
    ]
    if not markers:
        return []
    marker_pattern = re.compile(
        "|".join(rf"\b{re.escape(marker)}\b" for marker in markers),
        re.IGNORECASE,
    )
    return [
        Finding(
            path,
            item.start[0],
            rule.name,
            rule.priority,
            "Development-only marker found in production source.",
            context="module",
        )
        for item in tokenize.generate_tokens(StringIO(source).readline)
        if item.type == token.COMMENT and marker_pattern.search(item.string)
    ]


def _empty_catch_findings(
    path: Path,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    parents: dict[int, ast.AST],
    contexts: dict[int, str],
) -> list[Finding]:
    rule = _rule(rules, EMPTY_CATCH_BLOCK_RULE_NAME)
    if rule is None:
        return []
    findings: list[Finding] = []
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not _is_empty_handler(handler):
            continue
        _, context = _design_scope(handler, parents, contexts)
        findings.append(
            Finding(
                path,
                handler.lineno,
                rule.name,
                rule.priority,
                f"Avoid using empty exception handlers in {context}.",
                context=context,
            )
        )
    return findings


def _is_empty_handler(handler: ast.ExceptHandler) -> bool:
    if len(handler.body) != 1:
        return False
    statement = handler.body[0]
    return isinstance(statement, ast.Pass) or (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def _coupling_findings(
    path: Path,
    tree: ast.Module,
    classes: Sequence[ClassInfo],
    rules: Sequence[LoadedRule],
) -> list[Finding]:
    rule = _rule(rules, COUPLING_BETWEEN_OBJECTS_RULE_NAME)
    if rule is None:
        return []
    maximum = _integer_property(rule, "maximum")
    aliases = _module_import_aliases(tree)
    module_names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    findings: list[Finding] = []
    for class_info in classes:
        count = len(_class_dependencies(class_info, aliases, module_names))
        if count < maximum:
            continue
        findings.append(
            _class_finding(
                path,
                class_info,
                rule,
                f"The class {class_info.name} has a coupling between objects value of {count}. "
                f"Consider to reduce the number of dependencies under {maximum}.",
            )
        )
    return findings


def _class_dependencies(
    class_info: ClassInfo,
    aliases: dict[str, tuple[str, bool]],
    module_names: set[str],
) -> set[str]:
    local_names = {
        class_info.name,
        *module_names,
        *class_info.fields,
        *(method.name for method in class_info.methods),
    }
    dependencies: set[str] = set()
    active_aliases = dict(aliases)
    active_names = set(local_names)
    for expression in [*class_info.node.bases, *class_info.node.decorator_list]:
        dependencies, active_aliases, active_names = _dependency_state(
            expression, active_aliases, active_names, dependencies
        )
    for statement in class_info.node.body:
        if not isinstance(statement, ast.ClassDef):
            dependencies, active_aliases, active_names = _dependency_state(
                statement, active_aliases, active_names, dependencies
            )
    if class_info.is_ast_visitor:
        dependencies = {dependency for dependency in dependencies if not dependency.startswith("ast.")}
    return dependencies


def _module_import_aliases(tree: ast.Module) -> dict[str, tuple[str, bool]]:
    aliases: dict[str, tuple[str, bool]] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for item in statement.names:
                binding = item.asname or item.name.split(".", 1)[0]
                target = item.name if item.asname else binding
                aliases[binding] = (target, False)
        elif isinstance(statement, ast.ImportFrom):
            module = _import_from_module(statement)
            for item in statement.names:
                aliases[item.asname or item.name] = (_imported_name(module, item.name), True)
    return aliases


def _import_from_module(node: ast.ImportFrom) -> str:
    return f"{'.' * node.level}{node.module or ''}"


def _imported_name(module: str, name: str) -> str:
    separator = "" if module.endswith(".") else "."
    return f"{module}{separator}{name}"


def _dependency_state(
    node: ast.AST,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return _dependency_scope(node, aliases, local_names, dependencies)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _dependency_import_state(node, aliases, local_names, dependencies)
    if isinstance(node, (ast.AnnAssign, ast.arg)):
        return _dependency_annotation_state(node, aliases, local_names, dependencies)
    referenced = _dependency_reference(node, aliases, local_names, dependencies)
    if referenced is not None:
        return referenced
    return _dependency_children(node, aliases, local_names, dependencies)


def _dependency_scope(
    node: ast.AST,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _dependency_function(node, aliases, local_names, dependencies)
    return dependencies, aliases, local_names


def _dependency_import_state(
    node: ast.Import | ast.ImportFrom,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    if isinstance(node, ast.ImportFrom):
        return _dependency_import(node, aliases, local_names, dependencies, symbol=True)
    return _dependency_import(node, aliases, local_names, dependencies, symbol=False)


def _dependency_annotation_state(
    node: ast.AnnAssign | ast.arg,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    if isinstance(node, ast.arg):
        return _dependency_annotation(node.annotation, aliases, local_names, dependencies)
    dependencies, aliases, local_names = _dependency_annotation(node.annotation, aliases, local_names, dependencies)
    if node.value is None:
        return dependencies, aliases, local_names
    return _dependency_state(node.value, aliases, local_names, dependencies)


def _dependency_reference(
    node: ast.AST,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]] | None:
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load):
            dependencies = _with_dependency(node.id, aliases, local_names, dependencies)
        return dependencies, aliases, local_names
    if isinstance(node, ast.Attribute):
        return _dependency_attribute(node, aliases, local_names, dependencies)
    return None


def _dependency_attribute(
    node: ast.Attribute,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]] | None:
    name = _dotted_name(node)
    if not name:
        return None
    return _with_dependency(name, aliases, local_names, dependencies), aliases, local_names


def _dependency_children(
    node: ast.AST,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    for child in ast.iter_child_nodes(node):
        dependencies, aliases, local_names = _dependency_state(child, aliases, local_names, dependencies)
    return dependencies, aliases, local_names


def _dependency_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    scope_names = {*(argument.arg for argument in _arguments(node.args)), *_direct_bindings(node)}
    inner_names = local_names | scope_names
    inner_aliases = {name: alias for name, alias in aliases.items() if name not in scope_names}
    for decorator in node.decorator_list:
        dependencies, inner_aliases, inner_names = _dependency_state(
            decorator, inner_aliases, inner_names, dependencies
        )
    for argument in _arguments(node.args):
        dependencies, inner_aliases, inner_names = _dependency_state(
            argument, inner_aliases, inner_names, dependencies
        )
    for default in [*node.args.defaults, *node.args.kw_defaults]:
        if default is not None:
            dependencies, inner_aliases, inner_names = _dependency_state(
                default, inner_aliases, inner_names, dependencies
            )
    dependencies, inner_aliases, inner_names = _dependency_annotation(
        node.returns, inner_aliases, inner_names, dependencies
    )
    for statement in node.body:
        dependencies, inner_aliases, inner_names = _dependency_state(statement, inner_aliases, inner_names, dependencies)
    return dependencies, aliases, local_names


def _dependency_import(
    node: ast.Import | ast.ImportFrom,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
    symbol: bool,
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    updated = dict(aliases)
    names = set(local_names)
    module = _import_from_module(node) if isinstance(node, ast.ImportFrom) else ""
    for item in node.names:
        if symbol:
            binding = item.asname or item.name
            updated[binding] = (_imported_name(module, item.name), True)
        else:
            binding = item.asname or item.name.split(".", 1)[0]
            updated[binding] = (item.name if item.asname else binding, False)
        names.discard(binding)
    return dependencies, updated, names


def _dependency_annotation(
    annotation: ast.expr | None,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> tuple[set[str], dict[str, tuple[str, bool]], set[str]]:
    expression = _annotation_expression(annotation)
    if expression is None:
        return dependencies, aliases, local_names
    return _dependency_state(expression, aliases, local_names, dependencies)


def _with_dependency(
    name: str,
    aliases: dict[str, tuple[str, bool]],
    local_names: set[str],
    dependencies: set[str],
) -> set[str]:
    root, *tail = name.split(".")
    if root in local_names or root in dir(builtins) or root == "typing":
        return dependencies
    if root in aliases:
        imported, is_symbol = aliases[root]
        dependency = imported if is_symbol else ".".join([imported, *tail[:1]])
    elif tail:
        dependency = ".".join([root, *tail[:1]])
    elif root[:1].isupper():
        dependency = root
    else:
        return dependencies
    if dependency.startswith(("typing.", "collections.abc.")):
        return dependencies
    return {*dependencies, dependency}


def _annotation_expression(annotation: ast.expr | None) -> ast.expr | None:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return annotation
    try:
        return ast.parse(annotation.value, mode="eval").body
    except (SyntaxError, RecursionError):
        return None


def _global_variable_findings(
    path: Path,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    parents: dict[int, ast.AST],
    bindings: dict[int, set[str]],
) -> list[Finding]:
    rule = _rule(rules, GLOBAL_VARIABLE_RULE_NAME)
    if rule is None:
        return []
    candidates, immutable_candidates, initial_targets = _global_candidates(tree)
    mutated = _mutated_global_names(tree, candidates, initial_targets, parents, bindings)
    selected = set(candidates) if _boolean_property(rule, "report-immutable") else mutated - immutable_candidates
    return [
        Finding(
            path,
            candidates[name].lineno,
            rule.name,
            rule.priority,
            f"Avoid using static mutable state: {name}.",
            context=name,
        )
        for name in sorted(selected, key=lambda item, candidates=candidates: candidates[item].lineno)
    ]


def _global_candidates(tree: ast.Module) -> tuple[dict[str, ast.Name], set[str], set[int]]:
    candidates: dict[str, ast.Name] = {}
    immutable_candidates: set[str] = set()
    initial_targets: set[int] = set()
    for target, annotation in _module_bindings(tree):
        for name in _target_names(target):
            if name.id in candidates:
                continue
            candidates[name.id] = name
            initial_targets.add(id(name))
            if annotation is not None and _is_final_annotation(annotation):
                immutable_candidates.add(name.id)
    return candidates, immutable_candidates, initial_targets


def _mutated_global_names(
    tree: ast.Module,
    candidates: dict[str, ast.Name],
    initial_targets: set[int],
    parents: dict[int, ast.AST],
    bindings: dict[int, set[str]],
) -> set[str]:
    return {
        name
        for node in ast.walk(tree)
        if (name := _mutated_global_name(node, candidates, initial_targets, parents, bindings, MUTATOR_METHOD_NAMES))
    }


def _is_decorator(node: ast.AST, parents: dict[int, ast.AST] | None) -> bool:
    if parents is None:
        return False
    parent = parents.get(id(node))
    return (
        isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and any(decorator is node for decorator in parent.decorator_list)
    )


def _mutator_target(
    node: ast.AST, mutators: frozenset[str], parents: dict[int, ast.AST] | None
) -> ast.expr | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in mutators:
        return node.func.value
    if isinstance(node, ast.Attribute) and node.attr in mutators and _is_decorator(node, parents):
        return node.value
    return None


def _mutated_global_name(
    node: ast.AST,
    candidates: dict[str, ast.Name],
    initial_targets: set[int],
    parents: dict[int, ast.AST],
    bindings: dict[int, set[str]],
    mutators: frozenset[str],
) -> str:
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return node.id if _is_mutated_module_name(node, candidates, initial_targets, parents) else ""
    if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return _unshadowed_candidate_root(node, candidates, parents, bindings)
    target = _mutator_target(node, mutators, parents)
    return _unshadowed_candidate_root(target, candidates, parents, bindings) if target is not None else ""


def _is_mutated_module_name(

    node: ast.Name,
    candidates: dict[str, ast.Name],
    initial_targets: set[int],
    parents: dict[int, ast.AST],
) -> bool:
    return id(node) not in initial_targets and node.id in candidates and _is_module_assignment(node, parents)


def _unshadowed_candidate_root(
    node: ast.AST,
    candidates: dict[str, ast.Name],
    parents: dict[int, ast.AST],
    bindings: dict[int, set[str]],
) -> str:
    root = _root_name(node)
    return root if root in candidates and not _is_function_shadowed(root, node, parents, bindings) else ""


def _module_bindings(node: ast.AST) -> list[tuple[ast.AST, ast.expr | None]]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return []
    if isinstance(node, ast.Assign):
        return [
            *((target, None) for target in node.targets),
            *_module_bindings(node.value),
        ]
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return [(node.target, node.annotation), *_module_bindings(node.value)]
    if isinstance(node, ast.NamedExpr):
        return [(node.target, None), *_module_bindings(node.value)]
    found: list[tuple[ast.AST, ast.expr | None]] = []
    for child in ast.iter_child_nodes(node):
        found.extend(_module_bindings(child))
    return found


def _is_module_assignment(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return _scope_declares_global(node, current, parents)
    return True


def _scope_declares_global(node: ast.AST, scope: ast.AST, parents: dict[int, ast.AST]) -> bool:
    return isinstance(node, ast.Name) and any(
        isinstance(statement, ast.Global)
        and node.id in statement.names
        and _same_scope(statement, scope, parents)
        for statement in ast.walk(scope)
    )


def _same_scope(node: ast.AST, scope: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if current is scope:
            return True
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return False
    return False


def _root_name(node: ast.AST) -> str:
    current = node
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return current.id if isinstance(current, ast.Name) else ""


def _cohesion_findings(
    path: Path, classes: Sequence[ClassInfo], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, LACK_OF_COHESION_RULE_NAME)
    if rule is None:
        return []
    maximum = _integer_property(rule, "maximum")
    findings: list[Finding] = []
    for class_info in classes:
        lcom = _lcom4(class_info)
        if lcom <= maximum:
            continue
        findings.append(
            _class_finding(
                path,
                class_info,
                rule,
                f"The class {class_info.name} has a Lack of Cohesion Of Methods (LCOM4) value of {lcom}. "
                f"Consider to split this class into {lcom} smaller classes.",
            )
        )
    return findings


def _lcom4(class_info: ClassInfo) -> int:
    accessor_fields = _accessor_fields(class_info)
    methods = _method_relationships(class_info, accessor_fields)
    active = _active_methods(methods)
    if not active:
        return 1
    return _relationship_component_count(methods, active)


def _method_relationships(
    class_info: ClassInfo, accessor_fields: dict[str, str]
) -> dict[str, _MethodRelationships]:
    methods: dict[str, _MethodRelationships] = {}
    for method in class_info.methods:
        if _excluded_from_cohesion(method, accessor_fields):
            continue
        receiver = _instance_receiver(method)
        if receiver is None:
            continue
        fields: frozenset[str] = frozenset()
        calls: frozenset[str] = frozenset()
        for statement in method.body:
            fields, calls = _method_relationship(statement, receiver, accessor_fields, fields, calls)
        methods[method.name] = _MethodRelationships(fields, calls)
    return methods


def _excluded_from_cohesion(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    accessor_fields: dict[str, str],
) -> bool:
    return (
        method.name.startswith("__")
        or _has_property_decorator(method)
        or _has_decorator(method, "staticmethod")
        or _has_decorator(method, "classmethod")
        or _is_contract_method(method)
        or _has_decorator(method, "abstractmethod")
        or method.name in accessor_fields
    )


def _active_methods(methods: dict[str, _MethodRelationships]) -> set[str]:
    active = {
        name
        for name, relationships in methods.items()
        if relationships.fields or relationships.calls & methods.keys()
    }
    active.update(
        called
        for relationships in methods.values()
        for called in relationships.calls
        if called in methods
    )
    return active


def _relationship_component_count(
    methods: dict[str, _MethodRelationships], active: set[str]
) -> int:
    connected = {name: name for name in active}
    methods_by_field: defaultdict[str, list[str]] = defaultdict(list)
    for name in active:
        for field in methods[name].fields:
            methods_by_field[field].append(name)
    for names in methods_by_field.values():
        first, *connected_names = names
        for name in connected_names:
            connected = _union_components(connected, first, name)
    names = sorted(active)
    for name in names:
        for called in methods[name].calls & active:
            connected = _union_components(connected, name, called)
    return len({_find_component(connected, name)[1] for name in active})


def _find_component(connected: dict[str, str], name: str) -> tuple[dict[str, str], str]:
    if connected[name] == name:
        return connected, name
    updated, root = _find_component(connected, connected[name])
    if updated[name] == root:
        return updated, root
    return {**updated, name: root}, root


def _union_components(connected: dict[str, str], left: str, right: str) -> dict[str, str]:
    connected, left_root = _find_component(connected, left)
    connected, right_root = _find_component(connected, right)
    if left_root == right_root:
        return connected
    return {**connected, left_root: right_root}


@dataclass(frozen=True)
class _MethodRelationships:
    fields: frozenset[str]
    calls: frozenset[str]


def _method_relationship(
    node: ast.AST,
    receiver: str,
    accessor_fields: dict[str, str],
    fields: frozenset[str],
    calls: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return fields, calls
    if isinstance(node, ast.Call) and _direct_receiver_attribute(node.func, receiver):
        return _receiver_call_relationship(node, receiver, accessor_fields, fields, calls)
    if _direct_receiver_attribute(node, receiver):
        return fields | {accessor_fields.get(node.attr, node.attr)}, calls
    return _method_relationship_children(node, receiver, accessor_fields, fields, calls)


def _receiver_call_relationship(
    node: ast.Call,
    receiver: str,
    accessor_fields: dict[str, str],
    fields: frozenset[str],
    calls: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    attribute = _called_attribute_name(node)
    if attribute in accessor_fields:
        fields = fields | {accessor_fields[attribute]}
    else:
        calls = calls | {attribute}
    for argument in [*node.args, *node.keywords]:
        fields, calls = _method_relationship(
            _call_argument_value(argument),
            receiver,
            accessor_fields,
            fields,
            calls,
        )
    return fields, calls


def _called_attribute_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _call_argument_value(argument: ast.expr | ast.keyword) -> ast.expr:
    if isinstance(argument, ast.keyword):
        return argument.value
    return argument


def _method_relationship_children(
    node: ast.AST,
    receiver: str,
    accessor_fields: dict[str, str],
    fields: frozenset[str],
    calls: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    for child in ast.iter_child_nodes(node):
        fields, calls = _method_relationship(child, receiver, accessor_fields, fields, calls)
    return fields, calls


def _direct_receiver_attribute(node: ast.AST, receiver: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == receiver
    )


def _accessor_fields(class_info: ClassInfo) -> dict[str, str]:
    return {
        method.name: field
        for method in class_info.methods
        if (field := _trivial_accessor_field(method)) is not None
    }


def _trivial_accessor_field(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if len(method.body) != 1:
        return None
    statement = method.body[0]
    target = _accessor_target(statement, method)
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return target.attr
    return None


def _accessor_target(statement: ast.stmt, method: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    if isinstance(statement, ast.Return):
        return statement.value
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        return statement.targets[0] if _is_plain_accessor_value(statement.value, method) else None
    if isinstance(statement, ast.AnnAssign) and statement.value is not None:
        return statement.target if _is_plain_accessor_value(statement.value, method) else None
    return None


def _is_plain_accessor_value(value: ast.expr, method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    receiver = _instance_receiver(method)
    return (
        isinstance(value, ast.Name)
        and value.id != receiver
        and value.id in {argument.arg for argument in _arguments(method.args)}
    )


def _design_scope(
    node: ast.AST, parents: dict[int, ast.AST], contexts: dict[int, str]
) -> tuple[ast.AST, str]:
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return current, contexts.get(id(current), "<lambda>")
    return current, "module"


def _expression_calls(node: ast.expr) -> list[ast.Call]:
    return _expression_call_nodes(node)


def _expression_call_nodes(node: ast.AST) -> list[ast.Call]:
    if isinstance(node, ast.Lambda):
        return []
    found = [node] if isinstance(node, ast.Call) else []
    for child in ast.iter_child_nodes(node):
        found.extend(_expression_call_nodes(child))
    return found


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def _imported_call_aliases(tree: ast.Module) -> dict[int, _ScopeCallImports]:
    return {id(scope): _scope_call_imports(scope) for scope in _binding_scopes(tree)}


def _scope_call_imports(scope: _BindingScope) -> _ScopeCallImports:
    call_modules: dict[str, str] = {}
    rebound: set[str] = set()
    for statement in _scope_statements(scope):
        call_modules.update(_call_import_map(statement))
        rebound.update(_rebound_names(statement))
    return _ScopeCallImports(call_modules=call_modules, rebound=rebound)


def _call_import_map(node: ast.AST) -> dict[str, str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return {}
    if isinstance(node, ast.Import):
        return _call_import_aliases(node)
    if isinstance(node, ast.ImportFrom) and node.module in {"sys", "os", "builtins", "pdb"}:
        return _call_import_from_aliases(node)
    if isinstance(node, (ast.ImportFrom,)):
        return {}
    found: dict[str, str] = {}
    for child in ast.iter_child_nodes(node):
        found.update(_call_import_map(child))
    return found


def _rebound_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.Lambda)):
        return set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    found = _pattern_binding_names(node)
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        found.add(node.id)
    for child in ast.iter_child_nodes(node):
        found.update(_rebound_names(child))
    return found


def _call_import_aliases(statement: ast.Import) -> dict[str, str]:
    return {
        imported.asname or imported.name: imported.name
        for imported in statement.names
        if imported.name in {"sys", "os", "builtins", "pdb"}
    }


def _call_import_from_aliases(statement: ast.ImportFrom) -> dict[str, str]:
    return {
        imported.asname or imported.name: f"{statement.module}.{imported.name}"
        for imported in statement.names
    }


def _binding_scopes(tree: ast.Module) -> list[_BindingScope]:
    scopes: list[_BindingScope] = [tree]
    scopes.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))
    )
    return scopes


def _scope_statements(scope: _BindingScope) -> list[ast.AST]:
    return [scope.body] if isinstance(scope, ast.Lambda) else list(scope.body)


def _scope_bindings(tree: ast.Module) -> dict[int, set[str]]:
    return {id(scope): _direct_bindings(scope) for scope in _binding_scopes(tree)}


def _direct_bindings(scope: _BindingScope) -> set[str]:
    names: set[str] = set()
    if not isinstance(scope, (ast.Module, ast.ClassDef)):
        names.update(argument.arg for argument in _arguments(scope.args))
    for statement in _scope_statements(scope):
        names.update(_scope_binding_names(statement))
    return names


def _scope_binding_names(node: ast.AST) -> set[str]:

    found = _recorded_binding_names(node)
    if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return found
    for child in ast.iter_child_nodes(node):
        found.update(_scope_binding_names(child))
    return found


def _recorded_binding_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id} if isinstance(node.ctx, ast.Store) else set()
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return set(_import_binding_names(node))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    return _pattern_binding_names(node)


def _import_binding_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    return [imported.asname or imported.name.split(".", 1)[0] for imported in node.names]


def _pattern_binding_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler)) and node.name is not None:
        return {node.name}
    if isinstance(node, ast.MatchMapping) and node.rest is not None:
        return {node.rest}
    return set()


def _is_function_shadowed(
    name: str,
    node: ast.AST,
    parents: dict[int, ast.AST],
    bindings: dict[int, set[str]],
) -> bool:
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if name in bindings[id(current)]:
                return True
    return False


def _is_shadowed(
    name: str,
    node: ast.AST,
    tree: ast.Module,
    parents: dict[int, ast.AST],
    bindings: dict[int, set[str]],
) -> bool:
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if name in bindings[id(current)]:
                return True
    return name in bindings[id(tree)]


def _selected_explicitness_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule], rule_names: AbstractSet[str]
) -> list[Finding]:
    if not _has_any_rule(rule_names, EXPLICITNESS_RULE_NAMES):
        return []
    return _explicitness_findings(path, tree, rules)


def _enclosing_scopes(
    node: ast.AST, tree: ast.Module, parents: dict[int, ast.AST]
) -> list[ast.AST]:
    # The scopes that hold the node, from the innermost function out to the module.
    scopes: list[ast.AST] = []
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            scopes.append(current)
    scopes.append(tree)
    return scopes


def _explicitness_findings(path: Path, tree: ast.Module, rules: Sequence[LoadedRule]) -> list[Finding]:
    finders = [
        (rule, finder)
        for rule, finder in (
            (_rule(rules, IMPLICIT_INPUT_RULE_NAME), _implicit_input_findings),
            (_rule(rules, IMPLICIT_OUTPUT_RULE_NAME), _implicit_output_findings),
            (_rule(rules, IMPLICIT_INSTANCE_INPUT_RULE_NAME), _implicit_instance_input_findings),
            (_rule(rules, IMPLICIT_INSTANCE_OUTPUT_RULE_NAME), _implicit_instance_output_findings),
        )
        if rule is not None
    ]
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    name_scopes = _name_scopes(tree)
    findings: list[Finding] = []
    for callable_info in _clean_code_callables(tree):
        enclosing = tuple(_enclosing_scopes(callable_info.node, tree, parents))
        chain = _ScopeChain(
            (callable_info.node, *enclosing),
            name_scopes,
            parents=parents,
            enclosing=enclosing,
        )
        for rule, finder in finders:
            findings.extend(finder(path, callable_info, rule, chain))
    return findings


def _implicit_input_findings(
    path: Path, callable_info: CleanCodeCallable, rule: LoadedRule, chain: _ScopeChain
) -> list[Finding]:
    first_reads: dict[str, ast.AST] = {}
    for node in _read_nodes(callable_info.node):
        node_chain = chain.for_node(node)
        name = _free_variable_read(node, node_chain) or _ambient_read(node, node_chain)
        if name:
            first_reads.setdefault(name, node)
    return _explicitness_report(
        path, callable_info, rule, first_reads, "reads the implicit input", "Pass it as an argument instead."
    )


def _implicit_output_findings(

    path: Path, callable_info: CleanCodeCallable, rule: LoadedRule, chain: _ScopeChain
) -> list[Finding]:
    nodes = _evaluated_nodes(callable_info.node)
    parameters = _caller_owned_parameters(callable_info, nodes, chain.parents)
    first_writes: dict[str, ast.AST] = {}
    for node in nodes:
        node_chain = chain.for_node(node)
        name = _state_write(node, node_chain, parameters) or _ambient_write(node, node_chain)
        if name:
            first_writes.setdefault(name, node)
    return _explicitness_report(
        path, callable_info, rule, first_writes, "writes the implicit output", "Return it instead."
    )



def _implicit_instance_input_findings(
    path: Path, callable_info: CleanCodeCallable, rule: LoadedRule, _chain: _ScopeChain
) -> list[Finding]:
    receiver = _method_receiver(callable_info)
    if receiver is None:
        return []
    nodes = _read_nodes(callable_info.node)
    called = {id(node.func) for node in nodes if isinstance(node, ast.Call)}
    first_reads: dict[str, ast.AST] = {}
    for node in nodes:
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and id(node) not in called:
            name = _receiver_attribute(node, receiver)
            if name:
                first_reads.setdefault(name, node)
    return _explicitness_report(
        path, callable_info, rule, first_reads, "reads the implicit input", "Pass it as an argument instead."
    )


def _implicit_instance_output_findings(
    path: Path, callable_info: CleanCodeCallable, rule: LoadedRule, chain: _ScopeChain
) -> list[Finding]:
    receiver = _method_receiver(callable_info)
    if receiver is None or _clean_code_callable_name(callable_info.node) in CONSTRUCTOR_METHOD_NAMES:
        return []
    first_writes: dict[str, ast.AST] = {}
    for node in _evaluated_nodes(callable_info.node):
        expression = _mutated_expression(node, chain.parents, chain.for_node(node))
        name = _receiver_attribute(expression, receiver) if expression is not None else ""
        if name:
            first_writes.setdefault(name, node)
    return _explicitness_report(
        path, callable_info, rule, first_writes, "writes the implicit output", "Return it instead."
    )


def _receiver_attribute(expression: ast.expr, receiver: str) -> str:

    # This finds the receiver attribute that holds the accessed value, for example self.items in self.items[0].
    current = expression
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        if isinstance(current, ast.Attribute) and isinstance(current.value, ast.Name) and current.value.id == receiver:
            return f"{receiver}.{current.attr}"
        current = current.value
    return ""


def _method_receiver(callable_info: CleanCodeCallable) -> str | None:
    # Python gives the receiver to each method that is not static, for example cls in __new__ and mcls in a metaclass.
    node = callable_info.node
    if callable_info.owner_name is None or isinstance(node, ast.Lambda) or _has_decorator(node, "staticmethod"):
        return None
    positional = [*node.args.posonlyargs, *node.args.args]
    return positional[0].arg if positional else None


def _read_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.AST]:
    # An augmented assignment reads its target before it writes it.
    nodes: list[ast.AST] = []
    for child in _evaluated_nodes(node):
        nodes.append(child)
        if isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name):
            loaded = ast.copy_location(ast.Name(child.target.id, ast.Load()), child.target)
            loaded._parent = child
            nodes.append(loaded)
        elif isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Attribute):
            loaded = ast.copy_location(ast.Attribute(child.target.value, child.target.attr, ast.Load()), child.target)
            loaded._parent = child
            nodes.append(loaded)
    return nodes


def _is_rebound_parameter(
    node: ast.AST, callable_node: ast.AST, parents: dict[int, ast.AST] | None
) -> bool:
    if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Store):
        return False
    return parents is None or _node_class_scope(node, callable_node, parents) is None


def _caller_owned_parameters(
    callable_info: CleanCodeCallable,
    nodes: Sequence[ast.AST],
    parents: dict[int, ast.AST] | None = None,
) -> set[str]:
    # A parameter that the function rebinds is a local copy. The method receiver is instance state.
    # Python makes new *args and **kwargs containers on each call.
    arguments = callable_info.node.args
    rebound = {node.id for node in nodes if _is_rebound_parameter(node, callable_info.node, parents)}
    packed = {argument.arg for argument in (arguments.vararg, arguments.kwarg) if argument is not None}
    parameters = {argument.arg for argument in _arguments(arguments)} - rebound - packed
    parameters.discard(_method_receiver(callable_info) or "")
    return parameters


def _explicitness_report(
    path: Path,
    callable_info: CleanCodeCallable,
    rule: LoadedRule,
    first_nodes: dict[str, ast.AST],
    action: str,
    remedy: str,
) -> list[Finding]:
    context = _clean_code_context(callable_info)
    kind = "function" if callable_info.owner_name is None else "method"
    return [
        Finding(
            path,
            node.lineno,
            rule.name,
            rule.priority,
            f"The {kind} {context}() {action} {name}. {remedy}",
            context=context,
        )
        for name, node in first_nodes.items()
    ]


def _state_write(node: ast.AST, chain: _ScopeChain, parameters: AbstractSet[str]) -> str:
    # A plain name write leaves the function only when the name belongs to an outer scope.
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return node.id if chain.binding(node.id)[1] in chain.enclosing else ""
    changed = _changed_object(node, chain)
    if changed is None:
        return ""
    root = _root_name(changed)
    return _dotted_prefix(changed) if root in parameters or not _is_local_object(root, chain) else ""


def _is_local_object(name: str, chain: _ScopeChain) -> bool:
    # A local object stays in the function. A local import is shared module state.
    _, scope = chain.binding(name)
    return scope not in chain.enclosing and name not in chain.name_scopes[id(scope)].imports


def _changed_object(node: ast.AST, chain: _ScopeChain) -> ast.expr | None:
    # This finds what the node changes: sys.stdout in sys.stdout = value, sys.modules in sys.modules[key] = value.
    expression = _mutated_expression(node, chain.parents, chain)
    if expression is None:
        return None
    if isinstance(expression, ast.Subscript):
        return expression.value
    if _is_builtin_attribute_mutator(node, chain):
        return expression
    if not (isinstance(node, ast.Call) or _is_decorator(node, chain.parents)):
        return expression
    # A call such as os.remove() or dict.clear(self) runs a function. It does not change the module or the builtin.
    if isinstance(expression, ast.Name) and (
        chain.is_module(expression.id) or chain.binding(expression.id)[0] == "unbound"
    ):
        return None
    return expression


def _dotted_prefix(expression: ast.expr) -> str:
    current = expression
    while not _dotted_name(current) and isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return _dotted_name(current)


def _mutated_expression(
    node: ast.AST, parents: dict[int, ast.AST] | None = None, chain: _ScopeChain | None = None
) -> ast.expr | None:
    if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return node
    target = _builtin_attribute_target(node, chain)
    if target is not None:
        return target
    return _mutator_target(node, MUTATOR_METHOD_NAMES, parents)


def _is_builtin_attribute_mutator(node: ast.AST, chain: _ScopeChain | None) -> bool:
    return (
        chain is not None
        and isinstance(node, ast.Call)
        and chain.qualified_name(node.func) in BUILTIN_ATTRIBUTE_MUTATORS
    )


def _literal_attribute_name(argument: ast.expr) -> str:
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and argument.value.isidentifier():
        return argument.value
    return ""


def _builtin_attribute_target(node: ast.AST, chain: _ScopeChain | None) -> ast.expr | None:
    if not _is_builtin_attribute_mutator(node, chain) or len(node.args) < 2:  # type: ignore[union-attr]
        return None
    target, attribute_argument = node.args[0], node.args[1]  # type: ignore[union-attr]
    if isinstance(target, ast.Starred) or isinstance(attribute_argument, ast.Starred):
        return None
    attribute_name = _literal_attribute_name(attribute_argument)
    if not attribute_name:
        return target
    is_del = chain is not None and chain.qualified_name(node.func) == "builtins.delattr"  # type: ignore[union-attr]
    context = ast.Del() if is_del else ast.Store()
    return ast.Attribute(value=target, attr=attribute_name, ctx=context)


def _free_variable_read(node: ast.AST, chain: _ScopeChain) -> str:

    if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
        return ""
    kind, scope = chain.binding(node.id)
    return node.id if kind == "variable" and scope in chain.enclosing else ""


def _ambient_read(node: ast.AST, chain: _ScopeChain) -> str:
    if isinstance(node, ast.Call) and chain.qualified_name(node.func) in OPEN_CALL_NAMES:
        return "open" if _open_mode_reads(_open_mode(node)) else ""
    return _ambient_name(node, chain, IMPLICIT_INPUT_NAMES)


def _ambient_write(node: ast.AST, chain: _ScopeChain) -> str:
    if isinstance(node, ast.Call) and chain.qualified_name(node.func) in OPEN_CALL_NAMES:
        return "open" if _open_mode_writes(_open_mode(node)) else ""
    return _ambient_name(node, chain, IMPLICIT_OUTPUT_NAMES)


def _ambient_name(node: ast.AST, chain: _ScopeChain, names: AbstractSet[str]) -> str:
    if not isinstance(node, (ast.Name, ast.Attribute)) or not isinstance(node.ctx, ast.Load):
        return ""
    qualified = chain.qualified_name(node)
    return qualified.removeprefix("builtins.") if qualified in names else ""


def _open_mode(call: ast.Call) -> str | None:
    # A missing mode is the read mode. A mode that is not a literal is unknown.
    mode = call.args[1] if len(call.args) > 1 else next(
        (keyword.value for keyword in call.keywords if keyword.arg == "mode"), ast.Constant("r")
    )
    return mode.value if isinstance(mode, ast.Constant) and isinstance(mode.value, str) else None


def _open_mode_reads(mode: str | None) -> bool:
    return mode is None or "+" in mode or not set(mode) & set("wax")


def _open_mode_writes(mode: str | None) -> bool:
    return mode is not None and bool(set(mode) & set("wax+"))


@dataclass(frozen=True)
class _ScopeChain:
    """The scopes that a callable reads free names from, from the callable out to the module."""

    scopes: tuple[ast.AST, ...]
    name_scopes: dict[int, _NameScope]
    parents: dict[int, ast.AST] | None = None
    enclosing: tuple[ast.AST, ...] = ()
    callable_node: ast.AST | None = None

    def __post_init__(self) -> None:
        if not self.enclosing and len(self.scopes) > 1:
            object.__setattr__(self, "enclosing", self.scopes[1:])
        if self.callable_node is None and self.scopes:
            object.__setattr__(self, "callable_node", self.scopes[0])

    def for_node(self, node: ast.AST) -> _ScopeChain:
        if self.parents is None or self.callable_node is None:
            return self
        class_scope = _node_class_scope(node, self.callable_node, self.parents)
        if class_scope is None or class_scope is self.scopes[0]:
            return self
        return _ScopeChain(
            (class_scope, *self.scopes),
            self.name_scopes,
            self.parents,
            enclosing=self.enclosing,
            callable_node=self.callable_node,
        )

    def binding(self, name: str) -> tuple[str, ast.AST]:
        # This follows the order in which Python resolves a free name. Class scopes are not in the chain.
        for scope in self.scopes[:-1]:
            name_scope = self.name_scopes[id(scope)]
            if name in name_scope.global_names:
                break
            if name in name_scope.nonlocal_names:
                continue
            kind = _binding_kind(name, name_scope)
            if kind:
                return kind, scope
        module = self.scopes[-1]
        return _binding_kind(name, self.name_scopes[id(module)]) or "unbound", module

    def qualified_name(self, node: ast.expr) -> str:
        dotted = _dotted_name(node)
        if not dotted:
            return ""
        root, separator, member = dotted.partition(".")
        kind, scope = self.binding(root)
        if kind == "unbound":
            base = f"builtins.{root}"
        elif kind == "definition":
            base = self.name_scopes[id(scope)].imports.get(root, "")
        else:
            base = ""
        return f"{base}{separator}{member}" if base else ""

    def is_module(self, name: str) -> bool:
        kind, scope = self.binding(name)
        return kind == "definition" and name in self.name_scopes[id(scope)].modules


def _node_class_scope(
    node: ast.AST, callable_node: ast.AST, parents: dict[int, ast.AST]
) -> ast.ClassDef | None:
    current = getattr(node, "_parent", node)
    prev = current
    while id(current) in parents:
        prev = current
        current = parents[id(current)]
        if current is callable_node:
            return None
        if isinstance(current, ast.ClassDef) and prev in current.body:
            return current
    return None


@dataclass(frozen=True)
class _NameScope:
    """The names that one scope binds, split into variables and fixed definitions."""

    variables: frozenset[str]
    definitions: frozenset[str]
    global_names: frozenset[str]
    nonlocal_names: frozenset[str]
    imports: dict[str, str]
    modules: frozenset[str]


def _name_scopes(tree: ast.Module) -> dict[int, _NameScope]:
    declared_globals = {name for node in ast.walk(tree) if isinstance(node, ast.Global) for name in node.names}
    name_scopes: dict[int, _NameScope] = {}
    for scope in _binding_scopes(tree):
        extra = declared_globals if isinstance(scope, ast.Module) else (
            set() if isinstance(scope, ast.ClassDef) else {argument.arg for argument in _arguments(scope.args)}
        )
        name_scopes[id(scope)] = _scope_name_record(_scope_statements(scope), extra)
    return name_scopes


@dataclass(frozen=True)
class _NameParts:
    variables: frozenset[str] = frozenset()
    definitions: frozenset[str] = frozenset()
    constants: frozenset[str] = frozenset()
    global_names: frozenset[str] = frozenset()
    nonlocal_names: frozenset[str] = frozenset()
    imports: tuple[tuple[str, str], ...] = ()
    modules: frozenset[str] = frozenset()


def _scope_name_record(statements: Sequence[ast.AST], extra_variables: set[str]) -> _NameScope:
    parts = _NameParts(variables=frozenset(extra_variables))
    for statement in statements:
        parts = _name_parts(parts, statement)
    constants = {name for name in parts.variables if re.fullmatch(r"_*[A-Z][A-Z0-9_]*", name)} | set(parts.constants)
    return _NameScope(
        variables=frozenset(set(parts.variables) - constants),
        definitions=frozenset(set(parts.definitions) | constants),
        global_names=parts.global_names,
        nonlocal_names=parts.nonlocal_names,
        imports=dict(parts.imports),
        modules=parts.modules,
    )


def _name_parts(parts: _NameParts, node: ast.AST) -> _NameParts:
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return _declared_name_parts(parts, node)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _imported_name_parts(parts, node)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return replace(parts, definitions=parts.definitions | frozenset(_recorded_binding_names(node)))
    return _nested_name_parts(parts, node)


def _declared_name_parts(parts: _NameParts, node: ast.Global | ast.Nonlocal) -> _NameParts:
    if isinstance(node, ast.Global):
        return replace(parts, global_names=parts.global_names | frozenset(node.names))
    return replace(parts, nonlocal_names=parts.nonlocal_names | frozenset(node.names))


def _imported_name_parts(parts: _NameParts, node: ast.Import | ast.ImportFrom) -> _NameParts:
    modules = parts.modules
    if isinstance(node, ast.Import):
        modules = modules | frozenset(_import_binding_names(node))
    return replace(
        parts,
        definitions=parts.definitions | frozenset(_import_binding_names(node)),
        imports=(*parts.imports, *tuple(_import_qualified_names(node).items())),
        modules=modules,
    )


def _nested_name_parts(parts: _NameParts, node: ast.AST) -> _NameParts:
    parts = replace(parts, variables=parts.variables | frozenset(_recorded_binding_names(node)))
    if isinstance(node, ast.AnnAssign) and _is_constant_annotation(node.annotation):
        parts = _constant_annotation_parts(parts, node)
    if isinstance(node, ast.Lambda):
        return parts
    for child in ast.iter_child_nodes(node):
        parts = _name_parts(parts, child)
    return parts


def _constant_annotation_parts(parts: _NameParts, node: ast.AnnAssign) -> _NameParts:
    names = frozenset(name.id for name in _target_names(node.target))
    return replace(parts, constants=parts.constants | names)


def _import_qualified_names(node: ast.Import | ast.ImportFrom) -> dict[str, str]:
    if isinstance(node, ast.ImportFrom):
        module = _import_from_module(node)
        return {item.asname or item.name: _imported_name(module, item.name) for item in node.names}
    names: dict[str, str] = {}
    for item in node.names:
        package = item.name.split(".", 1)[0]
        names[item.asname or package] = item.name if item.asname else package
    return names


def _is_constant_annotation(annotation: ast.expr) -> bool:
    return _is_final_annotation(annotation) or _is_type_alias_annotation(annotation)


def _binding_kind(name: str, name_scope: _NameScope) -> str:
    # A name that is both imported and assigned, for example a fallback after an ImportError, is a definition.
    if name in name_scope.definitions:
        return "definition"
    if name in name_scope.variables:
        return "variable"
    return ""


def _clean_code_findings(
    path: Path,
    source: str,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    clean_code_callables: Sequence[CleanCodeCallable],
) -> list[Finding]:
    return [
        *_boolean_argument_flag_findings(path, clean_code_callables, rules),
        *_else_expression_findings(path, clean_code_callables, rules),
        *_static_access_findings(path, clean_code_callables, rules),
        *_if_statement_assignment_findings(path, source, tree, rules),
        *_duplicated_array_key_findings(path, tree, rules),
    ]


def _boolean_argument_flag_findings(
    path: Path, callables: Sequence[CleanCodeCallable], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, BOOLEAN_ARGUMENT_FLAG_RULE_NAME)
    if rule is None:
        return []
    exceptions = _exception_names(rule)
    ignored = _ignore_pattern(rule)
    findings: list[Finding] = []
    for callable_info in callables:
        if _ignore_boolean_flag_callable(callable_info, exceptions, ignored):
            continue
        node = callable_info.node
        for parameter in _boolean_parameters(node.args):
            if parameter.arg in {"self", "cls"} or parameter.arg.startswith("_"):
                continue
            context = _clean_code_context(callable_info)
            findings.append(
                Finding(
                    path,
                    parameter.lineno,
                    rule.name,
                    rule.priority,
                    f"The method {context} has a boolean flag argument {parameter.arg}, which is a certain sign "
                    "of a Single Responsibility Principle violation.",
                    context=context,
                )
            )
    return findings


def _ignore_boolean_flag_callable(
    callable_info: CleanCodeCallable, exceptions: set[str], ignored: re.Pattern[str]
) -> bool:
    node = callable_info.node
    return isinstance(node, ast.Lambda) or (
        node.name.startswith("_")
        or callable_info.owner_name in exceptions
        or bool(ignored.pattern and ignored.search(node.name))
    )


def _boolean_parameters(arguments: ast.arguments) -> list[ast.arg]:
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults = {
        id(parameter): default
        for parameter, default in zip(positional[-len(arguments.defaults) :], arguments.defaults)
    } if arguments.defaults else {}
    defaults.update(
        {
            id(parameter): default
            for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults)
            if default is not None
        }
    )
    return [
        parameter
        for parameter in _arguments(arguments)
        if _is_boolean_flag_annotation(parameter.annotation)
        or _is_boolean_literal(defaults.get(id(parameter)))
    ]


def _is_boolean_flag_annotation(node: ast.expr | None) -> bool:
    if _is_boolean_annotation(node):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_boolean_flag_annotation(node.left) or _is_boolean_flag_annotation(node.right)
    if isinstance(node, ast.Subscript) and _is_boolean_union_name(node.value):
        values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        return any(_is_boolean_flag_annotation(value) for value in values)
    return False


def _is_boolean_union_name(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in {"Optional", "Union"}
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
        and node.attr in {"Optional", "Union"}
    )


def _is_boolean_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _else_expression_findings(
    path: Path, callables: Sequence[CleanCodeCallable], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, ELSE_EXPRESSION_RULE_NAME)
    if rule is None:
        return []
    findings: list[Finding] = []
    for callable_info in callables:
        context = _clean_code_context(callable_info)
        nodes = _executable_nodes(callable_info.node)
        elif_nodes = _elif_nodes(nodes)
        for node in nodes:
            else_clause = _dead_else_clause(elif_nodes, node)
            if else_clause is None:
                continue
            findings.append(
                Finding(
                    path,
                    else_clause.lineno,
                    rule.name,
                    rule.priority,
                    f"The method {context} uses an else that follows a branch which always returns, raises, "
                    "continues, or breaks. That else clause is dead or misleading and you can simplify the "
                    "code by removing it.",
                    context=context,
                )
            )
    return findings


def _elif_nodes(nodes: Sequence[ast.AST]) -> set[int]:
    return {
        id(node.orelse[0])
        for node in nodes
        if isinstance(node, ast.If) and _is_single_if(node.orelse)
    }


def _dead_else_clause(elif_nodes: set[int], node: ast.AST) -> ast.stmt | None:
    if isinstance(node, ast.If):
        return None if id(node) in elif_nodes else _dead_else_after_if_chain(node)
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.TryStar)):
        return node.orelse[0] if node.orelse and _block_always_exits(node.body) else None
    return None


def _is_single_if(statements: Sequence[ast.stmt]) -> bool:
    return len(statements) == 1 and isinstance(statements[0], ast.If)


def _dead_else_after_if_chain(node: ast.If) -> ast.stmt | None:
    branches, tail = _if_chain(node)
    if not tail:
        return None
    if all(_block_always_exits(branch) for branch in branches):
        return tail[0]
    return None


def _if_chain(node: ast.If) -> tuple[list[list[ast.stmt]], list[ast.stmt]]:
    branches = [node.body]
    tail = node.orelse
    while _is_single_if(tail):
        inner = tail[0]
        branches.append(inner.body)
        tail = inner.orelse
    return branches, tail


def _block_always_exits(body: Sequence[ast.stmt]) -> bool:
    return any(_statement_always_exits(statement) for statement in body)


def _statement_always_exits(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
        return True
    if isinstance(statement, ast.If):
        return _if_statement_always_exits(statement)
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return _block_always_exits(statement.body)
    if isinstance(statement, (ast.Try, ast.TryStar)):
        return _try_statement_always_exits(statement)
    return False


def _if_statement_always_exits(node: ast.If) -> bool:
    branches, tail = _if_chain(node)
    if not tail:
        return False
    return all(_block_always_exits(branch) for branch in branches) and _block_always_exits(tail)


def _try_statement_always_exits(node: ast.Try | ast.TryStar) -> bool:
    if not node.handlers:
        return False
    if node.finalbody and _block_always_exits(node.finalbody):
        return True
    if not _block_always_exits(node.body) or (node.orelse and not _block_always_exits(node.orelse)):
        return False
    return all(_block_always_exits(handler.body) for handler in node.handlers)


def _static_access_findings(
    path: Path, callables: Sequence[CleanCodeCallable], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, STATIC_ACCESS_RULE_NAME)
    if rule is None:
        return []
    exceptions = _exception_names(rule)
    ignored = _ignore_pattern(rule)
    findings: list[Finding] = []
    for callable_info in callables:
        name = _clean_code_callable_name(callable_info.node)
        if ignored.pattern and ignored.search(name):
            continue
        for node, receiver in _static_accesses(callable_info, exceptions):
            context = _clean_code_context(callable_info)
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid using static access to class '{receiver.id}' in method '{name}'.",
                    context=context,
                )
            )
    return findings


def _static_accesses(
    callable_info: CleanCodeCallable, exceptions: set[str]
) -> list[tuple[ast.Call, ast.Name]]:
    accesses: list[tuple[ast.Call, ast.Name]] = []
    for node in _executable_nodes(callable_info.node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = node.func.value
        if not isinstance(receiver, ast.Name) or not receiver.id[:1].isupper():
            continue
        if receiver.id != callable_info.owner_name and receiver.id not in exceptions:
            accesses.append((node, receiver))
    return accesses


def _if_statement_assignment_findings(
    path: Path, source: str, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, IF_STATEMENT_ASSIGNMENT_RULE_NAME)
    if rule is None:
        return []
    lines = source.splitlines()
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.If, ast.While)):
            continue
        findings.extend(
            Finding(
                path,
                assignment.lineno,
                rule.name,
                rule.priority,
                "Avoid assigning values to variables in if clauses and the like "
                f"(line '{assignment.lineno}', column '{_character_column(lines, assignment)}').",
            )
            for assignment in _named_expressions(node.test)
        )
    return findings


def _character_column(lines: Sequence[str], node: ast.AST) -> int:
    line = lines[node.lineno - 1]
    prefix = line.encode("utf-8")[: node.col_offset].decode("utf-8")
    return len(prefix) + 1


def _named_expressions(node: ast.AST) -> list[ast.NamedExpr]:
    if isinstance(node, ast.Lambda):
        return []
    found = [node] if isinstance(node, ast.NamedExpr) else []
    for child in ast.iter_child_nodes(node):
        found.extend(_named_expressions(child))
    return found


def _duplicated_array_key_findings(
    path: Path, tree: ast.Module, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, DUPLICATED_ARRAY_KEY_RULE_NAME)
    if rule is None:
        return []
    findings: list[Finding] = []
    for dictionary in ast.walk(tree):
        if not isinstance(dictionary, ast.Dict):
            continue
        keys: dict[object, ast.expr] = {}
        for key in dictionary.keys:
            known, value = _static_dictionary_key(key)
            if not known or key is None:
                continue
            if value in keys:
                display = ast.unparse(key)
                findings.append(
                    Finding(
                        path,
                        key.lineno,
                        rule.name,
                        rule.priority,
                        f"Duplicated array key {display}, first declared at line {keys[value].lineno}.",
                        context=display,
                    )
                )
            else:
                keys[value] = key
    return findings


def _static_dictionary_key(node: ast.expr | None) -> tuple[bool, object]:
    if _is_static_constant(node):
        return True, node.value
    if isinstance(node, ast.UnaryOp):
        return _static_unary_key(node)
    if isinstance(node, ast.Tuple):
        return _static_tuple_key(node)
    return False, None


def _is_static_constant(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) in {
        str,
        bytes,
        int,
        float,
        complex,
        bool,
        type(None),
        type(Ellipsis),
    }


def _static_unary_key(node: ast.UnaryOp) -> tuple[bool, object]:
    if not isinstance(node.op, (ast.UAdd, ast.USub)):
        return False, None
    known, value = _static_dictionary_key(node.operand)
    if known and type(value) in {int, float, complex, bool}:
        return True, +value if isinstance(node.op, ast.UAdd) else -value
    return False, None


def _static_tuple_key(node: ast.Tuple) -> tuple[bool, object]:
    values = [_static_dictionary_key(element) for element in node.elts]
    return (
        (True, tuple(value for _, value in values))
        if all(known for known, _ in values)
        else (False, None)
    )


def _clean_code_callables(tree: ast.Module) -> list[CleanCodeCallable]:
    owners = _callable_owners(tree, None)
    return sorted(
        [
            CleanCodeCallable(node, owners.get(id(node)))
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        ],
        key=lambda callable_info: (callable_info.node.lineno, callable_info.node.col_offset),
    )


def _callable_owners(node: ast.AST, owner_name: str | None) -> dict[int, str]:
    if isinstance(node, ast.ClassDef):
        owners: dict[int, str] = {}
        for statement in node.body:
            owners.update(_callable_owners(statement, node.name))
        return owners
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        owners = {id(node): owner_name} if owner_name is not None else {}
        for statement in node.body:
            owners.update(_callable_owners(statement, None))
        return owners
    if isinstance(node, ast.Lambda):
        return {}
    owners = {}
    for child in ast.iter_child_nodes(node):
        owners.update(_callable_owners(child, owner_name))
    return owners


def _clean_code_callable_name(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> str:
    return "<lambda>" if isinstance(node, ast.Lambda) else node.name


def _clean_code_context(callable_info: CleanCodeCallable) -> str:
    name = _clean_code_callable_name(callable_info.node)
    return f"{callable_info.owner_name}.{name}" if callable_info.owner_name else name


def _executable_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.AST]:
    roots = [node.body] if isinstance(node, ast.Lambda) else node.body
    found: list[ast.AST] = []
    for root in roots:
        found.extend(_executable_node_list(root))
    return found


def _executable_node_list(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return []
    found = [node]
    for child in ast.iter_child_nodes(node):
        found.extend(_executable_node_list(child))
    return found


def _evaluated_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.AST]:
    roots = [node.body] if isinstance(node, ast.Lambda) else node.body
    found: list[ast.AST] = []
    for root in roots:
        found.extend(_evaluated_node_list(root))
    return found


def _evaluated_node_list(node: ast.AST) -> list[ast.AST]:
    # Python evaluates decorators, defaults, class bases, and nested class bodies here.
    # It does not evaluate a local annotation or a nested function body.
    if isinstance(node, ast.AnnAssign):
        return [node, *_evaluated_present([node.target, node.value])]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _evaluated_present([*node.decorator_list, *node.args.defaults, *node.args.kw_defaults])
    if isinstance(node, ast.Lambda):
        return _evaluated_present([*node.args.defaults, *node.args.kw_defaults])
    if isinstance(node, ast.ClassDef):
        return _evaluated_present([*node.decorator_list, *node.bases, *node.keywords, *node.body])
    found = [node]
    for child in ast.iter_child_nodes(node):
        found.extend(_evaluated_node_list(child))
    return found


def _evaluated_present(nodes: Sequence[ast.AST | None]) -> list[ast.AST]:
    found: list[ast.AST] = []
    for node in nodes:
        if node is not None:
            found.extend(_evaluated_node_list(node))
    return found


def _exception_names(rule: LoadedRule) -> set[str]:
    return {name.strip() for name in rule.properties.get("exceptions", "").split(",") if name.strip()}


def _unused_local_variable_findings(
    path: Path,
    rules: Sequence[LoadedRule],
    function_scopes: Sequence[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, symtable.SymbolTable, frozenset[str]]
    ],
    comprehension_scopes: Sequence[
        tuple[
            ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
            symtable.SymbolTable | None,
        ]
    ],
    protocol_method_ids: set[int],
) -> list[Finding]:
    rule = _rule(rules, UNUSED_LOCAL_VARIABLE_RULE_NAME)
    if rule is None:
        return []
    findings = _unused_function_local_findings(path, function_scopes, rule, protocol_method_ids)
    findings.extend(_unused_comprehension_local_findings(path, comprehension_scopes, rule))
    return findings


def _lookup_symbol(table: symtable.SymbolTable, name: str) -> symtable.Symbol | None:
    try:
        return table.lookup(name)
    except KeyError:
        return None


def _unused_function_local_findings(
    path: Path,
    function_scopes: Sequence[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, symtable.SymbolTable, frozenset[str]]
    ],
    rule: LoadedRule,
    protocol_method_ids: set[int],
) -> list[Finding]:
    findings: list[Finding] = []
    for node, table, used_names in function_scopes:
        if _is_conservative_callable(node, id(node) in protocol_method_ids):
            continue
        if isinstance(node, ast.Lambda):
            targets = _function_local_targets(node.body)
        else:
            targets = [target for statement in node.body for target in _function_local_targets(statement)]
        reported: set[str] = set()
        for target in targets:
            symbol = _lookup_symbol(table, target.id)
            if symbol is None or _ignore_function_local(target.id, symbol, used_names, reported):
                continue
            reported.add(target.id)
            findings.append(
                Finding(
                    path,
                    target.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid unused local variables such as '{target.id}'.",
                    context=target.id,
                )
            )
    return findings


def _ignore_function_local(
    name: str,
    symbol: symtable.Symbol,
    used_names: frozenset[str],
    reported: set[str],
) -> bool:
    return (
        name.startswith("_")
        or name in used_names
        or not symbol.is_local()
        or symbol.is_parameter()
        or name in reported
    )


def _unused_comprehension_local_findings(
    path: Path,
    comprehension_scopes: Sequence[
        tuple[
            ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
            symtable.SymbolTable | None,
        ]
    ],
    rule: LoadedRule,
) -> list[Finding]:
    findings: list[Finding] = []
    for node, table in comprehension_scopes:
        findings.extend(_scope_comprehension_findings(path, node, table, rule))
    return findings


def _scope_comprehension_findings(
    path: Path,
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    table: symtable.SymbolTable | None,
    rule: LoadedRule,
) -> list[Finding]:
    findings: list[Finding] = []
    reported: set[str] = set()
    used_names = _comprehension_used_names(node) if table is None else frozenset()
    for generator in node.generators:
        for target in _target_names(generator.target):
            symbol = _lookup_symbol(table, target.id) if table is not None else None
            if symbol is None and table is not None and not used_names:
                used_names = _comprehension_used_names(node)
            if _ignore_comprehension_local(target.id, symbol, used_names, reported):
                continue
            reported.add(target.id)
            findings.append(
                Finding(
                    path,
                    target.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid unused local variables such as '{target.id}'.",
                    context=target.id,
                )
            )
    return findings


def _ignore_comprehension_local(
    name: str,
    symbol: symtable.Symbol | None,
    used_names: frozenset[str],
    reported: set[str],
) -> bool:
    referenced = symbol.is_referenced() if symbol is not None else name in used_names
    return name.startswith("_") or referenced or (
        symbol is not None and not symbol.is_local()
    ) or name in reported


def _unused_formal_parameter_findings(
    path: Path,
    tree: ast.Module,
    rules: Sequence[LoadedRule],
    function_scopes: Sequence[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, symtable.SymbolTable, frozenset[str]]
    ],
    protocol_method_ids: set[int],
) -> list[Finding]:
    rule = _rule(rules, UNUSED_FORMAL_PARAMETER_RULE_NAME)
    if rule is None:
        return []
    findings: list[Finding] = []
    visitor_method_ids = _ast_visitor_method_ids(tree)
    for node, table, used_names in function_scopes:
        if _is_conservative_callable(node, id(node) in protocol_method_ids):
            continue
        for parameter in _unused_parameters(node, table, used_names, visitor_method_ids):
            findings.append(
                Finding(
                    path,
                    parameter.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid unused parameters such as '{parameter.arg}'.",
                    context=parameter.arg,
                )
            )
    return findings


def _unused_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    table: symtable.SymbolTable,
    used_names: frozenset[str],
    visitor_method_ids: set[int],
) -> list[ast.arg]:
    parameters = _arguments(node.args)
    visitor_parameter = _visitor_parameter(node, parameters, visitor_method_ids)
    return [
        parameter
        for parameter in parameters
        if parameter.arg not in {"self", "cls"}
        and not parameter.arg.startswith("_")
        and parameter is not visitor_parameter
        and parameter.arg not in used_names
        and (symbol := _lookup_symbol(table, parameter.arg)) is not None
        and symbol.is_parameter()
    ]


def _is_conservative_callable(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    is_protocol_method: bool,
) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
        is_protocol_method
        or bool(node.decorator_list)
        or _is_contract_method(node)
    )


def _visitor_parameter(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    parameters: list[ast.arg],
    visitor_method_ids: set[int],
) -> ast.arg | None:
    if id(node) not in visitor_method_ids:
        return None
    return next((parameter for parameter in parameters if parameter.arg not in {"self", "cls"}), None)


def _protocol_method_ids(tree: ast.Module) -> set[int]:
    protocol_names = _protocol_base_names(tree)
    return {
        id(method)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_protocol(node, protocol_names)
        for method in _class_member_statements(node.body)
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _function_scopes(
    source: str, tree: ast.Module
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, symtable.SymbolTable, frozenset[str]]]:
    tables = _function_tables(symtable.symtable(source, "<source>", "exec"))
    scopes = []
    usage_cache: dict[int, ScopeUsage] = {}
    callable_nodes = _collect_callable_nodes(tree)
    for node in callable_nodes:
        name = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "lambda"
        candidates = tables[(name, node.lineno)]
        if not candidates:
            continue
        table, remaining = _take_function_table(node, candidates)
        tables[(name, node.lineno)] = remaining
        if table is None:
            continue
        usage, usage_cache = _scope_usage(table, usage_cache)
        used_names = (
            usage.used_names
            | _comprehension_referenced_names(node)
            | _augmented_assignment_names(node)
            | _annotation_referenced_names(node)
        )
        scopes.append((node, table, used_names))
    return scopes


def _collect_callable_nodes(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda]:
    return _callable_nodes(tree)


def _callable_nodes(node: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda]:
    found: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        found.append(node)
    for child in ast.iter_child_nodes(node):
        found.extend(_callable_nodes(child))
    return found


def _take_function_table(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    candidates: list[symtable.SymbolTable],
) -> tuple[symtable.SymbolTable | None, list[symtable.SymbolTable]]:
    if not candidates:
        return None, candidates
    node_params = tuple(arg.arg for arg in _arguments(node.args))
    for index, candidate in enumerate(candidates):
        if tuple(candidate.get_parameters()) == node_params:
            return candidate, [*candidates[:index], *candidates[index + 1 :]]
    return candidates[0], candidates[1:]


def _comprehension_referenced_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> frozenset[str]:
    # symtable can omit enclosing-scope references used only by comprehensions.
    # Record those loads so they count as uses in the current callable.
    referenced: set[str] = set()
    for descendant in _executable_nodes(node):
        if isinstance(descendant, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            referenced.update(_loaded_non_target_names(descendant))
    return frozenset(referenced)


def _augmented_assignment_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> frozenset[str]:
    # symtable does not mark a plain Name target of an augmented assignment as
    # referenced, yet `name += 1` reads the previous value before storing.
    return frozenset(
        descendant.target.id
        for descendant in _executable_nodes(node)
        if isinstance(descendant, ast.AugAssign) and isinstance(descendant.target, ast.Name)
    )


def _annotation_referenced_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> frozenset[str]:
    roots = [node.body] if isinstance(node, ast.Lambda) else node.body
    names: set[str] = set()
    for root in roots:
        names.update(_annotation_reference_names(root))
    return frozenset(names)


def _annotation_reference_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.AnnAssign):
        return _annotation_name_loads(node.annotation)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _callable_annotation_name_loads(node)
    if isinstance(node, ast.Lambda):
        return set()
    if isinstance(node, ast.ClassDef):
        names: set[str] = set()
        for statement in node.body:
            names.update(_annotation_reference_names(statement))
        return names
    names = set()
    for child in ast.iter_child_nodes(node):
        names.update(_annotation_reference_names(child))
    return names


def _callable_annotation_name_loads(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    annotations = [argument.annotation for argument in _arguments(node.args)]
    if node.returns is not None:
        annotations.append(node.returns)
    return {
        name
        for annotation in annotations
        if annotation is not None
        for name in _annotation_name_loads(annotation)
    }


def _annotation_name_loads(node: ast.AST) -> set[str]:
    return {
        descendant.id
        for descendant in ast.walk(node)
        if isinstance(descendant, ast.Name) and isinstance(descendant.ctx, ast.Load)
    }


def _loaded_non_target_names(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
) -> set[str]:
    own_targets = {
        target.id for generator in node.generators for target in _target_names(generator.target)
    }
    pending = list(ast.iter_child_nodes(node))
    loaded_names: set[str] = set()
    while pending:
        descendant = pending.pop()
        if isinstance(descendant, ast.Name) and isinstance(descendant.ctx, ast.Load):
            if descendant.id not in own_targets:
                loaded_names.add(descendant.id)
            continue
        if isinstance(
            descendant,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Lambda,
                ast.ClassDef,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            continue
        pending.extend(ast.iter_child_nodes(descendant))
    return loaded_names


def _comprehension_scopes(
    source: str, tree: ast.Module
) -> list[
    tuple[
        ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        symtable.SymbolTable | None,
    ]
]:
    tables = _comprehension_tables(symtable.symtable(source, "<source>", "exec"))
    names = {
        ast.ListComp: "listcomp",
        ast.SetComp: "setcomp",
        ast.DictComp: "dictcomp",
        ast.GeneratorExp: "genexpr",
    }
    scopes = []
    comprehension_nodes = _collect_comprehension_nodes(tree)
    for node in comprehension_nodes:
        kind = names[type(node)]
        candidates = tables[(kind, node.lineno)]
        table, remaining = _take_comprehension_table(node, candidates)
        tables[(kind, node.lineno)] = remaining
        scopes.append((node, table))
    return scopes


def _collect_comprehension_nodes(
    tree: ast.Module,
) -> list[ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp]:
    return _comprehension_nodes(tree)


def _comprehension_nodes(
    node: ast.AST,
) -> list[ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp]:
    found: list[ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp] = []
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        found.append(node)
    for child in ast.iter_child_nodes(node):
        found.extend(_comprehension_nodes(child))
    return found


def _take_comprehension_table(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    candidates: list[symtable.SymbolTable],
) -> tuple[symtable.SymbolTable | None, list[symtable.SymbolTable]]:
    if not candidates:
        return None, candidates
    target_names = {name.id for generator in node.generators for name in _target_names(generator.target)}
    for index, candidate in enumerate(candidates):
        if target_names.issubset(set(candidate.get_identifiers())):
            return candidate, [*candidates[:index], *candidates[index + 1 :]]
    return candidates[0], candidates[1:]


def _comprehension_used_names(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
) -> frozenset[str]:
    used: set[str] = set()
    for index, generator in enumerate(node.generators):
        for target in _target_names(generator.target):
            if _comprehension_target_is_used(node, index, target.id):
                used.add(target.id)
    return frozenset(used)


def _comprehension_target_is_used(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    generator_index: int,
    target_name: str,
) -> bool:
    used, shadowed = _later_comprehension_uses(node, generator_index, target_name)
    if shadowed:
        return used
    element = node.key if isinstance(node, ast.DictComp) else node.elt
    used = used or _name_is_loaded(element, target_name)
    if isinstance(node, ast.DictComp):
        used = used or _name_is_loaded(node.value, target_name)
    return used


def _later_comprehension_uses(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    generator_index: int,
    target_name: str,
) -> tuple[bool, bool]:
    used = _clause_conditions_load_name(node.generators[generator_index], target_name)
    for later_generator in node.generators[generator_index + 1 :]:
        used, shadowed = _following_clause_use(later_generator, target_name, used)
        if shadowed:
            return used, True
    return used, False


def _clause_conditions_load_name(generator: ast.comprehension, target_name: str) -> bool:
    used = False
    for condition in generator.ifs:
        used = used or _name_is_loaded(condition, target_name)
    return used


def _following_clause_use(
    generator: ast.comprehension,
    target_name: str,
    used: bool,
) -> tuple[bool, bool]:
    used = used or _name_is_loaded(generator.iter, target_name)
    if _generator_binds_name(generator, target_name):
        return used, True
    return _clause_conditions_load_name(generator, target_name) or used, False


def _name_is_loaded(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id == name
    if isinstance(node, ast.Lambda):
        return _lambda_loads_name(node, name)
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _comprehension_loads_name(node, name)
    return _child_loads_name(node, name)


def _lambda_loads_name(node: ast.Lambda, name: str) -> bool:
    loaded = _defaults_load_name(node.args, name)
    if name in _argument_name_set(node.args):
        return loaded
    return loaded or _name_is_loaded(node.body, name)


def _defaults_load_name(arguments: ast.arguments, name: str) -> bool:
    for default in (*arguments.defaults, *arguments.kw_defaults):
        if default is not None and _name_is_loaded(default, name):
            return True
    return False


def _argument_name_set(arguments: ast.arguments) -> frozenset[str]:
    return frozenset(argument.arg for argument in _arguments(arguments))


def _child_loads_name(node: ast.AST, name: str) -> bool:
    for child in ast.iter_child_nodes(node):
        if _name_is_loaded(child, name):
            return True
    return False


def _comprehension_loads_name(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, name: str
) -> bool:
    for generator in node.generators:
        found = _generator_clause_loads_name(generator, name)
        if found is not None:
            return found
    return _comprehension_element_loads_name(node, name)


def _generator_clause_loads_name(generator: ast.comprehension, name: str) -> bool | None:
    if _name_is_loaded(generator.iter, name):
        return True
    if _generator_binds_name(generator, name):
        return False
    if _clause_conditions_load_name(generator, name):
        return True
    return None


def _generator_binds_name(generator: ast.comprehension, name: str) -> bool:
    return name in _target_name_ids(generator.target)


def _target_name_ids(target: ast.AST) -> frozenset[str]:
    return frozenset(name.id for name in _target_names(target))


def _comprehension_element_loads_name(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    name: str,
) -> bool:
    element = node.key if isinstance(node, ast.DictComp) else node.elt
    if _name_is_loaded(element, name):
        return True
    return isinstance(node, ast.DictComp) and _name_is_loaded(node.value, name)


def _comprehension_tables(
    table: symtable.SymbolTable,
) -> defaultdict[tuple[str, int], list[symtable.SymbolTable]]:
    tables: defaultdict[tuple[str, int], list[symtable.SymbolTable]] = defaultdict(list)
    for key, child in _comprehension_table_entries(table):
        tables[key].append(child)
    return tables


def _comprehension_table_entries(
    table: symtable.SymbolTable,
) -> list[tuple[tuple[str, int], symtable.SymbolTable]]:
    found: list[tuple[tuple[str, int], symtable.SymbolTable]] = []
    if table.get_type() == "function" and table.get_name() in {"listcomp", "setcomp", "dictcomp", "genexpr"}:
        found.append(((table.get_name(), table.get_lineno()), table))
    for child in table.get_children():
        found.extend(_comprehension_table_entries(child))
    return found


def _function_tables(
    table: symtable.SymbolTable,
) -> defaultdict[tuple[str, int], list[symtable.SymbolTable]]:
    tables: defaultdict[tuple[str, int], list[symtable.SymbolTable]] = defaultdict(list)
    for key, child in _function_table_entries(table):
        tables[key].append(child)
    return tables


def _function_table_entries(
    table: symtable.SymbolTable,
) -> list[tuple[tuple[str, int], symtable.SymbolTable]]:
    found: list[tuple[tuple[str, int], symtable.SymbolTable]] = []
    if table.get_type() == "function":
        found.append(((table.get_name(), table.get_lineno()), table))
    for child in table.get_children():
        found.extend(_function_table_entries(child))
    return found


def _scope_usage(
    table: symtable.SymbolTable, usage_cache: dict[int, ScopeUsage] | None = None
) -> tuple[ScopeUsage, dict[int, ScopeUsage]]:
    cache = {} if usage_cache is None else usage_cache
    if id(table) in cache:
        return cache[id(table)], cache
    usage, cache = _uncached_scope_usage(table, cache)
    return usage, {**cache, id(table): usage}


def _uncached_scope_usage(
    table: symtable.SymbolTable, usage_cache: dict[int, ScopeUsage]
) -> tuple[ScopeUsage, dict[int, ScopeUsage]]:
    local_names = {name for name in table.get_identifiers() if table.lookup(name).is_local()}
    used_names = {name for name in table.get_identifiers() if table.lookup(name).is_referenced()}
    free_names = {name for name in table.get_identifiers() if table.lookup(name).is_free()}
    cache = usage_cache
    for child in table.get_children():
        child_usage, cache = _scope_usage(child, cache)
        captured = child_usage.free_names & local_names
        used_names.update(captured)
        free_names.update(child_usage.free_names - captured)
    return ScopeUsage(frozenset(used_names), frozenset(free_names)), cache


def _unused_private_field_findings(
    path: Path,
    tree: ast.Module,
    classes: Sequence[ClassInfo],
    rules: Sequence[LoadedRule],
    usage: PrivateMemberUsage | None,
) -> list[Finding]:
    rule = _rule(rules, UNUSED_PRIVATE_FIELD_RULE_NAME)
    if rule is None or usage is None:
        return []
    if usage.requires_conservative_handling:
        return []
    findings: list[Finding] = []
    dataclass_names = _dataclass_decorator_names(tree)
    for class_info in classes:
        if _is_dataclass(class_info.node, dataclass_names):
            continue
        fields = _private_fields(class_info.node)
        for name, line in fields.items():
            if name in usage.accessed_names or name in usage.exported_names:
                continue
            findings.append(
                Finding(
                    path,
                    line,
                    rule.name,
                    rule.priority,
                    f"Avoid unused private fields such as '{name}'.",
                    context=name,
                )
            )
    return findings


def _unused_private_method_findings(
    path: Path,
    classes: Sequence[ClassInfo],
    rules: Sequence[LoadedRule],
    usage: PrivateMemberUsage | None,
) -> list[Finding]:
    rule = _rule(rules, UNUSED_PRIVATE_METHOD_RULE_NAME)
    if rule is None or usage is None:
        return []
    if usage.requires_conservative_handling:
        return []
    findings: list[Finding] = []
    for class_info in classes:
        # An unresolved base may call protected hooks that this file cannot see.
        if class_info.has_unresolved_base:
            continue
        for method in class_info.methods:
            if not _is_unused_private_method(method, usage):
                continue
            findings.append(
                Finding(
                    path,
                    method.lineno,
                    rule.name,
                    rule.priority,
                    f"Avoid unused private methods such as '{method.name}'.",
                    context=method.name,
                )
            )
    return findings


def _is_unused_private_method(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    usage: PrivateMemberUsage,
) -> bool:
    return (
        _is_private_name(method.name)
        and method.name not in usage.accessed_names
        and method.name not in usage.exported_names
        and not method.decorator_list
        and not _is_contract_method(method)
    )


def _private_fields(node: ast.ClassDef) -> dict[str, int]:
    fields: dict[str, int] = {}
    for statement in _class_member_statements(node.body):
        for name in _field_names(statement):
            fields = _with_private_field(fields, name, statement.lineno)
    loads: set[str] = set()
    unknown = False
    for statement in _class_member_statements(node.body):
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            receiver = _instance_receiver(statement)
            for item in statement.body:
                fields, loads, unknown = _private_field_uses(item, receiver, fields, loads, unknown)
    if unknown:
        return {}
    return {name: line for name, line in fields.items() if name not in loads}


def _private_field_uses(
    node: ast.AST,
    receiver: str | None,
    fields: dict[str, int],
    loads: set[str],
    unknown: bool,
) -> tuple[dict[str, int], set[str], bool]:
    if isinstance(node, (ast.Lambda, ast.ClassDef)):
        return fields, loads, unknown
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _private_nested_function(node, receiver, fields, loads, unknown)
    fields, loads, unknown = _private_field_access(node, receiver, fields, loads, unknown)
    return _private_field_children(node, receiver, fields, loads, unknown)


def _private_nested_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    receiver: str | None,
    fields: dict[str, int],
    loads: set[str],
    unknown: bool,
) -> tuple[dict[str, int], set[str], bool]:
    if _function_shadows_receiver(node, receiver):
        return fields, loads, unknown
    return _private_field_children(node, receiver, fields, loads, unknown)


def _function_shadows_receiver(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    receiver: str | None,
) -> bool:
    return receiver is not None and _shadows_receiver(node, receiver)


def _private_field_access(
    node: ast.AST,
    receiver: str | None,
    fields: dict[str, int],
    loads: set[str],
    unknown: bool,
) -> tuple[dict[str, int], set[str], bool]:
    if isinstance(node, ast.Call):
        return _private_call_access(node, fields, loads, unknown)
    if isinstance(node, ast.AugAssign):
        return _private_augassign_access(node, receiver, fields, loads, unknown)
    if isinstance(node, ast.Attribute):
        return _private_attribute_access(node, receiver, fields, loads, unknown)
    return fields, loads, unknown


def _private_call_access(
    node: ast.Call,
    fields: dict[str, int],
    loads: set[str],
    unknown: bool,
) -> tuple[dict[str, int], set[str], bool]:
    names, has_unknown_access = _dynamic_attribute_accesses(node)
    return fields, loads | names, unknown or has_unknown_access


def _private_augassign_access(
    node: ast.AugAssign,
    receiver: str | None,
    fields: dict[str, int],
    loads: set[str],
    unknown: bool,
) -> tuple[dict[str, int], set[str], bool]:
    target = node.target
    if _names_receiver(target, receiver):
        return fields, loads | {target.attr}, unknown
    return fields, loads, unknown


def _private_attribute_access(
    node: ast.Attribute,
    receiver: str | None,
    fields: dict[str, int],
    loads: set[str],
    unknown: bool,
) -> tuple[dict[str, int], set[str], bool]:
    if isinstance(node.ctx, ast.Load):
        return fields, loads | {node.attr}, unknown
    if _names_receiver(node, receiver) and isinstance(node.ctx, ast.Store):
        return _with_private_field(fields, node.attr, node.lineno), loads, unknown
    return fields, loads, unknown


def _names_receiver(node: ast.AST, receiver: str | None) -> bool:
    if receiver is None or not isinstance(node, ast.Attribute):
        return False
    return isinstance(node.value, ast.Name) and node.value.id == receiver


def _private_field_children(
    node: ast.AST,
    receiver: str | None,
    fields: dict[str, int],
    loads: set[str],
    unknown: bool,
) -> tuple[dict[str, int], set[str], bool]:
    for child in ast.iter_child_nodes(node):
        fields, loads, unknown = _private_field_uses(child, receiver, fields, loads, unknown)
    return fields, loads, unknown


def _with_private_field(fields: dict[str, int], name: str, line: int) -> dict[str, int]:
    if not _is_private_name(name) or name in fields:
        return fields
    return {**fields, name: line}


def _is_private_name(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _dataclass_decorator_names(tree: ast.Module) -> set[str]:
    return {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "dataclasses"
        for alias in statement.names
        if alias.name == "dataclass"
    } | {"dataclass"}


def _is_dataclass(node: ast.ClassDef, decorator_names: set[str]) -> bool:
    return any(
        _called_name(decorator.func if isinstance(decorator, ast.Call) else decorator) in decorator_names | {"dataclass"}
        for decorator in node.decorator_list
    )


def _private_member_usage(tree: ast.Module) -> PrivateMemberUsage:
    dynamic_names, has_unknown_dynamic_access = _dynamic_attribute_accesses(tree, _dynamic_access_aliases(tree))
    exported_names, has_unknown_exports = _exported_names(tree)
    loads = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    } | dynamic_names
    return PrivateMemberUsage(
        frozenset(loads),
        frozenset(exported_names),
        has_unknown_dynamic_access or has_unknown_exports,
    )


def _dynamic_access_aliases(tree: ast.Module) -> set[str]:
    return {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "builtins"
        for alias in statement.names
        if alias.name in {"getattr", "hasattr", "setattr", "delattr"}
    }


def _exported_names(tree: ast.Module) -> tuple[set[str], bool]:
    names: set[str] = set()
    has_unknown_exports = False
    for statement in ast.walk(tree):
        targets, value, augmented = _export_assignment(statement)
        if augmented:
            has_unknown_exports = True
            continue
        if targets is None:
            continue
        if not _assigns_exports(targets):
            continue
        static_names = _static_export_names(value)
        if static_names is None:
            has_unknown_exports = True
            continue
        names.update(static_names)
    return names, has_unknown_exports


def _assigns_exports(targets: list[ast.expr]) -> bool:
    return any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets)


def _static_export_names(value: ast.expr | None) -> set[str] | None:
    if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return None
    if not all(
        isinstance(element, ast.Constant) and isinstance(element.value, str)
        for element in value.elts
    ):
        return None
    return {element.value for element in value.elts if isinstance(element, ast.Constant)}


def _export_assignment(
    statement: ast.AST,
) -> tuple[list[ast.expr] | None, ast.expr | None, bool]:
    if isinstance(statement, ast.Assign):
        return statement.targets, statement.value, False
    if isinstance(statement, ast.AnnAssign):
        return [statement.target], statement.value, False
    augmented = (
        isinstance(statement, ast.AugAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == "__all__"
    )
    return None, None, augmented


def _dynamic_attribute_accesses(node: ast.AST, aliases: set[str] | None = None) -> tuple[set[str], bool]:
    names: set[str] = set()
    has_unknown_access = False
    calls = [node] if isinstance(node, ast.Call) else ast.walk(node)
    for candidate in calls:
        if not isinstance(candidate, ast.Call):
            continue
        attribute_index = _dynamic_attribute_index(candidate, aliases or set())
        if attribute_index is None or len(candidate.args) <= attribute_index:
            continue
        attribute = candidate.args[attribute_index]
        if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
            names.add(attribute.value)
        else:
            has_unknown_access = True
    return names, has_unknown_access


def _dynamic_attribute_index(candidate: ast.Call, aliases: set[str]) -> int | None:
    function_name = _called_name(candidate.func)
    if function_name in {"getattr", "hasattr", "setattr", "delattr"} | aliases:
        return 1
    if function_name in {"__getattribute__", "__setattr__", "__delattr__"}:
        return 0
    return None


def _function_local_targets(node: ast.AST) -> list[ast.Name]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return []
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _named_expression_targets(node)
    found = _stored_binding_targets(node)
    for child in ast.iter_child_nodes(node):
        found.extend(_function_local_targets(child))
    return found


def _stored_binding_targets(node: ast.AST) -> list[ast.Name]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return [node]
    bound = ""
    line = getattr(node, "lineno", 0)
    column = getattr(node, "col_offset", 0)
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name is not None:
        bound = node.name
    elif isinstance(node, ast.MatchMapping) and node.rest is not None:
        bound = node.rest
    if not bound:
        return []
    return [ast.Name(id=bound, ctx=ast.Store(), lineno=line, col_offset=column)]


def _named_expression_targets(node: ast.AST) -> list[ast.Name]:
    found: list[ast.Name] = []
    pending = list(ast.iter_child_nodes(node))
    while pending:
        child = pending.pop()
        if isinstance(child, ast.NamedExpr):
            found.extend(_target_names(child.target))
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        pending.extend(ast.iter_child_nodes(child))
    return found


def _naming_findings(path: Path, tree: ast.Module, rules: Sequence[LoadedRule]) -> list[Finding]:
    targets, callables = _naming_roles(tree)
    findings: list[Finding] = []
    findings.extend(_short_class_name_findings(path, targets, rules))
    findings.extend(_long_class_name_findings(path, targets, rules))
    findings.extend(_short_variable_findings(path, targets, rules))
    findings.extend(_long_variable_findings(path, targets, rules))
    findings.extend(_short_method_name_findings(path, targets, rules))
    findings.extend(_constant_naming_findings(path, targets, rules))
    findings.extend(_boolean_get_method_name_findings(path, callables, rules))
    findings.extend(_strict_python_naming_findings(path, targets, rules))
    return findings


def _short_class_name_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, SHORT_CLASS_NAME_RULE_NAME)
    if rule is None:
        return []
    minimum = _integer_property(rule, "minimum")
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"Avoid using short class names like {target.name}. Configured minimum length is {minimum}.",
        )
        for target in targets
        if target.role == "class" and not _is_exempt_target(target) and len(target.name) < minimum
    ]


def _long_class_name_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, LONG_CLASS_NAME_RULE_NAME)
    if rule is None:
        return []
    maximum = _integer_property(rule, "maximum")
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"Avoid excessively long class names like {target.name}. Configured maximum length is {maximum}.",
        )
        for target in targets
        if target.role == "class" and not _is_exempt_target(target) and len(target.name) > maximum
    ]


def _short_variable_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, SHORT_VARIABLE_RULE_NAME)
    if rule is None:
        return []
    minimum = _integer_property(rule, "minimum")
    return _variable_length_findings(path, targets, rule, minimum, too_long=False)


def _long_variable_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, LONG_VARIABLE_RULE_NAME)
    if rule is None:
        return []
    maximum = _integer_property(rule, "maximum")
    return _variable_length_findings(path, targets, rule, maximum, too_long=True)


def _variable_length_findings(
    path: Path, targets: Sequence[NamingTarget], rule: LoadedRule, limit: int, too_long: bool
) -> list[Finding]:
    if too_long:
        message = lambda target, limit=limit: (
            f"Avoid excessively long variable names like {target.name}. Configured maximum length is {limit}."
        )
    else:
        message = lambda target, limit=limit: (
            f"Avoid variables with short names like {target.name}. Configured minimum length is {limit}."
        )
    return [
        _naming_finding(path, target, rule, message(target))
        for target in targets
        if target.role in {"parameter", "property", "variable"}
        and not _is_exempt_target(target)
        and (len(target.name) > limit if too_long else len(target.name) < limit)
    ]


def _short_method_name_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, SHORT_METHOD_NAME_RULE_NAME)
    if rule is None:
        return []
    minimum = _integer_property(rule, "minimum")
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"Avoid using short method names like {target.name}(). Configured minimum length is {minimum}.",
        )
        for target in targets
        if target.role in {"function", "method"} and not _is_exempt_target(target) and len(target.name) < minimum
    ]


def _constant_naming_findings(path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]) -> list[Finding]:
    rule = _rule(rules, CONSTANT_NAMING_CONVENTIONS_RULE_NAME)
    if rule is None:
        return []
    return [
        _naming_finding(
            path,
            target,
            rule,
            f"The constant {target.name} should use UPPER_CASE naming.",
        )
        for target in targets
        if target.role == "constant"
        and not _is_exempt_target(target)
        and re.fullmatch(r"[A-Z][A-Z0-9_]*", target.name) is None
    ]


def _boolean_get_method_name_findings(
    path: Path, callables: Sequence[NamingCallable], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, BOOLEAN_GET_METHOD_NAME_RULE_NAME)
    if rule is None:
        return []
    return [
        Finding(
            path,
            callable_info.node.lineno,
            rule.name,
            rule.priority,
            f"The boolean method {callable_info.node.name}() should not use the get prefix.",
            context=callable_info.node.name,
        )
        for callable_info in callables
        if callable_info.role == "method"
        and _is_getter_name(callable_info.node.name)
        and _has_boolean_result(callable_info.node)
    ]


def _strict_python_naming_findings(
    path: Path, targets: Sequence[NamingTarget], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule_roles = {
        CAMEL_CASE_CLASS_RULE_NAME: {"class"},
        CAMEL_CASE_METHOD_RULE_NAME: {"function", "method"},
        CAMEL_CASE_PROPERTY_RULE_NAME: {"property"},
        CAMEL_CASE_PARAMETER_RULE_NAME: {"parameter"},
        CAMEL_CASE_VARIABLE_RULE_NAME: {"variable"},
    }
    findings: list[Finding] = []
    for rule_name, roles in rule_roles.items():
        rule = _rule(rules, rule_name)
        if rule is None:
            continue
        for target in targets:
            if target.role not in roles or _is_exempt_target(target):
                continue
            if target.role == "class":
                valid = re.fullmatch(r"[A-Z][A-Za-z0-9]*", target.name) is not None
                convention = "CapWords"
            else:
                valid = _is_snake_case_name(target.name)
                convention = "snake_case"
            if valid:
                continue
            subject = "method" if target.role == "function" else target.role
            findings.append(
                _naming_finding(
                    path,
                    target,
                    rule,
                    f"The {subject} {target.name} is not named in {convention}.",
                )
            )
    return findings


def _is_snake_case_name(name: str) -> bool:
    if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", name) is not None:
        return True
    return (
        name.endswith("_")
        and keyword.iskeyword(name[:-1])
        and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", name[:-1]) is not None
    )


def _naming_finding(path: Path, target: NamingTarget, rule: LoadedRule, message: str) -> Finding:
    return Finding(path, target.line, rule.name, rule.priority, message, context=target.name)


def _is_exempt_target(target: NamingTarget) -> bool:
    if target.name.startswith("_"):
        return True
    if target.contract:
        return True
    if target.role == "property" and target.name in {"i", "j", "k", "n", "x", "y", "z"}:
        return True
    return target.role in {"parameter", "variable"} and target.name in {
        "self",
        "cls",
        "e",
        "err",
        "exc",
        "ex",
        "i",
        "j",
        "k",
        "n",
        "x",
        "y",
        "z",
    }


def _is_getter_name(name: str) -> bool:
    return name.startswith("get_") or (name.startswith("get") and len(name) > 3 and name[3].isupper())


def _has_boolean_result(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return _is_boolean_annotation(node.returns) or _all_paths_return_boolean(node.body)


def _is_boolean_annotation(node: ast.expr | None) -> bool:
    return (isinstance(node, ast.Name) and node.id == "bool") or (
        isinstance(node, ast.Constant) and node.value == "bool"
    )


def _all_paths_return_boolean(statements: Sequence[ast.stmt]) -> bool:
    if not statements:
        return False
    statement, *remaining = statements
    if isinstance(statement, ast.Return):
        return statement.value is not None and _is_boolean_expression(statement.value)
    if isinstance(statement, ast.If):
        return _all_paths_return_boolean([*statement.body, *remaining]) and _all_paths_return_boolean(
            [*statement.orelse, *remaining]
        )
    if _contains_return(statement):
        return False
    return _all_paths_return_boolean(remaining)


def _contains_return(node: ast.AST) -> bool:
    if isinstance(node, ast.Return):
        return True
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return False
    return any(_contains_return(child) for child in ast.iter_child_nodes(node))


def _is_boolean_expression(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Compare)
        or isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
        or isinstance(node, ast.Constant) and isinstance(node.value, bool)
        or isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"bool", "isinstance", "issubclass"}
    )


def _called_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _cyclomatic_complexity_findings(
    path: Path, callables: Sequence[CallableInfo], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == CYCLOMATIC_COMPLEXITY_RULE_NAME), None)
    if rule is None:
        return []
    try:
        threshold = int(rule.properties["reportlevel"])
    except (KeyError, ValueError) as error:
        raise RulesetError("CyclomaticComplexity property 'reportLevel' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in callables:
        complexity = _cyclomatic_complexity(callable_info.node)
        if complexity < threshold:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name}() has a Cyclomatic Complexity of {complexity}. "
            f"The configured cyclomatic complexity threshold is {threshold}."
        )
        findings.append(
            Finding(
                path,
                callable_info.node.lineno,
                CYCLOMATIC_COMPLEXITY_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _cyclomatic_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> int:
    roots = [node.body] if isinstance(node, ast.Lambda) else node.body
    return 1 + sum(_decision_count(statement) for statement in roots)


def _decision_count(node: ast.AST) -> int:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return 0
    if isinstance(node, ast.AnnAssign):
        return _decision_count(node.value) if node.value is not None else 0
    count = _decision_weight(node)
    for child in ast.iter_child_nodes(node):
        count += _decision_count(child)
    return count


def _decision_weight(node: ast.AST) -> int:
    if isinstance(node, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)):
        return 1
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    if isinstance(node, ast.Match):
        return len(node.cases)
    return 0


def _npath_complexity_findings(
    path: Path, callables: Sequence[CallableInfo], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == NPATH_COMPLEXITY_RULE_NAME), None)
    if rule is None:
        return []
    try:
        threshold = int(rule.properties["minimum"])
    except (KeyError, ValueError) as error:
        raise RulesetError("NPathComplexity property 'minimum' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in callables:
        complexity = _npath_complexity(callable_info.node)
        if complexity < threshold:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name}() has an NPath complexity of {complexity}. "
            f"The configured NPath complexity threshold is {threshold}."
        )
        findings.append(
            Finding(
                path,
                callable_info.node.lineno,
                NPATH_COMPLEXITY_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _npath_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> int:
    return _npath_expression(node.body) if isinstance(node, ast.Lambda) else _npath_block(node.body)


def _npath_block(statements: Sequence[ast.stmt]) -> int:
    complexity = 1
    for statement in statements:
        complexity *= _npath_statement(statement)
    return complexity


def _npath_statement(node: ast.stmt) -> int:
    if isinstance(node, ast.If):
        return _npath_expression(node.test) * (_npath_block(node.body) + _npath_block(node.orelse))
    elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        return _npath_loop(node)
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        return _npath_with(node)
    elif isinstance(node, (ast.Try, ast.TryStar)):
        return _npath_try(node)
    elif isinstance(node, ast.Match):
        return _npath_match(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return 1
    elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Return, ast.Raise)):
        value = getattr(node, "value", None)
        return _npath_expression(value) if value is not None else 1
    return 1


def _npath_loop(node: ast.For | ast.AsyncFor | ast.While) -> int:
    condition = node.iter if isinstance(node, (ast.For, ast.AsyncFor)) else node.test
    return _npath_expression(condition) * (_npath_block(node.body) + _npath_block(node.orelse))


def _npath_with(node: ast.With | ast.AsyncWith) -> int:
    complexity = 1
    for item in node.items:
        complexity *= _npath_expression(item.context_expr)
    return complexity * _npath_block(node.body)


def _npath_try(node: ast.Try | ast.TryStar) -> int:
    handlers = sum(_npath_block(handler.body) for handler in node.handlers)
    return (_npath_block(node.body) + handlers) * _npath_block(node.orelse) * _npath_block(node.finalbody)


def _npath_match(node: ast.Match) -> int:
    case_paths = sum(
        _npath_block(case.body) + (_npath_expression(case.guard) if case.guard is not None else 0)
        for case in node.cases
    )
    if not any(
        case.guard is None and _npath_match_pattern_is_irrefutable(case.pattern)
        for case in node.cases
    ):
        case_paths += 1
    return _npath_expression(node.subject) * case_paths


def _npath_match_pattern_is_irrefutable(pattern: ast.AST) -> bool:
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None or _npath_match_pattern_is_irrefutable(pattern.pattern)
    return isinstance(pattern, ast.MatchOr) and any(
        _npath_match_pattern_is_irrefutable(option) for option in pattern.patterns
    )


def _npath_expression(node: ast.AST | None) -> int:
    if node is None:
        return 1
    if isinstance(node, ast.BoolOp):
        return sum(_npath_expression(value) for value in node.values)
    if isinstance(node, ast.IfExp):
        return _npath_expression(node.test) + _npath_expression(node.body) + _npath_expression(node.orelse)
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        return _npath_comprehension(node)
    if isinstance(node, ast.Lambda):
        return 1
    complexity = 1
    for child in ast.iter_child_nodes(node):
        complexity *= _npath_expression(child)
    return complexity


def _npath_comprehension(
    node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp,
) -> int:
    complexity = 1
    for generator in node.generators:
        filters = 1
        for condition in generator.ifs:
            filters += _npath_expression(condition)
        complexity *= _npath_expression(generator.iter) * filters
    if isinstance(node, ast.DictComp):
        return complexity * _npath_expression(node.key) * _npath_expression(node.value)
    return complexity * _npath_expression(node.elt)


def _excessive_parameter_list_findings(
    path: Path, callables: Sequence[CallableInfo], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == EXCESSIVE_PARAMETER_LIST_RULE_NAME), None)
    if rule is None:
        return []
    try:
        threshold = int(rule.properties["minimum"])
    except (KeyError, ValueError) as error:
        raise RulesetError("ExcessiveParameterList property 'minimum' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in callables:
        if callable_info.parameter_count < threshold:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name} has {callable_info.parameter_count} parameters. "
            f"Consider reducing the number of parameters to less than {threshold}."
        )
        findings.append(
            Finding(
                path,
                callable_info.node.lineno,
                EXCESSIVE_PARAMETER_LIST_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _parameter_count(arguments: ast.arguments) -> int:
    return (
        len(arguments.posonlyargs)
        + len(arguments.args)
        + len(arguments.kwonlyargs)
        + int(arguments.vararg is not None)
        + int(arguments.kwarg is not None)
    )


def _callables(tree: ast.Module) -> list[CallableInfo]:
    callables = [
        *_callable_statements(tree.body, in_class_body=False),
        *(
            CallableInfo(node, "<lambda>", "lambda", _parameter_count(node.args))
            for node in ast.walk(tree)
            if isinstance(node, ast.Lambda)
        ),
    ]
    return sorted(callables, key=lambda callable_info: callable_info.node.lineno)


def _callable_statements(statements: Sequence[ast.stmt], in_class_body: bool) -> list[CallableInfo]:
    found: list[CallableInfo] = []
    for node in statements:
        if isinstance(node, ast.ClassDef):
            found.extend(_callable_statements(node.body, in_class_body=True))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "method" if in_class_body else "function"
            found.append(CallableInfo(node, node.name, kind, _parameter_count(node.args)))
            found.extend(_callable_statements(node.body, in_class_body=False))
        else:
            found.extend(_callable_statements(_child_statements(node), in_class_body=in_class_body))
    return found


@dataclass(frozen=True)
class _NamingState:
    targets: tuple[NamingTarget, ...] = ()
    target_names: frozenset[NamingTarget] = frozenset()
    callables: tuple[NamingCallable, ...] = ()
    contexts: tuple[str, ...] = ()
    class_depth: int = 0
    receivers: tuple[str | None, ...] = ()
    constant_target_ids: frozenset[int] = frozenset()
    generic_target_ids: frozenset[int] = frozenset()
    visitor_method_ids: frozenset[int] = frozenset()
    type_alias_annotation_ids: frozenset[int] = frozenset()


def _naming_roles(tree: ast.Module) -> tuple[list[NamingTarget], list[NamingCallable]]:
    state = _naming_visit(
        tree,
        _NamingState(
            visitor_method_ids=frozenset(_ast_visitor_method_ids(tree)),
            type_alias_annotation_ids=frozenset(_type_alias_annotation_ids(tree)),
        ),
    )
    for target in _named_binding_targets(tree):
        state = _with_naming_target(state, target.name, target.line, target.role)
    targets = sorted(state.targets, key=lambda target: (target.line, target.role, target.name))
    callables = sorted(state.callables, key=lambda callable_info: callable_info.node.lineno)
    return targets, callables


def _named_binding_targets(tree: ast.Module) -> list[NamingTarget]:
    targets: list[NamingTarget] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.name is not None:
            targets.append(NamingTarget(node.name, node.lineno, "variable"))
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name is not None:
            targets.append(NamingTarget(node.name, node.lineno, "variable"))
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            targets.append(NamingTarget(node.rest, node.lineno, "variable"))
    return targets


def _type_alias_annotation_ids(tree: ast.Module) -> set[int]:
    found, _aliases = _type_alias_ids(tree, {}, ())
    return found


def _type_alias_ids(
    node: ast.AST,
    aliases: dict[str, tuple[str, bool]],
    class_outer: tuple[dict[str, tuple[str, bool]], ...],
) -> tuple[set[int], dict[str, tuple[str, bool]]]:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return set(), {**aliases, **_statement_import_aliases(node)}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _type_alias_function_ids(node, aliases, class_outer)
    if isinstance(node, ast.ClassDef):
        return _type_alias_class_ids(node, aliases, class_outer)
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return _type_alias_assignment_ids(node, aliases, class_outer)
    return _type_alias_child_ids(node, aliases, class_outer)


def _type_alias_function_ids(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, tuple[str, bool]],
    class_outer: tuple[dict[str, tuple[str, bool]], ...],
) -> tuple[set[int], dict[str, tuple[str, bool]]]:
    inherited = class_outer[-1] if class_outer else aliases
    local_names = _direct_bindings(node)
    inner = {name: alias for name, alias in inherited.items() if name not in local_names}
    found: set[int] = set()
    for statement in node.body:
        statement_ids, inner = _type_alias_ids(statement, inner, class_outer)
        found |= statement_ids
    return found, _aliases_without(aliases, node.name)


def _type_alias_class_ids(
    node: ast.ClassDef,
    aliases: dict[str, tuple[str, bool]],
    class_outer: tuple[dict[str, tuple[str, bool]], ...],
) -> tuple[set[int], dict[str, tuple[str, bool]]]:
    body_aliases = dict(aliases)
    found: set[int] = set()
    enclosed = (*class_outer, aliases)
    for statement in node.body:
        statement_ids, body_aliases = _type_alias_ids(statement, body_aliases, enclosed)
        found |= statement_ids
    return found, _aliases_without(aliases, node.name)


def _type_alias_assignment_ids(
    node: ast.Assign | ast.AnnAssign | ast.AugAssign,
    aliases: dict[str, tuple[str, bool]],
    class_outer: tuple[dict[str, tuple[str, bool]], ...],
) -> tuple[set[int], dict[str, tuple[str, bool]]]:
    found = _recorded_type_alias_ids(node, aliases)
    found, aliases = _type_alias_child_ids(node, aliases, class_outer, found)
    return found, _aliases_without_assignment(aliases, node)


def _recorded_type_alias_ids(
    node: ast.Assign | ast.AnnAssign | ast.AugAssign,
    aliases: dict[str, tuple[str, bool]],
) -> set[int]:
    if isinstance(node, ast.AnnAssign) and _is_type_alias_annotation(node.annotation, aliases):
        return {id(node.annotation)}
    return set()


def _type_alias_child_ids(
    node: ast.AST,
    aliases: dict[str, tuple[str, bool]],
    class_outer: tuple[dict[str, tuple[str, bool]], ...],
    found: set[int] | None = None,
) -> tuple[set[int], dict[str, tuple[str, bool]]]:
    accumulated = set(found) if found is not None else set()
    for child in ast.iter_child_nodes(node):
        child_ids, aliases = _type_alias_ids(child, aliases, class_outer)
        accumulated |= child_ids
    return accumulated, aliases


def _aliases_without(
    aliases: dict[str, tuple[str, bool]],
    name: str,
) -> dict[str, tuple[str, bool]]:
    restored = dict(aliases)
    restored.pop(name, None)
    return restored


def _aliases_without_assignment(
    aliases: dict[str, tuple[str, bool]],
    statement: ast.stmt,
) -> dict[str, tuple[str, bool]]:
    restored = dict(aliases)
    for name in _statement_assigned_names(statement):
        restored.pop(name, None)
    return restored


def _naming_visit(node: ast.AST, state: _NamingState) -> _NamingState:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return _naming_definition(node, state)
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Name, ast.Attribute)):
        return _naming_binding(node, state)
    type_alias = getattr(ast, "TypeAlias", None)
    if type_alias is not None and isinstance(node, type_alias):
        return _naming_type_alias(node, state)
    return _naming_children(node, state)


def _naming_definition(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef,
    state: _NamingState,
) -> _NamingState:
    if isinstance(node, ast.ClassDef):
        return _naming_class(node, state)
    if isinstance(node, ast.Lambda):
        return _naming_lambda(node, state)
    return _naming_function(node, state)


def _naming_class(node: ast.ClassDef, state: _NamingState) -> _NamingState:
    state = _with_naming_target(state, node.name, node.lineno, "class")
    state = replace(state, contexts=(*state.contexts, "class"), class_depth=state.class_depth + 1)
    for statement in node.body:
        state = _naming_visit(statement, state)
    return replace(state, contexts=state.contexts[:-1], class_depth=state.class_depth - 1)


def _naming_function(node: ast.FunctionDef | ast.AsyncFunctionDef, state: _NamingState) -> _NamingState:
    direct_class_member = bool(state.contexts) and state.contexts[-1] == "class"
    role = _naming_callable_role(node, direct_class_member)
    state = _with_naming_target(
        state,
        node.name,
        node.lineno,
        role,
        id(node) in state.visitor_method_ids,
    )
    state = replace(state, callables=(*state.callables, NamingCallable(node, role)))
    state = _naming_parameters(node.args, state)
    state = _naming_expressions(node.decorator_list, state)
    state = _naming_expressions(_present_defaults(node.args), state)
    receiver = _instance_receiver(node) if direct_class_member else None
    state = replace(state, contexts=(*state.contexts, "function"), receivers=(*state.receivers, receiver))
    for statement in node.body:
        state = _naming_visit(statement, state)
    return replace(state, contexts=state.contexts[:-1], receivers=state.receivers[:-1])


def _naming_lambda(node: ast.Lambda, state: _NamingState) -> _NamingState:
    state = _naming_parameters(node.args, state)
    state = _naming_expressions(_present_defaults(node.args), state)
    state = replace(state, contexts=(*state.contexts, "function"), receivers=(*state.receivers, None))
    state = _naming_visit(node.body, state)
    return replace(state, contexts=state.contexts[:-1], receivers=state.receivers[:-1])


def _naming_binding(
    node: ast.Assign | ast.AnnAssign | ast.Name | ast.Attribute,
    state: _NamingState,
) -> _NamingState:
    if isinstance(node, ast.Assign):
        return _naming_assign(node, state)
    if isinstance(node, ast.AnnAssign):
        return _naming_annotated_assign(node, state)
    if isinstance(node, ast.Name):
        return _naming_name(node, state)
    return _naming_attribute(node, state)


def _naming_assign(node: ast.Assign, state: _NamingState) -> _NamingState:
    targets = _assignment_name_targets(node.targets)
    generic_ids = state.generic_target_ids
    constant_ids = state.constant_target_ids
    if _is_type_parameter_factory(node.value):
        generic_ids = generic_ids | _name_ids(targets)
    if _is_module_or_class_scope(state.contexts):
        constant_ids = constant_ids | _uppercase_target_ids(targets)
    state = replace(state, generic_target_ids=generic_ids, constant_target_ids=constant_ids)
    return _naming_children(node, state)


def _naming_annotated_assign(node: ast.AnnAssign, state: _NamingState) -> _NamingState:
    targets = _target_names(node.target)
    if id(node.annotation) in state.type_alias_annotation_ids:
        return _naming_type_alias_assignment(node, targets, state)
    if _annotated_assignment_is_constant(node, targets, state.contexts):
        state = replace(state, constant_target_ids=state.constant_target_ids | _name_ids(targets))
    return _naming_children(node, state)


def _naming_type_alias_assignment(
    node: ast.AnnAssign,
    targets: Sequence[ast.Name],
    state: _NamingState,
) -> _NamingState:
    state = replace(state, generic_target_ids=state.generic_target_ids | _name_ids(targets))
    for target in targets:
        state = _with_naming_target(state, target.id, target.lineno, "class")
    return _naming_children(node, state)


def _naming_name(node: ast.Name, state: _NamingState) -> _NamingState:
    if not isinstance(node.ctx, ast.Store):
        return state
    if id(node) in state.generic_target_ids:
        return state
    if id(node) in state.constant_target_ids:
        return _with_naming_target(state, node.id, node.lineno, "constant")
    return _with_naming_target(state, node.id, node.lineno, _naming_variable_role(state.contexts))


def _naming_attribute(node: ast.Attribute, state: _NamingState) -> _NamingState:
    if _stores_current_receiver_attribute(node, state):
        state = _with_naming_target(state, node.attr, node.lineno, "property")
    return _naming_children(node, state)


def _naming_type_alias(node: ast.AST, state: _NamingState) -> _NamingState:
    alias_name = node.name
    state = replace(state, generic_target_ids=state.generic_target_ids | {id(alias_name)})
    state = _with_naming_target(state, alias_name.id, alias_name.lineno, "class")
    return _naming_visit(node.value, state)


def _naming_children(node: ast.AST, state: _NamingState) -> _NamingState:
    for child in ast.iter_child_nodes(node):
        state = _naming_visit(child, state)
    return state


def _naming_parameters(arguments: ast.arguments, state: _NamingState) -> _NamingState:
    for argument in _arguments(arguments):
        state = _with_naming_target(state, argument.arg, argument.lineno, "parameter")
    return state


def _naming_expressions(nodes: Sequence[ast.expr], state: _NamingState) -> _NamingState:
    for node in nodes:
        state = _naming_visit(node, state)
    return state


def _present_defaults(arguments: ast.arguments) -> list[ast.expr]:
    defaults: list[ast.expr] = []
    for default in (*arguments.defaults, *arguments.kw_defaults):
        if default is not None:
            defaults.append(default)
    return defaults


def _with_naming_target(
    state: _NamingState,
    name: str,
    line: int,
    role: str,
    contract: bool = False,
) -> _NamingState:
    target = NamingTarget(name, line, role, contract)
    if target in state.target_names:
        return state
    return replace(state, targets=(*state.targets, target), target_names=state.target_names | {target})


def _assignment_name_targets(targets: Sequence[ast.expr]) -> list[ast.Name]:
    names: list[ast.Name] = []
    for target in targets:
        names.extend(_target_names(target))
    return names


def _name_ids(targets: Sequence[ast.Name]) -> frozenset[int]:
    return frozenset(id(target) for target in targets)


def _uppercase_target_ids(targets: Sequence[ast.Name]) -> frozenset[int]:
    return frozenset(id(target) for target in targets if re.fullmatch(r"[A-Z][A-Z0-9_]*", target.id) is not None)


def _annotated_assignment_is_constant(
    node: ast.AnnAssign,
    targets: Sequence[ast.Name],
    contexts: Sequence[str],
) -> bool:
    if _is_final_annotation(node.annotation):
        return True
    if not _is_module_or_class_scope(contexts):
        return False
    for target in targets:
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", target.id) is not None:
            return True
    return False


def _stores_current_receiver_attribute(node: ast.Attribute, state: _NamingState) -> bool:
    receiver = state.receivers[-1] if state.receivers else None
    if state.class_depth == 0 or receiver is None:
        return False
    if not isinstance(node.ctx, ast.Store) or not isinstance(node.value, ast.Name):
        return False
    return node.value.id == receiver


def _naming_variable_role(contexts: Sequence[str]) -> str:
    return "property" if contexts and contexts[-1] == "class" else "variable"


def _is_module_or_class_scope(contexts: Sequence[str]) -> bool:
    return not contexts or contexts[-1] == "class"


def _naming_callable_role(node: ast.FunctionDef | ast.AsyncFunctionDef, direct_class_member: bool) -> str:
    if not direct_class_member:
        return "function"
    return "property" if _has_property_decorator(node) else "method"


def _arguments(arguments: ast.arguments) -> list[ast.arg]:
    values = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        values.append(arguments.vararg)
    if arguments.kwarg is not None:
        values.append(arguments.kwarg)
    return values


def _target_names(node: ast.AST) -> list[ast.Name]:
    if isinstance(node, ast.Name):
        return [node]
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _target_names(element)]
    return []


def _is_type_alias_annotation(
    node: ast.expr,
    import_aliases: dict[str, tuple[str, bool]] | None = None,
) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TypeAlias" or _resolved_import_name(node, import_aliases or {}) == "typing.TypeAlias"
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
        and node.attr == "TypeAlias"
    ) or _resolved_import_name(node, import_aliases or {}) == "typing.TypeAlias"


def _is_final_annotation(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "Final"
    if isinstance(node, ast.Attribute):
        return node.attr == "Final"
    return isinstance(node, ast.Subscript) and _is_final_annotation(node.value)


def _is_type_parameter_factory(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and _called_name(node.func) in {"TypeVar", "ParamSpec", "TypeVarTuple"}


def _excessive_method_length_findings(
    path: Path, callables: Sequence[CallableInfo], rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = next((candidate for candidate in rules if candidate.name == METHOD_LENGTH_RULE_NAME), None)
    if rule is None:
        return []
    try:
        method_length_limit = int(rule.properties["minimum"])
    except (KeyError, ValueError) as error:
        raise RulesetError("ExcessiveMethodLength property 'minimum' must be an integer.") from error
    findings: list[Finding] = []
    for callable_info in callables:
        node = callable_info.node
        line_count = (node.end_lineno or node.lineno) - node.lineno + 1
        if line_count < method_length_limit:
            continue
        message = (
            f"The {callable_info.kind} {callable_info.name}() has {line_count} lines of code. "
            f"Current threshold is set to {method_length_limit}. Avoid really long methods."
        )
        findings.append(
            Finding(
                path,
                node.lineno,
                METHOD_LENGTH_RULE_NAME,
                rule.priority,
                message,
                context=callable_info.name,
            )
        )
    return findings


def _class_findings(
    path: Path,
    source_lines: Sequence[str],
    classes: Sequence[ClassInfo],
    rules: Sequence[LoadedRule],
) -> list[Finding]:
    findings: list[Finding] = []
    for class_info in classes:
        findings.extend(_excessive_class_length_findings(path, source_lines, class_info, rules))
        findings.extend(_excessive_public_count_findings(path, class_info, rules))
        findings.extend(_too_many_fields_findings(path, class_info, rules))
        findings.extend(_too_many_methods_findings(path, class_info, rules, public_only=False))
        findings.extend(_too_many_methods_findings(path, class_info, rules, public_only=True))
        findings.extend(_excessive_class_complexity_findings(path, class_info, rules))
    return findings


def _excessive_class_length_findings(
    path: Path, source_lines: Sequence[str], class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, EXCESSIVE_CLASS_LENGTH_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "minimum")
    ignore_whitespace = _boolean_property(rule, "ignore-whitespace")
    start = class_info.node.lineno
    end = class_info.node.end_lineno or start
    lines = source_lines[start - 1 : end]
    line_count = sum(bool(line.strip()) for line in lines) if ignore_whitespace else len(lines)
    if line_count < threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has {line_count} lines of code. "
            f"Current threshold is set to {threshold}. Avoid really long classes.",
        )
    ]


def _excessive_public_count_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, EXCESSIVE_PUBLIC_COUNT_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "minimum")
    count = sum(_is_public(name) for name in class_info.fields) + sum(
        _is_public(method.name)
        for method in class_info.methods
        if not _is_contract_method(method)
    )
    if count < threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has {count} public methods and attributes. "
            f"Consider reducing the number of public items to less than {threshold}.",
        )
    ]


def _too_many_fields_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, TOO_MANY_FIELDS_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "maxfields")
    count = len(class_info.fields)
    if count <= threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has {count} fields. Consider redesigning {class_info.name} "
            f"to keep the number of fields under {threshold}.",
        )
    ]


def _too_many_methods_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule], public_only: bool
) -> list[Finding]:
    name = TOO_MANY_PUBLIC_METHODS_RULE_NAME if public_only else TOO_MANY_METHODS_RULE_NAME
    rule = _rule(rules, name)
    if rule is None:
        return []
    threshold = _integer_property(rule, "maxmethods")
    ignore = _ignore_pattern(rule)
    methods = [
        method
        for method in class_info.methods
        if not _is_contract_method(method)
        and not ignore.match(method.name)
        and (not public_only or _is_public(method.name))
    ]
    count = len(methods)
    if count <= threshold:
        return []
    return [_class_finding(path, class_info, rule, _too_many_methods_message(class_info, count, threshold, public_only))]


def _too_many_methods_message(
    class_info: ClassInfo, count: int, threshold: int, public_only: bool
) -> str:
    if public_only:
        return (
            f"The class {class_info.name} has {count} public methods. Consider refactoring {class_info.name} "
            f"to keep number of public methods under {threshold}."
        )
    return (
        f"The class {class_info.name} has {count} non-getter- and setter-methods. "
        f"Consider refactoring {class_info.name} to keep number of methods under {threshold}."
    )


def _excessive_class_complexity_findings(
    path: Path, class_info: ClassInfo, rules: Sequence[LoadedRule]
) -> list[Finding]:
    rule = _rule(rules, EXCESSIVE_CLASS_COMPLEXITY_RULE_NAME)
    if rule is None:
        return []
    threshold = _integer_property(rule, "maximum")
    complexity = sum(
        _cyclomatic_complexity(method)
        for method in class_info.methods
        if not _is_contract_method(method)
    )
    if complexity < threshold:
        return []
    return [
        _class_finding(
            path,
            class_info,
            rule,
            f"The class {class_info.name} has an overall complexity of {complexity} which is very high. "
            f"The configured complexity threshold is {threshold}.",
        )
    ]


def _classes(tree: ast.Module) -> list[ClassInfo]:
    classes = []
    protocol_names = _protocol_base_names(tree)
    visitor_ids = _ast_visitor_class_ids(tree)
    qualified_names, classes_by_qualified_name = _qualified_class_index(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or _is_protocol(node, protocol_names):
            continue
        classes.append(
            _class_info(
                node,
                id(node) in visitor_ids,
                _has_unresolved_base(node, qualified_names, classes_by_qualified_name),
            )
        )
    return sorted(classes, key=lambda class_info: class_info.node.lineno)


def _ast_visitor_class_ids(tree: ast.Module) -> set[int]:
    class_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    visitor_ids = _direct_ast_visitor_class_ids(class_nodes, _class_import_aliases(tree))
    qualified_names, classes_by_qualified_name = _qualified_class_index(tree)
    inherited_ids = _inherited_ast_visitor_class_ids(
        class_nodes,
        qualified_names,
        classes_by_qualified_name,
        visitor_ids,
    )
    return visitor_ids | inherited_ids


def _child_statements(node: ast.AST) -> list[ast.stmt]:
    statements: list[ast.stmt] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            statements.append(child)
        elif isinstance(child, (ast.match_case, ast.ExceptHandler)):
            statements.extend(child.body)
    return statements


def _base_dotted_name(node: ast.expr) -> str:
    while isinstance(node, ast.Subscript):
        node = node.value
    return _dotted_name(node)


def _direct_ast_visitor_class_ids(
    class_nodes: list[ast.ClassDef],
    aliases_by_class: dict[int, dict[str, tuple[str, bool]]],
) -> set[int]:
    visitor_bases = {"ast.NodeVisitor", "ast.NodeTransformer"}
    return {
        id(node)
        for node in class_nodes
        if {
            _resolved_import_name(base, aliases_by_class.get(id(node), {}))
            for base in node.bases
        }
        & visitor_bases
    }


def _class_import_aliases(tree: ast.Module) -> dict[int, dict[str, tuple[str, bool]]]:
    return _index_class_import_aliases(tree.body, {})


def _index_class_import_aliases(
    statements: list[ast.stmt],
    inherited: dict[str, tuple[str, bool]],
) -> dict[int, dict[str, tuple[str, bool]]]:
    aliases = dict(inherited)
    aliases_by_class: dict[int, dict[str, tuple[str, bool]]] = {}
    for statement in statements:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            aliases.update(_statement_import_aliases(statement))
            continue
        if isinstance(statement, ast.ClassDef):
            aliases_by_class[id(statement)] = dict(aliases)
            aliases_by_class.update(_index_class_import_aliases(statement.body, aliases))
            aliases.pop(statement.name, None)
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            aliases_by_class.update(_index_class_import_aliases(statement.body, aliases))
            aliases.pop(statement.name, None)
            continue
        for name in _statement_assigned_names(statement):
            aliases.pop(name, None)
        aliases_by_class.update(_index_class_import_aliases(_child_statements(statement), aliases))
    return aliases_by_class


def _statement_import_aliases(
    statement: ast.Import | ast.ImportFrom,
) -> dict[str, tuple[str, bool]]:
    if isinstance(statement, ast.Import):
        return {
            item.asname or item.name.split(".", 1)[0]: (
                item.name if item.asname else item.name.split(".", 1)[0],
                False,
            )
            for item in statement.names
        }
    module = _import_from_module(statement)
    return {
        item.asname or item.name: (_imported_name(module, item.name), True)
        for item in statement.names
    }


def _statement_assigned_names(statement: ast.stmt) -> set[str]:
    if isinstance(statement, ast.Assign):
        return {name for target in statement.targets for name in _assigned_names(target)}
    if isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
        return set(_assigned_names(statement.target))
    return set()


def _inherited_ast_visitor_class_ids(
    class_nodes: list[ast.ClassDef],
    qualified_names: dict[int, str],
    classes_by_qualified_name: defaultdict[str, list[ast.ClassDef]],
    direct_ids: set[int],
) -> set[int]:
    visitor_ids = set(direct_ids)
    changed = True
    while changed:
        changed = False
        for node in class_nodes:
            if id(node) in visitor_ids:
                continue
            if _has_known_visitor_base(
                node,
                qualified_names,
                classes_by_qualified_name,
                visitor_ids,
            ):
                visitor_ids.add(id(node))
                changed = True
    return visitor_ids - direct_ids


def _has_known_visitor_base(
    node: ast.ClassDef,
    qualified_names: dict[int, str],
    classes_by_qualified_name: defaultdict[str, list[ast.ClassDef]],
    visitor_ids: set[int],
) -> bool:
    for base in node.bases:
        base_node = _local_base_class(
            node,
            _base_dotted_name(base),
            qualified_names,
            classes_by_qualified_name,
        )
        if base_node is not None and id(base_node) in visitor_ids:
            return True
    return False


def _qualified_class_index(
    tree: ast.Module,
) -> tuple[dict[int, str], defaultdict[str, list[ast.ClassDef]]]:
    return _index_qualified_classes(tree.body, "")


def _index_qualified_classes(
    statements: list[ast.stmt],
    prefix: str,
) -> tuple[dict[int, str], defaultdict[str, list[ast.ClassDef]]]:
    qualified_names: dict[int, str] = {}
    classes_by_name: defaultdict[str, list[ast.ClassDef]] = defaultdict(list)
    for statement in statements:
        if isinstance(statement, ast.ClassDef):
            qualified_name = f"{prefix}.{statement.name}" if prefix else statement.name
            qualified_names[id(statement)] = qualified_name
            classes_by_name[qualified_name].append(statement)
            qualified_names, classes_by_name = _merged_qualified_classes(
                qualified_names,
                classes_by_name,
                _index_qualified_classes(statement.body, qualified_name),
            )
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_prefix = f"{prefix}.{statement.name}" if prefix else statement.name
            qualified_names, classes_by_name = _merged_qualified_classes(
                qualified_names,
                classes_by_name,
                _index_qualified_classes(statement.body, function_prefix),
            )
        else:
            qualified_names, classes_by_name = _merged_qualified_classes(
                qualified_names,
                classes_by_name,
                _index_qualified_classes(_child_statements(statement), prefix),
            )
    return qualified_names, classes_by_name


def _merged_qualified_classes(
    qualified_names: dict[int, str],
    classes_by_name: defaultdict[str, list[ast.ClassDef]],
    indexed: tuple[dict[int, str], defaultdict[str, list[ast.ClassDef]]],
) -> tuple[dict[int, str], defaultdict[str, list[ast.ClassDef]]]:
    nested_names, nested_classes = indexed
    merged_names = {**qualified_names, **nested_names}
    merged_classes: defaultdict[str, list[ast.ClassDef]] = defaultdict(list, classes_by_name)
    for name, nodes in nested_classes.items():
        merged_classes[name] = [*merged_classes[name], *nodes]
    return merged_names, merged_classes


def _local_base_class(
    node: ast.ClassDef,
    base_name: str,
    qualified_names: dict[int, str],
    classes_by_qualified_name: defaultdict[str, list[ast.ClassDef]],
) -> ast.ClassDef | None:
    owner_name = qualified_names.get(id(node))
    if owner_name is None:
        return None
    owner_parts = owner_name.split(".")[:-1]
    candidate_names = [
        ".".join([*owner_parts[:depth], base_name])
        for depth in range(len(owner_parts), -1, -1)
    ]
    for candidate_name in candidate_names:
        earlier = [candidate for candidate in classes_by_qualified_name[candidate_name] if candidate.lineno < node.lineno]
        if earlier:
            return earlier[-1]
    return None


def _has_unresolved_base(
    node: ast.ClassDef,
    qualified_names: dict[int, str],
    classes_by_qualified_name: defaultdict[str, list[ast.ClassDef]],
) -> bool:
    return any(
        _local_base_class(node, _base_dotted_name(base), qualified_names, classes_by_qualified_name) is None
        for base in node.bases
    )


def _resolved_import_name(
    node: ast.expr,
    aliases: dict[str, tuple[str, bool]],
) -> str:
    name = _base_dotted_name(node)
    root, *tail = name.split(".")
    if root not in aliases:
        return ""
    imported, _is_symbol = aliases[root]
    return ".".join([imported, *tail])


def _ast_visitor_method_ids(tree: ast.Module) -> set[int]:
    visitor_ids = _ast_visitor_class_ids(tree)
    return {
        id(statement)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and id(node) in visitor_ids
        for statement in _class_member_statements(node.body)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_ast_visitor_handler(statement.name)
    }


def _class_info(node: ast.ClassDef, is_ast_visitor: bool, has_unresolved_base: bool) -> ClassInfo:
    members = _class_member_statements(node.body)
    methods = tuple(
        statement
        for statement in members
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    fields = tuple(
        dict.fromkeys(
            [
                *(name for statement in members for name in _field_names(statement)),
                *(name for method in methods for name in _instance_field_names(method)),
            ]
        )
    )
    return ClassInfo(node, node.name, fields, methods, is_ast_visitor, has_unresolved_base)


def _class_member_statements(statements: Sequence[ast.stmt]) -> list[ast.stmt]:
    members: list[ast.stmt] = []
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members.append(statement)
            continue
        if isinstance(statement, ast.ClassDef):
            continue
        members.append(statement)
        members.extend(_class_member_statements(_child_statements(statement)))
    return members


def _field_names(statement: ast.stmt) -> list[str]:
    if isinstance(statement, ast.AnnAssign):
        return _assigned_names(statement.target)
    if isinstance(statement, ast.Assign):
        return [name for target in statement.targets for name in _assigned_names(target)]
    if isinstance(statement, ast.AugAssign):
        return _assigned_names(statement.target)
    return []


def _assigned_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _assigned_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _assigned_names(element)]
    return []


def _instance_field_names(method: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    receiver = _instance_receiver(method)
    if receiver is None:
        return []
    names: list[str] = []
    for statement in method.body:
        names.extend(_instance_fields(statement, receiver))
    return names


def _instance_receiver(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if _has_decorator(method, "staticmethod"):
        return None
    arguments = [*method.args.posonlyargs, *method.args.args]
    if not arguments:
        return None
    receiver = arguments[0].arg
    if receiver == "self" or (_has_decorator(method, "classmethod") and receiver == "cls"):
        return receiver
    return None


def _shadows_receiver(function: ast.FunctionDef | ast.AsyncFunctionDef, receiver: str) -> bool:
    arguments = function.args
    candidates = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        arguments.vararg,
        arguments.kwarg,
    ]
    return any(argument is not None and argument.arg == receiver for argument in candidates)


def _instance_fields(node: ast.AST, receiver: str) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if _shadows_receiver(node, receiver):
            return []
        return _instance_field_children(node, receiver)
    if isinstance(node, (ast.Lambda, ast.ClassDef)):
        return []
    found: list[str] = []
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.value, ast.Name)
        and node.value.id == receiver
    ):
        found.append(node.attr)
    found.extend(_instance_field_children(node, receiver))
    return found


def _instance_field_children(node: ast.AST, receiver: str) -> list[str]:
    found: list[str] = []
    for child in ast.iter_child_nodes(node):
        found.extend(_instance_fields(child, receiver))
    return found


def _protocol_base_names(tree: ast.Module) -> set[str]:
    return {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "typing"
        for alias in statement.names
        if alias.name == "Protocol"
    } | {"Protocol"}


def _is_protocol(node: ast.ClassDef, protocol_names: set[str] | None = None) -> bool:
    names = protocol_names or {"Protocol"}
    return any(_is_protocol_base(base, names) for base in node.bases)


def _is_protocol_base(base: ast.AST, protocol_names: set[str]) -> bool:
    target = base.value if isinstance(base, ast.Subscript) else base
    return (
        isinstance(target, ast.Name) and target.id in protocol_names
    ) or (isinstance(target, ast.Attribute) and target.attr == "Protocol")


def _is_contract_method(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return _has_decorator(method, "overload") or _is_stub_body(method.body)


def _is_ast_visitor_handler(name: str) -> bool:
    return re.fullmatch(r"visit_(?:[A-Z][A-Za-z0-9]*|arg|comprehension)", name) is not None


def _has_property_decorator(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return _has_decorator(method, "property") or any(
        isinstance(decorator, ast.Attribute) and decorator.attr in {"getter", "setter", "deleter"}
        for decorator in method.decorator_list
    )


def _has_decorator(method: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == name)
        or (isinstance(decorator, ast.Attribute) and decorator.attr == name)
        for decorator in method.decorator_list
    )


def _is_stub_body(statements: Sequence[ast.stmt]) -> bool:
    body = _body_without_docstring(statements)
    if not body:
        return True
    if all(isinstance(statement, ast.Pass) for statement in body):
        return True
    return len(body) == 1 and (_is_ellipsis_statement(body[0]) or (
        isinstance(body[0], ast.Raise) and _raises_not_implemented(body[0])
    ))


def _body_without_docstring(statements: Sequence[ast.stmt]) -> list[ast.stmt]:
    body = list(statements)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _is_ellipsis_statement(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def _raises_not_implemented(statement: ast.Raise) -> bool:
    exception = statement.exc
    if isinstance(exception, ast.Name):
        return exception.id == "NotImplementedError"
    return isinstance(exception, ast.Call) and isinstance(exception.func, ast.Name) and exception.func.id == "NotImplementedError"


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _rule(rules: Sequence[LoadedRule], name: str) -> LoadedRule | None:
    return next((candidate for candidate in rules if candidate.name == name), None)


def _has_any_rule(rule_names: AbstractSet[str], names: AbstractSet[str]) -> bool:
    return bool(rule_names & names)


def _integer_property(rule: LoadedRule, property_name: str) -> int:
    try:
        return int(rule.properties[property_name])
    except (KeyError, ValueError) as error:
        raise RulesetError(f"{rule.name} property '{property_name}' must be an integer.") from error


def _boolean_property(rule: LoadedRule, property_name: str) -> bool:
    value = rule.properties.get(property_name, "false").casefold()
    if value == "true":
        return True
    if value == "false":
        return False
    raise RulesetError(f"{rule.name} property '{property_name}' must be true or false.")


def _ignore_pattern(rule: LoadedRule) -> re.Pattern[str]:
    value = rule.properties.get("ignorepattern", "").strip()
    ignore_case = value.endswith(")i")
    pattern = value[:-1].strip() if ignore_case else value
    if not pattern:
        # An empty (or whitespace-only) pattern would match every name, so it
        # excludes nothing: fall back to a pattern that never matches.
        return re.compile(r"(?!)")
    try:
        return re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as error:
        raise RulesetError(f"{rule.name} property 'ignorepattern' must be a valid regular expression.") from error


def _class_finding(path: Path, class_info: ClassInfo, rule: LoadedRule, message: str) -> Finding:
    return Finding(path, class_info.node.lineno, rule.name, rule.priority, message, context=class_info.name)


def _apply_suppressions(source: str, tree: ast.Module, findings: Sequence[Finding]) -> list[Finding]:
    directives, source_lines = _suppression_directives(source)
    source_line_set = set(source_lines)
    comment_finding_rules: dict[int, set[str]] = {}
    for finding in findings:
        if finding.line not in source_line_set:
            comment_finding_rules.setdefault(finding.line, set()).add(_rule_identity(finding.rule_name))
    source_lines = sorted(source_line_set | set(comment_finding_rules))
    header_lines = _definition_header_lines(tree)
    active_counts: dict[str, int] = {}
    next_line_rules: dict[int, set[str]] = {}
    directive_index = 0
    directive_count = len(directives)
    suppressed: list[Finding] = []
    for finding in sorted(findings, key=lambda candidate: candidate.line):
        while directive_index < directive_count and directives[directive_index][0] < finding.line:
            active_counts, next_line_rules = _apply_suppression_directive(
                directives[directive_index],
                source_lines,
                comment_finding_rules,
                header_lines,
                active_counts,
                next_line_rules,
            )
            directive_index += 1
        identity = _rule_identity(finding.rule_name)
        is_suppressed = active_counts.get(identity, 0) > 0 or identity in next_line_rules.get(
            finding.line, set()
        )
        suppressed.append(replace(finding, suppressed=is_suppressed))
    return suppressed


def _definition_header_lines(tree: ast.Module) -> dict[int, range]:
    header_lines: dict[int, range] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        header = range(node.lineno, _signature_end_line(node) + 1)
        first_line = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
        for line in range(first_line, node.lineno + 1):
            header_lines[line] = header
    return header_lines


def _signature_end_line(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    # A wrapped signature puts parameter findings on the lines below the def line.
    if isinstance(node, ast.ClassDef):
        return node.lineno
    signature_parts = [node.args] + ([node.returns] if node.returns else [])
    return max(
        getattr(part, "end_lineno", None) or node.lineno
        for signature_part in signature_parts
        for part in ast.walk(signature_part)
    )


def _apply_suppression_directive(
    directive: tuple[int, str, set[str]],
    source_lines: list[int],
    comment_finding_rules: dict[int, set[str]],
    header_lines: dict[int, range],
    active_counts: dict[str, int],
    next_line_rules: dict[int, set[str]],
) -> tuple[dict[str, int], dict[int, set[str]]]:
    line, action, rule_names = directive
    if action == "disable-next-line":
        return active_counts, _next_line_suppression(
            next_line_rules, source_lines, comment_finding_rules, header_lines, line, rule_names
        )
    delta = 1 if action == "disable" else -1
    updated = dict(active_counts)
    for rule_name in rule_names:
        updated[rule_name] = max(0, updated.get(rule_name, 0) + delta)
    return updated, next_line_rules


def _next_line_suppression(
    next_line_rules: dict[int, set[str]],
    source_lines: list[int],
    comment_finding_rules: dict[int, set[str]],
    header_lines: dict[int, range],
    line: int,
    rule_names: set[str],
) -> dict[int, set[str]]:
    next_line_index = bisect_right(source_lines, line)
    for target_line in source_lines[next_line_index:]:
        if target_line in comment_finding_rules and not (comment_finding_rules[target_line] & rule_names):
            continue
        rules = _with_rule_names(next_line_rules, target_line, rule_names)
        for header_line in header_lines.get(target_line, ()):
            rules = _with_rule_names(rules, header_line, rule_names)
        return rules
    return next_line_rules


def _with_rule_names(rules: dict[int, set[str]], line: int, rule_names: set[str]) -> dict[int, set[str]]:
    return {**rules, line: set(rules.get(line, ())) | rule_names}


def _suppression_directives(source: str) -> tuple[list[tuple[int, str, set[str]]], list[int]]:
    directives: list[tuple[int, str, set[str]]] = []
    source_lines: set[int] = set()
    ignored_tokens = {
        token.COMMENT,
        token.DEDENT,
        token.ENDMARKER,
        token.INDENT,
        token.NEWLINE,
        token.NL,
    }
    for item in tokenize.generate_tokens(StringIO(source).readline):
        if item.type == token.COMMENT:
            directive = _suppression_directive(item.string, item.start[0])
            if directive is not None:
                directives.append(directive)
        elif item.type not in ignored_tokens:
            source_lines.add(item.start[0])
    return directives, sorted(source_lines)


def _suppression_directive(comment: str, line: int) -> tuple[int, str, set[str]] | None:
    match = DIRECTIVE_PATTERN.fullmatch(comment[1:].strip())
    if match is None:
        return None
    rule_text = match.group(2)
    if rule_text is None or re.search(r",\s*(?:,|$)", rule_text):
        return None
    rule_names = re.split(r"[\s,]+", rule_text.strip())
    if not rule_names or not all(RULE_NAME_PATTERN.fullmatch(name) for name in rule_names):
        return None
    return line, match.group(1).casefold(), {_rule_identity(name) for name in rule_names}


def _rule_identity(name: str) -> str:
    return name.casefold()


def _source_files(
    paths: Sequence[Path], suffixes: AbstractSet[str], exclusions: Sequence[str], ignore_tests: bool
) -> list[Path]:
    source_files: set[Path] = set()
    for path in paths:
        source_files.update(_source_files_under(path, suffixes, exclusions, ignore_tests, root=path))
    return sorted(source_files, key=lambda candidate: candidate.as_posix())


def _source_files_under(
    path: Path,
    suffixes: AbstractSet[str],
    exclusions: Sequence[str],
    ignore_tests: bool,
    root: Path | None = None,
) -> set[Path]:
    scan_root = root if root is not None else path
    if _is_root_ignored(path, exclusions, ignore_tests, scan_root):
        return set()
    if path.is_file():
        return {path.resolve()} if path.suffix.lower() in suffixes else set()
    if not path.is_dir():
        raise OSError("Input path does not exist")
    return _collect_directory_source_files(path, suffixes, exclusions, ignore_tests, scan_root)


def _collect_directory_source_files(
    path: Path,
    suffixes: AbstractSet[str],
    exclusions: Sequence[str],
    ignore_tests: bool,
    root: Path,
) -> set[Path]:
    source_files: set[Path] = set()
    for candidate in sorted(path.iterdir(), key=lambda entry: entry.name):
        source_files.update(
            _source_files_for_candidate(candidate, suffixes, exclusions, ignore_tests, root)
        )
    return source_files


def _is_root_ignored(
    path: Path, exclusions: Sequence[str], ignore_tests: bool, root: Path
) -> bool:
    if _is_excluded(path, exclusions, root):
        return True
    return ignore_tests and _is_test_path(path, root)


def _is_candidate_directory_ignored(
    candidate: Path, exclusions: Sequence[str], ignore_tests: bool, root: Path
) -> bool:
    if candidate.is_symlink() or candidate.name.lower() in DEFAULT_IGNORED_DIRECTORY_NAMES:
        return True
    if _is_excluded(candidate, exclusions, root):
        return True
    return ignore_tests and _is_test_path(candidate, root)


def _is_candidate_file_ignored(
    candidate: Path, exclusions: Sequence[str], ignore_tests: bool, root: Path
) -> bool:
    if _is_excluded(candidate, exclusions, root):
        return True
    return ignore_tests and _is_test_path(candidate, root)


def _source_files_for_candidate(
    candidate: Path,
    suffixes: AbstractSet[str],
    exclusions: Sequence[str],
    ignore_tests: bool,
    root: Path,
) -> set[Path]:
    if candidate.is_dir():
        if _is_candidate_directory_ignored(candidate, exclusions, ignore_tests, root):
            return set()
        return _source_files_under(candidate, suffixes, exclusions, ignore_tests, root=root)
    if not candidate.is_file() or candidate.suffix.lower() not in suffixes:
        return set()
    if _is_candidate_file_ignored(candidate, exclusions, ignore_tests, root):
        return set()
    return {candidate.resolve()}


def _relative_parts(path: Path, root: Path | None = None) -> tuple[str, ...]:
    if root is not None and path != root:
        try:
            return path.relative_to(root).parts
        except ValueError:
            return (path.name,) if path.name else ()
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).parts
    except ValueError:
        return (path.name,) if path.name else ()


def _is_excluded(path: Path, exclusions: Sequence[str], root: Path | None = None) -> bool:
    if not exclusions:
        return False
    parts = _relative_parts(path, root)
    return any(exclusion in parts for exclusion in exclusions)


def _is_test_path(path: Path, root: Path | None = None) -> bool:
    if path.is_file() and (
        path.name.lower().startswith("test_") or path.stem.lower().endswith("_test")
    ):
        return True
    parts = _relative_parts(path, root)
    test_parts = parts[:-1] if path.is_file() else parts
    return any(part.lower() in TEST_DIRECTORY_NAMES for part in test_parts)
