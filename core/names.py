"""Canonical client-name normalization (A-5 cycle break).

``normalized_name`` is a dependency-free string helper used by nearly every
registry/checker module.  Keeping it in ``tool_registry`` forced pure consumers
(``config_store``, ``profile_loader``) to import ``tool_registry`` — which pulls
``config_store`` back in via ``effective_tools`` — creating a cycle that was
hidden by lazy imports.  A leaf module holding the one shared helper breaks it.
"""


def normalized_name(value: str) -> str:
    """Lower-case and strip every non-alphanumeric character from ``value``."""
    return "".join(character for character in value.lower() if character.isalnum())
