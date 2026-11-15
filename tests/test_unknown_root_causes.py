"""两个「未知」根因的修复（2026-11-15）。

实测本机最后剩的 2 个 unknown，都不是真的查不了：

1. `code-simplifier`：来源 `simonwong/agent-skills` 改名了。GitHub API 返回
   **301 重定向**（不是 404），但 `_http_get_json` 的 curl 没带 `-L`，
   于是把「改名」读成了「仓库不存在」。上游 npx skills 同样误报为
   "Private or deleted repo"。
2. `lark-unified`：仓库形态判定里 `_skillhub_meta.json` 被算作「本地未提交修改」。
   但该文件只记录本机绝对路径（`iconLocalPath: /Users/<某用户>/...`），
   在另一台机器上被自动改写是**必然**，与技能内容无关。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))


class RedirectTest(unittest.TestCase):
    def test_http_get_json_follows_redirect(self):
        """curl 必须带 -L，否则 301（仓库改名）会被当成失败。"""
        import inspect
        import skill_market
        src = inspect.getsource(skill_market._http_get_json)
        self.assertIn('"-L"', src,
                      "_http_get_json 的 curl 缺少 -L：仓库改名(301)会被误判为不存在")

    def test_urllib_fallback_follows_redirect(self):
        """urllib 回退路径同样要处理重定向。"""
        import inspect
        import skill_market
        src = inspect.getsource(skill_market._http_get_json)
        # urlopen 本身跟随重定向，但需确认没有被 HTTPError 分支提前吞掉 301
        self.assertIn("urlopen", src)


class MachineMetaFilterTest(unittest.TestCase):
    """本机元数据不得算作「本地未提交修改」。"""

    def test_machine_meta_files_are_ignored(self):
        from skill_repo_source import MACHINE_LOCAL_FILES, filter_machine_local

        paths = [
            "lark-unified/_skillhub_meta.json",
            "lark-doc/SKILL.md",
            "_core/README.md",
        ]
        kept, dropped = filter_machine_local(paths)
        self.assertIn("lark-unified/_skillhub_meta.json", dropped)
        self.assertIn("lark-doc/SKILL.md", kept)
        self.assertIn(_MEMBER := "_core/README.md", kept)
        self.assertIn("_skillhub_meta.json", MACHINE_LOCAL_FILES)

    def test_filter_handles_rename_syntax(self):
        from skill_repo_source import filter_machine_local
        kept, dropped = filter_machine_local(
            ["lark-unified/{old.json => _skillhub_meta.json}"])
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)

    def test_all_machine_meta_means_not_dirty(self):
        """整批都是本机元数据时，过滤后应为空 —— 即「不脏」。"""
        from skill_repo_source import filter_machine_local
        kept, _ = filter_machine_local(["lark-unified/_skillhub_meta.json"])
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
