# skill-mcp-studio 详细设计文档

**——阶段一：endpoint profile 抽象**

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-01 | 基于《产品定位与路线图规划》v1.1 与 skills-mcp-unifier 代码实测状态编写 |
| v1.1 | 2026-09-01 | 对接《决策记录-待决问题定案》D3/D4/D5：pin `schema_version`、profile 独立仓库分发、公开前 git 历史零拓扑 |

## 1. 引言

### 1.1 目的与范围

本文档是 skill-mcp-studio 阶段一（endpoint profile 抽象）的详细设计，回答"怎么改"：配置 schema、模块职责、接口签名、关键流程、兼容性策略、测试方案与目标目录结构。读者是实施改造的工程师与评审人。

范围边界：

- **覆盖**：阶段一全部改造（规划文档 5.1 第 1–6 步），以及为阶段二/三预留的接口约定；
- **不覆盖**：阶段二的能力组模板库完整设计、阶段三 Tauri GUI 实现细节（仅约定数据契约，见第 12 节）。

### 1.2 与规划文档的关系

规划文档（《产品定位与路线图规划》v1.1）回答"做什么、为什么"；本文档回答"怎么做"。本文档编写前对现有代码做了逐项实测（18 个 core 模块、10 个测试文件、CLI 全量参数、探测与修复流程源码），所有接口描述均以实测为准；与规划文档表述不一致处，在第 13 节设计决策记录中显式说明。

### 1.3 术语

| 术语 | 定义 |
|------|------|
| profile | 对一个统一 MCP 端点的完整声明：名称、URL、传输方式、所需能力组、遗留命名、识别规则 |
| 四问模型 | 安装证据 → 路径合规 → 配置正确 → 端点活体，四层独立验证 |
| 能力组 | 一组必须同时存在的工具名（如 hermes_memory = [memory_search, memory_add]），用于判定端点能力覆盖 |
| legacy 条目 | 客户端配置中指向旧端点/旧通道的 MCP 条目（如 hermes-nas、ai-memory） |
| 活体探测 | 对端点发起 initialize + notifications/initialized + tools/list 三步 JSON-RPC 调用 |
| source of truth | config.yaml 中的客户端注册表（mcp_tools / tools / auto_discover 段） |

## 2. 设计目标与约束

### 2.1 设计目标（阶段一）

1. **多 profile**：单一写死的 `unified_mcp` 段演进为 `profiles` 集合，CLI 按 `--profile` 选择，默认取 `active_profile`；
2. **主干零个人拓扑**：改造完成后，主干代码库（不含 `profiles/` 子包）全文检索无个人域名、内网网段、设备名命中；
3. **默认行为零变化**：默认 profile 下 `scan.py --full` 输出与改造前逐行一致；
4. **旧配置无感兼容**：旧结构（有 `unified_mcp` 无 `profiles`）自动包装为单一 profile，不报错，给出迁移提示；
5. **引擎接口稳定**：阶段二（能力组模板库）与阶段三（GUI）在本阶段预留的接口上扩展，不需要再次重构引擎传参方式。

### 2.2 设计约束（继承自现有代码的硬事实）

实测确认、设计必须尊重的约束：

| 约束 | 出处 | 对设计的影响 |
|------|------|--------------|
| `probe_mcp` 强制 URL 校验：必须 HTTPS、有 hostname、路径以 `/mcp` 结尾 | core/mcp_checker.py `is_valid_mcp_url` | 本地/非标端点无法探测，需引入 profile 级 `url_policy`（见 5.4） |
| 探测仅支持 HTTP 传输（urllib POST，JSON-RPC over streamable-http/SSE） | core/mcp_probe.py | stdio 传输端点无法活体探测，阶段一示例 profile 只能是 HTTP 端点（见 ADR-3） |
| 探测鉴权读环境变量 `HERMES_MCP_AUTH_TOKEN`（命名 hermes 专属） | core/mcp_probe.py:62 | 需泛化为 profile 声明的 token 来源（见 5.4） |
| 能力组判定语义：`bool(required) and all(...)`——空能力组判为不可用 | core/combined_checker.py `_has_group` | 泛化后空 `required_capabilities` 不生成能力组字段，而非生成"不可用"字段（见 4.2） |
| 修复流程已含完整安全链：备份 → 原子写入 → 重解析验证 → 失败回滚 | core/mcp_fixer.py | 保留不动，仅扩展 profile 传参 |
| hermes_checker 的识别规则（HERMES_SIGNATURES）与三通道校验硬编码在 core/ | core/hermes_checker.py | 必须泛化为 profile 声明驱动（见 5.5），这是改造量最大的一块 |
| CLI 参数由 `cli_modes.resolve_modes` 统一归一化 | core/cli_modes.py | `--profile` 的默认值解析放在归一化之后、各阶段执行之前 |

