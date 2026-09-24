"""技能使用统计（core/skill_usage.py）契约测试。

核心防线：只有工具调用记录（function_call / custom_tool_call）才算使用证据。
会话里注入的 host_skills 清单、以及工具返回内容（function_call_output）里
都会出现技能名与 SKILL.md 路径，一旦误算，命中数会虚高到 100% 误报。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_usage import scan_usage, summarize_text  # noqa: E402

SKILLS_ROOT = "/Users/tester/.skills-manager/skills"


def rec(payload, ts="2026-05-09T05:19:27.508Z", ordinal=0):
    """一条 response_item 记录（与 Codex rollout jsonl 同构）。"""
    return json.dumps(
        {"timestamp": ts, "ordinal": ordinal, "type": "response_item", "payload": payload},
        ensure_ascii=False,
    )


def call(tool, arguments, ptype="function_call"):
    if ptype == "function_call":
        return {"type": "function_call", "name": tool,
                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                "call_id": "call_x"}
    return {"type": "custom_tool_call", "name": tool, "status": "completed",
            "input": arguments if isinstance(arguments, str) else json.dumps(arguments),
            "call_id": "call_x"}


class SessionFixture(unittest.TestCase):
    """在临时目录里造 sessions + skills 两边数据。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.sessions = base / "sessions"
        self.sessions.mkdir()
        self.skills = base / "skills"
        for name in ("taste-skill", "hermes", "never-used", "ls-only", "ghost-skill"):
            (self.skills / name).mkdir(parents=True)
        (self.skills / ".git").mkdir()          # 隐藏目录不是技能
        self.addCleanup(self._tmp.cleanup)

    def write(self, filename, lines):
        (self.sessions / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def scan(self, **kw):
        return scan_usage(session_dirs=[str(self.sessions)], skills_dir=str(self.skills), **kw)


class LoadClassificationTest(SessionFixture):
    def test_reading_skill_md_counts_as_load(self):
        self.write("a.jsonl", [
            rec(call("exec_command", {"cmd": f"sed -n '1,240p' {SKILLS_ROOT}/taste-skill/SKILL.md"})),
        ])
        s = self.scan()["skills"]["taste-skill"]
        self.assertEqual(s["load"], 1)
        self.assertEqual(s["browse"], 0)
        self.assertTrue(s["used"])

    def test_spawn_agent_declaring_skill_counts_as_load(self):
        self.write("b.jsonl", [
            rec(call("spawn_agent", {"agent_type": "explorer", "items": [
                {"type": "skill", "name": "frontend-design",
                 "path": f"{SKILLS_ROOT}/frontend-design/SKILL.md"}]})),
        ])
        self.assertEqual(self.scan()["skills"]["frontend-design"]["load"], 1)

    def test_request_permissions_listing_skill_md_counts_as_load(self):
        self.write("c.jsonl", [
            rec(call("request_permissions", {"permissions": {"file_system": {
                "read": [f"{SKILLS_ROOT}/feishu-lark/SKILL.md"]}}})),
        ])
        self.assertEqual(self.scan()["skills"]["feishu-lark"]["load"], 1)

    def test_directory_listing_only_counts_as_browse(self):
        self.write("d.jsonl", [
            rec(call("exec_command", {"cmd": f"ls -la {SKILLS_ROOT}/hermes/"})),
        ])
        s = self.scan()["skills"]["hermes"]
        self.assertEqual(s["load"], 0)
        self.assertEqual(s["browse"], 1)
        self.assertTrue(s["used"])

    def test_apply_patch_counts_as_edit_not_load(self):
        patch = (f"*** Begin Patch\n*** Update File: {SKILLS_ROOT}/ghost-skill/SKILL.md\n"
                 "@@\n-old\n+new\n*** End Patch")
        self.write("e.jsonl", [rec(call("apply_patch", patch, ptype="custom_tool_call"))])
        s = self.scan()["skills"]["ghost-skill"]
        self.assertEqual(s["edit"], 1)
        self.assertEqual(s["load"], 0)

    def test_write_tool_counts_as_edit(self):
        self.write("f.jsonl", [
            rec(call("write", {"path": f"{SKILLS_ROOT}/hermes/SKILL.md", "content": "x"})),
        ])
        s = self.scan()["skills"]["hermes"]
        self.assertEqual(s["edit"], 1)
        self.assertEqual(s["load"], 0)

    def test_custom_tool_call_input_is_parsed(self):
        self.write("g.jsonl", [
            rec(call("js", {"code": f"readFileSync('{SKILLS_ROOT}/ui-ux-pro-max/SKILL.md')"},
                     ptype="custom_tool_call")),
        ])
        self.assertEqual(self.scan()["skills"]["ui-ux-pro-max"]["load"], 1)


class FalsePositiveGuardTest(SessionFixture):
    """注入文本与工具输出绝不能被当成使用。"""

    def test_injected_host_skills_list_is_ignored(self):
        # 每个会话都会把全量技能清单注入 developer message：
        # 若按名字/路径 grep，所有技能都会「被使用」。
        injected = ("以下技能可用：taste-skill、never-used、ls-only。"
                    f"清单正文引用 {SKILLS_ROOT}/never-used/SKILL.md")
        self.write("h.jsonl", [
            rec({"type": "message", "role": "developer",
                 "content": [{"type": "input_text", "text": injected}]}),
        ])
        out = self.scan()
        self.assertNotIn("never-used", out["skills"])
        self.assertIn("never-used", out["summary"]["never_used"])

    def test_function_call_output_is_ignored(self):
        # 工具返回内容里常回显其它技能的 SKILL.md 路径。
        self.write("i.jsonl", [
            rec({"type": "function_call_output", "call_id": "call_x",
                 "output": f"File: {SKILLS_ROOT}/never-used/SKILL.md says hello"}),
        ])
        self.assertNotIn("never-used", self.scan()["skills"])

    def test_reasoning_and_event_msg_are_ignored(self):
        self.write("j.jsonl", [
            rec({"type": "reasoning", "summary": f"用 {SKILLS_ROOT}/never-used/SKILL.md 好了"}),
            json.dumps({"timestamp": "2026-05-09T05:19:27.508Z", "ordinal": 1,
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": None}}),
        ])
        out = self.scan()
        self.assertNotIn("never-used", out["skills"])
        self.assertEqual(out["tool_calls"], 0)

    def test_session_meta_line_is_ignored(self):
        self.write("k.jsonl", [
            json.dumps({"timestamp": "2026-05-09T05:19:27.508Z", "ordinal": 0,
                        "type": "session_meta", "payload": {"id": "x"}}),
        ])
        self.assertEqual(self.scan()["tool_calls"], 0)


class RobustnessTest(SessionFixture):
    def test_escaped_forward_slashes_still_match(self):
        # JSON 允许把 / 写成 \/。二次编码的 arguments 里若保留转义，
        # 不归一化就会漏匹配（实测踩过的坑）。
        inner = json.dumps({"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"})
        inner_escaped = inner.replace("/", "\\/")
        self.write("l.jsonl", [
            json.dumps({"timestamp": "2026-05-09T05:19:27.508Z", "ordinal": 0,
                        "type": "response_item",
                        "payload": {"type": "function_call", "name": "exec_command",
                                    "arguments": inner_escaped, "call_id": "c"}}),
        ])
        self.assertEqual(self.scan()["skills"]["taste-skill"]["load"], 1)

    def test_malformed_lines_are_skipped_not_fatal(self):
        self.write("m.jsonl", [
            "{not json at all",
            "",
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"})),
            "null",
        ])
        out = self.scan()
        self.assertEqual(out["skills"]["taste-skill"]["load"], 1)

    def test_missing_dirs_degrade_cleanly(self):
        with tempfile.TemporaryDirectory() as empty:
            out = scan_usage(session_dirs=[str(Path(empty) / "nope")],
                             skills_dir=str(Path(empty) / "alsonope"))
        self.assertEqual(out["scanned_files"], 0)
        self.assertEqual(out["skills"], {})
        self.assertEqual(out["summary"]["installed"], 0)

    def test_hidden_dirs_are_not_skills(self):
        self.assertEqual(
            self.scan()["summary"]["installed_names"],
            ["ghost-skill", "hermes", "ls-only", "never-used", "taste-skill"])


class AggregationTest(SessionFixture):
    def test_sessions_deduped_per_file(self):
        line = rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"}))
        self.write("n.jsonl", [line, line, line])
        s = self.scan()["skills"]["taste-skill"]
        self.assertEqual(s["load"], 3)
        self.assertEqual(s["sessions"], 1)

    def test_timestamps_track_first_and_last(self):
        self.write("o.jsonl", [
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"}),
                ts="2026-07-01T00:00:00.000Z"),
            rec(call("exec_command", {"cmd": f"ls {SKILLS_ROOT}/hermes"}),
                ts="2026-03-01T00:00:00.000Z"),
            rec(call("exec_command", {"cmd": f"head {SKILLS_ROOT}/hermes/SKILL.md"}),
                ts="2026-09-05T12:00:00.000Z"),
        ])
        s = self.scan()["skills"]["hermes"]
        self.assertEqual(s["first_used"], "2026-03-01T00:00:00.000Z")
        self.assertEqual(s["last_used"], "2026-09-05T12:00:00.000Z")

    def test_summary_buckets_installed_skills(self):
        self.write("p.jsonl", [
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"})),
            rec(call("exec_command", {"cmd": f"ls {SKILLS_ROOT}/ls-only/"})),
        ])
        out = self.scan()
        s = out["summary"]
        self.assertEqual(s["installed"], 5)
        self.assertEqual(s["loaded"], 1)                      # taste-skill
        self.assertEqual(s["browse_only"], 1)                 # ls-only
        self.assertEqual(s["never_used"], ["ghost-skill", "hermes", "never-used"])
        self.assertEqual(s["unused_load"], ["ls-only"])

    def test_ranking_sorted_by_load_desc(self):
        lines = [rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"}))] * 3
        lines.append(rec(call("exec_command", {"cmd": f"head {SKILLS_ROOT}/hermes/SKILL.md"})))
        self.write("q.jsonl", lines)
        ranking = self.scan()["ranking"]
        self.assertEqual(ranking[0]["name"], "taste-skill")
        self.assertEqual(ranking[1]["name"], "hermes")

    def test_limit_files_bounds_work(self):
        self.write("r.jsonl", [rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"}))])
        self.write("s.jsonl", [rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"}))])
        self.assertEqual(self.scan(limit_files=1)["scanned_files"], 1)

    def test_tool_breakdown_recorded(self):
        self.write("t.jsonl", [
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"})),
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"})),
            rec(call("spawn_agent", {"items": [{"type": "skill",
                "path": f"{SKILLS_ROOT}/hermes/SKILL.md"}]})),
        ])
        self.assertEqual(self.scan()["skills"]["hermes"]["tools"],
                         {"exec_command": 2, "spawn_agent": 1})


    def test_nested_date_dirs_are_scanned(self):
        # ~/.codex/sessions 实际形态：sessions/2026/09/23/*.jsonl，必须递归命中。
        nested = self.sessions / "2026" / "09" / "23"
        nested.mkdir(parents=True)
        (nested / "rollout-x.jsonl").write_text(
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"})) + "\n",
            encoding="utf-8")
        out = self.scan()
        self.assertEqual(out["skills"]["taste-skill"]["load"], 1)
        self.assertEqual(out["scanned_files"], 1)

    def test_since_window_filters_older_actions(self):
        self.write("v.jsonl", [
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"}),
                ts="2026-01-05T00:00:00.000Z"),
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"}),
                ts="2026-09-10T00:00:00.000Z"),
        ])
        out = self.scan(since="2026-09-01")
        self.assertEqual(out["since"], "2026-09-01")
        self.assertEqual(out["tool_calls"], 1)
        self.assertNotIn("taste-skill", out["skills"])
        self.assertIn("hermes", out["skills"])

    def test_since_drops_records_without_timestamp(self):
        line = json.dumps({"ordinal": 0, "type": "response_item",
                           "payload": call("exec_command", {
                               "cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"})})
        self.write("w.jsonl", [line])
        self.assertEqual(self.scan(since="2026-09-01")["tool_calls"], 0)
        # 不加 since 时仍然计入（无时间戳也能证明「用过」）
        self.assertEqual(self.scan()["skills"]["hermes"]["load"], 1)


class SummarizeTextTest(SessionFixture):
    def test_human_summary_lists_ranking_and_candidates(self):
        self.write("u.jsonl", [
            rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/taste-skill/SKILL.md"})),
        ])
        text = summarize_text(self.scan())
        self.assertIn("数据来源: codex", text)
        self.assertIn("taste-skill", text)
        self.assertIn("零触达（清理候选）", text)
        self.assertIn("never-used", text)


class ScanProgressTest(SessionFixture):
    """扫描进度：总量可算时必须给"准确进度"，不是估算。

    会话文件是先收集完再逐个读的，所以 total 在扫描前就已知 —— 这正是
    GUI 能显示 N/total 而不是只显示秒数的依据。
    """

    def _progress_path(self):
        return str(Path(self._tmp.name) / "progress.json")

    def _read(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def test_reports_exact_total_and_finishes_at_100(self):
        for i in range(6):
            self.write(f"s{i}.jsonl",
                       [rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"}))])
        p = self._progress_path()
        self.scan(progress_path=p)
        last = self._read(p)
        self.assertEqual(last["phase"], "完成")
        self.assertEqual(last["total"], 6)
        self.assertEqual(last["done"], 6)
        self.assertEqual(last["pct"], 100)

    def test_first_progress_reports_total_before_reading(self):
        """总量必须在开扫之初就报出来，否则前端只能一直显示秒数。"""
        for i in range(4):
            self.write(f"t{i}.jsonl", [rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"}))])
        p = self._progress_path()
        self.scan(progress_path=p)
        self.assertEqual(self._read(p)["total"], 4)

    def test_no_progress_file_when_not_requested(self):
        """不传 progress_path 时不得凭空写盘：统计是只读出口。"""
        self.write("a.jsonl", [rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"}))])
        before = sorted(x.name for x in Path(self._tmp.name).iterdir())
        self.scan()
        after = sorted(x.name for x in Path(self._tmp.name).iterdir())
        self.assertEqual(before, after)

    def test_progress_write_failure_does_not_break_scan(self):
        """进度只是过程信号：写不进去（如目录不存在）也必须照常出结论。"""
        self.write("a.jsonl", [rec(call("exec_command", {"cmd": f"cat {SKILLS_ROOT}/hermes/SKILL.md"}))])
        out = self.scan(progress_path=str(Path(self._tmp.name) / "no-such-dir" / "p.json"))
        self.assertEqual(out["skills"]["hermes"]["load"], 1)


if __name__ == "__main__":
    unittest.main()
