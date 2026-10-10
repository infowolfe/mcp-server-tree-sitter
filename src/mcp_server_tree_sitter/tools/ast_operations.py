"""AST operation tools for MCP server."""

import logging
from typing import Any, Dict, Optional

from ..exceptions import FileAccessError, ParsingError
from ..language.scope_types import kind_for_node_type
from ..models.ast import node_to_dict
from ..utils.file_io import read_binary_file
from ..utils.security import validate_file_access
from ..utils.tree_sitter_helpers import (
    get_node_text,
    parse_source,
)

logger = logging.getLogger(__name__)


def get_file_ast(
    project: Any,
    path: str,
    language_registry: Any,
    tree_cache: Any,
    max_depth: Optional[int] = None,
    include_text: bool = True,
) -> Dict[str, Any]:
    """
    Get the AST for a file.

    Args:
        project: Project object
        path: File path (relative to project root)
        language_registry: Language registry
        tree_cache: Tree cache instance
        max_depth: Maximum depth to traverse the tree
        include_text: Whether to include node text

    Returns:
        AST as a nested dictionary

    Raises:
        FileAccessError: If file access fails
        ParsingError: If parsing fails
    """
    abs_path = project.get_file_path(path)

    try:
        validate_file_access(abs_path, project.root_path)
    except Exception as e:
        raise FileAccessError(f"Access denied: {e}") from e

    language = language_registry.language_for_file(path)
    if not language:
        raise ParsingError(f"Could not detect language for {path}")

    tree, source_bytes = parse_file(abs_path, language, language_registry, tree_cache)

    return {
        "file": path,
        "language": language,
        "tree": node_to_dict(
            tree.root_node,
            source_bytes,
            include_children=True,
            include_text=include_text,
            max_depth=max_depth if max_depth is not None else 5,
        ),
    }


def parse_file(file_path: Any, language: str, language_registry: Any, tree_cache: Any) -> tuple[Any, bytes]:
    """
    Parse a file using tree-sitter.

    Args:
        file_path: Path to file
        language: Language identifier
        language_registry: Language registry
        tree_cache: Tree cache instance

    Returns:
        (Tree, source_bytes) tuple

    Raises:
        ParsingError: If parsing fails
    """
    # Always check the cache first, even if caching is disabled
    # This ensures cache misses are tracked correctly in tests
    cached = tree_cache.get(file_path, language)
    if cached:
        tree, bytes_data = cached
        return tree, bytes_data

    try:
        # Parse the file using helper
        parser = language_registry.get_parser(language)
        # Use source directly with parser to avoid parser vs. language confusion
        source_bytes = read_binary_file(file_path)
        tree = parse_source(source_bytes, parser)
        result_tuple = (tree, source_bytes)

        # Cache the tree only if caching is enabled
        is_cache_enabled = False
        try:
            # Get cache enabled state from tree_cache
            is_cache_enabled = tree_cache._is_cache_enabled()
        except Exception:
            # Fallback to instance value if method not available
            is_cache_enabled = getattr(tree_cache, "enabled", False)

        # Store in cache only if enabled
        if is_cache_enabled:
            tree_cache.put(file_path, language, tree, source_bytes)

        return result_tuple
    except Exception as e:
        raise ParsingError(f"Error parsing {file_path}: {e}") from e


def find_node_at_position(root_node: Any, row: int, column: int) -> Optional[Any]:
    """
    Find the most specific node at a given position.

    Args:
        root_node: Root node to search from
        row: Row (line) number, 0-based
        column: Column number, 0-based

    Returns:
        Node at position or None if not found
    """
    from ..models.ast import find_node_at_position as find_node

    return find_node(root_node, row, column)


_C_NAME_TYPES = {"identifier", "field_identifier", "destructor_name", "operator_name"}
_CPP_CLASS_TYPES = {"class_specifier", "struct_specifier"}
_C_DECLARATOR_WRAPPERS = {
    "function_declarator",
    "pointer_declarator",
    "reference_declarator",
    "parenthesized_declarator",
}
_DART_SIGNATURES = {"function_signature", "method_signature"}
_DART_BODY_ANCHORS = _DART_SIGNATURES | {
    "constructor_signature",
    "getter_signature",
    "setter_signature",
}
_CPP_TEMPLATE_SCOPES = ("function_definition", "class_specifier", "struct_specifier")


