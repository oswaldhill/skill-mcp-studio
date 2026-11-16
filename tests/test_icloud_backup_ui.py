"""iCloud 备份卡片的界面契约（2026-11-16）。

## 守什么、不守什么

只守这张卡片的**顶层不变量**（规则见项目 AGENTS 的双轨约定）：

- 卡片容器与三个动作入口存在，且动作名与 `handleAction` 分发一致；
- 恢复按钮必须带 `data-id`（否则点下去拿不到备份 id，只能报错）；
- 状态行与列表容器存在（异步加载的挂载点）；
- 字号/间距必须走 token，不写死 px；
- 说明文案必须保留「含明文密钥」的警示 —— 这是安全边界，不能因改文案而丢。

不守内部 class 名与排版细节（那些由 `test_design_spec_contract` 的通用门禁覆盖）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "gui" / "dashboard.html"


class IcloudBackupCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = DASHBOARD.read_text(encoding="utf-8")

    def test_card_container_exists(self):
        self.assertIn('id="icloud-backup-card"', self.html)

    def test_card_is_rendered_into_settings_panel(self):
        """卡片变量必须真的被插进设置面板，否则定义了也看不见。"""
        self.assertIn("${icloudBackupCard}", self.html)
        panel = re.search(
            r'data-panel="appearance">(.*?)</div>`', self.html, re.S
        )
        self.assertIsNotNone(panel)
        self.assertIn("${icloudBackupCard}", panel.group(1))

    def test_three_actions_present(self):
        for action in ("icloud-backup", "restore-icloud-backup", "prune-icloud-backups"):
            self.assertIn(f'data-action="{action}"', self.html, f"缺少动作入口: {action}")

    def test_actions_are_dispatched(self):
        """按钮有了但没接线 = 点了没反应，所以分发必须一起断言。"""
        for action in ("icloud-backup", "restore-icloud-backup", "prune-icloud-backups"):
            self.assertRegex(
                self.html,
                rf'else if \(a === "{re.escape(action)}"\)',
                f"动作 {action} 未在 handleAction 里分发",
            )

    def test_restore_button_carries_backup_id(self):
        """恢复按钮必须带 data-id —— 否则拿不到要恢复哪一份。"""
        match = re.search(
            r'data-action="restore-icloud-backup"[^>]*data-id="\$\{escapeHtml\(it\.id\)\}"',
            self.html,
        )
        self.assertIsNotNone(match, "恢复按钮缺少 data-id 绑定")

    def test_status_mount_points_exist(self):
        self.assertIn('id="icloud-backup-status-line"', self.html)
        self.assertIn('id="icloud-backup-list"', self.html)

    def test_status_loader_is_called_after_render(self):
        """状态加载必须在 renderSettings 里触发，否则永远显示「加载中」。"""
        self.assertIn("loadIcloudBackupStatus();", self.html)

    def test_uses_design_tokens_not_literal_px(self):
        """卡片内联样式不得写死 px 字号（项目 token 纪律）。"""
        card = re.search(
            r'const icloudBackupCard = `(.*?)`;', self.html, re.S
        )
        self.assertIsNotNone(card, "找不到 icloudBackupCard 定义")
        body = card.group(1)
        literal_font = re.findall(r"font-size:\s*\d+px", body)
        self.assertEqual([], literal_font, f"字号写死 px：{literal_font}")
        self.assertIn("var(--fs-sm)", body)

    def test_warns_about_plaintext_secrets(self):
        """安全警示是硬约束：备份含明文密钥，文案不能丢这条。"""
        card = re.search(r'const icloudBackupCard = `(.*?)`;', self.html, re.S)
        self.assertIsNotNone(card)
        self.assertIn("明文密钥", card.group(1))
        self.assertIn("请勿分享", card.group(1))

    def test_points_share_export_to_export_card(self):
        """换机/分享必须指向「导出配置」（脱敏），不能让人拿备份去分享。"""
        card = re.search(r'const icloudBackupCard = `(.*?)`;', self.html, re.S)
        self.assertIn("导出配置", card.group(1))


class IcloudBackupCliWiringTest(unittest.TestCase):
    """GUI 经 run_cli 调用的命令必须在 Rust 白名单内，否则一点就被拦。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lib = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    def test_cli_flags_are_allowlisted(self):
        for flag in (
            "--icloud-backup",
            "--icloud-backup-status",
            "--list-icloud-backups",
            "--restore-icloud-backup",
            "--prune-icloud-backups",
            "--keep",
        ):
            self.assertIn(f'"{flag}"', self.lib, f"{flag} 未登记进 run_cli 白名单")


if __name__ == "__main__":
    unittest.main()