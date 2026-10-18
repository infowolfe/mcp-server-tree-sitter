"""Query templates for common code patterns by language."""

import importlib
import logging
from pathlib import Path
from typing import Any

from . import installed as installed_grammars
from .templates import QUERY_TEMPLATES

logger = logging.getLogger(__name__)
_merged: set[str] = set()


def _merge_extras(language: str) -> None:
    """Add a lazy template module and .scm queries without dropping built-ins."""
    if language in _merged:
        return
    _merged.add(language)
    if language not in QUERY_TEMPLATES:
        module_path = Path(__file__).parent / "templates" / f"{language}.py"
        if module_path.is_file():
            try:
                module = importlib.import_module(f".templates.{language}", package=__package__)
                templates = getattr(module, "TEMPLATES", None)
                if isinstance(templates, dict):
                    QUERY_TEMPLATES[language] = dict(templates)
            except Exception as exc:
                logger.warning("Failed to load template module %s: %s", language, exc)
    current = dict(QUERY_TEMPLATES.get(language, {}))
    for name, source in installed_grammars.scm_templates_for(language).items():
        current.setdefault(name, source)
    if current:
        QUERY_TEMPLATES[language] = current


def get_query_template(language: str, template_name: str) -> str | None:
    """Get a query template for a language.

    Args:
        language: Language identifier
        template_name: Template name

    Returns:
        Query string or None if not found
    """
    _merge_extras(language)
    language_templates = QUERY_TEMPLATES.get(language)
    if language_templates:
        return language_templates.get(template_name)
    return None


def list_query_templates(language: str | list[str] | None = None) -> dict[str, Any]:
    """List available query templates.

    Args:
        language: Optional language or list of languages to filter by

    Returns:
        Dictionary of templates by language
    """
    if language:
        languages = [lang.strip() for lang in language.split(",")] if isinstance(language, str) else language
        for lang in languages:
            _merge_extras(lang)
        return {lang: QUERY_TEMPLATES.get(lang, {}) for lang in languages}
    for lang in list(QUERY_TEMPLATES):
        _merge_extras(lang)
    for lang in installed_grammars.discover_installed():
        _merge_extras(lang)
    return QUERY_TEMPLATES