def get_enclosing_scope(
    project: Any,
    path: str,
    row: int,
    column: int,
    language_registry: Any,
    tree_cache: Any,
    max_lines: int = 200,
) -> Optional[Dict[str, Any]]:
    """Return the nearest function, method, class, or module around a cursor.

    Positions are 0-based, matching get_node_at_position. File access is
    checked before the tree cache and before parse. A cursor on the tree's
    exclusive end point is the module. A cursor past the tree is None.

    Scope tables are adapted from Carlos Faria (cx-carlos-faria, CxMaster).

    Args:
        project: Project object
        path: File path relative to the project root
        row: Line number, 0-based
        column: Column number, 0-based byte offset
        language_registry: Language registry
        tree_cache: Tree cache instance
        max_lines: Maximum lines of scope text. 0 means no limit.

    Returns:
        Scope payload, or None when the position is outside the file

    Raises:
        FileAccessError: If file access fails
        ParsingError: If the language is unknown or parsing fails
    """
    abs_path = project.get_file_path(path)

    try:
        validate_file_access(abs_path, project.root_path)
    except Exception as e:
        raise FileAccessError(f"Access denied: {e}") from e

    language = language_registry.language_for_file(path)
    if not language:
        raise ParsingError(f"Could not detect language for {path}")

    tree, source_bytes = parse_file(abs_path, language, language_registry, tree_cache)
    root = tree.root_node
    here = (int(row), int(column))
    start = _point_tuple(root.start_point)
    end = _point_tuple(root.end_point)

    if _point_before(here, start) or _point_before(end, here):
        return None

    # end_point is exclusive, so a cursor sitting on it is still in the file.
    if here == end:
        return _scope_payload(root, "module", language, source_bytes, path, max_lines)

    node = _node_at_cursor(root, here, end)
    if node is None:
        return None

    scope_node, kind = _nearest_scope(language, node, root)
    return _scope_payload(scope_node, kind, language, source_bytes, path, max_lines)


def _node_at_cursor(root: Any, here: tuple[int, int], end: tuple[int, int]) -> Optional[Any]:
    """Return the node that starts at the cursor when a zero-width hit is an ancestor.

    Some grammars answer descendant_for_point_range(point, point) with the
    root even though a declaration starts on that point. A one-column range
    returns the node that actually starts there.
    """
    node = find_node_at_position(root, here[0], here[1])
    if node is None or _point_tuple(node.start_point) == here:
        return node
    wider_end = (here[0], here[1] + 1)
    if _point_before(end, wider_end):
        wider_end = end
    if wider_end == here or _point_before(wider_end, here):
        return node
    wider = root.descendant_for_point_range(here, wider_end)
    if wider is not None and _point_tuple(wider.start_point) == here:
        return wider
    return node


def _point_tuple(point: Any) -> tuple[int, int]:
    """Normalize a tree-sitter point to a pair of ints.

    Point equality against a raw tuple can fail even when ordering works.
    """
    return (int(point[0]), int(point[1]))


def _point_before(left: tuple[int, int], right: tuple[int, int]) -> bool:
    if left[0] != right[0]:
        return left[0] < right[0]
    return left[1] < right[1]