### 2.3 非目标

- 不改变四问模型的判定逻辑与各状态字段的语义；
- 不新增客户端、不新增配置格式解析器（注册表机制本身不动）；
- 不做 stdio 传输的活体探测（阶段二议题）；
- 不引入配置 schema 校验库（用纯代码校验 + 明确报错，见 ADR-5）。

## 3. 总体架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  表现层（现状：CLI / 阶段三预留：GUI）                          │
│  scan.py（argparse + 11 阶段编排）                            │
└──────────────┬──────────────────────────────────────────────┘
               │ check_agents(config, scan_result, live_probe)
               │ fix_mcp_clients(config, dry_run)
┌──────────────▼──────────────────────────────────────────────┐
│  引擎层 core/                                                 │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ combined_checker │  │ mcp_checker  │  │ legacy_checker │  │
│  │（四问聚合判定）   │  │（配置解析）   │  │（遗留接入检查， │  │
│  └────────┬────────┘  └──────────────┘  │  泛化自         │  │
│           │                              │  hermes_checker）│  │
│  ┌────────▼────────┐  ┌──────────────┐  └────────────────┘  │
│  │ mcp_probe       │  │ mcp_fixer    │                      │
│  │（活体探测）      │  │（安全修复）   │  + scanner / checker │
│  └─────────────────┘  └──────────────┘    hooks / reporter… │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  配置层                                                       │
│  config.yaml（profiles + active_profile + 客户端注册表）       │
│  profile_loader（新增：读取、校验、兼容包装）                   │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  profile 包 profiles/<name>/（部署脚本、拓扑文档、专属资源）    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 模块清单与改造后职责

实测 core/ 现有 18 个模块。阶段一各模块处置方式：

| 模块 | 现状职责 | 阶段一处置 |
|------|----------|-----------|
| scanner.py | 配置加载、工具自动发现、扫描编排 | 不动（`load_config` 已接受 `--config` 路径） |
| checker.py | skills 路径合规检查（第二问） | 不动 |
| combined_checker.py | 四问聚合判定（`check_agents`） | **改**：profile 段经参数注入，能力组字段动态生成（5.2） |
| mcp_checker.py | 多格式配置解析（第三问） | 微改：docstring 个人 URL 清理；`is_valid_mcp_url` 增加 relaxed 分支（5.4） |
| mcp_probe.py | 活体探测（第四问） | **改**：token 来源参数化、URL 校验策略参数化（5.4） |
| mcp_fixer.py | 备份→原子写入→回滚修复 | 微改：`expected` 段来源改为 profile，逻辑不动（5.3） |
| hermes_checker.py | hermes/NAS 遗留接入检查 | **改**：泛化为 legacy_checker，规则由 profile 声明驱动（5.5） |
| ai_memory_checker.py | ai-memory 接入检查（环境变量启发式） | 并入 legacy_checker 的声明式规则（5.5） |
| hooks_checker.py | 生命周期 hooks 检查 | 不动 |
| reporter.py | 控制台/Markdown 报告 | 微改：能力组列动态渲染（4.2） |
| tool_registry.py | 安装证据核验（第一问） | 不动 |
| cli_modes.py | CLI 模式归一化 | 微改：`--profile` 默认值解析 |
| fixer.py / git_sync.py / change_tracker.py / version_checker.py / skills_analyser.py / workspace_cleaner.py | skills 侧修复/同步/追踪/版本/分析/清理 | 不动（与端点无关） |
| —（新增） | — | **profile_loader.py**：profile 读取、校验、旧结构兼容包装（5.1） |

## 4. 核心数据模型

### 4.1 四问验证模型（不变）

| 层 | 问题 | 判定依据 | 对应状态字段 |
|----|------|----------|--------------|
| L1 | 客户端是否真实安装 | app bundle / PATH 命令 / 配置路径存在性（tool_registry.detect_installation） | installed + install_evidence |
| L2 | Skills 路径是否指向统一仓库 | 符号链接解析比对（checker.check_path） | skills_compliant |
| L3 | MCP 是否配置正确 | 按客户端格式解析配置，比对 expected name/url，识别 legacy 条目（mcp_checker.inspect_mcp_configuration） | mcp_configured + configured_url + legacy_channels |
| L4 | 端点是否活体且能力覆盖 | initialize + tools/list，工具名集合比对能力组（mcp_probe + _has_group） | mcp_initialize_ok / mcp_tools_list_ok / N 个能力组字段 |

设计原则沿用现状：**四层独立报告，不做短路合并**。配置正确但探测失败、探测通过但能力缺失，都是合法且需要分别呈现的状态。

### 4.2 状态模型演进：11 字段 → 7 固定 + N 能力组

现有 11 字段中，7 个与端点身份无关，保留为固定字段：

