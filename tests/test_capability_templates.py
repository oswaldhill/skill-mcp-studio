import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from capability_templates import (  # noqa: E402
    TemplateError,
    load_templates,
    resolve_capabilities,
)


class LoadTemplatesTest(unittest.TestCase):
    def test_no_templates_returns_empty(self):
        self.assertEqual(load_templates({}), {})

    def test_loads_builtin_templates(self):
        config = {
            "templates": {
                "memory-basic": {"capabilities": {"memory": ["memory_search"]}},
            }
        }
        templates = load_templates(config)
        self.assertIn("memory-basic", templates)
        self.assertEqual(
            templates["memory-basic"]["capabilities"]["memory"], ["memory_search"]
        )

    def test_empty_capabilities_fails(self):
        with self.assertRaises(TemplateError):
            load_templates({"templates": {"bad": {"capabilities": {}}}})

    def test_non_list_tools_fails(self):
        with self.assertRaises(TemplateError):
            load_templates(
                {"templates": {"bad": {"capabilities": {"g": "not-a-list"}}}}
            )

    def test_empty_group_name_fails(self):
        with self.assertRaises(TemplateError):
            load_templates(
                {"templates": {"bad": {"capabilities": {"": ["tool"]}}}}
            )


class ResolveCapabilitiesTest(unittest.TestCase):
    TEMPLATES = {
        "a": {"tags": [], "capabilities": {"mem": ["m1", "m2"]}},
        "b": {"tags": [], "capabilities": {"mem": ["m2", "m3"], "extra": ["e1"]}},
    }

    def test_no_extends_returns_handwritten_unchanged(self):
        profile = {"required_capabilities": {"mem": ["m1"]}}
        self.assertEqual(
            resolve_capabilities(profile, self.TEMPLATES), {"mem": ["m1"]}
        )

    def test_empty_required_returns_empty(self):
        self.assertEqual(resolve_capabilities({}, self.TEMPLATES), {})
        self.assertEqual(
            resolve_capabilities({"required_capabilities": {}}, self.TEMPLATES), {}
        )

    def test_extends_unions_groups_across_templates(self):
        profile = {"required_capabilities": {"extends": ["a", "b"]}}
        result = resolve_capabilities(profile, self.TEMPLATES)
        self.assertEqual(result["mem"], ["m1", "m2", "m3"])
        self.assertEqual(result["extra"], ["e1"])

    def test_handwritten_overrides_template_group(self):
        profile = {
            "required_capabilities": {"extends": ["a"], "mem": ["override"]}
        }
        result = resolve_capabilities(profile, self.TEMPLATES)
        self.assertEqual(result["mem"], ["override"])

    def test_single_string_extends(self):
        profile = {"required_capabilities": {"extends": "a"}}
        result = resolve_capabilities(profile, self.TEMPLATES)
        self.assertEqual(result["mem"], ["m1", "m2"])

    def test_unknown_template_fails(self):
        with self.assertRaises(TemplateError) as ctx:
            resolve_capabilities(
                {"required_capabilities": {"extends": ["nope"]}}, self.TEMPLATES
            )
        self.assertIn("nope", str(ctx.exception))


def _write(dirpath: Path, name: str, text: str) -> None:
    (dirpath / name).write_text(text, encoding="utf-8")


class DirTemplatesTest(unittest.TestCase):
    """用户/项目模板目录：装载、优先级与 fail-fast（评审 CLI-4 + 阶段二 §14.1）。"""

    def test_user_dir_template_overrides_inline(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp)
            _write(user, "mem.yaml", "capabilities:\n  memory: [from_user]\n")
            config = {
                "templates": {"mem": {"capabilities": {"memory": ["from_inline"]}}}
            }
            templates = load_templates(config, user_dir=str(user))
            self.assertEqual(
                templates["mem"]["capabilities"]["memory"], ["from_user"]
            )

    def test_project_dir_loaded_and_priority_user_gt_project_gt_inline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "proj"
            user = root / "user"
            proj.mkdir()
            user.mkdir()
            # 仅项目目录有的模板
            _write(proj, "shared.yaml", "capabilities:\n  g: [proj_tool]\n")
            # 同名：用户覆盖项目，项目覆盖内置
            _write(proj, "dup.yaml", "capabilities:\n  g: [proj_dup]\n")
            _write(user, "dup.yaml", "capabilities:\n  g: [user_dup]\n")
            config = {
                "templates": {"dup": {"capabilities": {"g": ["inline_dup"]}}}
            }
            templates = load_templates(
                config, user_dir=str(user), project_dir=str(proj)
            )
            self.assertEqual(templates["shared"]["capabilities"]["g"], ["proj_tool"])
            self.assertEqual(templates["dup"]["capabilities"]["g"], ["user_dup"])

    def test_malformed_yaml_fails_fast_with_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "broken.yaml", "capabilities: [unclosed\n")
            with self.assertRaises(TemplateError) as ctx:
                load_templates({}, user_dir=tmp)
            self.assertIn("broken.yaml", str(ctx.exception))

    def test_valid_yaml_without_capabilities_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "notemplate.yaml", "foo: bar\n")
            with self.assertRaises(TemplateError) as ctx:
                load_templates({}, user_dir=tmp)
            self.assertIn("notemplate.yaml", str(ctx.exception))

    def test_invalid_template_body_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "badgroup.yaml", "capabilities:\n  '': [t]\n")
            with self.assertRaises(TemplateError):
                load_templates({}, user_dir=tmp)

    def test_malformed_project_dir_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "broken.yml", ":::\n")
            with self.assertRaises(TemplateError) as ctx:
                load_templates({}, project_dir=tmp)
            self.assertIn("broken.yml", str(ctx.exception))

    def test_non_yaml_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "README.md", "capabilities: [oops\n")
            _write(Path(tmp), "notes.txt", "anything\n")
            self.assertEqual(load_templates({}, user_dir=tmp), {})

    def test_multiple_offenders_all_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "a.yaml", "foo: bar\n")
            _write(Path(tmp), "b.yaml", "capabilities: [unclosed\n")
            with self.assertRaises(TemplateError) as ctx:
                load_templates({}, user_dir=tmp)
            message = str(ctx.exception)
            self.assertIn("a.yaml", message)
            self.assertIn("b.yaml", message)


if __name__ == "__main__":
    unittest.main()