def _nearest_scope(language: str, node: Any, root: Any) -> tuple[Any, str]:
    current = node
    while current is not None:
        # The decorator is outside the function node. A cursor on it still
        # belongs to the definition that wrapper carries.
        if str(current.type) == "decorated_definition":
            definition = current.child_by_field_name("definition")
            if definition is not None:
                kind = _scope_kind(language, definition)
                if kind is not None:
                    return definition, kind
        # The friend keyword sits outside the function node.
        if str(current.type) == "friend_declaration":
            definition = _child_of_type(current, "function_definition")
            if definition is not None:
                kind = _scope_kind(language, definition)
                if kind is not None:
                    return definition, kind
        # template<...> is a wrapper. The declaration it applies to is the scope.
        if str(current.type) == "template_declaration":
            for wrapped in _CPP_TEMPLATE_SCOPES:
                definition = _child_of_type(current, wrapped)
                if definition is None:
                    continue
                kind = _scope_kind(language, definition)
                if kind is not None:
                    return definition, kind
        # A Dart signature does not contain its body. The body is the next sibling.
        if language == "dart" and str(current.type) in _DART_BODY_ANCHORS:
            body = _dart_body_after(current)
            if body is not None:
                kind = _scope_kind(language, body)
                if kind is not None:
                    return body, kind
        kind = _scope_kind(language, current)
        if kind is not None:
            return current, kind
        current = current.parent
    return root, "module"


def _scope_kind(language: str, node: Any) -> Optional[str]:
    node_type = str(node.type)
    if language == "go" and node_type == "type_spec" and not _is_go_struct_spec(node):
        return None

    if language == "julia" and node_type == "assignment":
        # f(y) = y + 1 is an assignment, not a function_definition.
        if _julia_short_function(node):
            return "function"
        return None

    kind = kind_for_node_type(language, node_type)
    if kind is None:
        return None
    if language == "python" and node_type == "function_definition":
        return _python_function_kind(node)
    if language == "cpp" and node_type == "function_definition" and _is_cpp_method(node):
        return "method"
    return kind


def _python_function_kind(node: Any) -> str:
    """Method only when the nearest enclosing scope is a class.

    A function nested in a method stays a function. block and
    decorated_definition are not scopes, so they are skipped with every
    other non-scope wrapper.
    """
    parent = node.parent
    while parent is not None:
        if kind_for_node_type("python", str(parent.type)) is not None:
            if parent.type == "class_definition":
                return "method"
            return "function"
        parent = parent.parent
    return "function"


def _is_go_struct_spec(node: Any) -> bool:
    """A grouped type declaration is a scope only for its struct specs."""
    type_node = node.child_by_field_name("type")
    if type_node is not None:
        return bool(type_node.type == "struct_type")
    for index in range(node.child_count):
        child = node.child(index)
        if child is not None and child.type == "struct_type":
            return True
    return False


def _is_cpp_method(node: Any) -> bool:
    """In-class functions are methods. A friend defined in the class is not.

    An out-of-line ``C::out`` is a method when ``C`` is a class or struct in
    this file. ``ns::h`` stays a function when ``ns`` is not.
    """
    if _defined_inside_class(node):
        return True
    return _qualified_scope_matches_class(node)


def _defined_inside_class(node: Any) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "friend_declaration":
            return False
        if parent.type in _CPP_CLASS_TYPES:
            return True
        parent = parent.parent
    return False


def _qualified_scope_matches_class(node: Any) -> bool:
    declarator = node.child_by_field_name("declarator")
    qualified = _find_node_type(declarator, "qualified_identifier")
    if qualified is None:
        return False
    scope = qualified.child_by_field_name("scope")
    if scope is None or not scope.text:
        return False
    root = node
    while root.parent is not None:
        root = root.parent
    return bytes(scope.text) in _class_and_struct_names(root)


def _class_and_struct_names(root: Any) -> set[bytes]:
    names: set[bytes] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current.type in _CPP_CLASS_TYPES:
            name = current.child_by_field_name("name")
            if name is not None and name.text:
                names.add(bytes(name.text))
        for index in range(current.child_count):
            child = current.child(index)
            if child is not None:
                stack.append(child)
    return names


def _child_of_type(node: Any, node_type: str) -> Optional[Any]:
    for index in range(node.child_count):
        child = node.child(index)
        if child is not None and child.type == node_type:
            return child
    return None


def _find_node_type(node: Any, node_type: str) -> Optional[Any]:
    if node is None:
        return None
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == node_type:
            return current
        for index in range(current.child_count):
            child = current.child(index)
            if child is not None:
                stack.append(child)
    return None