| 固定字段 | 语义 |
|----------|------|
| installed | 客户端已安装（L1） |
| skills_compliant | Skills 路径合规（L2） |
| mcp_configured | MCP 条目配置正确（L3） |
| mcp_initialize_ok | initialize 成功（L4） |
| mcp_tools_list_ok | tools/list 成功且非空（L4） |
| hooks_configured | 生命周期 hooks 已配置 |
| legacy_channels | 检测到的遗留通道清单 |

4 个 hermes 专属能力组字段（hermes_memory_available / ai_memory_available / tdai_available / hermes_available）改为动态生成：

- 呈现形式：嵌套 `capabilities: { "<组名>": bool, ... }` 单一字典（不再用扁平的 `capability_<组名>` 字段）；
- 生成条件：仅当 profile 的 `required_capabilities` 非空时生成键；组数为 0 的 profile（如 generic-http），报告中不出现能力组维度，只呈现 L4 基础探测结果；
- 判定语义不变：沿用 `_has_group` 的 `bool(required) and all(name in available)`——组内所有工具名必须全部出现在 tools/list 结果中；
- 未探测时（`live_probe=False` 或 mcp_configured=False）能力组字段全部为 False，与现状一致（configured_and_probed 门槛保留）。

记录结构（check_agents 返回的 record）相应演进，实测现有字段保留，能力组部分动态化：

```
record = {
  name, installed, install_evidence, skills_compliant,
  mcp_configured, configured_url,
  mcp_initialize_ok, mcp_tools_list_ok,
  capabilities: { "<组名>": bool, ... },   # 替代 4 个固定能力组字段
  hooks_configured, hook_events, legacy_channels
}
```

兼容要求：报告层（reporter）按 `capabilities` 字典动态渲染列；阶段三 GUI 矩阵视图直接消费同一结构（见第 12 节）。

### 4.3 profile schema v1

```yaml
schema_version: 1                       # profiles 段结构版本（决策记录 D5）
active_profile: hermes-home

profiles:
  hermes-home:
    # --- 端点身份 ---
    name: hermes                          # 写入客户端配置的规范条目名
    url: https://hermes-mcp.example.com/mcp
    transport: streamable-http            # 阶段一仅支持 http 系（streamable-http / sse）
    # --- 探测策略 ---
    url_policy: strict                    # strict=HTTPS+/mcp 结尾（现状）；relaxed=允许 http 与任意路径
    auth_token_env: HERMES_MCP_AUTH_TOKEN # 探测用 Bearer token 的环境变量名；省略=无鉴权
    probe_timeout: 8.0                    # 秒，省略取默认 8
    # --- 能力组（L4 覆盖判定） ---
    required_capabilities:
      hermes_memory: [memory_search, memory_add]
      ai_memory: [ai_memory_query, ai_memory_handoff_begin, ai_memory_call]
      tdai: [tdai_memory_search, tdai_knowledge]
      hermes: [hermes_health, hermes_chat]
    # --- 遗留条目治理 ---
    legacy_names: [hermes-nas, hermes-memory, hermes-gateway, ai-memory]
    # 供泛化后的 legacy_checker 使用，见 5.5。多类 legacy 端点用「列表」逐块声明；
    # 单类端点可省略列表直接给一个映射（向后兼容，等价于 label=hermes 的单元素列表）。
    legacy_detection:
      - label: hermes                     # 检测块标签（报告里标记 server 的 kind）
        server_name_keywords: [hermes]
        command_patterns: [hermes-bridge]
        env_keys: [NAS_GATEWAY_URL, NAS_API_KEY, NAS_MODEL]
        url_pattern: "nas[-_\\./].*:\\d+"
        gateway_url_env: NAS_GATEWAY_URL   # 深检：URL 所在环境变量
        api_key_env: NAS_API_KEY           # 深检：secret/key 所在环境变量
        placeholder_keys: [REPLACE_ME, your-key-here]  # key/token 占位值深检
        passthrough_patterns: [v2-bridge, mcp-bridge]
        verify_script: true                # true=脚本+key 深检（hermes）；false=token 深检（ai-memory）
        channels:                          # 通道完整性校验（原三通道逻辑声明化）
          - { label: nas,     canonical: hermes-nas,     match_keywords: [nas] }
          - { label: memory,  canonical: hermes-memory,  match_keywords: [memory] }
          - { label: gateway, canonical: hermes-gateway, match_keywords: [gateway] }
      - label: ai-memory                   # 会话交接层 legacy 入口（token 深检）
        server_name_keywords: [ai-memory, aimemory]
        command_patterns: [ai-memory-bridge]
        env_keys: [AI_MEMORY_SERVER_URL, AI_MEMORY_AUTH_TOKEN]
        gateway_url_env: AI_MEMORY_SERVER_URL
        api_key_env: AI_MEMORY_AUTH_TOKEN
        placeholder_keys: [REPLACE_ME, your-token-here, "<AI_MEMORY_TOKEN>"]
        verify_script: false
        channels: []

  generic-http:                           # 通用示例：任意 HTTP MCP 端点
    name: my-mcp
    url: https://example.internal/mcp
    transport: streamable-http
    url_policy: strict
    required_capabilities: {}             # 空 = 只验证 initialize + tools/list
```

