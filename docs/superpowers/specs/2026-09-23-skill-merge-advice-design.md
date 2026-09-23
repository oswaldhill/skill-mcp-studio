# 技能整理建议设计（FEAT-11）

日期：2026-09-23　状态：已批准，待实现
上游需求：「增加一个整理 skill 的功能，需要识别出最后的使用情况，看看是否有合并的必要」
前置：FEAT-10 技能使用统计（`docs/superpowers/specs/2026-09-23-skill-usage-statistics-design.md`）
本期定位：**只读建议报告**。不删、不改、不移动任何文件；执行能力另立 FEAT-12。

## 1. 本期要回答的问题

哪些技能是"同一目标的双重存在"，该归并；哪些只是"看着像"，其实是有意的变体，不该动。
产出三份可人工核验的清单：可执行合并组、上游技能标注组、被否决的变体对。

判据必须可解释（每条建议附命中规则与证据片段），因为这一期的目的就是**用真实数据验证判据准确率**。

## 2. 调研结论（本机实测，全部可复算）

技能库 `~/.skills-manager/skills`，202 个含 `SKILL.md` 的实体目录，git remote 为
`codeup-oswaldhill:oswaldhill/my-agent-skills.git`（**整库在用户自己的聚合仓下**）。

### 2.1 前缀族分布（20 族 ≥2 成员，覆盖 113/202）

| 族 | 成员 | load 合计 | 零触达 |
| --- | --- | --- | --- |
| lark | 29 | 303 | 19 |
| firecrawl | 13 | 0 | 13 |
| sensteed | 13 | 377 | 7 |
| grafana | 10 | 1 | 9 |
| wecomcli | 10 | 0 | 10 |
| macos / qclaw | 4 / 4 | 1 / 0 | 3 / 4 |
| agent / apple / hermes / skills | 3 | 52 / 1 / 466 / 11 | 2 / 2 / 0 / 2 |
| frontend / git / writing / ima | 2 | 100 / 308 / 109 / 23 | 0 / 0 / 1 / 0 |

**结论：前缀族只能当索引用，不能当合并判据**——`lark-doc` 与 `lark-im` 同族但业务不同；
`frontend-design` 与 `frontend-skill` 同族且真重复。

### 2.2 硬信号命中量（各规则的实测产出）

- **描述归一后完全相同**：2 组
  `ima` == `ima-skill`；`skills-mcp-unifier` == `skills-unifier`
- **描述自述为转发壳**（"仅当…显式指定…统一交由 X"）：4 个
  `lark-minutes`、`lark-note`、`lark-vc`、`lark-vc-agent` → 均指向 `lark-meeting`
- **名称词干归一相同**：1 组
  `grafana-dashboard` / `grafana-dashboards` / `grafana-dashboarding`
- **描述 token Jaccard ≥ 0.6**：26 对，其中约 **14 对是假阳性**

**判据预演（把四规则套到 202 个技能上的真实产出，作为实现验收基准）**：
`actionable` **3 组** —— `ima`+`ima-skill`（T1，保留 load=21 的 `ima`）、
`skills-mcp-unifier`+`skills-unifier`（T1）、`grafana-dashboard`+`-dashboards`+
`-dashboarding`（T3，三合一组而非三对）；`upstream_only` 0 组；
词表拦截 **18 对**，**全部**来自 `sensteed` 族（`*-review` 两两 × 语言限定词）。
即：护栏把一个都没有漏，也没有误伤真重复。

另发现 **4 个死壳指向不存在的技能**：`lark-minutes`/`lark-note`/`lark-vc`/`lark-vc-agent`
均声明"统一交由 `lark-meeting` 处理"，但库中**无 `lark-meeting` 目录**（含 meeting 的只有
`lark-workflow-meeting-summary`、`wecomcli-meeting`），且四者在 FEAT-10 中全部零触达。

### 2.3 决定性反例（决定了判据不能只看相似度）

