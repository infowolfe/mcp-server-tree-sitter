"""Helper functions for tree-sitter operations.

This module provides wrappers and utility functions for common tree-sitter operations
to ensure type safety and consistent handling of tree-sitter objects.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

# Import tree_cache at runtime as needed to avoid circular imports
from ..utils.file_io import read_binary_file
from ..utils.tree_sitter_types import (
    Language,
    Node,
    Parser,
    Tree,
    TreeCursor,
    ensure_cursor,
    ensure_language,
    ensure_node,
    ensure_parser,
    ensure_tree,
)

T = TypeVar("T")


def create_query(language: Any, query_string: str) -> Any:
    """Create a tree-sitter Query using the non-deprecated API.

    tree-sitter >= 0.25 deprecated Language.query() in favor of Query(language, query_string).
    """
    try:
        from tree_sitter import Query

        return Query(language, query_string)
    except (ImportError, TypeError):
        # Fall back to deprecated API for older tree-sitter versions
        return language.query(query_string)


def query_captures(query: Any, node: Any) -> Any:
    """Compat wrapper: works with both old (query.captures) and new (QueryCursor) API."""
    # New API (py-tree-sitter >= 0.24): Query has no .captures(), use QueryCursor.
    # The import is guarded for older tree-sitter versions that lack QueryCursor;
    # mypy can't see the runtime version branching, so silence attr-defined here.
    if not hasattr(query, "captures"):
        try:
            from tree_sitter import QueryCursor  # type: ignore[attr-defined]

            cursor = QueryCursor(query)
            return cursor.captures(node)
        except ImportError as err:
            raise AttributeError("tree_sitter.Query has no 'captures' and QueryCursor is unavailable") from err
    # Old API (py-tree-sitter < 0.24): query.captures(node)
    return query.captures(node)


def create_parser(language_obj: Any) -> Parser:
    """Create a parser configured for a specific language.

    tree-sitter 0.26 takes the language in the constructor and has no
    set_language method.

    Args:
        language_obj: Language object

    Returns:
        Configured Parser
    """
    safe_language = ensure_language(language_obj)
    parser = Parser(safe_language)
    return ensure_parser(parser)


def parse_source(source: bytes, parser: Parser | Any) -> Tree:
    """Parse source code using a configured parser.

    Args:
        source: Source code as bytes
        parser: Configured Parser object

    Returns:
        Parsed Tree
    """
    safe_parser = ensure_parser(parser)
    tree = safe_parser.parse(source)
    return ensure_tree(tree)


def parse_source_incremental(source: bytes, old_tree: Tree | None, parser: Parser) -> Tree:
    """Parse source code incrementally using a configured parser.

    Args:
        source: Source code as bytes
        old_tree: Previous tree for incremental parsing
        parser: Configured Parser object

    Returns:
        Parsed Tree
    """
    safe_parser = ensure_parser(parser)
    tree = safe_parser.parse(source, old_tree)
    return ensure_tree(tree)


def edit_tree(
    tree: Tree,
    edit_dict_or_start_byte: dict[str, Any] | int,
    old_end_byte: int | None = None,
    new_end_byte: int | None = None,
    start_point: tuple[int, int] | None = None,
    old_end_point: tuple[int, int] | None = None,
    new_end_point: tuple[int, int] | None = None,
) -> Tree:
    """Edit a syntax tree to reflect source code changes.

    Args:
        tree: Tree to edit
        edit_dict_or_start_byte: Edit dictionary or start byte of the edit
        old_end_byte: End byte of the old text (if not using edit dict)
        new_end_byte: End byte of the new text (if not using edit dict)
        start_point: Start point (row, column) of the edit (if not using edit dict)
        old_end_point: End point of the old text (if not using edit dict)
        new_end_point: End point of the new text (if not using edit dict)

    Returns:
        Edited tree
    """
    safe_tree = ensure_tree(tree)

    # Handle both dictionary and individual parameters
    if isinstance(edit_dict_or_start_byte, dict):
        edit_dict = edit_dict_or_start_byte
        safe_tree.edit(
            start_byte=edit_dict["start_byte"],
            old_end_byte=edit_dict["old_end_byte"],
            new_end_byte=edit_dict["new_end_byte"],
            start_point=edit_dict["start_point"],
            old_end_point=edit_dict["old_end_point"],
            new_end_point=edit_dict["new_end_point"],
        )
    else:
        # Using individual parameters
        # Tree-sitter expects non-None values for these parameters
        _old_end_byte = 0 if old_end_byte is None else old_end_byte
        _new_end_byte = 0 if new_end_byte is None else new_end_byte
        _start_point = (0, 0) if start_point is None else start_point
        _old_end_point = (0, 0) if old_end_point is None else old_end_point
        _new_end_point = (0, 0) if new_end_point is None else new_end_point

        safe_tree.edit(
            start_byte=edit_dict_or_start_byte,
            old_end_byte=_old_end_byte,
            new_end_byte=_new_end_byte,
            start_point=_start_point,
            old_end_point=_old_end_point,
            new_end_point=_new_end_point,
        )
    return safe_tree


def get_changed_ranges(old_tree: Tree, new_tree: Tree) -> list[tuple[int, int]]:
    """Get changed ranges between two syntax trees.

    Args:
        old_tree: Old syntax tree
        new_tree: New syntax tree

    Returns:
        List of changed ranges as tuples of (start_byte, end_byte)
    """
    safe_old_tree = ensure_tree(old_tree)
    safe_new_tree = ensure_tree(new_tree)

    # The Python binding may not expose changed_ranges. Compare the two
    # roots instead of asking the old tree for its changed ranges.

    # For now, return a basic comparison at the root level
    old_root = safe_old_tree.root_node
    new_root = safe_new_tree.root_node

    if old_root.start_byte != new_root.start_byte or old_root.end_byte != new_root.end_byte:
        # Return the entire tree as changed
        return [(new_root.start_byte, new_root.end_byte)]

    return []


def parse_file(file_path: Path, parser_or_language: Parser | str, registry: Any | None = None) -> tuple[Tree, bytes]:
    """Parse a file using a configured parser.

    Args:
        file_path: Path to the file
        parser_or_language: Configured Parser object or language string
        registry: Language registry (needed for compatibility with old API)

    Returns:
        Tuple of (Tree, source_bytes)
    """
    source_bytes = read_binary_file(file_path)

    # If we received a parser directly, use it
    if hasattr(parser_or_language, "parse"):
        parser = parser_or_language
        tree = parse_source(source_bytes, parser)
        return cast("tuple[Tree, bytes]", (tree, source_bytes))

    # If we received a language string and registry, get the parser
    if isinstance(parser_or_language, str) and registry is not None:
        try:
            parser = registry.get_parser(parser_or_language)
            tree = parse_source(source_bytes, parser)
            return cast("tuple[Tree, bytes]", (tree, source_bytes))
        except Exception as e:
            raise ValueError(f"Could not get parser for language '{parser_or_language}': {e}") from e

    # Invalid parameters
    raise ValueError(f"Invalid parser or language: {parser_or_language}")


def get_node_text(node: Node, source_bytes: bytes, decode: bool = True) -> str | bytes:
    """Safely get text for a node from source bytes.

    Args:
        node: Node object
        source_bytes: Source code as bytes
        decode: Whether to decode bytes to string (default: True)

    Returns:
        Text for the node as string or bytes
    """
    safe_node = ensure_node(node)
    try:
        node_bytes = source_bytes[safe_node.start_byte : safe_node.end_byte]
        if decode:
            try:
                return node_bytes.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                return str(node_bytes)
        return node_bytes
    except (IndexError, ValueError):
        return "" if decode else b""


def walk_tree(node: Node) -> TreeCursor:
    """Get a cursor for walking a tree from a node.

    Args:
        node: Node to start from

    Returns:
        Tree cursor
    """
    safe_node = ensure_node(node)
    cursor = safe_node.walk()
    return ensure_cursor(cursor)


def cursor_walk_tree(node: Node, visit_fn: Callable[[Node | None, str | None, int], bool]) -> None:
    """Walk a tree using cursor for efficiency.

    Args:
        node: Root node to start from
        visit_fn: Function called for each node, receives (node, field_name, depth)
                  Return True to continue traversal, False to skip children
    """
    cursor = walk_tree(node)
    field_name = None
    depth = 0

    if not visit_fn(cursor.node, field_name, depth):
        return

    if cursor.goto_first_child():
        depth += 1

        while True:
            # Get field name if available
            field_name = None
            if cursor.node and cursor.node.parent:
                parent_field_names = getattr(cursor.node.parent, "children_by_field_name", {})
                if hasattr(parent_field_names, "items"):
                    for name, nodes in parent_field_names.items():
                        if cursor.node in nodes:
                            field_name = name
                            break

            if visit_fn(cursor.node, field_name, depth) and cursor.goto_first_child():
                depth += 1
                continue

            # No children or children skipped, try siblings
            if cursor.goto_next_sibling():
                continue

            # No more siblings, go up
            while depth > 0:
                cursor.goto_parent()
                depth -= 1

                if cursor.goto_next_sibling():
                    break

            # If we've returned to the root, we're done
            if depth == 0:
                break


def collect_with_cursor(
    node: Node,
    collector_fn: Callable[[Node | None, str | None, int], T | None],
) -> list[T]:
    """Collect items from a tree using cursor traversal.

    Args:
        node: Root node to start from
        collector_fn: Function that returns an item to collect or None to skip
                     Receives (node, field_name, depth)

    Returns:
        List of collected items
    """
    items: list[T] = []

    def visit(node: Node | None, field_name: str | None, depth: int) -> bool:
        if node is None:
            return False
        item = collector_fn(node, field_name, depth)
        if item is not None:
            items.append(item)
        return True  # Continue traversal

    cursor_walk_tree(node, visit)
    return items


def find_nodes_by_type(root_node: Node, node_type: str) -> list[Node]:
    """Find all nodes of a specific type in a tree.

    Args:
        root_node: Root node to search from
        node_type: Type of node to find

    Returns:
        List of matching nodes
    """

    def collector(node: Node | None, _field_name: str | None, _depth: int) -> Node | None:
        if node is None:
            return None
        if node.type == node_type:
            return node
        return None

    return collect_with_cursor(root_node, collector)


def get_node_descendants(node: Node | None, max_depth: int | None = None) -> list[Node]:
    """Get all descendants of a node.

    Args:
        node: Node to get descendants for
        max_depth: Maximum depth to traverse

    Returns:
        List of descendant nodes
    """
    descendants: list[Node] = []

    if node is None:
        return descendants

    def visit(node: Node | None, _field_name: str | None, depth: int) -> bool:
        if node is None:
            return False
        if max_depth is not None and depth > max_depth:
            return False  # Skip children

        if depth > 0:  # Skip the root node
            descendants.append(node)

        return True  # Continue traversal

    cursor_walk_tree(node, visit)
    return descendants


def parse_with_cached_tree(
    file_path: Path, language: str, language_obj: Language, tree_cache: Any = None
) -> tuple[Tree, bytes]:
    """Parse a file with tree caching.

    Args:
        file_path: Path to the file
        language: Language identifier
        language_obj: Language object
        tree_cache: Tree cache instance (optional, falls back to container if not provided)

    Returns:
        Tuple of (Tree, source_bytes)
    """
    # Get tree cache from container if not provided
    if tree_cache is None:
        from ..di import get_container

        tree_cache = get_container().tree_cache

    # Check if we have a cached tree
    cached = tree_cache.get(file_path, language)
    if cached:
        tree, source_bytes = cached
        # Ensure tree is properly typed
        return ensure_tree(tree), source_bytes

    # Parse the file using our own parser to avoid registry complications
    parser = create_parser(language_obj)
    source_bytes = read_binary_file(file_path)
    tree = parse_source(source_bytes, parser)

    # Cache the tree
    tree_cache.put(file_path, language, tree, source_bytes)

    return cast("tuple[Tree, bytes]", (tree, source_bytes))


def update_cached_tree(
    file_path: Path,
    language: str,
    language_obj: Language,
    start_byte: int,
    old_end_byte: int,
    new_end_byte: int,
    start_point: tuple[int, int],
    old_end_point: tuple[int, int],
    new_end_point: tuple[int, int],
    tree_cache: Any = None,
) -> tuple[Tree, bytes] | None:
    """Update a cached tree with edit operation.

    Args:
        file_path: Path to the source file
        language: Language identifier
        language_obj: Language object
        start_byte: Start byte of the edit
        old_end_byte: End byte of the replaced range
        new_end_byte: End byte of the replacement
        start_point: Start row and column of the edit
        old_end_point: End row and column of the replaced range
        new_end_point: End row and column of the replacement
        tree_cache: Tree cache instance (optional, falls back to container if not provided)

    Returns:
        Updated (tree, source_bytes) if successful, None otherwise
    """
    # Get tree cache from container if not provided
    if tree_cache is None:
        from ..di import get_container

        tree_cache = get_container().tree_cache

    # Check if we have a cached tree
    cached = tree_cache.get(file_path, language)
    if not cached:
        return None

    old_tree, _old_source = cached

    try:
        # Apply edit to the tree
        edit_dict = {
            "start_byte": start_byte,
            "old_end_byte": old_end_byte,
            "new_end_byte": new_end_byte,
            "start_point": start_point,
            "old_end_point": old_end_point,
            "new_end_point": new_end_point,
        }
        edit_tree(old_tree, edit_dict)

        # Read updated source
        with open(file_path, "rb") as f:
            new_source = f.read()

        # Parse incrementally
        parser = create_parser(language_obj)
        new_tree = parse_source_incremental(new_source, old_tree, parser)

        # Update cache
        tree_cache.put(file_path, language, new_tree, new_source)

        return cast("tuple[Tree, bytes]", (new_tree, new_source))
    except Exception:
        # If incremental parsing fails, fall back to full parse
        return parse_with_cached_tree(file_path, language, language_obj, tree_cache=tree_cache)


# Additional helper functions required by tests


def create_edit(
    start_byte: int,
    old_end_byte: int,
    new_end_byte: int,
    start_point: tuple[int, int],
    old_end_point: tuple[int, int],
    new_end_point: tuple[int, int],
) -> dict[str, Any]:
    """Create an edit dictionary for modifying trees.

    Args:
        start_byte: Start byte of the edit
        old_end_byte: End byte of the old text
        new_end_byte: End byte of the new text
        start_point: Start point (row, column) of the edit
        old_end_point: End point of the old text
        new_end_point: End point of the new text

    Returns:
        Edit dictionary with all parameters
    """
    return {
        "start_byte": start_byte,
        "old_end_byte": old_end_byte,
        "new_end_byte": new_end_byte,
        "start_point": start_point,
        "old_end_point": old_end_point,
        "new_end_point": new_end_point,
    }


def parse_file_with_detection(file_path: Path, language: str | None, registry: Any) -> tuple[Tree, bytes]:
    """Parse a file with language detection.

    Args:
        file_path: Path to the file
        language: Optional language identifier (detected from extension if None)
        registry: Language registry for getting parsers

    Returns:
        Tuple of (Tree, source_bytes)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if language is None:
        language = registry.language_for_file(str(file_path))
        if not language:
            raise ValueError(f"Could not detect language for file: {file_path}")

    if language is None:
        raise ValueError(f"Language required for parsing file: {file_path}")

    # Get parser for language
    try:
        parser = registry.get_parser(language)
    except Exception as e:
        raise ValueError(f"Could not get parser for language '{language}': {e}") from e

    # Read file and parse
    source_bytes = read_binary_file(file_path)
    tree = parse_source(source_bytes, parser)

    return cast("tuple[Tree, bytes]", (tree, source_bytes))