字段约束：

| 字段 | 必填 | 校验规则 |
|------|------|----------|
| name | 是 | 非空字符串，作为写入各客户端配置的条目名 |
| url | 是 | 合法 URL；`url_policy: strict` 时另须满足 HTTPS + hostname + `/mcp` 结尾 |
| transport | 否 | 当前仅 `streamable-http` / `sse` 有效；其他值加载时报错（stdio 见 ADR-3） |
| url_policy | 否 | `strict`（默认）/ `relaxed` |
| auth_token_env | 否 | 环境变量名；该变量不存在时按无 token 探测 |
| probe_timeout | 否 | 正浮点数，默认 8.0 |
| required_capabilities | 否 | 组名→工具名列表的映射；空映射 = 无能力组要求 |
| legacy_names | 否 | 字符串列表；`--remove-legacy-mcp` 的移除对象 |
| legacy_detection | 否 | 单个映射或映射列表；省略时 legacy_checker 按内置默认块（hermes + ai-memory）识别，仅按 legacy_names 精确匹配的旧语义由封闭块实现 |

顶层键 `schema_version: 1`（必填）为 profiles 段结构版本，由 `profile_loader` 校验，未知版本 fail fast 并给出升级指引（决策记录 D5）。

`mcp_tools`、`tools`、`auto_discover`、`unified_skills_dir` 四段不属于 profile（它们是客户端侧配置，与端点无关），保持在 config.yaml 顶层不变。每工具的 `unified_name` 覆盖机制保留，语义为"该客户端在本 profile 下使用的条目名"。

### 4.4 客户端注册表（沿用，不改）

实测 `mcp_tools` 条目结构（7 个客户端：Claude Code / Cursor / WorkBuddy / Codex / Reasonix / OpenCode / DSH），字段：

```
- name / aliases
- install: { app_bundles, commands, config_paths }   # L1 安装证据三通道
- config_path + format                                # json / toml / jsonc / reasonix_toml / cordis_yaml
- mcp_key_path                                        # 配置内 MCP 容器路径
- config_candidates: [{ path, format, key_path }]     # 多路径回退（DSH 在用）
- unified_name                                        # 可选，覆盖 profile.name
- fix_supported                                       # 是否允许 --fix-mcp 写入
- hooks_config_path                                   # 可选，hooks 检查目标
```

新增客户端仍是"加一段声明"，阶段一不动此机制。

### 4.5 持久化文件

- `data/state.yaml`：上次扫描快照（时间戳、技能数、汇总、各工具状态），供变更追踪（阶段 4）对比。改造点：快照中记录 `active_profile`，避免跨 profile 的状态对比产生误导；
- `data/discovered_tools.yaml`：自动发现的新工具清单，不动。

## 5. 模块详细设计

### 5.1 profile_loader（新增）

唯一新增模块，职责：读取、校验、兼容包装。接口：

```python
def load_profile(config: dict, profile_name: str | None = None) -> ProfileBundle:
    """
    返回 ProfileBundle = { "name": 段名, "profile": profile 字典, "config": 完整 config }
    - profile_name 为空时取 config["active_profile"]；
    - 旧结构（有 unified_mcp 无 profiles）自动包装为单一 profile，
      段名取 unified_mcp.name，并向 stderr 打印一次性迁移提示；
    - 段不存在、必填字段缺失、取值非法时抛 ProfileError，
      错误信息指明字段名与期望格式（不静默降级）。
    """

def resolve_profile_name(args, config: dict) -> str:
    """CLI 层调用：--profile 显式值 > active_profile > 旧结构包装名。"""
```

设计要点：

- 包装后的内部结构与原生 profile 段完全一致，引擎层不感知"旧配置"的存在；
- 校验在加载期一次完成（fail fast），后续引擎代码可以信任 profile 结构合法；
- 迁移提示只打印一次（同一进程内），文案给出目标结构示例。
- 校验顶层 `schema_version`，未知版本 fail fast 并给出升级指引（决策记录 D5）。
- 支持 `profile_sources` 声明式引用（决策记录 D4）：加载前先把 git/path 两类 source 挂载到本地缓存、合并进可检索 profiles 集合；无 `profile_sources` 时行为等价于「全部 profile 在本 config.yaml」。

### 5.2 combined_checker 改造

