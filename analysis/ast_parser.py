"""AST parsing utilities using tree-sitter for PRGuard AI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from tree_sitter import Language, Parser, Node


@dataclass
class AstSummary:
    """Structured summary of a source file's AST."""

    functions: List[Dict[str, Any]]
    variables: List[str]
    control_structures: List[Dict[str, Any]]


_PY_LANGUAGE: Language | None = None


def _load_python_language() -> Language:
    """
    Load the tree-sitter Python language.

    For local development this expects a compiled language bundle at
    ``build/my-languages.so`` that includes the Python grammar under
    the name ``python``.
    """
    global _PY_LANGUAGE
    if _PY_LANGUAGE is not None:
        return _PY_LANGUAGE

    lib_path = "build/my-languages.so"
    try:
        _PY_LANGUAGE = Language(lib_path, "python")
    except Exception as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "Failed to load tree-sitter language library. Ensure the shared object "
            "is built and available at 'build/my-languages.so' with the Python "
            "grammar compiled in."
        ) from exc
    return _PY_LANGUAGE


def _create_parser() -> Parser:
    parser = Parser()
    parser.set_language(_load_python_language())
    return parser


def parse_ast(file_content: str, parser: Optional[Parser] = None) -> Node:
    """
    Parse raw source code into a tree-sitter AST root node.
    """
    if parser is None:
        parser = _create_parser()
    tree = parser.parse(file_content.encode("utf-8"))
    return tree.root_node


def _node_text(source: str, node: Node) -> str:
    return source[node.start_byte : node.end_byte]


def extract_function_definitions(ast_root: Node, source: str) -> List[Dict[str, Any]]:
    """
    Extract function definitions from the AST.

    Returns a list of dictionaries with keys:
    - name
    - start_line
    - end_line
    - parameters
    """
    functions: List[Dict[str, Any]] = []

    def walk(node: Node) -> None:
        if node.type == "function_definition":
            name_node = next((c for c in node.children if c.type == "identifier"), None)
            params_node = next((c for c in node.children if c.type == "parameters"), None)
            params: List[str] = []
            if params_node is not None:
                for child in params_node.children:
                    if child.type == "identifier":
                        params.append(_node_text(source, child))
            functions.append(
                {
                    "name": _node_text(source, name_node) if name_node is not None else None,
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


def extract_control_structures(ast_root: Node, source: str) -> List[Dict[str, Any]]:
    """
    Extract control-structure nodes (if/for/while/try/with).
    """
    control_types = {
        "if_statement",
        "for_statement",
        "while_statement",
        "try_statement",
        "with_statement",
    }
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


def summarize_source(source: str, parser: Optional[Parser] = None) -> AstSummary:
    """
    Produce a concise AST-based summary of Python source code.
    """
    root = parse_ast(source, parser=parser)
    return AstSummary(
        functions=extract_function_definitions(root, source),
        variables=extract_variable_names(root, source),
        control_structures=extract_control_structures(root, source),
    )


def summarize_file(path: str | Path, parser: Optional[Parser] = None) -> AstSummary:
    content = Path(path).read_text(encoding="utf-8")
    return summarize_source(content, parser=parser)


__all__ = [
    "AstSummary",
    "parse_ast",
    "extract_function_definitions",
    "extract_variable_names",
    "extract_control_structures",
    "summarize_source",
    "summarize_file",
]

