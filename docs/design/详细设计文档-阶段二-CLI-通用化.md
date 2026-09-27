# skill-mcp-studio 详细设计文档

**——阶段二：CLI 通用化**

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-01 | 基于《产品形态与开发计划》v1.0 §9 与《阶段一详细设计》v1.0 的接口约定编写 |

## 1. 引言

### 1.1 目的与范围

本文档是 skill-mcp-studio 阶段二的详细设计，回答「怎么把内部工具变成陌生人可用的产品」。阶段二的四条主线：**能力组模板库、跨 profile 汇总报告、独立打包分发、stdio 传输活体探测**，并承接阶段一遗留的退出码约定与技术债清理。

范围边界：

- **覆盖**：阶段二全部改造（总体规划 §9.1–§9.5），以及为阶段三 GUI 预留的汇总报告数据契约；
- **不覆盖**：阶段三 Tauri GUI 的实现细节（仅约定其消费的汇总报告 JSON，见第 12 节）；阶段四按需加载（立项另定）。

### 1.2 与已有文档的关系

《产品形态与开发计划.md》v1.0 §9 回答「阶段二做什么」；本文回答「怎么做」。本文的所有接口描述以阶段一交付的模块与数据契约为准（profile_loader、legacy_checker、combined_checker 的 profile 注入与动态能力组、mcp_probe 的 token_env/url_policy 参数化、`check_agents` 返回结构）。与总体规划表述不一致处，在第 13 节 ADR 中显式说明。

### 1.3 术语

| 术语 | 定义 |
|------|------|
| 能力组模板 | 一组可复用、可命名的能力组集合（组名→工具名列表），供 profile 的 `required_capabilities` 引用 |
| 汇总报告 | 一次运行遍历多个 profile，输出「profile × 客户端 × 状态字段」矩阵（CSV/JSON） |
| transport | 活体探测的传输抽象：HTTP 系（streamable-http / sse，阶段一已有）与 stdio（阶段二新增） |
| 退出码 | 进程结束语义：0=全绿，1=存在不合规项，2=配置/运行错误 |
| source of truth | config.yaml 的客户端注册表（mcp_tools / tools / auto_discover 段） |

## 2. 设计目标与约束

### 2.1 设计目标（阶段二）

1. **能力组模板化**：把「能力组 = 一组工具名」从每个 profile 手写升级为可引用、可合并、可校验的模板，内置起手模板 + 用户自定义模板目录；
2. **跨 profile 汇总**：`--all-profiles` 一次遍历全部 profile，产出机读矩阵，供 CI 断言与阶段三 GUI 消费；
3. **stdio 活体探测**：探测层引入 transport 抽象，补齐 stdio（本地 MCP 服务器）的第四层验证，维持「探测无副作用」承诺；
4. **独立分发**：单命令安装（pipx / brew），排除源码依赖即可完成一次审计；补齐退出码契约；
5. **默认行为零变化**：不传 `--all-profiles` 时的单 profile 审计行为与阶段一完全一致。

### 2.2 设计约束（继承自阶段一的硬事实）

阶段一已交付、阶段二必须尊重的事实：

| 约束 | 出处 | 对阶段二的影响 |
|------|------|--------------|
| profile 由 `profile_loader.load_profile` 统一装载，`ProfileBundle = {name, profile, config}` | core/profile_loader.py | 模板解析能力扩展在 load_profile 内完成，引擎层不感知 |
| 探测入口 `probe_mcp(url, *, timeout, token, token_env, url_policy)`，仅 HTTP（urllib POST） | core/mcp_probe.py | stdio 抽象以该入口为基准新增 transport 分派，不改 HTTP 既有行为 |
| 能力组判定 `_has_group`：`bool(required) and all(...)`；空能力组不生成字段 | core/combined_checker.py | 模板合并后仍是「组名→工具名」映射，判定语义不变 |
| 状态模型「7 固定 + N 动态能力组」，record 含 `capabilities` 字典 | core/combined_checker.py | 汇总矩阵的能力组列由各 profile 的 `required_capabilities` 键动态并集生成 |
| 报告契约 `check_agents` 返回 `{endpoint, profile, probe, records, unmanaged, summary}` | 阶段一详细设计 §12 | `--all-profiles` 的 JSON 是该结构的列表包装，不二次定义 |
| 退出码现状：全流程无 `sys.exit` 调用，恒返回 0 | 阶段一详细设计 §9 | 引入退出码需先排查依赖「恒为 0」的脚本（开放问题 3 → 阶段二定案） |
| `url_policy: relaxed` 已存在 | 阶段一 core/mcp_probe.py | stdio 端点无需 URL，url_policy 仅对 HTTP transport 生效 |