现状（实测）：`check_agents(config, scan_result, *, live_probe)` 内部 `expected = config.get("unified_mcp", {})`，能力组判定硬编码 4 个字段。

改造后：

```python
def check_agents(config, scan_result, *, live_probe=False, profile: dict | None = None):
    expected = profile if profile is not None else config.get("unified_mcp", {})
    probe = probe_mcp(
        expected_url,
        token_env=expected.get("auth_token_env"),
        url_policy=expected.get("url_policy", "strict"),
        timeout=expected.get("probe_timeout", 8.0),
    ) if live_probe else NOT_PROBED
    ...
    # 能力组动态生成
    capabilities = {
        group: _has_group(tool_names, names)
        for group, names in expected.get("required_capabilities", {}).items()
    }
```

- 保留 `profile=None` 回退分支，使现有测试与旧调用方不破坏；入口（scan.py）统一走 profile_loader 注入；
- `configured_and_probed` 门槛、unmanaged 客户端检测、summary 聚合逻辑不动；
- record 输出按 4.2 的结构演进（`capabilities` 字典替代 4 个固定字段）。

### 5.3 mcp_fixer 改造（最小化）

实测现有接口已接收 `expected` 字典：`fix_mcp_tool(tool, expected, *, dry_run)`、`fix_mcp_clients(config, *, dry_run)`。改造只有一处：

- `fix_mcp_clients` 从"内部取 `config['unified_mcp']`"改为"接受 profile 注入"（新增 `profile` 参数，默认回退旧行为，与 5.2 同模式）；
- 渲染器（_render_json / _render_toml / _render_reasonix / _render_reasonix_toml / _render_cordis_yaml）、备份（`.bak-{timestamp}`）、原子写入、`_validate_written_config` 重解析验证、`_restore_backup` 回滚、`remove_legacy_mcp_tool`/`remove_legacy_mcp_clients` 全部不动；
- `remove_legacy` 系列读取的 `legacy_names` 来源随 profile 注入切换。

### 5.4 mcp_probe 与 URL 校验

现状（实测）：

```python
probe_mcp(url, *, timeout=8.0, token=None) -> {
    "initialize_ok": bool, "tools_list_ok": bool,
    "tool_names": [...], "error": str
}
# token 默认读 HERMES_MCP_AUTH_TOKEN；url 必须通过 is_valid_mcp_url
```

改造：

```python
def probe_mcp(url, *, timeout=8.0, token=None, token_env=None, url_policy="strict"):
    # token 优先级：显式 token > 环境变量 token_env > 无
    # url_policy="strict" 走现有 is_valid_mcp_url；
    # url_policy="relaxed" 只要求 scheme in {https, http} 且有 hostname
```

- `is_valid_mcp_url` 保留原语义不动（其他地方仍按严格标准引用），新增 `_is_probeable_url(url, policy)` 内部分支；
- 探测三步流程（initialize → notifications/initialized → tools/list）、SSE `data:` 行解码、Mcp-Session-Id 会话维持均不动。

### 5.5 legacy_checker（泛化自 hermes_checker，改造量最大）

现状问题（实测）：hermes_checker.py 内 22 处专属逻辑——`HERMES_SIGNATURES` 字典（服务名/命令/环境变量/网关 URL 四类启发式）、`NAS_API_KEY` 占位值深检、三通道完整性校验（nas/memory/gateway）全部硬编码，且被 scan.py 的 `--hermes`/`--full` 接线使用；ai_memory_checker.py 同构（`AI_MEMORY_SERVER_URL` 等）。

改造方案：

1. 新建 `core/legacy_checker.py`，核心接口：

```python
def check_legacy_channels(installed_tools, profile: dict) -> dict:
    """
    按 profile["legacy_detection"] 声明（单个映射或映射列表）执行启发式识别：
    - 每个检测块用 server_name_keywords / command_patterns / env_keys / url_pattern
      四类匹配，深检由 verify_script 选择脚本+key（hermes）或 token（ai-memory）；
    - channels 声明驱动通道完整性校验；
    - 未声明 legacy_detection 时回落内置默认块 [hermes, ai-memory]（等价旧 --hermes
      与 --ai-memory 两条路径的并集）。
    返回结构与现有 check_hermes_connectivity 对齐
    （hermes_connected → legacy_connected 等字段名保留旧名做别名映射，
    保证报告层与测试平滑迁移）。
    """
```

