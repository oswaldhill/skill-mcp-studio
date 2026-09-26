"""FEAT-9: 技能市场访问层（只读）契约测试。"""

import json as _json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_market import (  # noqa: E402
    _npx_env,
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
        with mock.patch("skill_market.which_with_fallback", return_value=None):
            info = detect_backend()
        self.assertFalse(info["available"])
        self.assertIsNone(info["npx_path"])
        self.assertTrue(info["reason"])

    def test_npx_lookup_goes_through_path_fallback(self):
        """回归：GUI 壳（Finder 启动）PATH 受限时，npx 必须经兜底目录命中。

        原先裸查 ``shutil.which("npx")``，最小 PATH 下必然落空，技能市场恒报
        「未找到 npx」；改走 ``which_with_fallback`` 后与 CLI 探测策略一致。
        """
        with mock.patch(
            "skill_market.which_with_fallback", return_value="/opt/homebrew/bin/npx"
        ) as finder, mock.patch(
            "skill_market._run_npx",
            return_value={"code": 0, "stdout": "", "stderr": ""},
        ):
            info = detect_backend()
        finder.assert_called_once_with("npx")
        self.assertTrue(info["available"])
        self.assertEqual(info["npx_path"], "/opt/homebrew/bin/npx")

    def test_npx_env_exposes_node_next_to_npx(self):
        """npx 是 `#!/usr/bin/env node` 脚本：只给绝对路径仍找不到 node。"""
        env = _npx_env("/opt/homebrew/bin/npx")
        self.assertEqual(env["PATH"].split(os.pathsep)[0], "/opt/homebrew/bin")


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
                        return_value=("2026-09-01T00:00:00Z", "ok")):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "outdated")
        self.assertEqual(by["b"], "unknown")

    def test_up_to_date_state(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        return_value=("2025-12-01T00:00:00Z", "ok")):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "current")

    def test_remote_failure_is_unknown_not_error(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        return_value=(None, "unavailable")):
            out = check_updates()
        by = {r["name"]: r["state"] for r in out["updates"]}
        self.assertEqual(by["a"], "unknown")
        self.assertTrue(next(r for r in out["updates"] if r["name"] == "a")["note"])

    def test_counts_reported(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        return_value=(None, "unavailable")):
            out = check_updates()
        self.assertEqual(out["summary"]["total"], 2)
        self.assertEqual(out["summary"]["unknown"], 2)

    def test_only_filters_to_requested_names(self):
        with mock.patch("skill_market.list_installed", return_value=self._installed()), \
             mock.patch("skill_market._remote_commit_time",
                        return_value=(None, "unavailable")):
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
    """HTTP 传输护栏：只读、区分状态码、不依赖 Python 根证书。"""

    def _run(self, stdout, returncode=0):
        with mock.patch("skill_market.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("skill_market.subprocess.run") as m:
            m.return_value = mock.Mock(returncode=returncode, stdout=stdout, stderr="")
            from skill_market import _http_get_json
            return _http_get_json("https://example.com/x"), m

    def test_success_returns_data_and_200(self):
        (data, status), m = self._run('{"ok":1}\n200')
        self.assertEqual(data, {"ok": 1})
        self.assertEqual(status, 200)
        argv = m.call_args[0][0]
        self.assertEqual(argv[0], "/usr/bin/curl")
        self.assertIn("-sS", argv)
        self.assertIn("--max-time", argv)
        # 只读：绝不能出现写方法
        joined = " ".join(argv)
        for bad in ("-X POST", "-X PUT", "-X DELETE", "--data"):
            self.assertNotIn(bad, joined)

    def test_rate_limit_status_is_surfaced(self):
        """403 必须透出，否则会被误读成「仓库不存在」。"""
        (data, status), _ = self._run('{"message":"API rate limit exceeded"}\n403')
        self.assertIsNone(data)
        self.assertEqual(status, 403)

    def test_missing_repo_status_is_surfaced(self):
        (data, status), _ = self._run('{"message":"Not Found"}\n404')
        self.assertIsNone(data)
        self.assertEqual(status, 404)

    def test_curl_failure_returns_zero_status(self):
        (data, status), _ = self._run("", returncode=6)
        self.assertIsNone(data)
        self.assertEqual(status, 0)

    def test_bad_json_with_200_returns_none(self):
        (data, status), _ = self._run("not json\n200")
        self.assertIsNone(data)
        self.assertEqual(status, 200)


class RemoteCommitTimeStatusTest(unittest.TestCase):
    def _call(self, body, code=200):
        with mock.patch("skill_market._http_get_json",
                        return_value=(body, code)):
            from skill_market import _remote_commit_time
            return _remote_commit_time("o", "r", "p")

    def test_ok_returns_time(self):
        time, status = self._call(
            [{"commit": {"committer": {"date": "2026-08-11T18:57:14Z"}}}])
        self.assertEqual(time, "2026-08-11T18:57:14Z")
        self.assertEqual(status, "ok")

    def test_403_maps_to_rate_limited(self):
        time, status = self._call({"message": "rate limit"}, 403)
        self.assertIsNone(time)
        self.assertEqual(status, "rate_limited")

    def test_429_also_maps_to_rate_limited(self):
        time, status = self._call({"message": "too many"}, 429)
        self.assertEqual(status, "rate_limited")

    def test_empty_list_is_no_commits(self):
        time, status = self._call([])
        self.assertIsNone(time)
        self.assertEqual(status, "no_commits")


if __name__ == "__main__":
    unittest.main()