### 2.3 非目标

- 不说话 skill/技能安装、分发、市场（企业级同步平台领域）；
- 不做 GUI 写入按钮（阶段三仍只读）；
- 不做云端托管、多用户权限；
- 不引入配置文件 schema 校验库（延续 ADR-5，手写校验）。

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  表现层  scan.py（argparse + 阶段编排 + 退出码）                 │
│          --profile / --all-profiles / --format              │
└──────────────┬──────────────────────────────────────────────┘
               │ load_profile（含模板解析） / check_agents
┌──────────────▼──────────────────────────────────────────────┐
│  引擎层 core/                                                 │
│  ┌─────────────────────┐  ┌─────────────────────────────┐   │
│  │ capability_templates│  │ mcp_probe（transport 分派）  │   │
│  │（模板加载/合并/校验） │  │  ├─ HTTP  阶段一即有        │   │
│  └─────────┬───────────┘  │  └─ STDIO 阶段二新增        │   │
│            │              └─────────────────────────────┘   │
│  ┌─────────▼────────────┐  ┌─────────────────────────────┐   │
│  │ combined_checker     │  │ multi_profile_reporter      │   │
│  │（7+N 动态能力组）     │  │（矩阵 JSON / CSV 输出）      │   │
│  └──────────────────────┘  └─────────────────────────────┘   │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  配置层 config.yaml（profiles + templates + 客户端注册表）      │
│  profile_loader（装载 / 模板引用解析 / 旧结构兼容包装）           │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 模块清单与阶段二处置

| 模块 | 现状（阶段一后） | 阶段二处置 |
|------|------------------|-----------|
| profile_loader.py | profile 读取/校验/旧结构包装 | **改**：解析 `required_capabilities` 的模板引用（第 5.1 节） |
| mcp_probe.py | HTTP 探测，token_env/url_policy 参数化 | **改**：新增 transport 分派，stdio 分支（第 5.2 节） |
| combined_checker.py | profile 注入 + 动态能力组 | 微改：能力组来源改为「模板合并后的 required_capabilities」，逻辑不变 |
| reporter.py | 动态列渲染（单 profile） | **改**：新增矩阵模式（跨 profile 列表列渲染） |
| cli_modes.py | CLI 模式归一化 | **改**：`--all-profiles` / `--format` 归一化 |
| scan.py | 11 阶段编排 | **改**：退出码、`--all-profiles` 循环、`--format` 透传 |
| tools_registry / mcp_fixer / mcp_checker / legacy_checker / hooks_checker 等 | 不变 | 不动 |
| —（新增） | — | **capability_templates.py**：模板加载/合并/校验 |
| —（新增） | — | **transport.py**：探测传输抽象接口 + stdio 实现 |
| —（新增） | — | **multi_profile_reporter.py**：汇总报告 |

## 4. 核心数据模型

### 4.1 能力组模板 schema v1

模板与 profile 同级列入 config.yaml，新增顶层 `templates` 段：

```yaml
templates:
  memory-basic:                     # 模板名（模板间引用/校验标识）
    tags: [memory]                  # 可选，检索/文档用途
    capabilities:
      memory: [memory_search, memory_add, memory_get]

  hermes-full:                      # 内置起手模板二：hermes 专用
    tags: [memory, ai-memory, tdai, hermes]
    capabilities:
      hermes_memory: [memory_search, memory_add]
      ai_memory: [ai_memory_query, ai_memory_handoff_begin, ai_memory_call]
      tdai: [tdai_memory_search, tdai_knowledge]
      hermes: [hermes_health, hermes_chat]
```