2. hermes-home profile 的 `legacy_detection` 段即现有 `HERMES_SIGNATURES` + 三通道规则 + `AI_MEMORY_SIGNATURES` 的原文转写（见 4.3 示例），行为等价；ai-memory 的接入识别并入同一结构，`--hermes`/`--ai-memory` 一次 `check_legacy_channels` 调用同时覆盖两类 legacy 通道，ai-memory 的 hooks/修复保留在 ai_memory_checker 的独立职责里；
3. `scan.py` 的 `--hermes`/`--ai-memory` 参数保留为别名（向后兼容），内部统一走 legacy_checker；
4. ai_memory_checker.py 在确认测试全绿后移除接入检测（归入 legacy_checker），仅保留 hooks + 修复；hermes_checker.py 已删除（决策记录 D7）；
5. `NAS_API_KEY` / `AI_MEMORY_AUTH_TOKEN` 占位值深检这类"通用机制 + 专属键名"的逻辑，键名清单并入检测块的 `placeholder_keys`，机制留在主干。

退路（与规划文档一致）：若声明化改造受阻，hermes_checker 整体移入 `profiles/hermes-home/`，CLI 按 profile 动态加载，不阻塞主线。

### 5.6 unified_mcp_server.py 参数化

现状（实测）：通用网关脚本，但内置个人常量——`OPS_KEYWORDS`（含内网网段 192.168.x./10.x. 等）与按 hermes 能力组写死的 `EXPOSED_TOOL_NAMES`。

改造：两个常量改为启动时从配置文件或环境变量注入（`--keywords-file` / `--exposed-tools`），默认值为空或通用最小集；脚本本体按规划保留在主干（它是通用网关，不是部署脚本），个人常量现值移入 profile 独立仓库（`profiles-hermes-home`）的资源文件（决策记录 D4）。

## 6. 关键流程

### 6.1 审计流程（只读，`--full`）

现有 11 阶段编排（实测）：①主目录验证 → ②git 同步（可选）→ ③扫描 → ④变更追踪 → ⑤分布分析（可选）→ ⑥修复（可选）→ ⑦legacy 接入检查 → ⑦b ai-memory 检查 → ⑧版本检查（可选）→ ⑨状态保存 → ⑩报告 → ⑪工作区清理（可选）。

阶段一的改动点只有三处：

- 入口：`resolve_modes` 之后、阶段 ① 之前，调用 `profile_loader.load_profile` 解析出本次运行的 profile；
- 阶段 ⑦/⑦b：合并为 legacy_checker 一次调用（由 profile 声明驱动）；
- 阶段 ⑨：state.yaml 记录 active_profile。

其余阶段的触发条件与顺序不变。`--scan-only` 仍只保留 always-on 阶段（①③④⑨）。

### 6.2 修复流程（`--fix-mcp`，不动）

实测现状已满足产品级要求，原样保留：

```
对每个已安装且 fix_supported 的客户端：
  1. 读取现有配置（不存在则按格式生成初始骨架）
  2. _render 渲染规范条目（不触碰其他条目；渲染结果与原文件相同 → 报 unchanged）
  3. 备份：复制为 <path>.bak-<timestamp>（备份失败 → 中止，不做任何修改）
  4. 原子写入：同目录临时文件 + 替换（写失败 → 原文件不变）
  5. _validate_written_config 重解析验证
     （失败 → _restore_backup 自动回滚；回滚也失败 → 显式报错提示人工处理）
```

状态枚举（报告用）：updated / unchanged / dry-run / not-installed / missing / unsupported / error。`--dry-run` 只输出将执行的操作，不产生任何写入。

### 6.3 遗留条目移除流程（`--remove-legacy-mcp`，不动）

门槛条件保持现状：**规范端点全能力探针通过后**才允许移除——`remove_legacy_mcp_clients` 对每个客户端备份后删除 `legacy_names` 命中的条目，删除前新端点必须已验证可用。旧条目在新端点验证通过前绝不删除，此承诺写入门槛逻辑，不因 profile 化放宽。

### 6.4 向后兼容流程（旧配置）

```
加载 config.yaml
  ├─ 有 profiles 段 → 按 active_profile / --profile 选取（常规路径）
  ├─ 只有 unified_mcp 段 → 包装为单一 profile：
  │     段名 = unified_mcp.name
  │     url_policy 缺省补 strict，auth_token_env 缺省补 HERMES_MCP_AUTH_TOKEN
  │     （补默认值是为了保证包装后行为与旧代码逐字节一致）
  │     向 stderr 打印一次性迁移提示
  └─ 两者都无 → 报错退出，提示至少声明一个 profile
```

## 7. CLI 设计

### 7.1 现有参数（实测全量）

按功能分组：

| 组 | 参数 |
|----|------|
| 检查 | --skills / --mcp / --hooks / --probe-mcp / --hermes / --ai-memory / --update / --full / --scan-only |
| 修复 | --fix（--fix-skills 别名）/ --fix-mcp（--fix-ai-memory 别名）/ --remove-legacy-mcp / --setup-all / --dry-run / --no-interactive |
| 环境 | --config / --unified-dir / --discover |
| 工作流 | --sync / --analyze / --clean / --push / --report |

