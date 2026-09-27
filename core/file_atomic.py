"""Leaf file-safety helpers: backup path + atomic write (A-5 cycle break).

``mcp_fixer``, ``config_store`` and ``skill_toggle`` all need the same backup →
atomic write → fsync → chmod → replace safety shape.  Historically those two
functions lived in ``mcp_fixer``, so importing them pulled ``mcp_fixer``'s
``tool_registry``/``mcp_checker``/``profile_loader`` dependency chain into
``config_store``/``skill_toggle`` and forced a web of lazy imports to hide the
resulting cycle.

This module depends only on the standard library, so any module may import it at
top level without re-introducing a cycle.
"""

import os
import tempfile
from datetime import datetime


def backup_path(path: str) -> str:
    """Timestamped ``.bak-YYYYMMDD-HHMMSS-ffffff`` sibling path for ``path``."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{path}.bak-{timestamp}"


def atomic_write(path: str, content: str, mode: int) -> None:
    """Write ``content`` to ``path`` atomically (mkstemp + fsync + chmod + replace)."""
    directory = os.path.dirname(path) or "."
    descriptor, temp_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def restore_backup(backup: str, path: str, mode: int) -> None:
    """Copy ``backup`` back over ``path`` via an atomic write."""
    with open(backup, "r", encoding="utf-8") as handle:
        original = handle.read()
    atomic_write(path, original, mode)
