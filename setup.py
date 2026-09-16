#!/usr/bin/env python3
"""Build shim: flatten ``core/*.py`` into top-level modules for the wheel.

The source tree keeps ``scan.py`` alongside a ``core/`` directory of flat,
top-level modules (scan.py bootstraps ``core/`` onto ``sys.path`` at runtime).
A stock ``[tool.setuptools] py-modules`` list cannot reference modules in a
subdirectory, so this subclass copies each ``core/*.py`` into the build root so
the installed ``scan:main`` console script keeps resolving
``from scanner import ...``-style imports exactly as it does from a checkout.
"""

from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py

CORE_MODULES = sorted(p.stem for p in Path("core").glob("*.py"))


class FlattenCoreModules(build_py):
    def run(self):
        super().run()
        for name in CORE_MODULES:
            src = Path("core") / f"{name}.py"
            dst = Path(self.build_lib) / f"{name}.py"
            shutil.copyfile(src, dst)


setup(
    py_modules=["scan"] + CORE_MODULES,
    cmdclass={"build_py": FlattenCoreModules},
)