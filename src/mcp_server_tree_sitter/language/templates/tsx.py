"""Query templates for TSX.

The grammar id is tsx, separate from typescript, so a JSX tag is not an ERROR
node. The mapping follows ajisulist's TSX work.
"""

from .typescript import TEMPLATES as _TYPESCRIPT

TEMPLATES = {
    **_TYPESCRIPT,
    "jsx": """
        (jsx_self_closing_element
            name: (identifier) @jsx.name) @jsx

        (jsx_opening_element
            name: (identifier) @jsx.name) @jsx

        (jsx_element) @jsx
    """,
}
