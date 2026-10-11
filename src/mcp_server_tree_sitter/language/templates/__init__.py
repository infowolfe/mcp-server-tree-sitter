"""Language-specific query templates collection."""

from typing import Dict

from . import (
    apl,
    c,
    cpp,
    csharp,
    css,
    css_modules,
    dart,
    go,
    java,
    javascript,
    julia,
    kotlin,
    python,
    rust,
    scss,
    scss_modules,
    swift,
    tsx,
    typescript,
)

# Combine all language templates
QUERY_TEMPLATES: Dict[str, Dict[str, str]] = {
    "python": python.TEMPLATES,
    "javascript": javascript.TEMPLATES,
    "typescript": typescript.TEMPLATES,
    "tsx": tsx.TEMPLATES,
    "css": css.TEMPLATES,
    "css_modules": css_modules.TEMPLATES,
    "scss": scss.TEMPLATES,
    "scss_modules": scss_modules.TEMPLATES,
    "go": go.TEMPLATES,
    "rust": rust.TEMPLATES,
    "c": c.TEMPLATES,
    "cpp": cpp.TEMPLATES,
    "csharp": csharp.TEMPLATES,
    "dart": dart.TEMPLATES,
    "swift": swift.TEMPLATES,
    "java": java.TEMPLATES,
    "kotlin": kotlin.TEMPLATES,
    "julia": julia.TEMPLATES,
    "apl": apl.TEMPLATES,
}