### 7.2 新增 `--profile`

```
--profile <name>    选择本次运行使用的 endpoint profile（默认 active_profile）
--list-profiles     列出配置中所有 profile 及当前激活项（只读，随查随走）
```

规则：

- `--profile` 指定的段不存在时报错退出，列出可用段名（不静默回退）；
- `--hermes`/`--ai-memory` 保留，语义并入 legacy 检查（旧参数别名策略与现有 `--fix`/`--fix-skills` 一致）；
- `--full` 的行为范围不变，仅判定依据切换为所选 profile。

## 8. 安全设计

沿用并显式承诺现有安全工作流（这也是产品差异化的一部分）：

1. **只读与写入显式分离**：默认全部检查只读；任何写入必须显式传 `--fix-*` / `--remove-legacy-mcp`；
2. **dry-run 优先**：所有写入类操作支持 `--dry-run` 预览；
3. **备份强制**：写入前必须备份成功，否则中止；
4. **原子写入**：同目录临时文件 + 替换，杜绝半写状态；
5. **写后验证**：重解析写入结果，不通过自动回滚；
6. **移除有门槛**：legacy 条目移除以全能力探针通过为前提；
7. **探测无副作用**：活体探测只发 initialize/notifications/tools/list 三类只读 JSON-RPC 请求，不调用任何业务工具；
8. **token 不落盘**：鉴权令牌只经环境变量传入，不写入配置、不进报告（报告只呈现"已配置/未配置"）。

## 9. 错误处理与退出行为

- 配置层错误（profile 缺失/非法）：fail fast，明确报错，不降级运行；
- 单客户端错误（配置文件损坏、不可解析）：该客户端报 error 状态，不阻断其他客户端（现状行为，保留）；
- 探测错误（超时/连接拒绝/协议错误）：记入 `probe.error`，L4 字段置 False，不影响 L1–L3 报告；
- 退出码：现状未使用非零退出码（实测无 `sys.exit` 调用）。阶段二打包分发时补退出码约定（0=全绿，1=有不合规项，2=配置/运行错误），阶段一不动，避免破坏现有脚本集成。

## 10. 测试设计

### 10.1 现有测试参数化

实测 10 个测试文件中 6 个含个人拓扑标识，分两类处理：

| 文件 | 耦合性质 | 处理 |
|------|----------|------|
| test_combined_checker.py | 端点 URL 写死在断言（6 处） | URL/能力组提取为公共夹具常量 |
| test_mcp_checker.py | 端点 URL 写死在断言（11 处） | 同上 |
| test_mcp_fixer.py | 端点 URL 写死在断言（2 处） | 同上 |
| test_reporter.py | 端点 URL 写死在断言（2 处） | 同上 |
| test_fnos_ingress_keeper.py | 拓扑脚本自身测试 | 随脚本迁入 profiles/hermes-home/，测试同迁 |
| test_easytier_sni_route_keeper.py | 拓扑脚本自身测试 | 同上 |

公共夹具置于 `tests/fixtures.py`（端点常量、示例 profile 字典、示例客户端注册表），测试逻辑与断言不变。

### 10.2 新增测试组

1. **profile_loader 单测**：profiles 正常加载 / active_profile 缺省 / `--profile` 指定不存在段报错 / 旧结构自动包装（断言包装结果与手写 profile 等价）/ 非法字段报错文案；
2. **通用 profile 行为测试**：`required_capabilities: {}` 时只检查 initialize + tools/list，report 无能力组列；`url_policy: relaxed` 接受 http 端点；未声明 `legacy_detection` 时只做精确名字匹配；
3. **动态能力组测试**：N 组生成 N 个 `capability_*` 字段；空组判不可用的语义回归（锁定 `_has_group` 行为）。

### 10.3 回归验证方法

阶段一收尾执行双轨对比：

1. 全量测试通过（无新增跳过项）；
2. 改造前后各跑一次 `scan.py --full`（默认 profile），报告逐行 diff 必须为空。对比在改造开始前先录制基线快照；
3. 公开前置（决策记录 D3）：含 `git log` 历史在内全文检索无个人域名/内网网段/设备名；有历史残留则 `git filter-repo` 或 squash 重建。

## 11. 目标目录结构

