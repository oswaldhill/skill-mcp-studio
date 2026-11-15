"""技能安装源：GitHub URL 识别、仓库预览、重名检测。

对应需求（2026-11-14）：Skill 页支持两种安装入口 ——
  ① 搜索/输入包名 → 安装到统一目录；
  ② 直接给 GitHub 地址 → 安装对应仓库的技能。

全部 mock，绝不真的调用 npx（沿用 test_skill_market_ops.py 的纪律）。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_market_ops import (  # noqa: E402
    classify_install_source,
    plan_install_repo,
    plan_repo_preview,
    detect_conflicts,
)


class ClassifySourceTest(unittest.TestCase):
    """输入分派：GitHub URL / 包名 / 非法。"""

    def test_https_github_url_is_github(self):
        r = classify_install_source("https://github.com/vercel-labs/agent-skills")
        self.assertEqual(r["kind"], "github")
        self.assertEqual(r["owner"], "vercel-labs")
        self.assertEqual(r["repo"], "agent-skills")
        self.assertTrue(r["ok"])

    def test_url_with_git_suffix(self):
        r = classify_install_source("https://github.com/owner/repo.git")
        self.assertEqual(r["kind"], "github")
        self.assertEqual(r["repo"], "repo")

    def test_ssh_style_github_url(self):
        r = classify_install_source("git@github.com:owner/repo.git")
        self.assertEqual(r["kind"], "github")

    def test_bare_owner_slash_repo_is_package(self):
        r = classify_install_source("vercel-labs/agent-skills")
        self.assertEqual(r["kind"], "package")

    def test_package_with_skill_suffix(self):
        r = classify_install_source("vercel-labs/agent-skills@my-skill")
        self.assertEqual(r["kind"], "package")
        self.assertEqual(r["package"], "vercel-labs/agent-skills@my-skill")

    def test_empty_is_rejected(self):
        for raw in ("", "   ", None):
            r = classify_install_source(raw)
            self.assertFalse(r["ok"], raw)
            self.assertTrue(r["reason"])

    def test_non_github_url_is_rejected(self):
        """安全：只允许 GitHub，拒绝任意 URL（避免装来源不明的仓库）。"""
        r = classify_install_source("https://evil.example.com/owner/repo")
        self.assertFalse(r["ok"])
        self.assertEqual(r["kind"], "rejected")
        self.assertIn("github", r["reason"].lower())

    def test_file_url_is_rejected(self):
        r = classify_install_source("file:///etc/passwd")
        self.assertFalse(r["ok"])

    def test_url_with_subpath_skill_is_accepted(self):
        """GitHub 子目录形式：一个仓库里定位到单个 skill。"""
        r = classify_install_source(
            "https://github.com/owner/repo/tree/main/skills/foo")
        self.assertEqual(r["kind"], "github")
        self.assertEqual(r["owner"], "owner")
        self.assertEqual(r["repo"], "repo")


class RepoPreviewTest(unittest.TestCase):
    """仓库预览：一个 repo 常含多个 skill，装前必须先列出来。"""

    def test_preview_plan_shape(self):
        plan = plan_repo_preview("https://github.com/owner/repo")
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["action"], "preview")
        self.assertEqual(plan["argv"][0], "add")
        self.assertIn("-l", plan["argv"])

    def test_preview_never_installs(self):
        """护栏：预览不得带 -y/-g，也不得带 --all —— 它只读不装。"""
        argv = plan_repo_preview("https://github.com/owner/repo")["argv"]
        for flag in ("-y", "--yes", "-g", "--global", "--all"):
            self.assertNotIn(flag, argv)

    def test_preview_rejects_non_github(self):
        plan = plan_repo_preview("https://evil.example.com/a/b")
        self.assertFalse(plan["ok"])


class PlanInstallRepoTest(unittest.TestCase):
    """带选定技能/客户端的安装计划。"""

    def test_install_specific_skills(self):
        plan = plan_install_repo(
            "https://github.com/owner/repo", skills=["foo", "bar"])
        self.assertTrue(plan["ok"])
        self.assertIn("--skill", plan["argv"])
        self.assertIn("foo,bar", plan["argv"])

    def test_install_all_skills_requires_explicit_all(self):
        """不传 skills 不得静默装全部；必须显式 all=True。"""
        plan = plan_install_repo("https://github.com/owner/repo")
        self.assertFalse(plan["ok"])
        self.assertIn("未选择", plan["reason"])

    def test_install_all_uses_skill_star(self):
        plan = plan_install_repo(
            "https://github.com/owner/repo", all_skills=True)
        self.assertTrue(plan["ok"])
        idx = plan["argv"].index("--skill")
        self.assertEqual(plan["argv"][idx + 1], "*")

    def test_install_pins_global(self):
        plan = plan_install_repo(
            "https://github.com/owner/repo", all_skills=True)
        self.assertIn("-g", plan["argv"])

    def test_install_agents_flag(self):
        plan = plan_install_repo(
            "https://github.com/owner/repo", all_skills=True,
            agents=["codex", "claude"])
        self.assertIn("--agent", plan["argv"])
        self.assertIn("codex,claude", plan["argv"])

    def test_install_never_uses_check(self):
        plan = plan_install_repo(
            "https://github.com/owner/repo", all_skills=True)
        self.assertNotIn("check", plan["argv"])

    def test_install_rejects_both_skills_and_all(self):
        plan = plan_install_repo(
            "https://github.com/owner/repo", skills=["foo"], all_skills=True)
        self.assertFalse(plan["ok"])


class ConflictTest(unittest.TestCase):
    """装前重名检测：不得静默覆盖已装技能。"""

    def test_detects_existing(self):
        with mock.patch("skill_market_ops._skills_dir") as d:
            d.return_value = Path("/tmp/nonexistent-skills-root-for-test")
            r = detect_conflicts(["foo"])
        self.assertIn("foo", r["missing"])
        self.assertEqual(r["conflicts"], [])

    def test_reports_present_as_conflict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "foo").mkdir()
            with mock.patch("skill_market_ops._skills_dir",
                            return_value=Path(tmp)):
                r = detect_conflicts(["foo", "bar"])
        self.assertEqual(r["conflicts"], ["foo"])
        self.assertEqual(r["missing"], ["bar"])
        self.assertTrue(r["has_conflict"])

    def test_empty_names(self):
        r = detect_conflicts([])
        self.assertEqual(r["conflicts"], [])
        self.assertFalse(r["has_conflict"])


if __name__ == "__main__":
    unittest.main()

class ParsePreviewTest(unittest.TestCase):
    """解析 `npx skills add -l` 的输出，得到可勾选的技能清单。

    实测输出形状（2026-11-15）：
        ◇  Found 9 skills
        │
        ◇  Available Skills
        │
        │    vercel-composition-patterns
        │
        │      React composition patterns that scale. ...
        │
        │    deploy-to-vercel
        │
        │      Deploy applications and websites to Vercel. ...
  """

    RAW = (
        "\u250c   skills \n"
        "\u2502\n"
        "\u25c7  Source: https://github.com/vercel-labs/agent-skills.git\n"
        "\u2502\n"
        "\u25c7  Found 3 skills\n"
        "\u2502\n"
        "\u25c7  Available Skills\n"
        "\u2502\n"
        "\u2502    vercel-composition-patterns\n"
        "\u2502\n"
        "\u2502      React composition patterns that scale. Use when refactoring.\n"
        "\u2502\n"
        "\u2502    deploy-to-vercel\n"
        "\u2502\n"
        "\u2502      Deploy applications and websites to Vercel.\n"
        "\u2502\n"
        "\u2502    vercel-optimize\n"
        "\u2502\n"
        "\u2502      Use for Vercel cost and performance optimization.\n"
        "\u2502\n"
        "\u2514  Use --skill <name> to install specific skills\n"
    )

    def test_parses_names_and_descriptions(self):
        from skill_market_ops import parse_preview_skills
        r = parse_preview_skills(self.RAW)
        self.assertTrue(r["ok"])
        names = [s["name"] for s in r["skills"]]
        self.assertEqual(names, [
            "vercel-composition-patterns",
            "deploy-to-vercel",
            "vercel-optimize",
        ])
        self.assertIn("React composition", r["skills"][0]["description"])
        self.assertIn("Deploy applications", r["skills"][1]["description"])

    def test_declared_count_matches(self):
        from skill_market_ops import parse_preview_skills
        r = parse_preview_skills(self.RAW)
        self.assertEqual(r["declared_count"], 3)
        self.assertEqual(r["parsed_count"], 3)

    def test_count_mismatch_is_flagged(self):
        """声明 3 个却只解析出 1 个：必须报出来，不能静默当成完整的。"""
        from skill_market_ops import parse_preview_skills
        raw = (
            "\u25c7  Found 3 skills\n"
            "\u2502    only-one\n"
            "\u2502      desc\n"
        )
        r = parse_preview_skills(raw)
        self.assertEqual(r["parsed_count"], 1)
        self.assertTrue(r["count_mismatch"])

    def test_strips_ansi(self):
        from skill_market_ops import parse_preview_skills
        raw = (
            "\x1b[38;5;250m\u25c7  Found 1 skills\x1b[0m\n"
            "\x1b[1G\x1b[J\u2502    alpha-skill\n"
            "\u2502\n"
            "\u2502      first description\n"
        )
        r = parse_preview_skills(raw)
        self.assertEqual([s["name"] for s in r["skills"]], ["alpha-skill"])

    def test_empty_output_is_not_ok(self):
        from skill_market_ops import parse_preview_skills
        r = parse_preview_skills("")
        self.assertFalse(r["ok"])
        self.assertTrue(r["reason"])

    def test_rejects_noise_lines(self):
        """'Found N skills'、'Available Skills'、'Use --skill' 不能当技能名。"""
        from skill_market_ops import parse_preview_skills
        r = parse_preview_skills(self.RAW)
        names = {s["name"] for s in r["skills"]}
        for noise in ("Found", "Available", "Use", "skills", "Source"):
            self.assertNotIn(noise, names)
        self.assertTrue(all(" " not in n for n in names))

    def test_skill_with_version_suffix(self):
        """多行描述不应被误当成技能名（描述行缩进更深）。"""
        from skill_market_ops import parse_preview_skills
        r = parse_preview_skills(self.RAW)
        self.assertEqual(len(r["skills"]), 3)