`sensteed-java17-standard` × `sensteed-java8-standard` 的 **Jaccard = 1.00**（全库最高分之一），
但它们是**按 Java 版本分工的平行规范分册**，描述本就只差版本号，合并会毁掉版本路由。
同族 `sensteed-*-review` 8 个两两 0.80–0.90，它们是 `sensteed-review-hub` 的路由目标。
`grafana-oss` × `grafana`、`lark-oss` × `lark-openapi` 同理：同族不同实现/不同目标。

**推论：真重复与有意变体的区别不在"像不像"，而在名称差异部分是噪声后缀还是实质限定词。**
纯相似度方案（B）被此否决。

### 2.4 来源判据（决定"能不能动"）

lock 文件实际位置 `~/.agents/.skill-lock.json`，`skills` 段登记 **58 条**，与实体目录交集 **57**。
每条含 `source` / `sourceType` / `sourceUrl` / `skillPath` / `installedAt` / `updatedAt`。

- 上游（有登记）57 个：`lark-*` 27/29、`firecrawl-*` 13/13、`agent-*` 2/3 等
- 自持（无登记）145 个：`sensteed-*` 13、`grafana-*` 10、`wecomcli-*` 10 等

**注意纠偏**：直觉上"看起来像第三方"的 `grafana/wecomcli/sensteed` 恰恰**不在 lock 里**；
它们是经 Hermes sync / 手工渠道进来的，已在用户聚合仓内，升级不会被拉回，可自由处置。

因此采用硬定义：**只有 lock 登记者视为"有上游"**，其余一律"自持"。

## 3. 判据（四条规则 + 两张词表）

按强度排序，命中即成组，每条附证据。

| 规则 | 判据 | 实测命中 |
| --- | --- | --- |
| **T1 铁证** | `description` 归一（去非字母数字、转小写）后**逐字相同**，且**归一后**长度 > 40 字 | 2 组 |
| **T2 别名壳** | `description` 自述「仅当…显式指定…统一交由 X」/「请改用 X」 | 4 个，`fold_into=lark-meeting` |
| **T3 词干重复** | 连字符切分后逐段做词干归一（去 `s`/`ing`/`ed` 尾，长度 > 4 才归一），**归一后名称相同** | 1 组（grafana 三兄弟） |
| **T4 弱相似** | token Jaccard ≥ 0.6 **且**名称 token 对称差集**全部**落在噪声后缀集 | 需过词表关 |

### 3.1 两张词表（T4 的关卡，第二张优先）

- **噪声后缀集（可合）**：`skill` `skills` `unified` `unifier` `manager` `pro` `max`
  `tools` `core` `suite` `helper` `common`
- **实质限定词表（命中即否决，优先于上一条）**
  - 版本号：`\d+`、`java8` `java17` `java25`、`v1` `v2` `v3`
  - 语言/平台：`android` `ios` `vue` `react` `nodejs` `python` `frontend` `java` `kotlin` `swift` `web`
  - 动作类型：`review`
  - 实现/形态：`oss` `openapi` `ops-recovery` `alerting` `promql` `opentelemetry` `bridge` `cli`

两表都要写理由注释（为什么 `oss`/`openapi` 是实质限定词：同一产品的不同实现面）。
顺序不可颠倒：`sensteed-java8` × `java17` 名称里**不含任何噪声词**，只有靠实质限定词表才能拦住。

### 3.2 组归并（必须先定，否则同一技能会同时落进多个组）

规则是按**技能对**产出的，而 `ima`/`ima-skill` 会被 T1 与 T4 同时命中，
`grafana` 三兄弟更是 T3 与 T4 交叉命中。故规定：