profile 通过 `required_capabilities` 的 `extends` 引用模板，并可与手写组合并：

```yaml
profiles:
  hermes-home:
    name: hermes
    url: https://hermes-mcp.example.com/mcp
    required_capabilities:
      extends: [hermes-full]        # 引用一个或多个模板
      # 手写补充（可选），与模板组做并集；同名组以手写为准覆盖
      custom_group: [extra_tool]
```

字段约束：

| 字段 | 必填 | 校验规则 |
|------|------|----------|
| templates.<name>.capabilities | 是 | 组名→工具名列表；组名与工具名均非空字符串 |
| templates.<name>.tags | 否 | 字符串列表 |
| required_capabilities.extends | 否 | 模板名列表；引用的模板必须存在（fail fast） |
| 名称冲突 | — | 手写组与模板组同名时，**手写覆盖模板**（意图显式优先） |

**合并语义**（`resolve_capabilities(profile) -> dict`）：

```
resolved = {}
for tpl in profile.required_capabilities.extends ?? []:
    for group, tools in templates[tpl].capabilities:
        resolved[group] = resolved.get(group) ∪ tools     # 同组并集
for group, tools in profile.required_capabilities 手写组:
    resolved[group] = tools                              # 手写覆盖（整组替换）
```

合并后得到一个普通的「组→工具名」映射，交给 combined_checker；`_has_group` 判定语义不变。

### 4.2 stdio transport 数据模型

```python
# profile 中新增 stdio 相关字段（阶段一 schema 的增量）
profiles:
  local-notes:
    name: my-notes-mcp
    transport: stdio                    # 新增合法取值
    command: ["my-notes-server"]        # 必填：argv（无 shell 解释）
    args: ["--config", "~/.notes.toml"] # 可选：追加参数
    env:                                 # 可选：子进程环境变量（含鉴权 token 注入）
      NOTES_AUTH_TOKEN: "${NOTES_AUTH_TOKEN}"   # 支持 ${ENV} 展开，避免令牌落盘
```

- `transport: stdio` 时 `url` 不再是必填（stdio 端点无 URL）；`url_policy`/`probe_timeout`/`auth_token_env` 对 stdio 不适用或语义另定（timeout 复用为「启动+握手总超时」）；
- `command`/`args` 必须按列表声明，**禁用 shell 字符串**（安全，见第 8 节）。

### 4.3 汇总报告 schema（`--all-profiles`）

JSON 输出 = 阶段一 §12 数据契约的列表包装，不重复定义 record 结构：

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-01T16:00:00Z",
  "active_profile": "hermes-home",
  "profiles": ["hermes-home", "local-notes"],
  "results": [
    { "profile": "hermes-home", "ok": true,  "...": "check_agents 返回结构原样" },
    { "profile": "local-notes", "ok": false, "...": "check_agents 返回结构原样" }
  ]
}
```

CSV 输出 = 矩阵展平（每行一个客户端，列 = profile + 7 固定字段 + 能力组字段）：

```
profile,client,installed,skills_compliant,mcp_configured,mcp_initialize_ok,mcp_tools_list_ok,capability_memory,capability_hermes_memory,...,hooks_configured,legacy_channels
```

- 能力组列 = 所有 profile `required_capabilities` 键的**并集**；某 profile 无该组时该列留空（不写 False，避免与「探测失败」混淆）；
- 空值语义（定案）：CSV 中能力组列的值只能是 `True` / `False` / 空串三种——`True`/`False` 表示「该 profile 声明了此组」且「满足/未满足」，**空串**表示「该 profile 未要求此组」。消费方（Excel/脚本）应把空串视为 `N/A` 而非 `False`；`legacy_channels` 列空串表示「无 legacy 通道」；
- `--format json|csv|md|table` 默认 `table`（终端）÷ `csv`/`json`（CI/机读）。

## 5. 模块详细设计

### 5.1 capability_templates（新增）

职责：模板装载、引用解析、合并、循环引用检测。接口：

```python
def load_templates(config: dict) -> dict[str, Template]:
    """从 config['templates'] 装载，fail fast：重复名、空 capabilities 报 TemplateError。"""