def parse_file_incremental(file_path: Path, old_tree: Tree, language: str, registry: Any) -> tuple[Tree, bytes]:
    """Parse a file incrementally using a previous tree.

    Args:
        file_path: Path to the file
        old_tree: Previous tree for incremental parsing
        language: Language identifier
        registry: Language registry for getting parsers

    Returns:
        Tuple of (Tree, source_bytes)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Get parser for language
    parser = registry.get_parser(language)

    # Read file and parse incrementally
    source_bytes = read_binary_file(file_path)
    tree = parse_source_incremental(source_bytes, old_tree, parser)

    return cast("tuple[Tree, bytes]", (tree, source_bytes))


def get_node_with_text(node: Node, source_bytes: bytes, text: bytes) -> Node | None:
    """Find a node containing specific text.

    Args:
        node: Root node to search from
        source_bytes: Source code as bytes
        text: Text to search for (as bytes)

    Returns:
        Node containing the text or None if not found
    """
    # Ensure we get bytes back from get_node_text
    if text in get_node_text(node, source_bytes, decode=False):
        # Check if any child contains the text
        for child in node.children:
            result = get_node_with_text(child, source_bytes, text)
            if result is not None:
                return result
        # If no child contains the text, return this node
        return node
    return None


def is_node_inside(pos_or_node: Node | tuple[int, int], container_node: Node) -> bool:
    """Check if a node or position is inside another node.

    Args:
        pos_or_node: Node or position (row, column) to check
        container_node: Node that might contain the other node/position

    Returns:
        True if the node/position is inside the container node, False otherwise
    """
    # Handle position case
    if isinstance(pos_or_node, tuple):
        row, column = pos_or_node
        start_row, start_col = container_node.start_point
        end_row, end_col = container_node.end_point

        # Check if position is within node boundaries
        if row < start_row or row > end_row:
            return False
        if row == start_row and column < start_col:
            return False
        return not (row == end_row and column > end_col)

    # Handle node case
    node = pos_or_node
    if node == container_node:
        return True  # Node is inside itself

    # Check if node's boundaries are within container's boundaries
    return is_node_inside(node.start_point, container_node) and is_node_inside(node.end_point, container_node)


def find_all_descendants(node: Node, max_depth: int | None = None) -> list[Node]:
    """Find all descendant nodes of a given node.

    Args:
        node: Root node to search from
        max_depth: Maximum depth to search

    Returns:
        List of all descendant nodes
    """
    return get_node_descendants(node, max_depth)