1. 先算每一对的**最强命中**，优先级 `T1 > T2 > T3 > T4`，一对只保留最强规则标签；
2. 用**并查集**把成对关系合成组（`grafana-dashboard/-dashboards/-dashboarding` 合成 1 组，不是 3 对）；
3. **一个技能只属于一个组**：已在较强规则组里的技能，被弱规则再命中时只追加证据，不另立组；
4. 每组 `rule`/`evidence` 取最强那条；组 `id` 由排序后的成员名生成，保证确定性。

### 3.3 上游分流

| 组成员构成 | 归属清单 |
| --- | --- |
| 全部自持 | `actionable`（T2 例外：其归属看 `fold_into` 目标是否自持） |
| 全部有上游 | `upstream_only`（只标注 `source`，升级会覆盖，合并无效） |
| 混合（上游 × 自持） | 进 `rejected`，`verdict="跨来源并存，需选边：改用上游版或自持一份，不归并"` |

混合对不放第四张清单，避免界面复杂度上升。

**T2 的悬空目标特例（真实数据回灌）**：`lark-minutes` / `lark-note` / `lark-vc` /
`lark-vc-agent` 四个壳都写着"统一交由 **lark-meeting** 技能处理"，但实测
`~/.skills-manager/skills/` 下**没有 `lark-meeting` 目录**（含 meeting 的只有
`lark-workflow-meeting-summary` 与 `wecomcli-meeting`）。这类不是合并机会，而是
**悬空转发缺陷**：壳在把请求交给一个不存在的地方。故规定：T2 命中但 `fold_into`
目标目录不存在时，**不进 `actionable`**，落 `rejected`，
`verdict="转发目标缺失（悬空引用），不构成合并建议"`，并透出 `fold_into_exists: false`。
成员只要有一个"有上游"就整组按上游处理，故这 4 个壳同时满足 `upstream_only` 条件；
**悬空判定优先于上游分流**（它更接近缺陷而非归属问题）。

**「有上游」是运维口径，不是作者归属**（已确认的取舍）：定义 = **在 `.skill-lock.json`
有登记**，因为只有登记项会被 `npx skills update` 复原。实测有 10 个技能带 `LICENSE`
文件（`byted-seedance-video-generate`、`byted-seedream-image-generate`、`figma`、
`archify`、`dws`、`qclaw-skill-creator`、`frontend-skill` 等）明显是第三方整包，
却**不在 lock 里**；`grafana`/`wecomcli`/`sensteed` 三族 lock 覆盖均为 0%。
它们仍归 `actionable`，因为**归并它们不会被升级拉回，操作是安全的**。
为免误读，`actionable` 的每个成员透出 `has_license` 与族级 `lock_coverage`，
让人一眼看出"这个建议针对的是第三方整包但未被 lock 纳管"。

### 3.4 `keep`（推荐保留者）打分

**「无上游」是组级准入门槛，不是成员级 tiebreak**：按 §3.3，能进 `actionable` 的组成员
**全部**自持，故"无上游"在组内恒等、不具区分力；它真正的用处是决定一组**能否**进
`actionable`（含上游 → `upstream_only`；跨来源 → `rejected`）。

组内 `keep` 逐项比较，首个分出高下即定（全部可解释、可复算）：

1. `load` 更高（来自 FEAT-10，受窗口影响）——在用者优先保留
2. `description` 更长（信息量更大）
3. 带 `scripts/` 或 `references/`（内容更完整）
4. 名称字典序取前（最终兜底，保证输出确定性）

lock `updatedAt` 不参与 `actionable` 打分（组内无 lock 可比），只用于 `upstream_only`
清单的展示排序：最近被上游升级的排前面，便于判断哪个还在活跃维护。

### 3.5 输出证据字段（供人工核验，缺一不可判断）

`actionable` 每个成员至少透出：`name`、`load`、`last_used`、`clients`、
`has_scripts`、`has_license`、`lock_coverage`（该技能前缀族的 lock 覆盖率，
`0.0` 即"全族无上游登记"）。理由：判据是启发式，**看建议的人必须能凭字段自己判断
这条建议可不可信**；只给"建议合并 X 和 Y"而不给依据，等于把误判风险转移给人却不让
他复核。`upstream_only` 额外透出 `source`（仓库地址），因为它的作用就是"告诉你去找谁"。

