"""FEAT-9: 技能市场访问层（只读）契约测试。"""

import json as _json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_market import (  # noqa: E402
    check_updates,
    detect_backend,
    list_installed,
    parse_github_source,
    read_sources,
    search,
    strip_ansi,
)


class DetectBackendTest(unittest.TestCase):
    def test_returns_dict_with_expected_keys(self):
        info = detect_backend()
        for key in ("available", "npx_path", "version", "reason"):
            self.assertIn(key, info)

    def test_missing_npx_degrades_without_raising(self):
        """后端缺失必须降级为 available=False，不得抛异常。"""
        with mock.patch("skill_market.shutil.which", return_value=None):
            info = detect_backend()
        self.assertFalse(info["available"])
        self.assertIsNone(info["npx_path"])
        self.assertTrue(info["reason"])


class ReadSourcesTest(unittest.TestCase):
    def test_three_sources_always_present(self):
        """三个源恒在清单中，缺失的标 unavailable 而非省略。"""
        srcs = read_sources()
        self.assertEqual(set(srcs["sources"]), {"skills.sh", "qwenwork", "enterprise"})

    def test_unavailable_sources_carry_reason(self):
        srcs = read_sources()
        for s in srcs["sources"].values():
            if not s["available"]:
                self.assertTrue(s["reason"], f"{s['id']} 不可用但未给原因")


