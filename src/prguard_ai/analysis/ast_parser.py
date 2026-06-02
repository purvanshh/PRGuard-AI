"""AST parsing utilities using tree-sitter for PRGuard AI."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import ast

try:  # pragma: no cover - exercised indirectly in environments with dependencies installed
    from tree_sitter import Language, Node, Parser
except Exception:  # pragma: no cover - dependency availability is environment specific
    Language = Any  # type: ignore[assignment]
    Node = Any  # type: ignore[assignment]
    Parser = Any  # type: ignore[assignment]
    _TREE_SITTER_AVAILABLE = False
else:
    _TREE_SITTER_AVAILABLE = True


@dataclass
class AstSummary:
    """Structured summary of a source file's AST."""

    functions: List[Dict[str, Any]]
    variables: List[str]
    control_structures: List[Dict[str, Any]]
    language: str | None = None


_LANGUAGE_CACHE: Dict[str, Language] = {}

_EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mts": "typescript",
    ".cts": "typescript",
    ".rs": "rust",
}

_LANGUAGE_BINDINGS = {
    "python": ("tree_sitter_python", "language"),
    "go": ("tree_sitter_go", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "rust": ("tree_sitter_rust", "language"),
}

_FUNCTION_NODE_TYPES = {
    "python": {"function_definition"},
    "go": {"function_declaration", "method_declaration"},
    "typescript": {"function_declaration", "method_definition"},
    "tsx": {"function_declaration", "method_definition"},
    "rust": {"function_item"},
}

_CONTROL_NODE_TYPES = {
    "python": {"if_statement", "for_statement", "while_statement", "try_statement", "with_statement"},
    "go": {"if_statement", "for_statement", "expression_switch_statement", "type_switch_statement", "select_statement"},
    "typescript": {"if_statement", "for_statement", "while_statement", "switch_statement", "try_statement"},
    "tsx": {"if_statement", "for_statement", "while_statement", "switch_statement", "try_statement"},
    "rust": {"if_expression", "for_expression", "while_expression", "loop_expression", "match_expression"},
}

_PARAMETER_CONTAINER_TYPES = {
    "python": {"parameters"},
    "go": {"parameter_list"},
    "typescript": {"formal_parameters"},
    "tsx": {"formal_parameters"},
    "rust": {"parameters"},
}

_FUNCTION_NAME_NODE_TYPES = {"identifier", "field_identifier", "property_identifier"}


def detect_language(path: str | Path | None) -> str | None:
    """Infer the supported tree-sitter language from a file path."""
    if path is None:
        return None

    candidate = Path(path)
    name = candidate.name.lower()
    if name.endswith(".d.ts"):
        return "typescript"

    for suffix in reversed(candidate.suffixes):
        language_name = _EXTENSION_LANGUAGE_MAP.get(suffix.lower())
        if language_name is not None:
            return language_name
    return None


def _normalize_language_name(language_name: str | None) -> str:
    if not language_name:
        return "python"
    normalized = language_name.lower()
    if normalized not in _LANGUAGE_BINDINGS:
        raise ValueError(f"Unsupported tree-sitter language: {language_name}")
    return normalized


def _coerce_language(binding: object) -> Language:
    if isinstance(binding, Language):
        return binding
    return Language(binding)


def _load_language(language_name: str) -> Language:
    """Load a tree-sitter grammar from the per-language Python bindings."""
    normalized = _normalize_language_name(language_name)
    if normalized in _LANGUAGE_CACHE:
        return _LANGUAGE_CACHE[normalized]
    if not _TREE_SITTER_AVAILABLE:
        raise RuntimeError("tree-sitter is not installed")

    module_name, attr_name = _LANGUAGE_BINDINGS[normalized]
    try:
        module = import_module(module_name)
        binding = getattr(module, attr_name)()
        language = _coerce_language(binding)
    except Exception as exc:  # pragma: no cover - depends on installed bindings
        raise RuntimeError(
            f"Failed to load tree-sitter grammar for {normalized}. "
            f"Install the '{module_name.replace('_', '-')}' package."
        ) from exc

    _LANGUAGE_CACHE[normalized] = language
    return language


def _create_parser(language_name: str = "python") -> Parser:
    parser = Parser()
    language = _load_language(language_name)
    if hasattr(parser, "set_language"):
        parser.set_language(language)
    else:  # pragma: no cover - depends on tree-sitter version
        parser.language = language
    return parser


def parse_ast(
    file_content: str,
    parser: Optional[Parser] = None,
    *,
    file_path: str | Path | None = None,
    language_name: str | None = None,
) -> Node:
    """
    Parse raw source code into a tree-sitter AST root node.
    """
    resolved_language = language_name or detect_language(file_path)
    if resolved_language is None:
        if file_path is not None:
            raise ValueError(f"Unsupported file type for AST parsing: {file_path}")
        resolved_language = "python"
    if parser is None:
        parser = _create_parser(resolved_language)
    tree = parser.parse(file_content.encode("utf-8"))
    return tree.root_node


def _node_text(source: str, node: Node) -> str:
    return source[node.start_byte : node.end_byte]


def _iter_descendants(node: Node) -> Iterable[Node]:
    for child in node.children:
        yield child
        yield from _iter_descendants(child)


def _extract_function_name(node: Node, source: str) -> str | None:
    for child in node.children:
        if child.type in _FUNCTION_NAME_NODE_TYPES:
            return _node_text(source, child)
    return None


def _extract_parameter_names(node: Node, source: str, language_name: str) -> List[str]:
    parameter_container_types = _PARAMETER_CONTAINER_TYPES.get(language_name, set())
    params: List[str] = []
    seen: set[str] = set()

    for child in node.children:
        if child.type not in parameter_container_types:
            continue
        for descendant in _iter_descendants(child):
            if descendant.type != "identifier":
                continue
            text = _node_text(source, descendant)
            if text not in seen:
                seen.add(text)
                params.append(text)
    return params


def extract_function_definitions(ast_root: Node, source: str, language_name: str = "python") -> List[Dict[str, Any]]:
    """
    Extract function definitions from the AST.

    Returns a list of dictionaries with keys:
    - name
    - start_line
    - end_line
    - parameters
    """
    functions: List[Dict[str, Any]] = []
    function_node_types = _FUNCTION_NODE_TYPES.get(language_name, set())

    def walk(node: Node) -> None:
        if node.type in function_node_types:
            name = _extract_function_name(node, source)
            params = _extract_parameter_names(node, source, language_name)
            functions.append(
                {
                    "name": name,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "parameters": params,
                }
            )
        for child in node.children:
            walk(child)

    walk(ast_root)
    return functions


def extract_variable_names(ast_root: Node, source: str) -> List[str]:
    """
    Extract variable names from identifiers in the AST.
    """
    names: set[str] = set()

    def walk(node: Node) -> None:
        if node.type == "identifier":
            names.add(_node_text(source, node))
        for child in node.children:
            walk(child)

    walk(ast_root)
    return sorted(names)


def extract_control_structures(ast_root: Node, source: str, language_name: str = "python") -> List[Dict[str, Any]]:
    """
    Extract control-structure nodes (if/for/while/try/with).
    """
    control_types = _CONTROL_NODE_TYPES.get(language_name, set())
    controls: List[Dict[str, Any]] = []

    def walk(node: Node) -> None:
        if node.type in control_types:
            controls.append(
                {
                    "type": node.type,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "text": _node_text(source, node),
                }
            )
        for child in node.children:
            walk(child)

    walk(ast_root)
    return controls


def summarize_source(
    source: str,
    parser: Optional[Parser] = None,
    *,
    file_path: str | Path | None = None,
    language_name: str | None = None,
) -> AstSummary:
    """
    Produce a concise AST-based summary of source code.

    Prefers tree-sitter when available. Python falls back to the stdlib `ast`
    module when tree-sitter or its grammar bindings are unavailable.
    """
    detected_language = language_name or detect_language(file_path)
    if detected_language is None and file_path is not None:
        return AstSummary(functions=[], variables=[], control_structures=[], language=None)

    resolved_language = _normalize_language_name(detected_language or "python")
    try:
        root = parse_ast(source, parser=parser, file_path=file_path, language_name=resolved_language)
        return AstSummary(
            functions=extract_function_definitions(root, source, resolved_language),
            variables=extract_variable_names(root, source),
            control_structures=extract_control_structures(root, source, resolved_language),
            language=resolved_language,
        )
    except Exception:
        if resolved_language != "python":
            return AstSummary(functions=[], variables=[], control_structures=[], language=resolved_language)

        # Fallback: basic structural summary using Python's stdlib `ast`.
        try:
            py_tree = ast.parse(source)
        except SyntaxError:
            # If the snippet is not valid Python (e.g. raw diff context),
            # return an empty but well-formed summary so callers can proceed.
            return AstSummary(functions=[], variables=[], control_structures=[], language=resolved_language)

        functions: List[Dict[str, Any]] = []
        variables: List[str] = []
        controls: List[Dict[str, Any]] = []

        for node in ast.walk(py_tree):
            if isinstance(node, ast.FunctionDef):
                params = [arg.arg for arg in node.args.args]
                functions.append(
                    {
                        "name": node.name,
                        "start_line": getattr(node, "lineno", 1),
                        "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                        "parameters": params,
                    }
                )
            elif isinstance(node, ast.Name):
                variables.append(node.id)
            elif isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                controls.append(
                    {
                        "type": type(node).__name__.lower(),
                        "start_line": getattr(node, "lineno", 1),
                        "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                        "text": "",  # omitted in fallback
                    }
                )

        return AstSummary(
            functions=functions,
            variables=sorted(set(variables)),
            control_structures=controls,
            language=resolved_language,
        )


def summarize_file(path: str | Path, parser: Optional[Parser] = None) -> AstSummary:
    content = Path(path).read_text(encoding="utf-8")
    return summarize_source(content, parser=parser, file_path=path)


__all__ = [
    "AstSummary",
    "detect_language",
    "parse_ast",
    "extract_function_definitions",
    "extract_variable_names",
    "extract_control_structures",
    "summarize_source",
    "summarize_file",
]
