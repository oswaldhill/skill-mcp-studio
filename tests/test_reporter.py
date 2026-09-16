import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from reporter import write_markdown_report  # noqa: E402


class MarkdownReporterTest(unittest.TestCase):
    def test_combined_mcp_state_is_written_to_same_report(self):
        scan_result = {
            "unified_dir": "~/.skills-manager/skills",
            "results": [],
            "summary": {},
        }
        combined = {
            "endpoint": "https://mcp.example.com/mcp",
            "probe": {"error": "not probed"},
            "summary": {
                "installed": 1,
                "skills_compliant": 1,
                "mcp_configured": 1,
                "mcp_connected": 1,
                "full_capabilities": 1,
                "hooks_configured": 0,
                "legacy_channels": 1,
            },
            "capability_groups": ["hermes_memory", "ai_memory", "tdai", "hermes"],
            "records": [{
                "name": "Reasonix",
                "installed": True,
                "skills_compliant": True,
                "mcp_configured": True,
                "mcp_initialize_ok": True,
                "mcp_tools_list_ok": True,
                "capabilities": {
                    "hermes_memory": True,
                    "ai_memory": True,
                    "tdai": True,
                    "hermes": True,
                },
                "hooks_configured": False,
                "legacy_channels": ["hermes-gateway"],
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.md"
            write_markdown_report(scan_result, str(path), combined)
            text = path.read_text(encoding="utf-8")

        self.assertIn("## IDE / Agent Unified MCP", text)
        self.assertIn("https://mcp.example.com/mcp", text)
        self.assertIn("| Reasonix | True | True | True |", text)
        self.assertIn("Hermes memory | AI memory | TDAI | Hermes", text)
        self.assertIn("hermes-gateway", text)


if __name__ == "__main__":
    unittest.main()
