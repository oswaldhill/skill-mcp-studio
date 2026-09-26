"""P0-1 回归：release-notes.yml 依赖的 CHANGELOG 契约必须常驻可测。

`release-notes.yml` 在三个平台构建完成后，用正则从 CHANGELOG.md 抽取
「当前 tag 对应的段落」写进 GitHub Release 正文（方案 B：不再由三个平台各自
generate_release_notes）。它对 CHANGELOG 有两条硬要求：

1. 必须存在 `## [v<version.json 的 version>]` 标题；
2. 该段落正文非空。

原先这两条只在**发布那一刻**由 release.sh 校验；平时改 version.json 却忘了补
CHANGELOG 段落，要到打 tag 后 workflow 失败才发现。本测试把它提前到日常 CI。

抽取正则与 workflow 中那段保持**逐字一致**（含 lookahead 到下一个 `## [`），
否则测试通过而 workflow 失败，等于没测。
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 与 .github/workflows/release-notes.yml 的提取步骤同一形态。
SECTION_RE_TEMPLATE = r"^## \[v{ver}\][^\n]*\n(.*?)(?=^## \[|\Z)"


def _extract(version: str, text: str):
    pat = re.compile(SECTION_RE_TEMPLATE.format(ver=re.escape(version)), re.M | re.S)
    m = pat.search(text)
    return None if m is None else m.group(1).strip()


class ChangelogReleaseSectionTest(unittest.TestCase):
    def setUp(self):
        self.changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.version = json.loads(
            (ROOT / "version.json").read_text(encoding="utf-8")
        )["version"]

    def test_current_version_has_section(self):
        """version.json 的版本必须在 CHANGELOG 里有对应标题。"""
        body = _extract(self.version, self.changelog)
        self.assertIsNotNone(
            body,
            f"CHANGELOG.md 缺少 `## [v{self.version}]` 段落；"
            "release-notes.yml 会因此 sys.exit 失败，Release 正文写不进去。",
        )

    def test_current_version_section_not_empty(self):
        """该段落正文不能为空 —— workflow 对空段落同样会失败。"""
        body = _extract(self.version, self.changelog)
        self.assertIsNotNone(body, "段落缺失（见上一个用例）")
        self.assertTrue(
            body.strip(),
            f"CHANGELOG.md 中 v{self.version} 的段落是空的；"
            "workflow 会以「正文段落是空的」失败。",
        )

    def test_extraction_stops_at_next_version_heading(self):
        """抽取必须在下一个 `## [` 处停止，否则会把后续版本内容也写进 Release。"""
        body = _extract(self.version, self.changelog)
        self.assertIsNotNone(body, "段落缺失")
        for line in body.splitlines():
            self.assertFalse(
                line.startswith("## ["),
                "抽取越过了下一个版本标题，说明 lookahead 失效："
                f"遇到 {line[:40]!r}",
            )

    def test_unreleased_section_present(self):
        """`## [Unreleased]` 是变更记录的常驻入口，缺失说明 CHANGELOG 结构被破坏。"""
        self.assertIn("## [Unreleased]", self.changelog)


if __name__ == "__main__":
    unittest.main()
