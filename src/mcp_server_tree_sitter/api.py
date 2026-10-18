"""API functions for accessing container dependencies.

This module provides function-based access to dependencies managed by the
container, helping to break circular import chains and simplify access.
"""

import logging
from typing import Any

from .di import get_container
from .exceptions import ProjectError

logger = logging.getLogger(__name__)


def get_project_registry() -> Any:
    """Get the project registry."""
    return get_container().project_registry


def get_language_registry() -> Any:
    """Get the language registry."""
    return get_container().language_registry


def get_tree_cache() -> Any:
    """Get the tree cache."""
    return get_container().tree_cache


def get_config() -> Any:
    """Get the current configuration."""
    return get_container().get_config()


def get_config_manager() -> Any:
    """Get the configuration manager."""
    return get_container().config_manager


def register_project(path: str, name: str | None = None, description: str | None = None) -> dict[str, Any]:
    """Register a project."""
    project_registry = get_project_registry()
    language_registry = get_language_registry()

    try:
        # Register project
        project = project_registry.register_project(name or path, path, description)

        # Scan for languages
        project.scan_files(language_registry)

        project_dict = project.to_dict()
        # Add type annotations
        result: dict[str, Any] = {
            "name": project_dict["name"],
            "root_path": project_dict["root_path"],
            "description": project_dict["description"],
            "languages": project_dict["languages"],
            "last_scan_time": project_dict["last_scan_time"],
        }
        return result
    except Exception as e:
        raise ProjectError(f"Failed to register project: {e}") from e


def list_projects() -> list[dict[str, Any]]:
    """List all registered projects."""
    return [
        {
            "name": project["name"],
            "root_path": project["root_path"],
            "description": project["description"],
            "languages": project["languages"],
            "last_scan_time": project["last_scan_time"],
        }
        for project in get_project_registry().list_projects()
    ]


def remove_project(name: str) -> dict[str, str]:
    """Remove a registered project."""
    get_project_registry().remove_project(name)
    return {"status": "success", "message": f"Project '{name}' removed"}


def clear_cache(project: str | None = None, file_path: str | None = None) -> dict[str, str]:
    """Clear cached parses and content-cache state.

    A file drops that file's parse trees and its stat note. Any other call
    drops every parse tree, every stat note, and the shared result files.
    """
    tree_cache = get_tree_cache()
    content_cache = get_container().content_cache

    if project and file_path:
        # Get file path
        project_registry = get_project_registry()
        project_obj = project_registry.get_project(project)
        abs_path = project_obj.get_file_path(file_path)

        # Clear cache
        tree_cache.invalidate(abs_path)
        content_cache.invalidate(abs_path)
        return {"status": "success", "message": f"Cache cleared for {file_path} in {project}"}
    # Clear all
    tree_cache.invalidate()
    content_cache.invalidate()
    return {"status": "success", "message": "Cache cleared"}
