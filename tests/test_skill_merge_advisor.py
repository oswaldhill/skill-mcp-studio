"""FEAT-11 判据测试。

重点不是"正例能不能成组"，而是**真实数据抓到的假阳性必须被拦住**：
`sensteed-java8-standard` × `sensteed-java17-standard` 的描述 token 相似度为 1.00，
是判据最容易上钩的形态（按 Java 版本分工的平行分册，合并会毁掉版本路由）。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import skill_merge_advisor as M          # noqa: E402


def meta(name, desc="", upstream=False, load=0, sessions=0, last_used=None,
         has_scripts=False, has_license=False, lock_coverage=0.0, source=None):
    return {"name": name, "description": desc, "upstream": upstream, "load": load,
            "sessions": sessions, "last_used": last_used, "has_scripts": has_scripts,
            "has_license": has_license, "lock_coverage": lock_coverage, "source": source}


LONG_A = ("统一的 IMA OpenAPI 技能，支持笔记管理和知识库操作。当用户提到知识库、资料库、"
          "笔记、备忘录、记事，或者想要上传文件、添加网页到知识库、搜索知识库内容时，"
          "使用此 skill。即使用户没有明确说知识库或笔记，只要意图涉及文件上传到知识库、"
          "网页收藏、知识搜索、个人文档存取，也应触发此 skill。")
LONG_B = ("山子高科 sensteed 开发规范代码审核技能之一：Android（Kotlin/Java）代码规范"
          "符合性审核。依据 sensteed 开发规范体系对代码进行审查。适用于审核代码、代码评审、"
          "code review、规范检查。只管 Android 原生 App 及组件 SDK。")
LONG_C = ("山子高科 sensteed 开发规范代码审核技能之一：iOS（Swift）代码规范符合性审核。"
          "依据 sensteed 开发规范体系对代码进行审查。适用于审核代码、代码评审、code review、"
          "规范检查。只管 iOS 原生 App 及 Swift 组件 SDK。")
STD8 = ("Apply or audit the Sensteed Java 8 microservice standard for Java 8, Spring Boot "
        "2.7, Spring Cloud 2021, Maven, security, testing, observability, and deployment "
        "work. Use only when a project is confirmed to target Java 8.")
STD17 = ("Apply or audit the Sensteed Java 17 microservice standard for Java 17, Spring Boot "
         "3.5, Spring Cloud 2025, Maven, security, testing, observability, and deployment "
         "work. Use only when a project is confirmed to target Java 17.")


class TextNormalizationTest(unittest.TestCase):
    def test_norm_ignores_punctuation_and_case(self):
        self.assertEqual(M._norm_desc("Foo, BAR!\n baz"), M._norm_desc("foo bar baz"))

    def test_stem_merges_plural_and_gerund(self):
        for n in ("grafana-dashboards", "grafana-dashboarding"):
            self.assertEqual(M._stem_name(n), "grafana-dashboard", n)
        self.assertEqual(M._stem_name("grafana-dashboard"), "grafana-dashboard")

    def test_stem_protects_short_segments(self):
        """长度下限是必需的：oss 剥 s 会变成 os，doc 剥 s 会变成 do。"""
        self.assertEqual(M._stem_name("grafana-oss"), "grafana-oss")
        self.assertEqual(M._stem_name("wecomcli-doc"), "wecomcli-doc")

    def test_substantive_detects_any_digit_token(self):
        self.assertIn("java8", M._substantive_tokens("sensteed-java8-standard"))
        self.assertIn("v2", M._substantive_tokens("tool-v2"))
        self.assertEqual(M._substantive_tokens("grafana-dashboard"), set())

    def test_alias_target_requires_both_markers(self):
        self.assertEqual(
            M._alias_target("仅当用户显式指定 lark-note 时使用，相关请求统一交由 "
                            "lark-meeting 技能处理。"), "lark-meeting")
        # 只有"统一交由"而无"仅当"：正常技能里的路由提示，不是转发壳
        self.assertIsNone(M._alias_target(
            "搜索表格文件请统一交由 lark-drive 处理，本技能负责表格内容操作。"))
        self.assertIsNone(M._alias_target("普通描述，没有任何转发声明。"))


class RulePositiveTest(unittest.TestCase):
    def test_T1_identical_description_groups(self):
        a, b, c = (meta("ima", LONG_A), meta("ima-skill", LONG_A), meta("other", LONG_B))
        act, ups, rej = M._pairs_by_rules([a, b, c])
        self.assertEqual(len(act), 1)
        self.assertEqual(act[0]["rule"], "T1")
        self.assertEqual(sorted(act[0]["members"]), ["ima", "ima-skill"])
        self.assertFalse(ups)
        self.assertFalse(rej)

    def test_T1_requires_length(self):
        """归一后过短的相同描述（如两个字）不足以判定同一份内容。"""
        act, _, _ = M._pairs_by_rules([meta("x1", "邮件管理"), meta("x2", "邮件管理")])
        self.assertEqual(act, [])

    def test_T2_uses_declared_target_as_keep(self):
        """T2 的保留者必须由壳自己指定，不能被 load 打分反过来抢走。"""
        shell = meta("lark-minutes",
                     "仅当用户或上游配置显式指定 lark-minutes 时使用，相关请求统一交由 "
                     "lark-meeting 技能处理。")
        tgt = meta("lark-meeting",
                   "飞书视频会议：预约会议、查询会议列表、获取会议详情、管理参会成员。"
                   "当用户需要创建会议、查看会议、取消会议时使用本技能。", load=77)
        act, _, rej = M._pairs_by_rules([shell, tgt])
        self.assertEqual(len(act), 1, rej)
        self.assertEqual(act[0]["rule"], "T2")
        self.assertEqual(act[0]["keep"], "lark-meeting")
        self.assertEqual(act[0]["fold"], ["lark-minutes"])
        self.assertEqual(act[0]["fold_into"], "lark-meeting")

    def test_T2_missing_target_is_dangling_defect(self):
        """目标不存在时不是合并机会而是悬空引用，必须落 rejected。"""
        shell = meta("lark-note",
                     "仅当用户或上游配置显式指定 lark-note 时使用，相关请求统一交由 "
                     "lark-meeting 技能处理。", upstream=True)
        act, ups, rej = M._pairs_by_rules([shell])
        self.assertEqual(act, [])
        self.assertEqual(ups, [], "悬空判定优先于上游分流，不得被判进 upstream_only")
        kinds = {r["kind"] for r in rej}
        self.assertEqual(kinds, {"dangling_alias"})
        self.assertFalse(rej[0]["fold_into_exists"])
        self.assertIn("lark-meeting", rej[0]["verdict"])

    def test_T3_stem_triple_becomes_one_group(self):
        m = [meta("grafana-dashboard", "A"), meta("grafana-dashboards", "B"),
             meta("grafana-dashboarding", "C")]
        act, _, _ = M._pairs_by_rules(m)
        self.assertEqual(len(act), 1, "三兄弟必须合成 1 组，不能列成 3 对")
        self.assertEqual(len(act[0]["members"]), 3)
        self.assertEqual(act[0]["rule"], "T3")
        self.assertEqual(sorted(act[0]["fold"]), ["grafana-dashboard", "grafana-dashboards"]
                         if act[0]["keep"] == "grafana-dashboarding" else
                         sorted(set(act[0]["members"]) - {act[0]["keep"]}))

    def test_T4_needs_similar_but_not_identical(self):
        """T4 的用武之地：同一件事换个说法（措辞不同但高度相似）。"""
        d1 = ("Create and manage production-ready Grafana dashboards for comprehensive "
              "system observability, panel configuration and operational insights.")
        d2 = ("Build and manage production Grafana dashboards for system observability, "
              "panel configuration, visualization and operational insights daily.")
        act, _, _ = M._pairs_by_rules([meta("foo", d1), meta("foo-skill", d2)])
        self.assertTrue(act, "名称差异仅为噪声后缀 -skill 时应成组")
        self.assertEqual(act[0]["rule"], "T4", "措辞不同不该被判成 T1")

    def test_T4_works_for_chinese_descriptions(self):
        """中文技能必须也能被 T4 捞到：bigram 分词就是为此而加。"""
        d1 = "飞书电子表格：创建和操作电子表格，支持工作表与行列结构的增删合并与隐藏冻结。"
        d2 = "飞书电子表格：创建并操作电子表格，管理工作表与行列结构，支持增删合并及隐藏冻结。"
        self.assertGreater(M._jaccard(M._desc_tokens(d1), M._desc_tokens(d2)), 0.6)
        act, _, _ = M._pairs_by_rules([meta("lark-sheets", d1),
                                       meta("lark-sheets-unified", d2)])
        self.assertTrue(act, "中文近重复描述应成组，T4 对中文失效即为回归")

    def test_one_skill_lives_in_one_group(self):
        """同一对被 T1 与 T4 同时命中时不得产生两个组。"""
        d = ("统一的 IMA OpenAPI 技能，支持笔记管理和知识库操作，上传文件、添加网页到"
             "知识库、搜索知识库内容、创建与编辑笔记。")
        d2 = ("统一的 IMA OpenAPI 技能，支持笔记管理与知识库操作，上传文件、添加网页进"
              "知识库、检索知识库内容、创建以及编辑笔记。")
        m = [meta("ima", d), meta("ima-skill", d), meta("ima-unified", d2)]
        act, _, _ = M._pairs_by_rules(m)
        self.assertEqual(len(act), 1)
        self.assertEqual(len(act[0]["members"]), 3)
        self.assertEqual(act[0]["rule"], "T1", "组规则取最强命中")
        self.assertIn("T4", act[0]["rules_hit"], "其余命中规则要留痕")


class SubstantiveGuardTest(unittest.TestCase):
    """这些是判据的全部价值所在：高相似但必须不合并。"""

    def _names(self, rej):
        return {tuple(sorted(r["members"])) for r in rej}

    def test_version_split_is_blocked_not_merged(self):
        act, ups, rej = M._pairs_by_rules([meta("sensteed-java8-standard", STD8),
                                           meta("sensteed-java17-standard", STD17)])
        self.assertEqual(act, [], "版本号分册被建议合并即为误报")
        self.assertEqual(ups, [])
        self.assertIn(("sensteed-java17-standard", "sensteed-java8-standard"),
                      self._names(rej))
        hit = [r for r in rej if r["kind"] == "variant"][0]
        self.assertGreater(hit["jaccard"], 0.6, "它确实高相似，才会被误捞")
        self.assertTrue(any(t.isdigit() or "java" in t for t in hit["blocked_by"]),
                        hit["blocked_by"])

    def test_language_review_split_is_blocked(self):
        act, _, rej = M._pairs_by_rules([meta("sensteed-android-review", LONG_B),
                                          meta("sensteed-ios-review", LONG_C)])
        self.assertEqual(act, [])
        blocked = [r for r in rej if r["kind"] == "variant"][0]["blocked_by"]
        self.assertIn("review", blocked)
        self.assertTrue({"android", "ios"} & set(blocked), blocked)

    def test_implementation_surface_is_blocked(self):
        d = ("Configure Grafana OSS dashboards from YAML, set up data sources Prometheus "
             "Loki Tempo Pyroscope, mint service-account tokens and validate each step.")
        act, _, rej = M._pairs_by_rules([meta("grafana-oss", d),
                                          meta("grafana-openapi", d[:150] + " openapi")])
        self.assertEqual(act, [])
        self.assertTrue(any(r["kind"] == "variant" for r in rej))

    def test_blocked_token_must_come_from_names_not_noise(self):
        """实质限定词优先：差异里同时有噪声词和实质词时，仍须否决。"""
        d1 = ("Apply or audit the Sensteed microservice standard for Maven security "
              "testing observability and deployment work with Spring Boot and Cloud.")
        d2 = ("Apply or audit the Sensteed microservice standard for Maven security, "
              "testing, observability and deployment work, using Spring Boot & Cloud.")
        act, _, rej = M._pairs_by_rules([meta("std-java8", d1),
                                          meta("std-java8-skill", d2)])
        self.assertEqual(act, [], "同时含 -skill 噪声与 java8 版本词时必须否决")
        self.assertTrue(any(r["kind"] == "variant" for r in rej))


class UpstreamRoutingTest(unittest.TestCase):
    def test_all_upstream_goes_to_annotation_only(self):
        d = ("Autonomously navigate websites and extract structured data across pages, "
             "handling navigation and no suitable ready-made workflow. Use for clicks.")
        m = [meta("firecrawl-agent", d, upstream=True, source="x/y"),
             meta("firecrawl-agent-pro", d[:190])]
        m[1]["upstream"] = True
        m[1]["source"] = "x/y"
        act, ups, rej = M._pairs_by_rules(m)
        self.assertEqual(act, [], "含上游成员的组不得进 actionable")
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]["sources"]["firecrawl-agent"], "x/y")

    def test_mixed_source_goes_to_rejected_with_verdict(self):
        d = LONG_A
        act, ups, rej = M._pairs_by_rules([meta("ima", d, upstream=True),
                                            meta("ima-skill", d)])
        self.assertEqual(act, [])
        self.assertEqual(ups, [])
        self.assertEqual([r["kind"] for r in rej], ["mixed_source"])
        self.assertIn("选边", rej[0]["verdict"])

    def test_self_held_group_is_actionable(self):
        """不在 lock 里就是自持：带 LICENSE 也允许给合并建议（升级不会拉回）。"""
        act, _, _ = M._pairs_by_rules([meta("foo", LONG_A, has_license=True),
                                        meta("foo-skill", LONG_A)])
        self.assertEqual(len(act), 1)


class KeepScoringTest(unittest.TestCase):
    def setUp(self):
        self.d1 = LONG_A
        self.d2 = LONG_A + " 额外补充一句更长的描述以增加信息量。"

    def test_load_wins_first(self):
        m = [meta("a-aaa", self.d1, load=0), meta("a-zzz", self.d1, load=9)]
        act, _, _ = M._pairs_by_rules(m)
        self.assertEqual(act[0]["keep"], "a-zzz", "在用者优先保留")

    def test_description_length_next(self):
        """用"同内容仅多标点"隔离长度这一档：归一后仍相同（T1 成组），原始长度有别。

        若改用两段措辞不同的文本，就会引入 T4 的名称噪声门槛与 0.6 阈值两个额外
        变量，测的就不再是 tiebreak 本身。
        """
        m = [meta("b-aaa", self.d1), meta("b-zzz", self.d1 + "！！！")]
        act, _, _ = M._pairs_by_rules(m)
        self.assertEqual(len(act), 1, "归一后逐字相同，必须成组")
        self.assertEqual(act[0]["keep"], "b-zzz", "load 相同时信息量大的优先")

    def test_scripts_then_lexical(self):
        m = [meta("c-aaa", self.d1, has_scripts=False),
             meta("c-bbb", self.d1, has_scripts=True)]
        act, _, _ = M._pairs_by_rules(m)
        self.assertEqual(act[0]["keep"], "c-bbb", "内容更完整的优先")
        m2 = [meta("d-zzz", self.d1), meta("d-aaa", self.d1)]
        act2, _, _ = M._pairs_by_rules(m2)
        self.assertEqual(act2[0]["keep"], "d-aaa", "全同则字典序兜底保证确定性")

    def test_fold_lists_the_rest(self):
        m = [meta("e-one", self.d1, load=3), meta("e-two", self.d1),
             meta("e-three", self.d1)]
        act, _, _ = M._pairs_by_rules(m)
        self.assertEqual(act[0]["fold"], ["e-three", "e-two"])
        self.assertNotIn(act[0]["keep"], act[0]["fold"])


class OutputContractTest(unittest.TestCase):
    def _payload(self):
        d = LONG_A
        return M._pairs_by_rules([
            meta("ima", d, load=21, sessions=12, last_used="2026-09-23T06:59:20.299Z"),
            meta("ima-skill", d, load=2, sessions=2),
            meta("sensteed-java8-standard", STD8),
            meta("sensteed-java17-standard", STD17)])

    def test_member_fields_complete(self):
        """缺一字段就剥夺人工核验能力。"""
        act, _, _ = self._payload()
        need = {"name", "upstream", "load", "sessions", "last_used",
                "has_scripts", "has_license", "lock_coverage"}
        for g in act:
            for d in g["detail"]:
                self.assertTrue(need <= set(d), need - set(d))

    def test_three_lists_are_mutually_exclusive(self):
        act, ups, rej = self._payload()
        in_act = {tuple(sorted(g["members"])) for g in act}
        in_ups = {tuple(sorted(g["members"])) for g in ups}
        for r in rej:
            pair = tuple(sorted(r["members"]))
            self.assertNotIn(pair, in_act, "同一对既建议合并又被否决，判据自相矛盾")
            self.assertNotIn(pair, in_ups)

    def test_output_is_deterministic(self):
        """同输入两次调用必须逐字节一致，否则 GUI 每次刷新都会跳行。"""
        a1, u1, r1 = self._payload()
        a2, u2, r2 = self._payload()
        self.assertEqual(json.dumps(a1, sort_keys=True, ensure_ascii=False),
                         json.dumps(a2, sort_keys=True, ensure_ascii=False))
        self.assertEqual(json.dumps(r1, sort_keys=True, ensure_ascii=False),
                         json.dumps(r2, sort_keys=True, ensure_ascii=False))
        self.assertEqual([g["id"] for g in a1], [g["id"] for g in a2])

    def test_ids_are_stable_and_sequential(self):
        act, _, _ = self._payload()
        self.assertEqual([g["id"] for g in act], [f"grp-{i:02d}" for i in range(1, len(act) + 1)])

    def test_sessions_field_has_variance(self):
        """防再次引入 `clients` 那种"每个技能取值都一样"的空字段。"""
        act, _, _ = self._payload()
        vals = [d["sessions"] for g in act for d in g["detail"]]
        self.assertGreater(len(set(vals)), 1, f"sessions 无方差即空字段: {vals}")


class LoadMetasTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _skill(self, name, desc, extra_files=()):
        d = self.root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n---\n\n正文\n", encoding="utf-8")
        for f in extra_files:
            (d / f).write_text("x", encoding="utf-8")
        return d

    def test_reads_description_and_flags(self):
        self._skill("alpha", LONG_A, extra_files=("LICENSE",))
        self._skill("alpha-skill", LONG_A)
        self._skill("beta", LONG_B)
        (self.root / "beta" / "scripts").mkdir()
        installed = [{"name": "alpha", "registered": True, "source": "o/r"},
                     {"name": "alpha-skill", "registered": False, "source": None}]
        metas = M.load_metas(skills_dir=self.root, usage={}, installed=installed)
        by = {m["name"]: m for m in metas}
        self.assertEqual(by["alpha"]["description"], " ".join(LONG_A.split()))
        self.assertTrue(by["alpha"]["upstream"])
        self.assertFalse(by["alpha-skill"]["upstream"])
        self.assertTrue(by["alpha"]["has_license"])
        self.assertFalse(by["alpha-skill"]["has_license"])
        self.assertTrue(by["beta"]["has_scripts"], "references/ 也算，见 load_metas")
        self.assertEqual(by["alpha"]["source"], "o/r")
        self.assertAlmostEqual(by["alpha"]["lock_coverage"], 0.5, places=3,
                               msg="alpha 族两成员一个登记 → 0.5")
        self.assertAlmostEqual(by["beta"]["lock_coverage"], 0.0, places=3)

    def test_ignores_non_skill_dirs_and_dotdirs(self):
        (self.root / ".git").mkdir()
        (self.root / "notaskill").mkdir()
        self._skill("ok", LONG_A)
        metas = M.load_metas(skills_dir=self.root, usage={}, installed=[])
        self.assertEqual([m["name"] for m in metas], ["ok"])

    def test_zero_touch_skill_defaults_to_zero_not_absent(self):
        """scan_usage 的 skills 字典只含有触达记录的技能，零触达必须补 0。"""
        self._skill("solo", LONG_A)
        usage = {"skills": {}}
        metas = M.load_metas(skills_dir=self.root, usage=usage, installed=[])
        self.assertEqual(metas[0]["load"], 0)
        self.assertEqual(metas[0]["sessions"], 0)
        self.assertIsNone(metas[0]["last_used"])

    def test_missing_dir_returns_empty(self):
        self.assertEqual(M.load_metas(skills_dir=self.root / "nope", usage={},
                                      installed=[]), [])

    def test_description_with_colon_survives(self):
        """描述里常有冒号，逐行 key: 匹配必须只在下一个顶层键处截止。"""
        self._skill("colons", "飞书文档：支持读取、创建。注意：链接形如 https://x/y 时使用")
        metas = M.load_metas(skills_dir=self.root, usage={}, installed=[])
        self.assertIn("https://x/y", metas[0]["description"])


class ScanAdviceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for n in ("ima", "ima-skill"):
            d = self.root / n
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {n}\ndescription: {LONG_A}\n---\n", encoding="utf-8")

    def test_end_to_end_with_injected_inputs(self):
        """注入 usage / installed，避免真扫 30 秒会话日志。"""
        usage = {"scanned_files": 42,
                 "skills": {"ima": {"load": 21, "sessions": 12,
                                    "last_used": "2026-09-23T06:59:20.299Z"}}}
        out = M.scan_advice(skills_dir=self.root, usage=usage, installed=[])
        self.assertEqual(out["scanned_skills"], 2)
        self.assertEqual(out["summary"]["actionable_groups"], 1)
        self.assertEqual(out["summary"]["zero_touch_in_actionable"], ["ima-skill"])
        self.assertEqual(out["usage_scanned_files"], 42)
        self.assertTrue(out["since"] is None or isinstance(out["since"], str))

    def test_summary_counts_rejected(self):
        d = self.root / "sensteed-java8-standard"
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: x\ndescription: {STD8}\n---\n", encoding="utf-8")
        d2 = self.root / "sensteed-java17-standard"
        d2.mkdir()
        (d2 / "SKILL.md").write_text(
            f"---\nname: y\ndescription: {STD17}\n---\n", encoding="utf-8")
        out = M.scan_advice(skills_dir=self.root, usage={"skills": {}}, installed=[])
        self.assertEqual(out["summary"]["actionable_groups"], 1, "只有 ima 该成组")
        self.assertGreaterEqual(out["summary"]["rejected_entries"], 1)

    def test_summarize_text_renders_three_sections(self):
        out = M.scan_advice(skills_dir=self.root, usage={"skills": {}}, installed=[])
        text = M.summarize_text(out)
        self.assertIn("可执行合并组", text)
        self.assertIn("ima-skill", text)
        self.assertIn("只读", text)

    def test_summarize_text_handles_empty(self):
        text = M.summarize_text({"summary": {"scanned": 0, "actionable_groups": 0,
                                             "upstream_only_groups": 0,
                                             "rejected_entries": 0},
                                 "actionable": [], "upstream_only": [], "rejected": []})
        self.assertIn("可执行合并组：无", text)


class ReadOnlyGuardTest(unittest.TestCase):
    """本功能必须全程只读：任何写盘调用都是越界。"""

    def test_module_source_has_no_writes(self):
        src = (ROOT / "core" / "skill_merge_advisor.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        for token in ("write_text", "open(", "shutil", "os.remove", "os.rename",
                      "mkdir", "unlink", "subprocess"):
            self.assertNotIn(token, code, f"只读出口出现写操作/外部调用片段 {token}")

    def test_does_not_import_write_channels(self):
        """`skill_market` 的写通道模块不得被引用（FEAT-9 的教训）。"""
        src = (ROOT / "core" / "skill_merge_advisor.py").read_text(encoding="utf-8")
        self.assertNotIn("skill_market_ops", src)
        self.assertNotIn("market_install", src)

    def test_no_dangerous_skills_cli(self):
        """绝不出现 `npx skills check/update`（名为检查实为升级）。"""
        src = (ROOT / "core" / "skill_merge_advisor.py").read_text(encoding="utf-8")
        self.assertNotIn("npx", src)


if __name__ == "__main__":
    unittest.main()