def resolve_capabilities(profile: dict, templates: dict) -> dict[str, list[str]]:
    """
    按 4.1 合并语义解析 profile 的能力组：
    - 无 extends → 直接返回手写 required_capabilities（等价阶段一行为）；
    - extends 引用缺失模板 → TemplateError（指明模板名与已定义模板清单）；
    - 检测模板间循环引用 → TemplateError（递推展开时记录调用栈）。
    返回合并后的 {'组名': [工具名]}，交给 combined_checker，判定语义不变。
    """
```

设计要点：

- 模板间 `extends` 在本阶段**不支持模板引用模板**（首版只允许 profile→模板；模板嵌套是阶段三之后议题，见 ADR-7），从而把循环引用问题收敛到「能否在 profile 层自引用」，大幅降低实现复杂度；
- 用户自定义模板目录 `~/.config/skill-mcp-studio/templates/*.yaml` 在 `config.yaml` 的内置 `templates` 之后装载，**用户模板覆盖同名内置模板**（覆盖优先级：用户侧 > 内置，见 ADR-8）。

### 5.2 transport 抽象与 stdio 探测（新增 + 改造）

现状 `probe_mcp` 是纯 HTTP 实现。阶段二引入 transport 维度而不破坏 HTTP 行为：

```python
# core/transport.py（新增）：抽象接口
class Transport(Protocol):
    def probe(self, spec: ProbeSpec, timeout: float) -> ProbeResult: ...

# ProbeSpec = 统一探测输入（URL 或 command，二选一）
# ProbeResult = { "initialize_ok", "tools_list_ok", "tool_names", "error" }  # 沿用现有结构

# core/mcp_probe.py 改造：入口按 transport 分派
def probe_mcp(*, transport="streamable-http", url=None, command=None, args=None,
              env=None, timeout=8.0, token=None, token_env=None, url_policy="strict"):
    if transport == "stdio":
        return StdioTransport().probe(...)
    return HttpTransport().probe(url=url, ...)   # 既有无变化，纯搬迁
```

stdio 探测流程（三步不变：initialize → notifications/initialized → tools/list）：

```
1. subprocess.Popen(command + args, stdin=PIPE, stdout=PIPE, stderr=PIPE,
                    env=展开后的 env，cwd=用户可选的 profile.workdir)   # 禁用 shell
2. 行式读取 stdout，半写 stdin：JSON-RPC 2.0 消息按 '\n' 分帧（Content-Length 帧与换行帧都支持）
3. 启动 + initialize 握手计入 timeout（默认 8s）；
4. 结束后 terminate 子进程（先 SIGTERM，超时 SIGKILL），清理会话
```

- token/env 展开：`${ENV}` 引用当前进程环境变量，缺失时报加载期错误（不静默置空）；
- 探测只发三类只读请求，维持「无副作用」承诺。

> **落地状态（2026-09-05 评审 CLI-5 整改）**：本节接口形态已完整落地——
> `ProbeSpec`（frozen dataclass）、`Transport` 协议（`runtime_checkable`）、
> `StdioTransport`/`HttpTransport`、`TRANSPORTS` 注册表与 `dispatch_probe`
> 统一分派；`probe_mcp` 的 stdio 分支经由注册表分派（不再直连 `probe_stdio`）。
> timeout 语义明确为**单一 deadline 预算**（启动 + 两次握手共享，评审 CLI-5a），
> 读取层为跨平台读线程 + 队列（替代 `select`，Windows 管道可用，评审 Windows 兼容）。
> 回归测试：`tests/test_transport_dispatch.py`。

### 5.3 multi_profile_reporter（新增）

```python
def report_all_profiles(results: list[CheckResult], fmt: str = "table") -> str:
    """results[i] = {profile, ok, ...check_agents 返回结构}；按 4.3 输出 table/csv/json。"""
```

- 矩阵列：固定 7 列 + 能力组列（所有 profile 键并集）+ profile 列；
- 能力组列缺失值留空（区分「未要求」与「探测为否」）；
- JSON 仅做 `results` 包装与 `schema_version` 注入，record 原样透传（阶段三直接消费）。

### 5.4 打包与分发

- `pyproject.toml`：PEP 621 元数据 + 控制台脚本入口 `skill-mcp-studio = scan:main`；
- 不含任何 `profiles/<name>` 与 `deploy/` 个人拓扑资源（分发白名单排除，防泄漏）；
- config 外置：安装后无 config 也能跑 `--help` 与 `--list-profiles`（空 profiles 时给出最小配置示例）；
- 发布前 checklist：README 三步入上手（安装 → 最小 config → 首跑审计）、`python -m build` 通过、`pipx run` 冒烟。

## 6. 关键流程

### 6.1 模板解析流程（load 时一次完成）

```
load_config(config.yaml)
  └─ profile_loader.load_templates(config)         # 装载 + 校验，fail fast
  └─ load_profile(config, name)                   # 选 profile
       └─ resolve_capabilities(profile, templates) # extends → 合并
            ├─ 缺失/循环 → TemplateError（加载期退出，退出码 2）
            └─ 得 resolved_capabilities，注入 check_agents
```

单 profile（无 `--all-profiles`）时，profile 未用模板则 `resolved == 手写 required_capabilities`，与阶段一行为逐字节一致。

### 6.2 stdio 探测流程（第四问）

详见 5.2。与 HTTP 探测的对等关系：同一 `probe_mcp` 入口 → 同一 `ProbeResult` → 同一 L4 判定，报告层不感知 transport。

### 6.3 汇总报告流程（`--all-profiles`）

```
for each profile in profiles:
    result = check_agents(config, scan_result, live_probe, profile=p)
    results.append({"profile": p.name, "ok": <无不合规>, ...result})
report_all_profiles(results, fmt)
exit = 0 if 全部 ok else 1
```

- 单个 profile 的扫描结果（installed / skills_compliant 等客户端侧字段）跨 profile 共享一次扫描，只重算端点相关（L3/L4）部分，节省成本；
- 单 profile 出错（如某 stdio 端点无法启动）不阻断其他 profile：该 profile 记 `ok=false` + `error`，继续其余。

### 6.4 打包发布流程

CI 触发：跑全量测试 → `--all-profiles` 冒烟（用于通用模板 + 假端点）→ build → 发布物校验（不含个人拓扑）→ 上架 pipx/brew。

## 7. CLI 设计

### 7.1 新增参数

```
--all-profiles        遍历 profiles 全部，输出汇总报告（与 --profile 互斥）
--format <fmt>        报告格式：table（默认）/ csv / json / md
```

### 7.2 退出码契约

| 码 | 语义 | 触发 |
|----|------|------|
| 0 | 全绿 | 所有已安装客户端通过其 profile 的合规判定（含空能力组场景） |
| 1 | 存在不合规项 | 任一 record 的必查字段为 False、发现 legacy_channels、存在 unmanaged 客户端、或探测失败 |
| 2 | 配置/运行错误 | config 非法、profile/模板缺失、transport 不支持、内部异常 |

规则：

- 退出码只反映「判定」而非「修复动作」；`--fix-*` 修复成功的场景退出码不变；
- `--dry-run` 只影响是否写盘，不影响退出码判定语义；
- 引入前执行 `grep` 排查外部脚本对「恒为 0」的依赖（阶段一开放问题 3），受影响的集成迁移到「区分 0/1/2」。

## 8. 安全设计

在阶段一 8 条承诺之上，阶段二新增：

1. **stdio 无 shell**：`command`/`args` 必须为 argv 列表，`Popen` 禁用 `shell=True`，杜绝从配置注入命令；
2. **令牌不落盘强化**：stdio 鉴权经 `env` 的 `${ENV}` 展开注入，令牌只存在于进程环境，不进 config、不进报告；
3. **子进程治理**：探测结束强制 terminate + 超时 kill，不遗留孤儿 stdio 进程；
4. **超时护栏**：stdio 启动 + initialize 握手计入 `probe_timeout`，防止挂死阻塞整个 `--all-profiles`；
5. **分发最小权限**：发布物白名单排除 `profiles/`、`deploy/` 与测试夹具中的个人拓扑，防泄漏（延续阶段一「零个人拓扑」）。

## 9. 错误处理

- 模板错误（缺失引用/循环/空组）→ `TemplateError` → 退出码 2，加载期 fail fast；
- stdio 子进程启动失败 / 握手超时 / stderr 协议错误 → 记入 `probe.error`，L4 置 False，**属退出码 1**（这是「探测结果」而非「工具错误」）；transport 值非法则属退出码 2；
- 单 profile 失败不阻断其余（`--all-profiles` 语义）；
- 单客户端配置损坏 → error 状态，不阻断其他客户端（沿用阶段一行为）。

## 10. 测试设计

- **模板解析单测**：extends 合并 / 手写覆盖 / 同组并集 / 缺失模板报错 / 循环引用报错 / 用户模板覆盖内置；重点断言「无 extends 时 resolved == 手写」，锁定阶段一回归；
- **stdio 探测单测**：用容器内假 stdio MCP 服务器（fixture）验证三步握手与 tool_names 提取；断言 terminate 后无残留进程（ps 检测）；
- **transport 分派对等**：同一 `probe_mcp` 下 HTTP profile 与 stdio profile 产出同构 `ProbeResult`；
- **汇总报告单测**：多 profile 矩阵的并集列、空值列、CSV/JSON 结构、单 profile 结论与 `--profile` 单独运行一致；
- **退出码测试**：构造全绿 / 含不合规 / 配置错误三组 fixture，断言 0/1/2；
- **回归**：阶段一 10 个测试文件全绿；默认单 profile `--full` 输出与阶段一基线逐行一致。

## 11. 目标目录结构

```
skill-mcp-studio/
├── scan.py                        # 入口：退出码、--all-profiles/--format
├── pyproject.toml                 # 打包元数据（阶段二新增）
├── config.yaml                    # profiles + templates + 客户端注册表
├── core/
│   ├── capability_templates.py    # 新增
│   ├── transport.py               # 新增：探测传输抽象
│   ├── multi_profile_reporter.py  # 新增
│   ├── profile_loader.py          # 改：模板引用解析
│   ├── mcp_probe.py               # 改：transport 分派
│   ├── combined_checker.py        # 微改：能力组来源 consolidated
│   ├── reporter.py                # 改：矩阵模式
│   ├── cli_modes.py               # 微改
│   └── …
├── tests/
│   ├── fixtures.py                # 已有（阶段一）
│   ├── test_capability_templates.py # 新增
│   ├── test_stdio_probe.py        # 新增
│   ├── test_multi_profile_reporter.py # 新增
│   └── …
├── data/
├── profiles/<name>/               # 个人拓扑资源，不参与分发
└── references/
```

## 12. 阶段三预留：GUI 消费汇总报告

GUI（只读审计看板）在单 profile 之外，直接消费 `--all-profiles --format json` 的 `results`：

- 视图一（单 profile）：`results[i]` 内的 `records`，等价阶段一 §12 契约；
- 视图二（跨 profile 切换）：`profiles` 列表 + `results[i].summary` 顶栏汇总；
- 约束延续：records 字段只增不删，GUI 矩阵列按 `capabilities` 键动态生成；GUI 无写入按钮。

## 13. 设计决策记录（ADR）

**ADR-7：模板首版只支持「profile → 模板」一层引用，不支持模板嵌套。**
理由：一层引用已覆盖「复用能力组」的诉求；模板嵌套（模板 extends 模板）带来循环引用检测与合并顺序的两大复杂度，收益在此阶段不成比例。预留 schema 空间，阶段三后按需启用。

**ADR-8：覆盖优先级「用户模板 > 内置模板 > profile 手写」改为「手写 > 用户模板 > 内置模板」。**
理由：能力组要求对某个具体 profile 而言是最具体的意图，应拥有最高优先级，与普遍直觉（更具体 → 覆盖更通用）一致。此决策修正了 v1.0 总纲 §9.1 中未显式声明优先级的含糊处。

**ADR-9：汇总报告机读格式仅为 CSV + JSON，不做 XML/YAML。**
理由：JSON 直接对接阶段三 GUI 与 CI 断言，CSV 便于 Excel 复核；引入更多格式无实际消费方。`--format` 保留 `table`（终端）与 `md`（贴文档）两种人读形态。

**ADR-10：退出码 1 覆盖「探测失败」，2 限定「工具自身运行错误」。**
理由：端点不可达是「被审计对象不合规」（1）而非「工具坏了」（2）；把两者分开，CI 才能区分「环境有问题」与「代码有 bug」。与阶段一 §9 的预约定一致。

**ADR-11：分发采用标准 pyproject + pipx/brew，不做 Docker 镜像分发。**
理由：目标用户是本地多客户端开发者，pipx/brew 是零心智的本地安装路径；Docker 隔离了文件系统，恰恰无法审计宿主机的客户端配置，与本产品「本地审计」的定位冲突。

**ADR-12：stdio 探测只支持 CWD-可启动的命令，不做远程/容器化 stdio 代理。**
理由：远程 stdio 需额外 ssh/容器编排，脱离「本地 MCP 服务器」的典型形态；阶段四若出现真实诉求再评估。

## 14. 开放问题（阶段二收口）

1. **模板分层目录** → **已落地（2026-09-05 评审整改）**：三层来源，后装载者覆盖同名——内置 `config['templates']` < 项目级 `<config 所在目录>/.skill-mcp-studio/templates/`（随主仓库分发，经 `load_profile(config_path=...)` 穿线）< 用户级 `~/.config/skill-mcp-studio/templates/`。同批落地评审 CLI-4：目录内任一 `*.yaml`/`*.yml` 畸形/不可读 → `TemplateError` fail fast（退出码 2）并逐一点名问题文件，不再静默跳过。测试：`test_capability_templates.py::DirTemplatesTest`、`test_end_to_end_template_audit.py::ProjectTemplatesWiringTest`。
2. **能力组列的空值与 False 表达** → **已定案**：CSV 中能力组列输出 `True`/`False` 仅当该 profile 的 `required_capabilities` 声明了该组；否则输出**空字符串**（`""`），语义为「本 profile 未要求该组」，与「探测为否」严格区分。`legacy_channels` 列空串表示「无 legacy 通道」。语义示例与 CSV 样例见 README「能力组模板」节与 §4.3。
3. **退出码迁移影响面** → **已定案（零影响面）**：已 `grep` 排查仓库内外，无任何外部脚本调用 `scan.py`/`skill-mcp-studio` 并依赖「恒为 0」——所有 `scan.py` 引用均在文档示例中，`scripts/` 仅含 MCP 服务器脚本、`core/*.py` 中的 `returncode == 0` 均为内部 `subprocess` 调用，不构成迁移阻塞。退出码 0/1/2 可直接启用（ADR-10）。
4. **schema_version 落地** → **已定案**：profile schema 的版本字段即 config **顶层** `schema_version: 1`，由 `profile_loader._validate_schema_version` 强制（未知版本 fail fast → 退出码 2）。汇总报告 JSON 的 `schema_version: 1` 沿用同一版本号，二者对齐。
5. **stdio 探测的 Windows 兼容** → **代码级适配已完成（2026-09-05 评审整改）**：`transport.py` 已消除三处 POSIX 专属依赖——`select.select`（Windows 不支持管道）改为后台读线程 + 队列；`SIGTERM/SIGKILL` 改为跨平台的 `proc.terminate()/proc.kill()`；Windows 下子进程加 `CREATE_NO_WINDOW` 避免闪窗。**真机验证仍待 Windows 环境**（本机仅 macOS），届时补跑 `test_stdio_probe`/`test_transport_dispatch` 即可收口。
