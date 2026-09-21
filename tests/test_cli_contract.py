"""CLI contract consistency (three-layer drift regression guard).

ARCH-1 (critical) root cause: the CLI surface is defined in three places that
drifted apart —

  1. ``scan.py`` argparse (the real engine surface),
  2. ``src-tauri/src/lib.rs`` ``ALLOWED`` allowlist (what the desktop shell may
     invoke),
  3. ``gui/dashboard.html`` ``runCli`` calls (what the webview actually asks the
     shell to run).

This test extracts each surface statically (no subprocess, no side effects) and
asserts the invariants that keep them aligned:

  * every GUI-first-flag exists in the argparse surface,
  * every Rust allowlist entry exists in the argparse surface.

If either invariant breaks, the desktop app's management actions silently stop
working (rejected by the allowlist) or error out at argparse — so these are
regression tests, not lint.
"""

import ast
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))


def _extract_argparse_flags() -> set:
    """Parse scan.py's argparse ``add_argument`` first-arg flag names via AST."""
    src = (ROOT / "scan.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    flags: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # parser.add_argument("--flag", ...) or add_argument("--flag", ...)
        name = ""
        if isinstance(func, ast.Attribute) and func.attr == "add_argument":
            name = "add_argument"
        elif isinstance(func, ast.Name) and func.id == "add_argument":
            name = "add_argument"
        if name != "add_argument" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            bare = first.value.split("=")[0]
            if bare.startswith("--"):
                flags.add(bare)
    return flags


def _extract_rust_allowlist() -> set:
    """Extract the ``ALLOWED`` string literals from src-tauri/src/lib.rs."""
    src = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    m = re.search(r"ALLOWED:\s*&\[&str\]\s*=\s*&\[(.*?)\];", src, re.S)
    if not m:
        return set()
    return set(re.findall(r'"(--[a-z-]+)"', m.group(1)))


def _extract_gui_first_flags() -> set:
    """Extract the first ``--flag`` literal from each ``runCli([...])`` call.

    The shell gates on the *first* flag in argv, so we only need the leading
    ``--flag`` of every literal array call (variable-built calls like
    ``mtAddArgs`` already start with ``--add-client`` and are covered by the
    literal ``--add-client`` call sites).
    """
    src = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")
    flags: set = set()
    for m in re.finditer(r"runCli\(\s*\[", src):
        tail = src[m.end():]
        # Capture the first --token in the array literal that follows.
        first_tokens = re.match(r"\s*[\"'](?P<flag>--[a-z-]+)[\"']", tail)
        if first_tokens:
            flags.add(first_tokens.group("flag"))
    return flags


class CliContractTest(unittest.TestCase):
    def setUp(self):
        self.argparse_flags = _extract_argparse_flags()
        self.rust_allowlist = _extract_rust_allowlist()
        self.gui_first_flags = _extract_gui_first_flags()

    def test_argparse_surface_probed(self):
        self.assertIn("--management", self.argparse_flags)
        self.assertIn("--update-client", self.argparse_flags)
        self.assertIn("--delete-skill", self.argparse_flags)

    def test_rust_allowlist_subset_of_argparse(self):
        """Every allowlisted subcommand must exist in the engine's argparse."""
        missing = self.rust_allowlist - self.argparse_flags
        self.assertEqual(missing, set(),
                         f"lib.rs ALLOWED 含 argparse 不存在的幽灵命令: {sorted(missing)}")

    def test_gui_first_flags_exist_in_argparse(self):
        """Every runCli first-flag must be a real argparse flag."""
        missing = self.gui_first_flags - self.argparse_flags
        self.assertEqual(missing, set(),
                         f"dashboard.html 调用了 argparse 不存在的命令: {sorted(missing)}")

    def test_skill_ops_are_allowlisted(self):
        """The four skill file operations must be white-listed for the shell."""
        for flag in ("--backup-skill", "--export-skill", "--rename-skill", "--delete-skill"):
            self.assertIn(flag, self.rust_allowlist, f"{flag} 不在 lib.rs 白名单")


if __name__ == "__main__":
    unittest.main()