"""Standalone tree-sitter grammar packages.

Adapted from Za-Pa-Al's installed-package loader. Discovery reads package
metadata only. Importing a grammar waits until that language is requested,
and both successes and failures are cached.
"""

import importlib
import logging
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distributions
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_SKIP = {"tree-sitter", "tree-sitter-language-pack"}
_ID_ALIASES = {"c-sharp": "csharp", "c_sharp": "csharp"}
_MODULE_ALIASES = {"csharp": ("tree_sitter_c_sharp",)}
_FUNCTION_ALIASES = {
    "csharp": ("language_c_sharp", "language_csharp"),
    "typescript": ("language_typescript", "language_tsx"),
    "php": ("language_php",),
    "ocaml": ("language_ocaml",),
    "xml": ("language_xml",),
}
_FAILED = object()

_discovered: Optional[Dict[str, "InstalledGrammar"]] = None
_load_cache: Dict[str, Any] = {}
_scm_cache: Dict[str, Dict[str, str]] = {}

# Bound names so tests can replace them without patching importlib itself.
_distributions = distributions
_import_module = importlib.import_module


@dataclass(frozen=True)
class InstalledGrammar:
    """One discovered grammar distribution."""

    language_id: str
    distribution_name: str
    display_name: Optional[str]
    module_names: Tuple[str, ...]


def language_id_for_distribution(name: str) -> Optional[str]:
    """Map a distribution name to a language id, or None when it is not a grammar."""
    normalized = name.strip().lower().replace("_", "-")
    if normalized in _SKIP or not normalized.startswith("tree-sitter-"):
        return None
    suffix = normalized[len("tree-sitter-") :]
    if not suffix or suffix == "language-pack":
        return None
    if suffix in _ID_ALIASES:
        return _ID_ALIASES[suffix]
    underscored = suffix.replace("-", "_")
    return _ID_ALIASES.get(underscored, underscored)


def module_names_for(language_id: str) -> Tuple[str, ...]:
    """Import names to try, aliases first."""
    names = list(_MODULE_ALIASES.get(language_id, ()))
    names.append(f"tree_sitter_{language_id}")
    return tuple(dict.fromkeys(names))


def _display_name(summary: str) -> Optional[str]:
    text = summary.strip()
    if not text:
        return None
    for marker in (" grammar for tree-sitter", "Tree-sitter grammar for "):
        if marker in text:
            part = text.split(marker, 1)
            return (part[0] if marker.startswith(" ") else part[1]).strip() or None
    return text


def discover_installed() -> Dict[str, InstalledGrammar]:
    """Scan installed distributions once. Does not import grammar modules."""
    global _discovered
    if _discovered is not None:
        return _discovered
    found: Dict[str, InstalledGrammar] = {}
    try:
        packages = _distributions()
    except Exception as exc:
        logger.warning("Failed to discover installed tree-sitter packages: %s", exc)
        _discovered = {}
        return _discovered
    for dist in packages:
        raw_name = dist.metadata["Name"] or ""
        language_id = language_id_for_distribution(raw_name)
        if language_id is None or language_id in found:
            continue
        summary = dist.metadata["Summary"] if "Summary" in dist.metadata else ""
        found[language_id] = InstalledGrammar(
            language_id=language_id,
            distribution_name=raw_name,
            display_name=_display_name(summary),
            module_names=module_names_for(language_id),
        )
    _discovered = found
    return found


def _default_language_ctor(capsule: Any) -> Any:
    from tree_sitter import Language

    return Language(capsule)


def _language_callable(module: Any, language_id: str) -> Optional[Callable[[], Any]]:
    if hasattr(module, "language"):
        return module.language  # type: ignore[no-any-return]
    specific = getattr(module, f"language_{language_id}", None)
    if specific is not None:
        return specific  # type: ignore[no-any-return]
    for alias in _FUNCTION_ALIASES.get(language_id, ()):
        candidate = getattr(module, alias, None)
        if candidate is not None:
            return candidate  # type: ignore[no-any-return]
    return None


def load_installed_language(language_id: str, language_ctor: Optional[Callable[[Any], Any]] = None) -> Any:
    """Import one grammar and build a Language. Failures stay cached."""
    if language_id in _load_cache:
        cached = _load_cache[language_id]
        if cached is _FAILED:
            raise ImportError(f"standalone grammar {language_id} previously failed to load")
        return cached
    ctor = language_ctor or _default_language_ctor
    try:
        module = None
        last_error: Optional[BaseException] = None
        for module_name in module_names_for(language_id):
            try:
                module = _import_module(module_name)
                break
            except ImportError as exc:
                last_error = exc
        if module is None:
            raise ImportError(f"no module for {language_id}") from last_error
        loader = _language_callable(module, language_id)
        if loader is None:
            raise AttributeError(f"{module_name} has no language() function")
        language = ctor(loader())
    except Exception:
        _load_cache[language_id] = _FAILED
        raise
    _load_cache[language_id] = language
    return language


def _queries_dir(module: Any) -> Optional[Path]:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return None
    module_path = Path(module_file).parent
    for candidate in (
        module_path / "queries",
        module_path.parent / "queries",
        module_path.parent.parent.parent / "queries",
    ):
        if candidate.is_dir():
            return candidate
    return None


def scm_templates_for(language_id: str) -> Dict[str, str]:
    """Load .scm queries for one language. A miss is cached and not retried."""
    if language_id in _scm_cache:
        return _scm_cache[language_id]
    templates: Dict[str, str] = {}
    try:
        grammar = discover_installed().get(language_id)
        if grammar is None:
            _scm_cache[language_id] = {}
            return {}
        if language_id_for_distribution(grammar.distribution_name) is None:
            _scm_cache[language_id] = {}
            return {}
        module = None
        for module_name in grammar.module_names:
            try:
                module = _import_module(module_name)
                break
            except ImportError:
                continue
        queries = _queries_dir(module) if module is not None else None
        if queries is not None:
            for scm_file in sorted(queries.glob("*.scm")):
                key = scm_file.stem.replace("-", "_")
                templates[key] = scm_file.read_text(encoding="utf-8")
    except (OSError, PackageNotFoundError, UnicodeError) as exc:
        logger.warning("Failed to load .scm queries for %s: %s", language_id, exc)
        templates = {}
    _scm_cache[language_id] = templates
    return templates