def _declarator_name_node(node: Any) -> Optional[Any]:
    """Walk function, pointer, reference, and parenthesized declarators.

    A reference_declarator in the C++ grammar has no declarator field. The
    inner function_declarator is an unnamed child, so follow that too.
    """
    current = node.child_by_field_name("declarator")
    for _ in range(16):
        if current is None:
            return None
        if current.type in _C_NAME_TYPES:
            return current
        nxt = current.child_by_field_name("declarator")
        if nxt is None:
            nxt = _declarator_wrapper_child(current)
        if nxt is not None:
            current = nxt
            continue
        for index in range(current.child_count):
            child = current.child(index)
            if child is not None and child.type in _C_NAME_TYPES:
                return child
        return None
    return None


def _declarator_wrapper_child(node: Any) -> Optional[Any]:
    for index in range(node.child_count):
        child = node.child(index)
        if child is not None and child.type in _C_DECLARATOR_WRAPPERS:
            return child
    return None


def _scope_payload(
    node: Any,
    kind: str,
    language: str,
    source_bytes: bytes,
    path: str,
    max_lines: int,
) -> Dict[str, Any]:
    text, truncated = _truncate_lines(_node_text(node, source_bytes), max_lines)
    start = _point_tuple(node.start_point)
    end = _point_tuple(node.end_point)
    return {
        "kind": kind,
        "type": node.type,
        "name": _scope_name(language, node, source_bytes),
        "text": text,
        "truncated": truncated,
        "start": {"row": start[0], "column": start[1]},
        "end": {"row": end[0], "column": end[1]},
        "file": path,
    }


def _scope_name(language: str, node: Any, source_bytes: bytes) -> Optional[str]:
    if language in ("c", "cpp") and node.type == "function_definition":
        name_node = _declarator_name_node(node)
        if name_node is None:
            return None
        return _node_text(name_node, source_bytes) or None

    if language == "kotlin":
        kotlin_name = _kotlin_name(node, source_bytes)
        if kotlin_name is not None:
            return kotlin_name

    if language == "dart" and node.type == "function_body":
        dart_name = _dart_function_name(node, source_bytes)
        if dart_name is not None:
            return dart_name

    if language == "swift" and node.type == "computed_property":
        property_name = _swift_property_name(node, source_bytes)
        if property_name is not None:
            return property_name

    if language == "julia":
        julia_name = _julia_name(node, source_bytes)
        if julia_name is not None:
            return julia_name

    if language == "rust" and node.type == "impl_item":
        # impl S stores the type in `type`. impl Trait for S does too.
        named = node.child_by_field_name("name") or node.child_by_field_name("type")
        if named is not None:
            return _node_text(named, source_bytes) or None

    named = node.child_by_field_name("name")
    if named is None:
        return None
    return _node_text(named, source_bytes) or None


def _kotlin_name(node: Any, source_bytes: bytes) -> Optional[str]:
    """Kotlin declarations have no name field."""
    if node.type in ("getter", "setter"):
        # The getter is the next sibling of the property, not a child of it.
        return _preceding_property_name(node, source_bytes)
    if node.type == "function_declaration":
        wanted = "simple_identifier"
    elif node.type == "class_declaration":
        wanted = "type_identifier"
    else:
        return None
    for index in range(node.child_count):
        child = node.child(index)
        if child is not None and child.type == wanted:
            return _node_text(child, source_bytes) or None
    return None


def _preceding_property_name(node: Any, source_bytes: bytes) -> Optional[str]:
    parent = node.parent
    if parent is None:
        return None
    previous = None
    for index in range(parent.child_count):
        child = parent.child(index)
        if child is None:
            continue
        if child.start_byte == node.start_byte and child.type == node.type:
            break
        if child.type == "property_declaration":
            previous = child
    if previous is None:
        return None
    ident = _first_descendant(previous, "simple_identifier")
    if ident is None:
        return None
    return _node_text(ident, source_bytes) or None


def _swift_property_name(node: Any, source_bytes: bytes) -> Optional[str]:
    parent = node.parent
    if parent is None or parent.type != "property_declaration":
        return None
    named = parent.child_by_field_name("name")
    if named is None:
        return None
    return _node_text(named, source_bytes) or None