class ListInstalledTest(unittest.TestCase):
    def _lock(self, tmp, payload):
        p = Path(tmp) / ".skill-lock.json"
        p.write_text(_json.dumps(payload), encoding="utf-8")
        return p

    def test_reads_source_fields_from_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = self._lock(tmp, {
                "version": 3,
                "skills": {
                    "find-skills": {
                        "source": "vercel-labs/skills",
                        "sourceType": "github",
                        "sourceUrl": "https://github.com/vercel-labs/skills.git",
                        "skillPath": "skills/find-skills/SKILL.md",
                        "skillFolderHash": "",
                        "installedAt": "2026-01-27T03:25:42.413Z",
                        "updatedAt": "2026-03-03T06:09:35.044Z",
                    }
                },
            })
            out = list_installed(lock_path=lock, skills_dir=Path(tmp) / "no-skills")
        row = next(r for r in out["installed"] if r["name"] == "find-skills")
        self.assertEqual(row["source"], "vercel-labs/skills")
        self.assertEqual(row["source_url"], "https://github.com/vercel-labs/skills.git")
        self.assertEqual(row["skill_path"], "skills/find-skills/SKILL.md")
        self.assertEqual(row["updated_at"], "2026-03-03T06:09:35.044Z")

    def test_empty_folder_hash_is_not_treated_as_version(self):
        """skillFolderHash 恒为空，不得据此判断版本。"""
        with tempfile.TemporaryDirectory() as tmp:
            lock = self._lock(tmp, {
                "version": 3,
                "skills": {"x": {"source": "a/b", "skillFolderHash": ""}},
            })
            out = list_installed(lock_path=lock, skills_dir=Path(tmp) / "no-skills")
        row = next(r for r in out["installed"] if r["name"] == "x")
        self.assertIsNone(row["folder_hash"])

    def test_missing_lock_degrades(self):
        """lock 与技能目录都不存在时降级为空清单，并给出原因。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = list_installed(
                lock_path=Path(tmp) / "nope.json",
                skills_dir=Path(tmp) / "no-skills",
            )
        self.assertEqual(out["installed"], [])
        self.assertTrue(out["reason"])

    def test_hidden_dirs_are_not_skills(self):
        """技能库根有 .git，它不是技能，不得进入清单。"""
        with tempfile.TemporaryDirectory() as tmp:
            skills = Path(tmp) / "skills"
            (skills / ".git").mkdir(parents=True)
            (skills / "real-skill").mkdir()
            lock = self._lock(tmp, {"version": 3, "skills": {}})
            out = list_installed(lock_path=lock, skills_dir=skills)
        names = [r["name"] for r in out["installed"]]
        self.assertEqual(names, ["real-skill"])


class StripAnsiTest(unittest.TestCase):
    def test_removes_color_codes(self):
        raw = "\x1b[38;5;145mvercel-labs/x@y\x1b[0m  736.1K installs"
        self.assertEqual(strip_ansi(raw), "vercel-labs/x@y  736.1K installs")

    def test_removes_progress_refresh_lines(self):
        """`◐ Fetching skills…` 这类原地刷新行必须清掉，否则解析出的条目是脏的。"""
        raw = "◐  Fetching skills…\x1b[1G\x1b[Jvercel-labs/x@y\n"
        out = strip_ansi(raw)
        self.assertNotIn("Fetching", out)
        self.assertIn("vercel-labs/x@y", out)

    def test_plain_text_unchanged(self):
        self.assertEqual(strip_ansi("hello world"), "hello world")


class SearchTest(unittest.TestCase):
    def test_parses_find_output(self):
        sample = (
            "\x1b[38;5;102mInstall with\x1b[0m npx skills add <owner/repo@skill>\n\n"
            "\x1b[38;5;145mvercel-labs/agent-skills@vercel-react-best-practices\x1b[0m"
            " \x1b[36m736.1K installs\x1b[0m\n"
            "\x1b[38;5;102m└ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices\x1b[0m\n"
        )
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 0, "stdout": sample, "stderr": ""}):
            out = search("react")
        self.assertEqual(len(out["results"]), 1)
        r = out["results"][0]
        self.assertEqual(r["package"], "vercel-labs/agent-skills@vercel-react-best-practices")
        self.assertIn("736.1K", r["installs"])
        self.assertEqual(r["url"],
                         "https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices")

    def test_backend_failure_returns_empty_with_reason(self):
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 1, "stdout": "", "stderr": "boom"}):
            out = search("x")
        self.assertEqual(out["results"], [])
        self.assertTrue(out["reason"])

    def test_empty_query_is_rejected_without_calling_npx(self):
        with mock.patch("skill_market._run_npx") as m:
            out = search("   ")
        self.assertEqual(out["results"], [])
        self.assertTrue(out["reason"])
        m.assert_not_called()

    def test_search_never_invokes_destructive_subcommands(self):
        """护栏：search 只允许 find。"""
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 0, "stdout": "", "stderr": ""}) as m:
            search("react")
        called = m.call_args[0][0]
        self.assertEqual(called[0], "find")
        self.assertNotIn("check", called)
        self.assertNotIn("update", called)

    def test_url_pairs_with_its_own_entry_not_by_order(self):
        """URL 必须绑定到它上方的条目；若某条缺 URL，后面的不得整体错位。
        样例取自真实输出（含 ASCII banner 与 └ 行）。"""
        sample = (
            "███████╗██╗  ██╗\n\n"
            "Install with npx skills add <owner/repo@skill>\n\n"
            "a/one@first 10K installs\n"
            "\u2514 https://skills.sh/a/one/first\n\n"
            "b/two@no-url 5K installs\n\n"
            "c/three@third 1K installs\n"
            "\u2514 https://skills.sh/c/three/third\n"
        )
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 0, "stdout": sample, "stderr": ""}):
            out = search("x")
        by = {r["package"]: r["url"] for r in out["results"]}
        self.assertEqual(by["a/one@first"], "https://skills.sh/a/one/first")
        self.assertIsNone(by["b/two@no-url"])
        self.assertEqual(by["c/three@third"], "https://skills.sh/c/three/third")

    def test_banner_is_not_parsed_as_result(self):
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 0,
                                      "stdout": "██╗     ██╗\n╚═╝     ╚═╝\n", "stderr": ""}):
            out = search("x")
        self.assertEqual(out["results"], [])

    def test_no_result_message_is_relayed_verbatim(self):
        """npx skills find 无结果时退出码为 0，转述它的原文案而非自造措辞。"""
        with mock.patch("skill_market._run_npx",
                        return_value={"code": 0,
                                      "stdout": '\nNo skills found for "zzz"\n', "stderr": ""}):
            out = search("zzz")
        self.assertEqual(out["results"], [])
        self.assertIn("No skills found", out["reason"])


class ParseGithubSourceTest(unittest.TestCase):
    def test_ssh_and_https_forms(self):
        for url in ("https://github.com/vercel-labs/skills.git",
                    "git@github.com:vercel-labs/skills.git",
                    "https://github.com/vercel-labs/skills"):
            owner, repo = parse_github_source(url)
            self.assertEqual((owner, repo), ("vercel-labs", "skills"), url)

    def test_non_github_returns_none(self):
        self.assertIsNone(parse_github_source("https://gitlab.com/a/b.git"))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_github_source(""))
        self.assertIsNone(parse_github_source(None))


class CheckUpdatesTest(unittest.TestCase):
    def _installed(self):
        return {"installed": [
            {"name": "a", "source_url": "https://github.com/o/r.git",
             "skill_path": "skills/a/SKILL.md", "updated_at": "2026-01-01T00:00:00.000Z",
             "registered": True},
            {"name": "b", "source_url": None, "skill_path": None,
             "updated_at": None, "registered": True},
        ]}

    def test_three_states(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        return_value="2026-09-01T00:00:00Z"):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "outdated")
        self.assertEqual(by["b"], "unknown")

    def test_up_to_date_state(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        return_value="2025-12-01T00:00:00Z"):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "current")

    def test_remote_failure_is_unknown_not_error(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time", return_value=None):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "unknown")
        self.assertTrue(next(r for r in out["updates"] if r["name"] == "a")["note"])

    def test_counts_reported(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time", return_value=None):
            out = check_updates()
        self.assertEqual(out["summary"]["total"], 2)
        self.assertEqual(out["summary"]["unknown"], 2)

    def test_only_filters_to_requested_names(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time", return_value=None):
            out = check_updates(only=["b"])
        self.assertEqual([r["name"] for r in out["updates"]], ["b"])

    def test_unregistered_skills_are_skipped(self):
        """没有来源登记就无法比对版本，不进更新清单。"""
        payload = {"installed": [{"name": "z", "registered": False,
                                  "source_url": None, "updated_at": None}]}
        with mock.patch("skill_market.list_installed", return_value=payload):
            out = check_updates()
        self.assertEqual(out["updates"], [])


class NoDestructiveCommandTest(unittest.TestCase):
    """护栏：只读模块不得把破坏性子命令当作参数传给 npx。

    只审计代码本身（剔除注释与文档字符串）—— 文档里必须保留对这两个命令的
    警告文字，否则后来者不知道为何不能用，那才是真正危险的。
    """

    @staticmethod
    def _code_only() -> str:
        import ast
        path = ROOT / "core" / "skill_market.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # 清空所有文档字符串，使其不参与审计
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.body:
                first = node.body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    first.value.value = ""
        return ast.unparse(tree)

    def test_no_check_or_update_subcommand_in_code(self):
        code = self._code_only()
        for bad in ('"check"', "'check'", '"update"', "'update'"):
            self.assertNotIn(
                bad, code,
                "只读模块把破坏性子命令 " + bad + " 用作参数；"
                "npx skills check 实为升级（实测一次更新 41 个技能），禁止调用")

    def test_documented_warning_is_retained(self):
        """反向护栏：警告文字不能被删掉。"""
        src = (ROOT / "core" / "skill_market.py").read_text(encoding="utf-8")
        self.assertIn("npx skills check", src)
        self.assertIn("禁止", src)

class HttpGetJsonTest(unittest.TestCase):
    """HTTP 传输的护栏：必须只读、且不依赖 Python 根证书。"""

    def test_uses_curl_when_available(self):
        from skill_market import _http_get_json
        with mock.patch("skill_market.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("skill_market.subprocess.run") as m:
            m.return_value = mock.Mock(returncode=0, stdout='{"ok":1}', stderr="")
            data = _http_get_json("https://example.com/x")
        self.assertEqual(data, {"ok": 1})
        argv = m.call_args[0][0]
        self.assertEqual(argv[0], "/usr/bin/curl")
        self.assertIn("-sS", argv)
        self.assertIn("--max-time", argv)
        # 只读：绝不能出现写方法
        joined = " ".join(argv)
        for bad in ("-X POST", "-X PUT", "-X DELETE", "--data", "-d "):
            self.assertNotIn(bad, joined)

    def test_returns_none_on_failure_not_raise(self):
        from skill_market import _http_get_json
        with mock.patch("skill_market.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("skill_market.subprocess.run") as m:
            m.return_value = mock.Mock(returncode=6, stdout="", stderr="could not resolve")
            self.assertIsNone(_http_get_json("https://example.com/x"))

    def test_returns_none_on_bad_json(self):
        from skill_market import _http_get_json
        with mock.patch("skill_market.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("skill_market.subprocess.run") as m:
            m.return_value = mock.Mock(returncode=0, stdout="not json", stderr="")
            self.assertIsNone(_http_get_json("https://example.com/x"))


if __name__ == "__main__":
    unittest.main()