## 4. 输出契约

```jsonc
{
  "summary": { "scanned": 202, "actionable_groups": N,
               "upstream_only_groups": M, "rejected_pairs": K },
  "actionable": [
    { "id": "grp-01", "rule": "T1",
      "keep": "ima", "fold": ["ima-skill"],
      "fold_into": null,                // 仅 T2 有值：目标技能名（如 lark-meeting）
      "evidence": "描述归一后逐字相同（412 字）",
      "members": [ { "name": "ima", "upstream": false, "load": 0,
                     "last_used": null, "clients": ["codex","agents"],
                     "has_scripts": false, "has_license": false,
                     "lock_coverage": 0.0 } ] }
  ],
  "upstream_only": [ { "rule": "T4", "members": ["lark-vc","lark-vc-agent"],
                       "sources": {"lark-vc":"...","lark-vc-agent":"..."},
                       "note": "同属上游，交由上游仓库处理" } ],
  "rejected": [ { "a": "sensteed-java8-standard", "b": "sensteed-java17-standard",
                  "jaccard": 1.0, "blocked_by": ["版本号","版本分册"],
                  "verdict": "有意变体，不合并" } ]
}
```

三清单**互斥**：任一技能对不得同时出现在 `actionable` 与 `rejected`。
输出必须**确定性**：同样输入两次调用逐字节一致（`set`/`dict` 迭代序需排序固化，否则 GUI 每次跳行）。

## 5. 代码结构

```
core/skill_usage.py          （已有）
core/skill_merge_advisor.py  （新增）
   scan_advice(skills_dir=None, session_dirs=None, lock_path=None,
               since=None, clients_states=None) -> dict   ← 唯一公开入口，负责读盘
   _pairs_by_rules(metas) -> (actionable, rejected)       ← 纯函数，判据全在此
   _pick_keep(members) / summarize_text(payload)
```

**依赖单向**：`skill_merge_advisor` → `skill_usage`（load/last_used）+
`skill_market.list_installed`（上游名单）。反向不得依赖，避免撞 `tests/test_import_acyclic.py`。

`_pairs_by_rules(metas)` 只收 `[{name, description, upstream, load, ...}]`，**不碰磁盘**：
T1–T4、两张词表、上游分流全在这一个纯函数内。判据测试因此无需造 202 个目录。

## 6. CLI 与 GUI

**CLI**：`scan.py --merge-advice [--usage-since ISO_DATE] [--format json]`
- 早返回路由**紧跟 `--skill-usage` 那一组**、排在通用快照之前（该坑 FEAT-9/10 各踩一次：
  否则 `--format json` 的 stdout 被快照截走）
- 加入 `src-tauri/src/lib.rs` 的 `ALLOWED`，否则 GUI 调用被安全边界拒绝
- 全程只读，无 `--yes`

**GUI**（复用 FEAT-10 已验证的接线范式）
- Skills 页新增按钮「整理建议」→ `advice-panel`（与 `usage-panel` 同级）
- **沿用 `market-*` 样式类，不新增 CSS**
- 内含全量会话扫描，点击后先显示"分析中…约 35 秒"
- 顶部复用近 30/90 天/全部窗口选择（`load` 参与 `keep` 打分）
- 渲染三段：可执行合并组（keep/fold + 命中规则 + 证据行 + 涉及客户端 + `has_license`
  来源存疑标记）→ 上游仅标注（带 `source` 仓库地址）→ 已否决变体（带 `blocked_by`）
- 组行**只读**，仅提示未来可用的 CLI；本期不放任何写操作按钮
- 守卫：`UndeclaredStateRefTest` 自动覆盖新增 JS（该守卫曾抓出 `MARKET_DATA` 未声明缺陷）

