"""Shared pytest path bootstrap (T-9).

The project's engine modules are flat files under ``core/`` and imported by
top-level scan.py via ``sys.path.insert(0, <dir>/core)`` at runtime.  Historically
every test file repeated that insert by hand.

``pytest`` auto-imports this ``conftest.py`` once per session, so pytest users
get the ``core/`` import path for free.  ``python3 -m unittest discover`` does
**not** import conftest.py, so the individual unittest modules keep their local
bootstrap for standalone discovery (the CI test job still passes either way).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"

if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