```
skill-mcp-studio/
├── scan.py                      # CLI 入口（编排 11 阶段）
├── config.yaml                  # profiles + profile_sources + 客户端注册表
├── core/
│   ├── profile_loader.py        # 新增
│   ├── legacy_checker.py        # 新增（泛化自 hermes/ai_memory_checker）
│   ├── combined_checker.py      # 改造：profile 注入 + 动态能力组
│   ├── mcp_probe.py             # 改造：token/url_policy 参数化
│   ├── mcp_fixer.py             # 微改：profile 注入
│   ├── mcp_checker.py           # 微改：校验分支
│   ├── cli_modes.py             # 微改
│   ├── reporter.py              # 微改：动态列渲染
│   └── …（其余 9 个模块不动）
├── tests/
│   ├── fixtures.py              # 新增：公共夹具
│   ├── test_profile_loader.py   # 新增
│   └── …（参数化后的既有测试）
├── data/                        # state.yaml / discovered_tools.yaml
├── profiles/
│   └── examples/
│       └── generic-http/        # 无敏感的最小示例（入主仓库，供陌生人/测试）
├── references/                  # ide-agent-setup.md 拆分后的通用部分
└── （真实 profile 不在此仓库，决策记录 D4）
    hermes-home → 独立私有仓库 profiles-hermes-home，经 config.profile_sources 引用；
    deploy/ scripts/ tests/ gateway-config/ README.md 均落在独立仓库内。
```

## 12. 阶段三预留：GUI 数据契约

GUI（只读审计看板）将直接消费引擎输出，不做二次解析。契约即 `check_agents` 的返回结构（JSON 序列化）：

```
{
  "endpoint": str,
  "probe": { initialize_ok, tools_list_ok, tool_names, error },
  "records": [ 每客户端一条，结构见 4.2 ],
  "unmanaged": [ 未纳管但已安装的客户端 ],
  "summary": { 各状态计数 },
  "capability_groups": [ 能力组名列表 ]
}
```

> 说明：`profile` 字段不在此顶层结构中——它由阶段二汇总层（`report_all_profiles`）在 `results[i].profile` 注入；阶段二新增的 `capability_groups` 才是本契约的能力组键来源（见阶段三详细设计 §2.4 契约漂移修正）。

约束：阶段一之后，records 字段只增不改名不删除；能力组以 `capabilities` 字典呈现，GUI 矩阵列按字典键动态生成。修复操作在阶段三仍仅由 CLI 触发，GUI 不提供写入按钮。

## 13. 设计决策记录（ADR）

**ADR-1：profile 注入采用"新参数 + 旧分支回退"而非直接改签名。**
理由：现有测试与 scan.py 多处调用 `check_agents(config, ...)`/`fix_mcp_clients(config)`，直接改签名会造成大面积测试返工；回退分支保留一个版本周期，阶段二清理。代价：引擎层暂时存在两条取 profile 的路径，需在代码注释中标注弃用时间表。

**ADR-2：能力组空映射 = 不生成能力组维度，而非生成"不可用"。**
理由：`_has_group` 对空组返回 False 是合理的判定语义（没有要求就没有"满足"），但在报告层把通用端点渲染成"能力不可用"会误导用户。generic-http 这类 profile 的审计结论应只有 L4 基础探测两项。

**ADR-3：阶段一活体探测仅限 HTTP 传输，示例 profile 不含 stdio 桥。**
理由：实测 `probe_mcp` 是纯 HTTP POST 实现，stdio 传输需要子进程会话管理，是完全不同的探测机制。规划文档阶段一验收标准中"本地 stdio 桥"的表述需相应修订为"任意 HTTP MCP 端点"；stdio 探测列入阶段二议题。

**ADR-4：`url_policy` 引入而非放宽全局校验。**
理由：`is_valid_mcp_url` 的严格标准（HTTPS + /mcp）是生产端点的安全基线，不应为本地测试端点全局放宽；按 profile 声明放松，责任归属清晰，默认仍严格。

**ADR-5：不引入 schema 校验库（jsonschema 等）。**
理由：profile schema 字段少、规则简单，手写校验可输出定制化错误文案（指明字段与期望格式），且不增加分发依赖（阶段二要单命令安装）。若阶段二 schema 复杂度上升再评估。

**ADR-6：hermes_checker 走"声明化泛化"而非"整体外迁"作为首选。**
理由：遗留接入检查（环境变量启发式、通道完整性）是审计产品的通用能力，hermes 只是第一个实例；外迁会丢失这部分产品价值。声明化改造虽是本阶段最大工作量，但一次性解决。外迁保留为退路。

## 14. 开放问题

> **已定案**（2026-09-01）：以下 4 项已由《决策记录-待决问题定案.md》定案（对应 D7–D10）：

1. **hermes_checker 旧文件去留** →【已决 D7】测试全绿后**删除**原文件（git 历史即归档），不保留归档副本；
2. **state.yaml 跨 profile 对比** →【已决 D8】按 profile 分键存储快照，切换 profile 重置基线；
3. **退出码** →【行动项 D9】已并入阶段二 §7.2，阶段二开工第一步 grep 排查「恒为 0」依赖；
4. **规划文档联动修订** →【已决 D10】ADR-3 的「本地 stdio 桥」已修订为「任意 HTTP 端点」，stdio 探测并入阶段二 §5.2。