**旧按钮改名（已批准）**：`一键合并技能` → **`修复链接`**。它实际调 `--fix-skills`
（把各客户端目录重挂 symlink），与技能去重无关；与新「整理建议」并列必然混淆。
只改文案与引用该文案的测试断言，不动 action、CLI 参数与行为。

## 7. 测试策略

**① 判据纯函数（核心）**
- 正例四条：T1（`ima`/`ima-skill` 形态）、T2（`lark-minutes` 形态，断言 `fold_into`）、
  T3（`grafana-dashboard/-dashboards/-dashboarding`）、T4（差异仅 `-skill` 后缀）
- 反例（必须落 `rejected`，一条不漏）：`sensteed-java8` × `java17` × `java25`（Jaccard 1.0 含版本号）、
  `*-review` 两两、`grafana-oss` × `grafana`、`lark-oss` × `lark-openapi`
- 上游分流：含 lock 成员不得进 `actionable`；混合对落 `rejected` 且带选边 `verdict`
- `keep` 打分：四条组内 tiebreak 逐项断言（load/描述长度/scripts/字典序），
  另断言「无上游」是**组级准入**：构造含上游成员的组，它必须落 `upstream_only` 而非 `actionable`
- 三清单互斥；输出确定性（两次调用逐字节一致）
- **悬空转发**：合成一个 `fold_into` 指向不存在的目录，断言它落 `rejected` 且
  `fold_into_exists=false`，**不得**因"全组有上游"被判进 `upstream_only`（悬空优先于分流）
- **预演基准**：断言真实数据的规则实现在合成语料上能复现 3 组 actionable 的形状
  （同描述对、同词干三兄弟合成 1 组），把上面 §2.2 的预演结果固化成回归
- **证据字段完整性**：`actionable` 每个成员必须齐备 `load`/`last_used`/`clients`/
  `has_scripts`/`has_license`/`lock_coverage` 六项（缺一项就剥夺了人工核验能力）；
  `upstream_only` 必须带 `source`

**② `scan_advice` 端到端**：临时目录造假技能库 + 假 `.skill-lock.json` +
假 `sessions/2026/09/01/*.jsonl`，断言三计数、`blocked_by` 透出、目录缺失时降级不抛异常

**③ 出口与界面**
- CLI 契约：argparse 存在、路由早于 `return _run_single_profile_snapshot(`、Rust `ALLOWED` 含 `--merge-advice`
- **只读 AST 护栏**：剔除文档字符串后审计 `core/skill_merge_advisor.py` 与 `_run_merge_advice`，
  断言无 `write_text` / `open(...,"w")` / `shutil` / `os.remove`，且**不 import `skill_market_ops`**
  （那是写通道）——沿用 FEAT-9 拦 `npx skills check` 的同款写法
- GUI 静态：按钮/容器接线，且 `open-advice`、`advice-close`、`advice-refresh`、
  `advice-window` 四个 `data-action` 均有路由分支；无 em-dash ⚠ ✓
- 反向护栏：确保"本期只读、不执行"的警告文案未被删除（删警告比删功能更危险）

预计新增 34–40 条；基线 732 passed + 28 subtests。

## 8. 边界与已知局限

不做：自动执行合并（`actionable` 供未来 FEAT-12 消费）、合并草案生成、embedding/向量聚类、
跨客户端 symlink 变更、"把一个技能拆成几个"的反向推荐。

局限：
- `load` 只覆盖 Codex 一个客户端（FEAT-10 §8 同源局限）
- 上游判定只认 lock（57/202），Hermes sync 渠道进来的第三方会被当"自持"——
  不影响安全（仍只读），只影响 `actionable` / `upstream_only` 归类精度
- 两张词表是启发式，靠本次真实数据校准。误判方向刻意设为**保守漏报**
  （宁可不成组，也不给出去错误的合并建议），与"先验证准确率"的本期定位一致
