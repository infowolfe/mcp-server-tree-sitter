"""Language registry for tree-sitter languages."""

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from tree_sitter_language_pack import get_language as pack_get_language
from tree_sitter_language_pack import get_parser as pack_get_parser

from ..config import ServerConfig

# Import parser_cache functions inside methods to avoid circular imports.
# The container passes prefer_installed_grammars in. Do not call get_container here.
from ..exceptions import LanguageNotFoundError
from ..utils.tree_sitter_helpers import create_parser
from ..utils.tree_sitter_types import (
    Language,
    Parser,
    ensure_language,
)
from . import installed as installed_grammars

logger = logging.getLogger(__name__)


class LanguageRegistry:
    """Manages tree-sitter language parsers."""

    def __init__(self, prefer_installed_grammars: bool = False) -> None:
        """Initialize the registry.

        prefer_installed_grammars is read once at startup. Changing the config
        later does not drop cached languages.
        """
        self._lock = threading.RLock()
        self.prefer_installed_grammars = prefer_installed_grammars
        self.languages: Dict[str, Language] = {}
        self._origins: Dict[str, str] = {}
        self._grammars: Optional[Dict[str, installed_grammars.InstalledGrammar]] = None
        self._display_names: Dict[str, str] = {}
        self._language_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "jsx": "javascript",
            "tsx": "typescript",
            "rb": "ruby",
            "rs": "rust",
            "go": "go",
            "java": "java",
            "c": "c",
            "cpp": "cpp",
            "cc": "cpp",
            "h": "c",
            "hpp": "cpp",
            "cs": "csharp",
            "php": "php",
            "scala": "scala",
            "swift": "swift",
            "dart": "dart",
            "kt": "kotlin",
            "jl": "julia",
            "lua": "lua",
            "hs": "haskell",
            "ml": "ocaml",
            "sh": "bash",
            "yaml": "yaml",
            "yml": "yaml",
            "json": "json",
            "md": "markdown",
            "html": "html",
            "css": "css",
            "scss": "scss",
            "sass": "scss",
            "sql": "sql",
            "proto": "proto",
            "elm": "elm",
            "clj": "clojure",
            "ex": "elixir",
            "exs": "elixir",
        }

    def preload_languages(self, config: ServerConfig) -> None:
        """
        Pre-load preferred languages from configuration.

        This method should be called after the dependency container is fully
        initialized to avoid circular import issues.

        Args:
            config: Server configuration containing language preferences
        """
        for lang in config.language.preferred_languages:
            try:
                self.get_language(lang)
            except Exception as e:
                logger.warning(f"Failed to pre-load language {lang}: {e}")

    def language_for_file(self, file_path: str) -> Optional[str]:
        """
        Detect language from file extension.

        Args:
            file_path: Path to the file

        Returns:
            Language identifier or None if unknown
        """
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapped = self._language_map.get(ext)
        if mapped:
            return mapped
        # A new installed id is reachable as .<id>. Ids already in the map
        # keep their existing extensions and do not gain another one.
        self._ensure_discovered()
        assert self._grammars is not None
        if ext in self._grammars and ext not in self._language_map.values():
            return ext
        return None

    def list_available_languages(self) -> List[str]:
        """
        List languages that are available via tree-sitter-language-pack.

        Returns:
            List of available language identifiers
        """
        # Start with loaded languages
        available = set(self.languages.keys())

        # Add all mappable languages from our extension map
        # These correspond to the languages available in tree-sitter-language-pack
        available.update(set(self._language_map.values()))
        self._ensure_discovered()
        assert self._grammars is not None
        available.update(self._grammars)

        # Add frequently used languages that might not be in the map
        common_languages = [
            "python",
            "javascript",
            "typescript",
            "java",
            "c",
            "cpp",
            "go",
            "rust",
            "ruby",
            "php",
            "swift",
            "kotlin",
            "scala",
            "bash",
            "html",
            "css",
            "json",
            "yaml",
            "markdown",
            "csharp",
            "objective_c",
            "xml",
        ]
        available.update(common_languages)

        # Return as a sorted list
        return sorted(available)

    def list_installable_languages(self) -> List[Tuple[str, str]]:
        """
        List languages that can be installed.
        With tree-sitter-language-pack, no additional installation is needed.

        Returns:
            Empty list (all languages are available via language-pack)
        """
        return []

    def is_language_available(self, language_name: str) -> bool:
        """
        Check if a language is available in tree-sitter-language-pack.

        Args:
            language_name: Language identifier

        Returns:
            True if language is available
        """
        try:
            self.get_language(language_name)
            return True
        except Exception:
            return False

    def get_language_display_name(self, language_name: str) -> str:
        """Return the distribution summary for an installed grammar, or the id."""
        self._ensure_discovered()
        return self._display_names.get(language_name, language_name)

    def _ensure_discovered(self) -> None:
        if self._grammars is not None:
            return
        self._grammars = installed_grammars.discover_installed()
        self._display_names = {
            language_id: grammar.display_name for language_id, grammar in self._grammars.items() if grammar.display_name
        }

    def _load_pack(self, language_name: str) -> Any:
        try:
            # language_name is dynamic; the pack types want a literal.
            language_obj = pack_get_language(language_name)  # type: ignore[arg-type]
        except Exception as exc:
            raise LanguageNotFoundError(
                f"Language {language_name} not available via tree-sitter-language-pack: {exc}"
            ) from exc
        language = ensure_language(language_obj)
        self.languages[language_name] = language
        self._origins[language_name] = "pack"
        return language

    def _load_installed(self, language_name: str) -> Optional[Any]:
        self._ensure_discovered()
        assert self._grammars is not None
        if language_name not in self._grammars:
            return None
        try:
            language = installed_grammars.load_installed_language(language_name)
        except Exception as exc:
            logger.warning("Skipping standalone grammar %s: %s", language_name, exc)
            return None
        self.languages[language_name] = language
        self._origins[language_name] = "installed"
        return language

    def get_language(self, language_name: str) -> Any:
        """
        Get or load a language by name.

        The default order is the language pack, then an installed tree-sitter-*
        package. prefer_installed_grammars reverses that order.

        Args:
            language_name: Language identifier

        Returns:
            Tree-sitter Language object

        Raises:
            LanguageNotFoundError: If language cannot be loaded
        """
        with self._lock:
            if language_name in self.languages:
                return self.languages[language_name]

            if self.prefer_installed_grammars:
                installed = self._load_installed(language_name)
                if installed is not None:
                    return installed
                return self._load_pack(language_name)

            try:
                return self._load_pack(language_name)
            except LanguageNotFoundError:
                installed = self._load_installed(language_name)
                if installed is not None:
                    return installed
                raise

    def get_parser(self, language_name: str) -> Parser:
        """
        Get a parser for the specified language.

        The parser is built from the same origin as the language object.
        Pack languages use the pack parser. Installed languages use
        Parser(language).

        Args:
            language_name: Language identifier

        Returns:
            Tree-sitter Parser configured for the language
        """
        language = self.get_language(language_name)
        if self._origins.get(language_name) == "pack":
            try:
                parser = pack_get_parser(language_name)  # type: ignore[arg-type]
                return parser  # type: ignore[no-any-return]
            except Exception:
                logger.debug("Pack parser failed for %s; building one from the language", language_name)
        return create_parser(language)
