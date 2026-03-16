"""AST parsing utilities using tree-sitter for PRGuard AI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from tree_sitter import Language, Parser


@dataclass
class AstNode:
    """Lightweight wrapper around a tree-sitter node."""

    type: str
    start_line: int
    end_line: int
    text: str


def _load_python_language() -> Language:
    """
    Load the tree-sitter Python language.

    This assumes `tree_sitter_languages` is installed, or the compiled library
    is available under the standard name. For production, this should be
    customized to the deployment environment.
    """
    # Placeholder dynamic library name; adjust as needed for real deployments.
    lib_path = "build/my-languages.so"
    try:
        return Language(lib_path, "python")
    except Exception as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "Failed to load tree-sitter language library. Ensure the shared object "
            "is built and available at 'build/my-languages.so'."
        ) from exc


def create_python_parser() -> Parser:
    """Create a tree-sitter parser configured for Python."""
    parser = Parser()
    language = _load_python_language()
    parser.set_language(language)
    return parser


def parse_source_to_ast_nodes(source: str, parser: Optional[Parser] = None) -> List[AstNode]:
    """
    Parse Python source code into a list of high-level AST nodes.

    This implementation flattens only top-level function and class definitions.
    """
    if parser is None:
        parser = create_python_parser()
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node

    nodes: List[AstNode] = []
    for child in root.children:
        if child.type in {"function_definition", "class_definition"}:
            nodes.append(
                AstNode(
                    type=child.type,
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    text=source[child.start_byte : child.end_byte],
                )
            )
    return nodes


def parse_file(path: str | Path, parser: Optional[Parser] = None) -> List[AstNode]:
    """Parse a file from disk into AST nodes."""
    content = Path(path).read_text(encoding="utf-8")
    return parse_source_to_ast_nodes(content, parser=parser)


__all__ = ["AstNode", "create_python_parser", "parse_source_to_ast_nodes", "parse_file"]

