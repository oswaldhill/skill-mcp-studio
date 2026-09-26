"""SKILL.md frontmatter 契约审计（只读）测试."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from frontmatter_audit import (  # noqa: E402
    audit_skill_frontmatter,
    format_frontmatter_markdown,
    format_frontmatter_report,
)


def _write_skill(repo: Path, name: str, body: str) -> None:
    d = repo / name
    d.mkdir(exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


class FrontmatterAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_skill_is_clean(self):
        _write_skill(
            self.repo, "alpha", "---\nname: alpha\ndescription: Does alpha things.\n---\n\n# Alpha\n"
        )
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["total_skills"], 1)
        self.assertEqual(audit["problems"], 0)
        self.assertEqual(audit["warnings"], 0)

    def test_missing_skillmd(self):
        (self.repo / "alpha").mkdir()
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["missing_skillmd"], ["alpha"])
        self.assertEqual(audit["problems"], 1)

    def test_missing_frontmatter_block(self):
        _write_skill(self.repo, "alpha", "# Alpha\n\nNo frontmatter here.\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["missing_frontmatter"], ["alpha"])

    def test_unclosed_frontmatter(self):
        _write_skill(self.repo, "alpha", "---\nname: alpha\n# no closing ---\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["missing_frontmatter"], ["alpha"])

    def test_unparsable_yaml(self):
        _write_skill(self.repo, "alpha", "---\nname: [broken\n---\n\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["unparsable"], ["alpha"])

    def test_missing_name(self):
        _write_skill(self.repo, "alpha", "---\ndescription: Has only description.\n---\n\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["missing_name"], ["alpha"])

    def test_nonstandard_title_substitute_for_name(self):
        _write_skill(self.repo, "alpha", "---\ntitle: Alpha Title\ndescription: D.\n---\n\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["nonstandard_name_field"], ["alpha"])

    def test_missing_description(self):
        _write_skill(self.repo, "alpha", "---\nname: alpha\n---\n\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["missing_description"], ["alpha"])

    def test_name_mismatch_is_warning(self):
        _write_skill(self.repo, "alpha", "---\nname: beta\ndescription: D.\n---\n\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["problems"], 0)
        self.assertEqual(audit["warnings"], 1)
        self.assertEqual(audit["name_mismatch"][0]["declared"], "beta")

    def test_overlong_description_is_warning(self):
        _write_skill(
            self.repo,
            "alpha",
            f"---\nname: alpha\ndescription: {'x' * 300}\n---\n\n",
        )
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["problems"], 0)
        self.assertEqual(audit["warnings"], 1)
        self.assertEqual(audit["overlong_description"][0]["length"], 300)

    def test_symlink_alias_skipped(self):
        _write_skill(self.repo, "real", "---\nname: real\ndescription: D.\n---\n\n")
        os.symlink(self.repo / "real", self.repo / "alias")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["total_skills"], 1)
        self.assertEqual(audit["problems"], 0)
        self.assertEqual(audit["skipped_aliases"], ["alias"])

    def test_dot_directory_skipped(self):
        _write_skill(self.repo, ".hidden", "---\nname: .hidden\ndescription: D.\n---\n\n")
        audit = audit_skill_frontmatter(str(self.repo))
        self.assertEqual(audit["total_skills"], 0)

    def test_formatters_do_not_crash(self):
        _write_skill(self.repo, "alpha", "---\nname: beta\ndescription: D.\n---\n\n")
        audit = audit_skill_frontmatter(str(self.repo))
        text = format_frontmatter_report(audit)
        md = format_frontmatter_markdown(audit)
        self.assertIn("契约审计", text)
        self.assertIn("name 与目录名不符", md)


if __name__ == "__main__":
    unittest.main()