def _julia_short_function(node: Any) -> bool:
    for index in range(node.child_count):
        child = node.child(index)
        if child is None:
            continue
        if child.type in ("=", "operator"):
            return False
        if child.type == "call_expression":
            return True
    return False


def _julia_name(node: Any, source_bytes: bytes) -> Optional[str]:
    if node.type == "function_definition":
        signature = _child_of_type(node, "signature")
        call = _child_of_type(signature, "call_expression") if signature is not None else None
        return _call_callee_name(call, source_bytes)
    if node.type == "struct_definition":
        head = _child_of_type(node, "type_head")
        ident = _child_of_type(head, "identifier") if head is not None else None
        if ident is None:
            return None
        return _node_text(ident, source_bytes) or None
    if node.type == "assignment" and _julia_short_function(node):
        return _call_callee_name(_child_of_type(node, "call_expression"), source_bytes)
    return None


def _call_callee_name(call: Any, source_bytes: bytes) -> Optional[str]:
    """The callee is the first identifier. Later identifiers are arguments."""
    if call is None:
        return None
    for index in range(call.child_count):
        child = call.child(index)
        if child is not None and child.type == "identifier":
            return _node_text(child, source_bytes) or None
    return None


def _first_descendant(node: Any, node_type: str) -> Optional[Any]:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == node_type:
            return current
        children = []
        for index in range(current.child_count):
            child = current.child(index)
            if child is not None:
                children.append(child)
        stack.extend(reversed(children))
    return None


def _dart_body_after(node: Any) -> Optional[Any]:
    current = node
    while current is not None and str(current.type) in _DART_BODY_ANCHORS:
        parent = current.parent
        if parent is None:
            return None
        seen = False
        for index in range(parent.child_count):
            child = parent.child(index)
            if child is None:
                continue
            if not seen:
                if child.start_byte == current.start_byte and child.type == current.type:
                    seen = True
                continue
            if child.type == "function_body":
                return child
            if str(child.type) in _DART_BODY_ANCHORS:
                break
        if str(parent.type) in _DART_BODY_ANCHORS:
            current = parent
            continue
        return None
    return None


def _dart_function_name(node: Any, source_bytes: bytes) -> Optional[str]:
    """The signature is the previous sibling, not a child of function_body."""
    parent = node.parent
    if parent is None:
        return None

    signature = None
    for index in range(parent.child_count):
        child = parent.child(index)
        if child is None:
            continue
        if child.start_byte == node.start_byte and child.type == node.type:
            break
        if child.type in _DART_SIGNATURES:
            signature = child
    if signature is None:
        return None

    named = signature.child_by_field_name("name")
    if named is not None:
        return _node_text(named, source_bytes) or None
    for index in range(signature.child_count):
        child = signature.child(index)
        if child is None:
            continue
        if child.type == "function_signature":
            named = child.child_by_field_name("name")
            if named is not None:
                return _node_text(named, source_bytes) or None
        elif child.type == "constructor_signature":
            return _dart_constructor_name(child, source_bytes)
        elif child.type in ("getter_signature", "setter_signature"):
            named = child.child_by_field_name("name")
            if named is not None:
                return _node_text(named, source_bytes) or None
    return None


def _dart_constructor_name(node: Any, source_bytes: bytes) -> Optional[str]:
    """Join C and C.named. The name field alone is only the type identifier."""
    parts: list[str] = []
    for index in range(node.child_count):
        child = node.child(index)
        if child is None:
            continue
        if child.type == "identifier":
            parts.append(_node_text(child, source_bytes))
        elif child.type == ".":
            parts.append(".")
        elif child.type == "formal_parameter_list":
            break
    if not parts:
        return None
    return "".join(parts) or None


def _node_text(node: Any, source_bytes: bytes) -> str:
    text = get_node_text(node, source_bytes, decode=True)
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text)


def _truncate_lines(text: str, max_lines: int) -> tuple[str, bool]:
    """Cut text to max_lines. 0 keeps the whole text."""
    if max_lines == 0:
        return text, False
    lines = text.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return text, False
    return "".join(lines[:max_lines]), True
