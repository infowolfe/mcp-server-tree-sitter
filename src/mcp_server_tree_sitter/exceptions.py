"""Exception classes for mcp-server-tree-sitter."""


class MCPTreeSitterError(Exception):
    """Base exception for mcp-server-tree-sitter."""


class LanguageError(MCPTreeSitterError):
    """Errors related to tree-sitter languages."""


class LanguageNotFoundError(LanguageError):
    """Raised when a language parser is not available."""


class LanguageInstallError(LanguageError):
    """Raised when language installation fails."""


class ParsingError(MCPTreeSitterError):
    """Errors during parsing."""


class ProjectError(MCPTreeSitterError):
    """Errors related to project management."""


class FileAccessError(MCPTreeSitterError):
    """Errors accessing project files."""


class QueryError(MCPTreeSitterError):
    """Errors related to tree-sitter queries."""


class SecurityError(MCPTreeSitterError):
    """Security-related errors."""


class CacheError(MCPTreeSitterError):
    """Errors related to caching."""
