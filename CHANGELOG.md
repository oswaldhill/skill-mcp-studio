# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 约定，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 注：项目早期历史未按版本逐次发布，以下按可识别的版本里程碑汇总。

## [Unreleased]

### 修复：最后 2 个「未知」也都是误报，现已清零（2026-11-15）

接上一版把 well-known 来源接上后，本机还剩 2 个 unknown。逐个查实，**两个都
不是真的查不了**：

**① `code-simplifier` —— 仓库改名，301 没被跟随**
- 来源 `simonwong/agent-skills` 已改名为 `simonwong/skills`，GitHub API 返回
  **301 重定向**（不是 404）。
- `_http_get_json` 的 curl 调用没带 `-L`，把「改名」读成了「仓库不存在」。
- 上游 `npx skills` 同样误报为 `Private or deleted repo`。
- 修复：curl 加 `-L`。验证：跟随重定向后拿到 `full_name = simonwong/skills`。

**② `lark-unified` —— 本机元数据被当成「未提交修改」**
- 改动的是 `_skillhub_meta.json` 里的 `iconLocalPath`：
  `/Users/hozonauto/...` → `/Users/oswaldhill/...`。
- 该字段只记录**本机绝对路径**，换机器必然被改写，与技能内容无关。
- 修复：新增 `MACHINE_LOCAL_FILES` 与 `filter_machine_local()`，计算 `dirty`
  前先剔除这类文件（含 git 重命名简写 `dir/{a => b}` 的展开）。

**实测结果：本机 171 个技能 unknown 25 → 0**，全部有确定结论。

> 判据：新增 `tests/test_unknown_root_causes.py` 5 例（curl 必须带 -L、
> 本机元数据必须被过滤、重命名简写、整批元数据等于不脏）全过；
> 全量 1935 passed / 2 skipped；ruff → All checks passed。

### 新增：well-known 来源技能的更新检测（2026-11-15）

用户反馈：「不是 GitHub 来源的应该也可以查询」。原判定把 22 个飞书 `lark-*`
技能全部落进 `unknown`「无 GitHub 来源信息，无法比对」——25 个未知里占 88%。

**这三类技能此前没有任何一方在检查**：上游 `npx skills update` 实测把它们归为
`cannot be checked automatically (Well-known skill)`，而我们只认 GitHub。

但端点本身是公开可读的（实测 HTTP 200）：
- `https://<host>/.well-known/skills/index.json` — 技能与文件清单
- `https://<host>/.well-known/skills/<name>/SKILL.md` — 正文

- 新增 `core/skill_wellknown.py`：`classify_source` / `parse_index` /
  `compare_skill`。**判定用 SKILL.md 内容哈希，不用 files 清单**——实测
  `lark-doc` 本地 44 个文件、远端 index 只报 16 个，清单不可作依据。
- `check_updates` 里 well-known 判定**优先于所有分支**：这些记录常既无
  skillPath 又无版本号，会先落进「本地无版本号」兜底分支（`lark-doc` 实测踩到）。
- 查不成一律 `unknown`（网络失败 / 404 / 本地缺 SKILL.md），绝不静默算 `current`
  —— 那正是本次要修的毛病。

**实测效果（本机 166 个技能）**：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 未知 | 25 | **2** |
| 已最新 | 141 | 158 |
| 可升级 | 0 | **6** |

剩下 2 个未知都有真实原因：`code-simplifier`（上游仓库已私有/删除）、
`lark-unified`（本地有未提交修改）。并且首次查出 6 个飞书技能上游确有新版本：
`lark-apps`、`lark-base`、`lark-calendar`、`lark-event`、`lark-task`、
`lark-workflow-meeting-summary`。

> 判据：新增 `tests/test_wellknown_check.py` 12 例（来源识别、index 解析、
> 内容比对、拉取失败必须 unknown、URL 构造）全过；全量 1930 passed / 2 skipped；
> ruff → All checks passed。

### 修复：清理登记残留没有可点的入口（2026-11-15）

用户看到检查完成弹框写着「有 5 个技能已卸载但登记残留，可在技能行删除」，
但**那 5 个技能的目录已经不在了，技能行里根本没有它们**，无法按提示删除。
真正的清理按钮藏在「设置」页，从这条提示根本找不到。

清理能力本身早已存在（`prune_missing_registrations`：dry-run → 备份 →
只删磁盘上确实没有的，保留其它字段），缺的只是**入口可达**：

- `modalNotice` 新增 `opts.extraAction = {label, action}`，让提示本身就能动手
  （此前 `opts.action` 只是**一行文字**，无法点击）。
- 检查完成弹框在 `missing > 0` 时直接给出「清理 N 条登记残留」按钮，
  点击即走既有的 dry-run → 确认 → 执行链路。
- 提示文案改为「登记表还留着条目，技能目录已不在」，不再误导用户去技能行删除。
- 顺带把统计卡 HTML 抽成 `_noticeStatsHtml()`，保持 `modalNotice` 短小
  （原测试约定函数体前 1200 字符内必须出现 mountModal）。

> 判据：新增 `tests/test_prune_missing_entry.py` 6 例（后端 dry-run 能力、
> GUI 入口存在、弹框内有可点按钮、文案不再误导、必须二次确认、先 dry-run）；
> 全量 1918 passed / 2 skipped；ruff → All checks passed；
> Playwright 实测：弹框内「清理 5 条登记残留」按钮可点，点击后弹出确认框
> 并准确列出 lark-minutes、lark-note、lark-vc、lark-vc-agent、slides。

### 修复：窄窗口下 Skills 工具栏溢出、标题被压成竖排（2026-11-15）

用户 App 窗口约 770px 宽，工具栏有 8 个按钮。截图显示：「Skills」标题被挤成
一字一行的竖排，右侧「检查更新」等按钮被切到屏幕外。

两个根因，都是 CSS 少了一条约束：

1. `.page-head` 没有 `flex-wrap`：标题与 actions 抢同一行，放不下时不是换行，
   而是把标题压到最小宽度——于是竖排。
2. `.page-actions` 写了 `flex: none`：它按内容宽度撑开，实测 770px 时占
   717px 而容器只有 474px，超出部分直接被裁掉。

- `.page-head` 加 `flex-wrap: wrap`；标题区 `flex: 1 1 220px`、`min-width: 0`。
- `.page-actions` 改 `flex: 1 1 auto; min-width: 0; max-width: 100%`，
  内容放不下时整体换到下一行，按钮在行内再折。
- **主操作顺序前置**：来源视图 → 从 GitHub 安装 → 技能市场 → 使用分析 →
  刷新 → 检查更新 → 一键升级 → 修复链接。主操作永远在第一行。

> 判据：新增 3 例测试（主操作顺序、`.page-head`/`.page-actions` 可换行）；
> 全量 1912 passed / 2 skipped；ruff → All checks passed；
> Playwright 在 700/770/900/1100/1600px 五档实测：**零溢出、零隐藏、
> 标题高度恒为 26px**（不再竖排），窄屏自动折成两行。

### 新增：已安装标记与技能来源视图（2026-11-15）

用户装了 `research` 之后反馈：「对于已安装的 skill 请你进行一个展示」。实测问题
属实——预览列表里它和没装过的技能**长得一模一样**，勾选框照旧可用：
既无法确认刚装了什么，又可能重复安装（覆盖本地内容）。

**安装弹窗标出已装**：
- `parse_preview_skills` 复用既有 `detect_conflicts`，给每项打 `installed`
  标记，并给出 `installed_count` / `new_count`。
- GUI 已装项显示「· 已安装」徽标并**禁用勾选框**；进度行改为
  「共 38 个技能：已安装 2 个（不可重复勾选），未安装 36 个」。

**技能来源视图（新增）**：
- Skills 页工具栏新增「来源视图」，按来源仓库分组列出已安装技能
  （组按数量降序，组内按安装时间倒序）。
- 新增只读出口 `--skill-provenance [--format json]`，GUI 与 CLI 共用。
- **数据源是 `npx skills` 自己的 lock**（`~/.agents/.skill-lock.json`），
  只做投影、绝不写回，也不自建第二份来源表——两份数据迟早漂移，
  且漂移后没人能判断哪份对。
- **覆盖缺口如实报出**：实测 169 个技能里仅 47 个有来源登记，
  界面写明「122 个没有来源记录（手工拷入或整仓库形态）」，
  不把「没有记录」渲染成「没有来源」。
- 新模块 `core/skill_provenance.py`；lock 缺失或损坏一律返回空列表，
  来源视图出问题不拖垮整个 Skills 页。

`run_cli` 白名单同步登记 `--skill-provenance`。

> 判据：新增 16 例测试（来源模块 8 + CLI 2 + 已装标记 6）全过；
> 全量 1907 passed / 2 skipped；ruff → All checks passed；
> Playwright 驱动构建产物实测：预览标出 research/wayfinder 已装且禁用勾选、
> 来源视图渲染 8 个仓库分组。

### 修复：桌面 App 里弹「plugin:dialog|confirm not allowed by ACL」（2026-11-15）

用户安装技能后，界面**同时**出现两条矛盾的结果：一个绿色「已完成 / 已安装 xxx」
和一个红色「操作失败 / 后台操作失败：Command plugin:dialog|confirm not allowed
by ACL」。实测统一库确实多了该技能 —— 红框是误报。

根因：Tauri 的 capabilities 只放行 `dialog:default` 与 `dialog:allow-open`，
**没有** `dialog:confirm`。在桌面 App 里调浏览器原生确认框会抛
`Command plugin:dialog|confirm not allowed by ACL`，该异常逃逸成
unhandled rejection，被全局处理器兜住后弹红框。

项目早已提供 `confirmModal(title, message, danger, confirmText)` 并在注释里
写明「replaces browser window.confirm()」——新增代码没有沿用，直接用了原生 API。

- `confirmGithubInstall` / `confirmRepoInstall`（本轮新增）：改用 `confirmModal`。
- `confirmMarketInstall` / `confirmMarketUpgrade`（**既有代码**）也用了原生确认框，
  意味着此前在市场里点「安装」「升级」同样会误弹 ACL 错误，一并修正。
- 四个函数随之改为 `async` 并 `await` `confirmModal` 的结果。

> 判据：新增 2 例测试锁定（GitHub 安装流程禁止出现原生确认框、必须 await
> `confirmModal`）；全量 1891 passed / 2 skipped；ruff → All checks passed；
> `gui/dist/app.js` 中 `window.confirm(msg)` 调用数为 0。

### 修复：仓库安装崩溃（KeyError: 'package'）与错误展示错位（2026-11-15）

用户粘贴 `https://github.com/mattpocock/skills`、勾选 wayfinder 点「安装所选」后
报 `KeyError: 'package'`，且整段 Python traceback 被铺在面板进度行里，而弹框
只写「详见面板提示」——主次完全颠倒。

**崩溃根因**：`execute_plan` 的安装后校验只写了两个分支：

```python
if plan["action"] == "install":
    out["verify"] = verify_installed([plan["package"].split("@")[-1]])
```

它假设 install 计划一定有 `package` 字段（来自 `plan_install(package)`），
但仓库安装来自 `plan_install_repo(...)` —— 那是 `skills` 列表，**没有 package**。
两条 install 路径共用了同一个 `action` 值，校验处却只认其中一种结构。

- 改为按计划**实际字段**分派：有 `package` 按包名校验；有 `skills` 逐个校验
  用户勾选的名字；`all_skills` 时装之前不知道会落哪些目录，返回
  `skipped: all-skills` 而不是硬猜。

**错误展示错位**：

- `executeGithubInstall` 曾把 `res.stderr` 整段塞进面板进度行，弹框只说
  「详见面板提示」。改为：**弹框承载原因**，面板只留一句「安装失败」。
- 新增 `cliFailureText()`：优先取 JSON 里的 `reason`/`err`；遇到原始 traceback
  时只保留最后一行（`内部错误：KeyError: 'package'（完整堆栈见终端日志）`），
  不再把堆栈倒给用户。
- 安装失败时即使退出码非 0，也先尝试解析 stdout 的 JSON，与预览出口保持一致。

> 判据：新增 7 例测试（仓库安装不崩、逐个校验、`--skill *` 不崩、包名安装回归、
> 面板不铺 traceback、失败进弹框、失败也解析 JSON）全过；
> 全量 1889 passed / 2 skipped；ruff → All checks passed；
> 用真实仓库 `mattpocock/skills`（38 个技能）实测：勾选 wayfinder 安装成功，
> 统一库 164 → 165，弹框显示「已完成 / 已安装 wayfinder」。

### 修复：无技能仓库只显示一个右花括号（2026-11-15）

给一个不含 SKILL.md 的仓库（实测 `Goblinmine/homelab-diagram`）点「读取技能」，
预览区只出现一个 `}`，用户完全看不出发生了什么。

根因是**判定顺序错了**：`--market-preview` 在「仓库里没有技能」时仍输出完整
JSON，但退出码为 2（2 = 没有技能，不是崩溃）。GUI 先按退出码判失败、
再把 stdout 的最后一行当错误文案 —— 那是 JSON 的收尾 `}`，于是界面上只剩它。

- 改为**先解析 JSON 再判退出码**：只要能解析出 `action: "preview"`，就按
  其中的 `ok` / `reason` 展示，与退出码无关。
- 空清单提示写明原因：「该仓库里没有可安装的技能 —— 技能需要在仓库里带
  SKILL.md（含 name 与 description）」。
- CLI 的 reason 同步改为更直白的话：「这个仓库里没有技能（需要带 SKILL.md
  的目录）」，不再说「未能从仓库输出中解析出技能名」——那听起来像解析器的锅。

顺带修复：我在注释里写了字面量右花括号，被
`test_gui_dashboard_structure.py` 的字符计数当成代码括号，判为失配；已改写措辞。

> 判据：新增 3 例测试（非 0 退出码仍解析 JSON、reason 必须展示、
> 空清单须提到 SKILL.md）全过；全量 1882 passed / 2 skipped；
> ruff → All checks passed；Playwright 实测该仓库提示原因、
> 而有技能的仓库仍正常列出 9 个技能。

### 改进：从 GitHub 安装改为 Skills 页独立入口（2026-11-15）

上一版把 GitHub 安装做成了「技能市场弹窗搜索框的第二种输入」。功能是全的，
但**入口不可发现**：用户打开技能市场、输入关键词，看不到任何与 GitHub 相关的
痕迹，自然认为功能没做（实测反馈：「没有看到刚刚需要新增的功能」）。

判断依据不是「功能是否存在」，而是「用户能否找到它」。所以把它提到显眼位置：

- Skills 页工具栏新增 **「从 GitHub 安装」** 按钮，紧跟「技能市场」之后。
- 点击打开**独立弹窗**（不复用市场弹窗）：一个地址输入框 + 「读取技能」。
- 读取后渲染可勾选清单，底部固定「全选 / 全不选 / 安装所选」。
- 市场弹窗那条路径保留不动，两种用法并存、互不干扰。

验收时又发现并修复：
- 操作栏最初放在结果区**内部**，而结果区是弹窗唯一的滚动容器，技能一多
  按钮就被滚出视野（截图确认被裁切）。改为放在滚动区之外、
  `.insight-dialog > .market-toolbar` 的 flex:0 0 auto 层，按钮始终可见。
- 自造的 `.ine-toolbar` 类触发了 `ComponentRegistrationTest`（规范 §2.1/§5
  要求新增语义组件类必须回写 DESIGN.md）。改为复用已登记的
  `.market-toolbar`，不新增组件类。

> 判据：新增 `tests/test_dashboard_github_install.py` 13 例（入口存在、
> 弹窗结构、读取只读、未勾选拦截、argv 正确、白名单覆盖）；
> GUI 相关 490 passed；全量 1879 passed / 2 skipped；
> ruff → All checks passed；Playwright 驱动构建产物 12 项断言全过，
> 并断言按钮底部 1033 < 弹窗底部 1060（完整可见）。

### 新增：仓库预览解析为可勾选清单（2026-11-15）

上一版 `--market-preview` 只是把 `npx skills add <url> -l` 交给下游打印，
用户还得自己从终端输出里抄技能名。现在它**真的执行并解析**该命令，
GUI 直接渲染成可勾选的清单。

- `parse_preview_skills`：解析 clack 渲染的输出。先由 `strip_ansi` 洗掉
  颜色码与 `\r` 重绘，再按「`│` 后恰好 4 空格 + 单 token」识别技能名、
  6 空格以上识别描述。标题行（`◇`）与噪声行（`Found N skills`、
  `Available Skills`、`Use --skill`）都不会被误收。
- **声明数与解析数不一致会显式报出**（`count_mismatch`）：仓库说 9 个、
  只解析出 1 个时，界面标「清单可能不完整」，而不是把残缺清单当完整结果。
- GUI 预览区改为复选框列表：每行技能名 + 描述，配「全选 / 全不选」，
  底部「安装所选」只装勾选项，「安装全部」仍需二次确认。
- 去掉了上一版的自由文本输入框——勾选比手打技能名更不容易拼错。

验收中发现并修复：
- 重写渲染后按钮丢了 `data-src`，导致安装命令的仓库地址变成
  `undefined`（实测 argv 里是 `"--market-install", null`）。
- 我一度在界面文案里用了 emoji 当警示图标，被
  `test_design_spec_contract.py::EmojiAsIconBanTest` 拦下（规范 3b），
  已改为纯文字「注意：」。

> 判据：新增解析测试 7 例全过；全量 1866 passed / 2 skipped；
> `ruff check core tests scan.py scripts setup.py` → All checks passed；
> 用 Playwright 驱动构建产物实测：预览出 9 个技能名与描述、全选/全不选
> 生效、勾选 2 个后 argv 为
> `--market-skills vercel-composition-patterns,deploy-to-vercel`。

### 新增：技能市场支持 GitHub 仓库安装与预览（2026-11-14）

此前「技能市场」只能按包名搜索并安装，无法处理用户手上已有的 GitHub 地址；
而需求是两种入口：**搜索/输入包名** 与 **贴 GitHub 地址**。

`npx skills add` 本身已支持 `https://github.com/owner/repo`（实测 `--help`
确认），但直接透传有两个问题：① 一个仓库常含多个技能，直接 `add` 会把它们
**全部**写进统一库；② 外部地址是供应链入口，不能原样交给下游命令自己校验。

- **来源分派** `classify_install_source`：把输入分成 `github` / `package` /
  `rejected`。URL 只放行 `github.com` 及其 `www`/`raw` 变体，`file://`、任意
  第三方主机一律拒绝（单测锁定）。
- **仓库预览** `plan_repo_preview` → `--market-preview URL`：生成
  `add <url> -l`，只列技能不安装。护栏测试断言该 argv 不含
  `-y/-g/--all`，防止「预览」退化成安装。
- **选择性安装** `plan_install_repo` → `--market-install URL --market-skills`：
  必须显式给技能名或 `*`；**不接受什么都不传**，否则一次误点会装进整仓库。
- **重名检测** `detect_conflicts`：安装前把「已存在」与「缺失」分开报，
  避免 `add` 静默覆盖统一库里的同名技能。
- **GUI**：技能市场弹窗的搜索框现在同时接受关键词与 GitHub 地址；输入 URL
  时自动走预览，渲染来源行（安装所选 / 安装全部）与技能名输入框，
  确认后经 `run_cli` 执行并刷新技能列表。

`run_cli` 白名单同步登记 `--market-preview`/`--market-skills`/`--market-agents`：
不登记的话前端一点就会被安全边界拦下（`test_run_cli_boundary` 会失败）。

> 判据：新增 `tests/test_skill_install_source.py`（22 例）与
> `tests/test_skill_install_cli.py`（7 例）全部通过；全量 1859 passed /
> 2 skipped；`ruff check core tests scan.py scripts setup.py` → All checks passed。

### 修复：测试类重名导致 v0.42.0 弹框度量用例从未执行（2026-11-14）

合并 `a05dc6b` 后 `tests/test_design_spec_contract.py` 出现两个同名
`ModalFamilyConsistencyTest`：v0.42.0 的（标题刻度 / 按钮度量 / 主体内边，
3 个用例）在前，v0.46.8 的（弹框家族六处漂移，15 个用例）在后。Python 后者
覆盖前者，**前一组 3 个用例从未真正运行**，而 CI 与本地一直显示「全绿」。

- 较新的 v0.46.8 组重命名为 `ModalFamilyMetricsConsistencyTest`，两组用例都生效。
- ruff `F811` 随之消除（这是仓库唯一的 ruff 诊断）。
- 单测总数 1829 → 1832（+3 即恢复的三个用例），全部通过。

> 判据：修复前 `ruff check core tests scan.py scripts setup.py` 报 1 error；
> 修复后 `All checks passed!`。

## [v0.47.13] - 2026-11-13

当前发布版本（build 216）。

**统一五套表格的对齐规则（用户：每个页面的每个表格都不太一样）。**

### 统一后的规则（只有一条）

> **表头与内容同向；行首列与长文本列左对齐；其余一律居中。**

| 表格 | 左对齐的列 | 其余 |
|---|---|---|
| `.skill-table` | 名称（行首）、用途（长文本） | 全部居中 |
| `.agent-list-table` | 名称、类型（前两列） | 全部居中 |
| `.mcp-table` | 客户端（行首） | 全部居中 |
| `.merge-table` | 客户端（行首）、Skills 路径（长文本） | 全部居中 |
| `.upg-table` | 技能名（行首） | 版本 / 箭头居中 |

### 本次实际改动

| 表 | 改前 | 改后 |
|---|---|---|
| `.agent-list-table` | 整表居中（名称也居中） | 前两列左、其余居中 |
| `.merge-table` | **全部左对齐** | 客户端 + 路径左，其余居中 |
| `.upg-table` | 表头左、版本**右** | 表头居中、版本居中 |

`.skill-table` / `.mcp-table` 已符合，未动。

### 真机验证（逐页截图）

用「每 5 秒自动切页」临时验证后逐张截图：

- IDE / Agent：名称、类型左；其余居中 ✓
- Skills：名称、用途左；其余居中 ✓
- MCP：客户端左；其余居中 ✓（前一轮已验）
- DSH 插件：客户端左；其余居中 ✓

验证完删除临时代码。

## [v0.47.12] - 2026-11-13

当前发布版本（build 215）。

**修「Skills 名称列、Agent 表多数列没有竖线」—— 真机逐页截图确认。**

### 真因：`::after` 被 `overflow: hidden` 裁掉

竖线原本用 `td:not(:last-child)::after` + `right: -0.5px` 画在单元格**右边缘外**。
但多个单元格带 `overflow: hidden`（为了长文本省略）：

| 元素 | overflow |
|---|---|
| `.agent-list-table td` | `hidden` |
| `.skill-table td.st-name` | `hidden` |

伪元素落在盒子外，被直接裁掉 —— 于是 Skills 的名称列、Agent 表多数列**看不到线**，
而没设 overflow 的列（MCP 表）能看到。

### 修复：改用 background-image

```css
td:not(:last-child) {
  background-image: linear-gradient(to right, transparent calc(100% - 1px), var(--line-strong) 0);
}
```

`background` 不受 `overflow` 裁切影响，也不与 `box-shadow`（异常行左侧色条）抢属性。
五套表（skill / agent / mcp / merge / upg）统一换成这一条。

### 真机验证（逐页截图 + 放大）

为验证，临时加了「每 5 秒自动切页」的代码，逐页截图后放大检查：

| 页面 | 竖线 |
|---|---|
| IDE / Agent | ✅ 10 列全部有 |
| Skills | ✅ 6 列全部有 |
| MCP | ✅ 4 列全部有 |
| DSH 插件（复用 `.mcp-table`） | ✅ 5 列全部有 |

验证完已删除临时代码，重新构建正式版。

### 门禁

`ListVerticalRulesTest` / `SkillTableVerticalRulesTest` / `TableColumnAlignmentTest`
三处断言从「必须有 `::after`」改为「必须有 background-image 竖线」，
并写明原因（伪元素会被 overflow 裁掉）。

## [v0.47.11] - 2026-11-13

当前发布版本（build 214）。

**修「MCP 表行高仍不一致」—— 这次在真实 App 里量过。**

### 为什么前两版没修好

前两版都是**在浏览器预览态**验证的（Chrome / Blink），而 App 用的是 **WKWebView
（Safari 内核）**。两者对 `<button>` 的默认 line-height / padding 处理不同：

```
同一份 CSS：浏览器量 40px，App 里量 51px
```

`.tag` 是 `<button class="tag tag-btn">`，胶囊的高度在 WKWebView 里比 Blink 高
约 11px —— 于是「有胶囊的行」被撑到 51px，「无胶囊的行」39px，差 12px。

### 三层修复

| 层 | 改动 |
|---|---|
| 胶囊高度 | `.tag` 显式 `height: 20px; line-height: 18px; box-sizing: border-box`，消除内核差异 |
| 行高 | 三套主表 `td` 改为 **`padding: 0` + `height: 40px` + `vertical-align: middle`** —— 行高完全由 height 决定，内部 flex 容器（客户端名 + 标签）再高也撑不开 |
| 竖线可见性 | `::after` 颜色 `--line` → **`--line-strong`**（暗色下 `#1C1C22` 与面板 `#131317` 几乎同色，等于没画） |

### 真机实测（截图 + 像素分析）

```
修复前：行高 43 / 44 / 43 / 40 / 41
修复后：行高 40 / 40 / 40 / 40 / 41   ← 全部一致
```

竖线在暗色下也可见了。

### 教训

**UI 改动必须在真实 App 里验证，不能只看浏览器预览态。** 本项目 App 用
WKWebView、浏览器用 Blink，`button` 等表单控件的默认样式存在内核差异。
这次为真机验证临时加了「启动后自动切到 MCP 页」的代码（验证完已删除）。

## [v0.47.9] - 2026-11-13

当前发布版本（build 212）。

**修「MCP 表行高仍然不一致」（用户第二次反馈）。**

### 真因：padding 没写，继承的是全局 9px

v0.47.8 给 `.mcp-table td` 加了 `height: 40px`，但**没写 padding** —— 它继承全局
`th, td { padding: var(--sp-3b) var(--sp-5) }`（**9px**），而技能表与 Agent 表是
显式的 8px。

于是：

```
有胶囊的行：9 + 22(胶囊) + 9 = 40 → 但胶囊实际 24px → 42px
无胶囊的行：9 + 18(文字) + 9 = 36 → height 兜到 40px
```

两行差 2px，肉眼可见（用户截图 `ima.copilot` / `VS Code` 比上面三行矮）。

### 修复

`.mcp-table td { height: var(--sp-9c); padding: var(--sp-3) var(--sp-5); }`

### 实测

```
修复前：有胶囊 42px / 无胶囊 40px
修复后：有胶囊 40px / 无胶囊 40px / 无胶囊 40px   ← 全部一致
```

### 门禁

`TableColumnAlignmentTest` 补第 9 条：`.mcp-table td` 必须**显式**写
`padding: var(--sp-3) var(--sp-5)` —— 只写 height 不写 padding 就会重蹈覆辙。

## [v0.47.8] - 2026-11-13

当前发布版本（build 211）。

**行高统一 + 竖线覆盖全部表格（用户评审「行高还是不一样」「要么都有要么都没有」）。**

### 问题

1. **同一张表里两种行高**：有胶囊（`.tag`）的行被撑到 38px，无胶囊的行只有 34px
   —— MCP 表里 `ima.copilot` / `VS Code` 两行明显比上面三行矮。
2. **竖线仍不齐**：技能表 / Agent 表 / MCP 表都有了，但弹框内的合并预览表与
   升级确认表还没有。

### 修复

| 项 | 改动 |
|---|---|
| 行高 | 三套主表 `td` 加 `height: var(--sp-9c)`（40px），胶囊与纯文字行一致 |
| 竖线 | `.merge-table` / `.upg-table` 补 `:not(:last-child)::after`，与主表同规则 |

**至此五套表格结构完全一致**：列竖线全有、行内边 8px 12px、行高 40px。

### 门禁

`ListVerticalRulesTest` 原有的「td 竖线规则」断言仍守 Agent 表（拆成独立块以保持
正则可匹配）；新表用同一套声明。

## [v0.47.7] - 2026-11-13

当前发布版本（build 210）。

**修「表格左右仍不平衡」+ 三套数据表结构统一（用户评审）。**

### 问题

1. Skills 页左侧仍空太多 —— 名称列居中，而行首本应贴左。
2. **有的列之间有分隔线，有的没有**：只有技能表与 Agent 表画了竖线，MCP 表没有。
3. **有的行宽有的行窄**：三套表的单元格上下内边分别是 6 / 7 / 9px。

### 修复

| 项 | 改动 |
|---|---|
| 名称列 | 居中 → **左对齐**（行首是行标识，居中会在左侧留大片空） |
| MCP 表 | 补 `:not(:last-child)::after` 竖线 + 自己的 `border-collapse` / 单元格定位 |
| 行内边 | 三套表统一 `var(--sp-3) var(--sp-5)`（8px 12px），原 6 / 7 / 9px |

### 规则沉淀（§2.3e-0）

- 对齐：**行首与长段落左对齐，其余居中**（表头与内容同向）
- 结构：**所有数据表共享**——每列画 1px 竖线；行内边统一 8px 12px

### 门禁

`TableColumnAlignmentTest` 补 2 条：
- 三套表的 `th/td:not(:last-child)::after` 竖线规则必须都存在
- 三套表的行内边必须是 `var(--sp-3) var(--sp-5)`

## [v0.47.6] - 2026-11-13

当前发布版本（build 209）。

**修「表格左侧空白太多、右侧太少」（用户反馈）。**

### 根因：左右留白不同源

| 侧 | 留白 | 来源 |
|---|---|---|
| 左 | **36px** | 名称列的展开箭头占位（`.nest-toggle` + gap） |
| 右 | **12px** | 常规单元格 padding |

两侧不是同一套度量，所以看起来一边空、一边挤。

### 修复

操作列补 `padding-right: var(--sp-9e)`（36px，与左侧箭头占位同档），
列宽 4% → 6%（36px 之后仍要放得下 22px 的 `⋯`）。表头同样补。

### 实测

```
修复前：左侧留白 36px，右侧留白 14px（差 22px）
修复后：左侧留白 36px，右侧留白 38px（差 2px，来自 ⋯ 图标在 padding 内居中）
```

### 门禁

`TableColumnAlignmentTest` 补第 6 条：操作列与表头的 `padding-right` 必须是
`var(--sp-9e)`，且列宽已加宽。

## [v0.47.5] - 2026-11-13

当前发布版本（build 208）。

**修「展开子技能后右侧显示异常」+ 对齐规则收敛为两档（用户定案）。**

### Bug：嵌套行 colspan 写成 7，而技能表只有 6 列

```html
<tr class="nest-tr" ...><td colspan="7">   ← 技能表只有 6 列
```

展开 `inference-sh` 后，这一行撑出第 7 列，表格右侧出现一条空白带
（用户截图红框）。改为 `colspan="6"`，并把旁边那句过时的「该表 5 列」注释改正。

### 对齐规则：从三档收敛为两档

v0.47.4 按「文本左 / 数字右 / 图标中」分了三档 —— 设计上「正确」，但在只有 6 列的
表里制造了三种视觉轴线。用户评审：「有的左对齐，有的右对齐，有的不知道是什么对齐，
很乱」。

**新规则（用户定案）**：

| 列 | 对齐 |
|---|---|
| **表头**（所有列） | **居中** |
| **短内容**（名称 / 分类 / 同步 / 启用 / 操作 / 数字 / 图标） | **居中** |
| **长段落**（用途 / 描述 / 路径） | **左** |

判定只有一问：这一列是「一个词/数字/图标」还是「一句话」？

**落地**：

| 表 | 左对齐的列 | 其余 |
|---|---|---|
| `.skill-table` | 用途 | 全部居中 |
| `.agent-list-table` | 无（无长段落列） | 全部居中 |
| `.mcp-table` / `.merge-table` / `.upg-table` | 客户端 / 路径 / 技能名 | 其余居中 |

**顺带修掉一个覆盖 bug**：`.skill-table th { text-align: left }` 与整列居中规则
同特异性、定义在后，把表头改回了左对齐 —— 导致「表头左、内容中」，正是用户
说的错位。已改为 `center`。

### 门禁

`TableColumnAlignmentTest` 重写为 5 条（整表居中 / 用途左 / Agent 表整表居中 /
嵌套行 colspan 必须等于列数 / 规范两档规则 + HTML 同步）。

## [v0.47.4] - 2026-11-13

当前发布版本（build 207）。

**定义表格列对齐规则，并统一五套表格（用户评审「对齐策略不统一」）。**

### 问题

五套表格各写各的，同一个内容类型在不同表里对齐方式相反：

| 列 | 技能表 | Agent 表 |
|---|---|---|
| 日期 / 数字（`11/12`、`N/M`） | 同步列左对齐、启用列右对齐 | 约束 / MCP 列**居中** |
| 操作（`⋯`） | 右对齐 | **居中** |
| 圆形数字徽标（APP / CLI / CONFIG） | — | **左对齐**（继承默认） |

规范里也没有全局规则，只有零散的「某表某列居中」记录。

### 新规则（§2.3e-0，按内容类型而非按表格）

| 列类型 | 对齐 |
|---|---|
| 文本（名称 / 类型 / 用途 / 路径 / 分类 tag） | 左 |
| 数字 / 计数 / 日期（`N/M`、版本、`11/12`） | 右 |
| 图标（`✓` / 链接 / 单个 `⋯`） | 居中 |
| 多按钮操作组 | 右 |
| 表头 | 与内容同向 |

**两个易错点写进了规范**：

1. **圆形数字徽标算「图标」**（居中），**裸数字文本算「数字」**（右对齐）—— 不能因为
   「都是数字」就同一处理。
2. **分类 tag 算「文本」**（左对齐），不居中 —— 它是名称的属性，跟着名称读。

### 改动

| 表 | 改了什么 |
|---|---|
| `.skill-table` | 同步列 left → **right**；操作列 right → **center** |
| `.agent-list-table` | APP/CLI/CONFIG 列 left → **center**；约束/MCP 列 center → **right** |
| `.mcp-table` / `.merge-table` / `.upg-table` | 已符合规则，未动 |

### 门禁

新增 `TableColumnAlignmentTest` 5 条（技能表同步右对齐 / 操作居中 / Agent 表数字列右 /
图标列居中 / 规范有该章节），逐条反向验证 5/5 通过。

> 反向验证过程中发现一条断言过宽：原来「截一段看有没有 `text-align: center`」，
> 把其中一列改坏仍会通过。已收紧为逐列断言（3-7 列都必须出现在居中块里）。

## [v0.47.3] - 2026-11-13

当前发布版本（build 206）。

**补齐「改技能库的写操作」对检查缓存的失效（收成公共出口）。**

v0.47.1 / v0.47.2 连续两次踩到同一个坑：写操作改了技能库，但「检查更新」的
1 小时缓存没失效，用户操作完立刻检查看到的还是旧快照。前两次只补了
prune / install / upgrade 三处，**删除 / 合并 / 回滚**三处仍漏着。

### 改动

新增公共出口 `skill_market.invalidate_check_cache()`，五处写操作统一调用：

| 操作 | 入口 |
|---|---|
| 删除技能 | `_run_skill_delete`（`--delete-skill`） |
| 合并技能 | `_run_merge_skills`（`--merge-*`） |
| 回滚 | `_run_skill_rollback`（`--skill-rollback`） |
| 安装 / 升级 | `_run_market_write` |
| 清理登记残留 | `_run_prune_skill_lock` |

前两处原本各自内联 `unlink`，现统一改为调用该函数 —— 新增写操作时只需调用一次，
不再各处复制。

### 门禁

新增 `SkillWriteCacheInvalidationTest` 两条：
1. 五个写入口的函数体里都必须出现 `invalidate_check_cache`
2. 该函数必须存在且内部真的 `unlink(missing_ok=True)`

旧的 `PruneCacheInvalidationTest` / `MarketWriteCacheInvalidationTest` 断言从
「内联 unlink」改为「调用公共出口」。

## [v0.47.2] - 2026-11-13

当前发布版本（build 205）。

**修「升级成功后，检查更新仍显示 N 可升级」。**

用户实测：升级完成弹框显示「升级完成（共 2 个）」，但随后点「检查更新」，
弹框标题带「（缓存）」且仍显示「2 可升级」。

### 两个独立原因

**原因 A：升级没让检查缓存失效**（与 v0.47.1 的清理残留同源）

`--market check` 有 1 小时 TTL 的 `data/market_check_cache.json`。
`--market-install` / `--market-upgrade` 写完后没动它 → 命中升级前的快照。
修复：`_run_market_write` 在 `result.ok` 后删除缓存文件。

**原因 B：本地时间取值优先 git 提交时间，而 npx 升级不 commit**

`_local_skill_time` 原逻辑是「git 有值就直接返回」。但 `npx skills upgrade`
只写文件、**不 git commit**，于是：

```
git 最后提交：2026-11-04   ← 升级后仍是这个
远端提交：    2026-11-10   ← 11-10 > 11-04 → 判 outdated
实际文件：    2026-11-13   ← 内容其实已经是最新的
```

再点升级，npx 认为已是最新、文件不变 → **永远「可升级」的死循环**
（与 2026-11-09 那次同源，只是那次是 lock 不更新，这次是 git 不更新）。

修复：改为取 `max(git 提交时间, SKILL.md mtime)`。文件被写过就说明内容可能是新的。

### 实测

```
# 修复前（删缓存重查）
{"outdated": 2, "current": 163}     ← api-review / claude-dispatch 仍报可升级

# 修复后（删缓存重查）
{"outdated": 0, "current": 165}     ← 全部判定为最新
```

### 门禁

- 新增 `MarketWriteCacheInvalidationTest`（安装/升级成功后必须删缓存）
- `test_prefers_git_commit_time` 改写为「git 新于 mtime 时取 git」，并新增
  `test_takes_newer_of_git_and_mtime` 守住「mtime 更新时取 mtime」

## [v0.47.1] - 2026-11-13

当前发布版本（build 204）。

**修「清理登记残留后，再点检查更新仍显示残留 N 条」。**

用户实测：清理掉 9 条残留、重新检查，弹框标题写着「检查完成（缓存）」，
残留数仍是 9 —— 看起来像清理没生效。

### 真因：清理没让检查缓存失效

`--market check` 有 1 小时 TTL 的 `data/market_check_cache.json`。
`--prune-skill-lock` 删掉登记表条目后**没有动这个缓存**，于是 1 小时内再检查，
命中的还是清理前的快照。

### 修复

`_run_prune_skill_lock` 在真正删除条目（`status=ok` 且有 `removed`）后，
删除 `data/market_check_cache.json`。`nothing-to-prune` 不删（没有变化就不该失效）。

### 顺带修一个测试缺陷

`test_check_is_read_only` 的快照把 `.git` 也算进去了 —— 而统一库本身是 git 仓库，
`--market check` 的 `git fetch` 必然更新 `.git` 的 mtime。此前有缓存时跳过 fetch
所以碰巧通过，缓存过期那一轮就误报「check 修改了技能库」。
现在快照排除隐藏条目，只比技能目录。

### 实测

```
# 注入 1 条假残留
$ scan.py --prune-skill-lock --format json
{"removed": 1, "status": "ok"}
清理前缓存: 存在
清理后缓存: 已删除 ✓

$ scan.py --market check --format json   # 缓存已失效 → 真检查
{"cache_hit": false, "summary": {"total": 165, "outdated": 2, "current": 163, "missing": 0}}
```

残留从 9 变成 **0**。

### 门禁

新增 `PruneCacheInvalidationTest`（断言清理实现引用缓存路径、成功后 unlink、
且只在 `status=ok` 时失效）。

## [v0.47.0] - 2026-11-13

当前发布版本（build 203）。

**全量 UI 评审后的页面层一致性修复（11 项）。**

弹框层此前已收干净，这一版修的是**页面层**：同一类交互在不同页面有不同实现，
规范里没有对应约束，所以门禁也没拦住。

### P0 — 违反已写明的规范

| 问题 | 修复 |
|---|---|
| 设置页布尔开关有两种形态：后台巡检用「开启/关闭」两个 `seg-btn`，共享约束同步用 `.switch` | 巡检改用 `.switch` + 状态文字（`aria-checked` 只服务读屏，视觉用户也要能读出状态） |
| 概览 6 张统计卡排成 5+1（`auto-fill minmax(190px)` 在 1200px 内容区正好卡在临界点） | 固定 3 列（3×2），900px 以下降 2 列 |
| Skills 页头 6 个按钮全同级、无主操作 | 分三级：「检查更新」primary / 「一键升级·修复链接」btn-soft / 「使用分析·技能市场·刷新技能」ghost |

### P1 — 一致性 / 可用性

| 问题 | 修复 |
|---|---|
| 22 处空态文案三种句式并存（「无匹配结果」「端点库为空」「尚未检查更新：…」） | 定义四句式模板写进 §2.5：`无 X` / `无 X：<引导>` / `尚未 X：点<入口>后…` / `<对象>失败`；禁止「X 为空」 |
| 骨架屏只覆盖 `agents-list`，其余三页空白直出 | `showSkeleton()` 扩展到 skills（表格骨架 `.sk-row`）/ mcp / dsh |
| Skills 页筛选 chip 与色点图例信息重复 | 删色点图例，只留 `.skill-legend-note` 一行 N/M 口径说明 |
| 弹框内空态文案不统一（「未检测到」「暂无备份」） | 统一为「无 X」 |

### P2 — 细节

| 项 | 结论 |
|---|---|
| 设置页 4 个 tab 的卡片间距 | **实测无问题**：四 tab 的卡片间距均 14px、padding 均 18px，差异来自内容密度而非样式 |
| 洞察面板规范过薄（§2.5f 只有 3 行） | 补全骨架、四条硬要求、四态覆盖、关闭路径 |
| 弹框宽度 9 档 | 合并 `task-card`(420) 与 `upg-modal`(440) 为 440，`upg-modal` 改为继承 |
| 1024px 下「用途」列截断 | **刻意保留**：行高一致优先于多显示几行字（v0.47.0 前的实测结论），已在 §2.3e 写明取舍 |

### 门禁

新增 `PageLevelConsistencyTest` 7 条断言（开关形态 / 统计卡列数 / 页头 primary /
空态句式 / 骨架屏覆盖 / 图例去重 / 宽度继承），逐条反向验证 7/7 通过。

全量回归：**1810 passed, 2 skipped, 181 subtests passed**。
（`test_skill_market_cli.py::test_check_is_read_only` 在全量跑时偶发失败，
单独复跑通过 —— 是既有测试的时序脆弱性，与本次改动无关。）

## [v0.46.9] - 2026-11-13

当前发布版本（build 202）。

**修「约束列 0/M，点『写入共享约束』仍然不成功」。**

用户截图：VS Code 约束列显示 `0/1`，点了修复没生效；ima.copilot 约束列是 `—`。

### 真因：GUI 的两道闸门与 CLI 的行为相反

CLI 的 `apply_client` 对**不存在的路径会创建文件**（dry-run 实测：
`state=missing` 但 `ok=true, changed=true`）。而 GUI 有两处假设「文件必须先存在」：

| 位置 | 原逻辑 | 后果 |
|---|---|---|
| `needFixRulesFor` | `if (!paths.some(x => x.exists)) return false` | 所有文件都不存在时，菜单里**根本不出现**「写入共享约束」 |
| `fixRulesFor` | `paths = all.filter(x => x.exists)` 后判空 | 即使点到了，也直接弹「还没有约束文件」返回，**从未调用 CLI** |

两道闸门叠加，表现为「约束列 0/M，菜单里没有修复项；偶尔点到也只得到一句
『请先让客户端生成规则文件』」。

### 修复

- `needFixRulesFor`：只要有约定路径就给出入口，不再看文件是否存在。
- `fixRulesFor`：改用全部路径，并算出 `toCreate`（尚不存在的），在确认框里
  明确写出「其中 N 个文件尚不存在，将新建」。
- 确认按钮文案按 §2.5b-4 的统一规则传「写入」（动词）。

### 实测

```
$ python3 scan.py --shared-rules-apply "VS Code" --format json
{"ok": true, "applied": [{"client": "VS Code", "changed": 1,
  "results": [{"path": "~/.copilot/copilot-instructions.md", "state": "missing",
               "ok": true, "changed": true}]}]}

$ ls -la ~/.copilot/copilot-instructions.md
-rw-r--r--@ 1 ... 461 Nov 13 11:39   ← 文件被创建

$ python3 scan.py --shared-rules-audit --format json
VS Code  current
```

### 关于 ima.copilot 的两个「—/手动」（不是 bug）

| 列 | 显示 | 为什么正确 |
|---|---|---|
| 约束 | `—` | ima.copilot 没有公开的本地规则文件约定（`~/Library/Application Support` 下无对应目录），注册表里没有 `rules_paths`。按 §2.3d-2「无约定用 —」 |
| MCP | `手动` | v0.46.7 新增的第五态：支持 MCP，但走应用内「设置 → MCP 连接」录入，没有可被本工具写入的配置文件 |

### 门禁

`tests/test_rules_shared.py` 补 2 条断言（菜单入口不得被文件存在性拦住 /
写入不得过滤不存在的路径），逐条反向验证 2/2 通过。

## [v0.46.8] - 2026-11-13

当前发布版本（build 201）。

**弹框 UI 全面改造：样式统一 + 层次感 + 头部重设计。**

用户连续三轮评审，从「检查所有弹框是否统一」到「需要一点设计感」到「有的色条有的没有」，
这一版把四类弹框（表单 / 确认 / 通知 / 详情）收成同一套规则。

### 弹框家族一致性（用户要求「检查所有弹框是否统一」）

逐个比对 29 处弹框调用后，骨架基本统一、度量有六处漂移，全部修掉：

| 问题 | 实测 | 修复 |
|---|---|---|
| `.form-actions` 规则声明两次，后一条的 `margin-top` 覆盖前一条的零值 | 表单弹框主体→底栏 **19px**，详情弹框 **0** | 合并为一条，底栏紧贴分隔线 |
| 两处弹框用内联 `style="width:min(...)"` 压 `.modal` 的 width | 640/920 字面值 + 92vw/94vw 混用 | 新增 `.modal-md` / `.modal-lg` 档位类，走 `--modal-w` |
| 29 处弹框只有 5 处手写 `role="dialog"` / `aria-modal` | 24 处读屏器不播报为对话框 | `mountModal` 挂载时由 `_ensureDialogA11y` 自动补齐，已手写的保留 |
| `.modal` 默认与 `.upg-modal` 用 92vw，其余 94vw | 窄屏留白不一致 | 统一 94vw |
| `.ad-head` 顶部内边 24px，`.form-head` 28px | 两家族标题距容器顶差 4px | 统一 `--sp-9a` |
| 规范写了「点遮罩关闭」，代码从未实现 | 点空白处无反应 | `_bindBackdropClose` 绑定，判 `e.target === backdrop` |

顺带清掉两处死代码：`.modal h3`（标题都走 `.form-title` / `.cfm-title` / `.ad-name`）、
以及设置页「活动端点」下拉把 CSS 选择器误写进 `class` 的 bug
（`class="modal-form .form-field input"`，会让该 `<select>` 继承 `.modal-form` 的
`padding: 0` 与 flex 布局）。

**规范同步**：`docs/DESIGN.md` 补家族表第四行（进度/任务）、宽度档位表、
「四组数字」（新增头部内边）、关闭路径与无障碍的落点说明；
`docs/DESIGN.html` 新增**四类弹框实物样例**（静态还原 + 度量标注）、
宽度档位表、关闭路径与无障碍说明块。

**门禁**：新增 `ModalFamilyConsistencyTest` 8 条断言，逐条反向验证（每条都
故意制造一次违规确认报错，0 条无效断言）。

### 弹框层次（用户反馈「需要一点设计感，现在没有层次感」）

**问题**：卡片、头部、底栏、按钮全用同一个 `--panel` 平面，只靠一条 1px 线分隔，
读起来是一张白纸；阴影只有外投影，没有内高光，浮层像贴纸。

**三档表面 + 两道高光**：

| 改动 | 取值 | 解决什么 |
|---|---|---|
| 底栏下沉一档 | `--modal-foot-bg`（`#F7F7F9` / 深色 `#0E0E12`） | 操作区与阅读面同色，没有「区」的概念 |
| 卡片上缘内高光 | `inset 0 1px 0 var(--modal-hi)` | 纯外投影的白卡片在浅底上像贴纸 |
| 头部层叠阴影 | `0 10px 18px -20px var(--modal-rail)` | 三段式只靠线分隔时仍是一张纸 |
| 图标语义光晕 | `0 0 0 4px <语义>-bg` | 40px 圆是纯色块，没有状态锚点的分量 |
| 实心按钮材质 | `inset 0 1px 0 rgba(255,255,255,.22)` + 悬停上浮 1px | 纯色块像印刷色，不像按键 |

**新增 token**：`--modal-hi` / `--modal-foot-bg` / `--modal-rail`，深浅两套同步。

**克制边界**：正文、表格行、列表项不加阴影与高光 —— 层次只给「容器」与「可操作物」，
不给内容。否则整页都在发光，反而没有层次。

**门禁**：`ModalFamilyConsistencyTest` 再补 3 条（内高光 / 底栏下沉 / 图标光晕），
逐条反向验证通过；文档 `docs/DESIGN.html` 的四类样例同步了同一套层次。

### 确认 / 通知弹框头部重设计（用户反馈「头有点轻，就一个大图标很不协调」）

**问题**：图标 40px 居中孤悬、标题在它下方垂直堆叠 —— 头部信息量太少，
视觉重量全压在一个圆上。

**新结构**：图标 32px + 标题**同一行**，图标作为标题前缀；顶部 3px 语义色带
按 kind 着色；头部与正文之间加一条 hairline；底栏按钮改右对齐（原居中）。

| 项 | 做法 | 为什么 |
|---|---|---|
| 布局 | `.cfm-card` 改 `display: grid`，`grid-template-columns: auto minmax(0, 1fr)`，图标/标题占第 1 行两列，其余元素 `grid-column: 1 / -1` | **不改 DOM**：6 个调用方（`modalNotice` / `confirmModal` / `confirmTypedKeyModal` / `progressBegin` / `progressFinish` / `runTaskModal`）的模板一行都不用动 |
| 图标 | 40px → 32px，去掉居中 `margin` | 与 16px 标题构成 2:1 比例；同行布局下居中 margin 是多余的 |
| 色带 | `.cfm-card::before` 3px，ok/warn/err/info/进度 accent 各自着色 | 头部只有「图标 + 标题」时仍偏单薄，色带补分类锚点且不占版面高度 |
| 分隔线 | `.cfm-msg` 加 `border-top` + `padding-top` | 图标与正文直接相贴时仍读成「一个图标 + 一段文字」 |

**进度卡复用同一套**：`.prog-spinner`（28px）占图标那一格，标题同行；进行中色带
用 `--accent`，结束后转 `notice-ok` / `notice-err`。

**对齐方式统一**：通知类标题从居中改左对齐、底栏从居中改右对齐 ——
同一应用里两种对齐并存会读成两个产品。`docs/DESIGN.md` §2.5b-4 已同步这条变更。

**顺带清理**：`--sp-9b`(32px) 在头部改紧凑后成为死 token（全库仅 `:root` 一处），
按项目规则删除，`docs/DESIGN.md` §1 同步移除。

**门禁**：`ModalFamilyConsistencyTest` 再补 4 条（头部同行 / 图标 32px / 语义色带 /
底栏右对齐），逐条反向验证 4/4 通过。

### 弹框样式完全统一（用户评审「有的有色条有的没有，按钮有的用好有的用确认」）

**两处不统一**：

1. **色带**只挂在 `.cfm-card` 上，表单和详情没有 → 四条弹框里两条有、两条没有。
2. **按钮文案**混用：「好」「关掉」「确认」「确认删除」「确认升级」并存。

**统一规则（写进 DESIGN.md §2.5b-4）**：

| 项 | 规则 |
|---|---|
| 色带 | 挂在 `.modal` 容器上，**四类家族统一都有**；颜色只表达语义不表达家族：accent=操作 / muted=只读 / ok·warn·err=结果 |
| 单出口按钮 | 一律「关闭」（原「好」「关掉」） |
| 双出口退出键 | 一律「取消」 |
| 双出口主操作 | 一律**动词本身**，不带「确认」前缀：删除 / 清除 / 移出 / 清理 / 升级 / 提交 / 回滚 / 保存 / 写入 |

**实现**：`.modal::before`（3px、上缘圆角、`pointer-events: none`），各家族只覆写
`background`。新增弹框挂上 `.modal` 就自动有色带，不需要单独写。

**`confirmModal` 兜底**：未传 `confirmText` 时 `danger` 用「删除」、否则「确定」；
危险但非删除的操作（清除 / 移出 / 清理）必须显式传文案 —— 已逐个补齐 8 处调用。

**门禁**：色带断言从 `.cfm-card::before` 改为 `.modal::before` 并覆盖四类家族；
升级按钮断言从「确认升级」改为「升级」。

**文档**：`docs/DESIGN.html` 的四类样例（舞台内 4 个 + 骨架对照 4 个）全部加上同规则
色带，按钮文案同步为「关闭」。

## [v0.46.7] - 2026-11-13

当前发布版本（build 200）。

**修「注册表声明被当成事实」：ima.copilot 被误报不支持 MCP、VSCode 提示成功但不更新。**

两个用户报障的共同根因相同：注册表说没有路径就推断成「不支持 MCP」，说错了路径就
推断成「已配置成功」。两处都缺一步「拿真实文件系统反向验证」。

### ima.copilot 被误报「不支持 MCP」

`supports_mcp` 原为 `bool(config_path)`，把**产品能力**和**能否自动写入配置**混为
一谈；注释里还把「ima.copilot 根本没有 MCP 能力」当事实写死。ima 实际有
「设置 → MCP 连接」入口，只是没有可被本工具写入的配置文件。

- 拆成两个维度：`supports_mcp`（能力，可用 `mcp_support` 显式声明）与
  `auto_configurable`（是否可自动写入）；派生 `manual_only` / `manual_hint`。
- 界面新增第五态「需手动接入」：半填充圆点 + 点状标签，与「已挂载」「缺失」
  「不支持」在形状与文案上都区分开，并单独计数。
- `checker` 不再把 `ima.copilot.app` 并进 `github-copilot` 的安装签名。

### VSCode「提示成功但不更新」

- **根因 A**：macOS 缺 `by_os` 分支，退化成 Linux 的 `~/.vscode/mcp.json`，而 VSCode
  实际读 `~/Library/Application Support/Code/User/mcp.json`。写入与校验用同一个错路径，
  互相印证，于是永远「已经是配置好的」。
- **根因 B**：修复只判断文件是否存在，不判断内容是否为空。目标文件是 0 字节时把空串
  交给 JSON 解析器，报 `Expecting value` 而静默失败。
- 两处修复后实测：`updated` → 真实写入 373 字节 → 再次运行才是真 `unchanged`。

### 缺失约束文件的新建与写入

用户：「这不是我现在写入的问题……如果没有的话，也需要有这个操作按钮」。

此前 `needFixRulesFor` 里 `if (!paths.some(x => x.exists)) return false`：
`~/.dsh/AGENTS.md` 不存在时，菜单里根本没有「写入共享约束」；即使点到了，
`fixRulesFor` 也会把不存在的路径过滤掉后直接弹警告返回 —— **从未调用 CLI**。
而 CLI 的 `write_rules` 本来就会新建文件与父目录。缺文件是可修复状态，不是
「无可写入」。

- **CLI**：`core/rules_files.py` / `core/rules_shared.py` 补 `creatable` / `kind`
  字段，区分「可新建的文件」与「只能逐文件编辑的目录」。
- **GUI**：`needFixRulesFor` 改为「至少有一个非目录目标」即给入口；`fixRulesFor`
  用 `writable`（`creatable || kind !== "dir"`），确认框用 `isNew(x)` 标注
  「文件不存在，将新建」。
- **边界**：只声明规则目录（`kind === "dir"`）的客户端仍拒绝整体写入，提示用
  「详情」进入目录逐文件编辑 —— 目录里可能已有用户自己的文件，整体写入会误伤。

### 测试

- 更新写死 `supports=False` 的断言，补 `manual_only` 与空文件用例。
- 补「缺失文件可写入」与「仅目录则拒绝」两组用例。
- 提交时全套 **1794 项通过**。

## [v0.46.6] - 2026-11-12

当前发布版本（build 199）。

**修「有未提交改动，点提交却说没有改动可提交」。**

### 真因：commit 分支缺 JSON 输出

```python
# push 分支（正确）
if as_json:
    print(json.dumps({"kind": "git-push", ...}))
else:
    print(...)

# commit 分支（缺 if as_json）
if not as_json:          ← 只有文本分支
    print(...)
return 0                 ← JSON 模式什么都不打印
```

带 `--format json` 时 stdout 是**空字符串**：

```bash
$ python3 scan.py --commit-git-sources --dry-run --format json
[没有任何输出]
[exit=0]
```

GUI 的 `JSON.parse("" || "{}")` 得到 `{}` → `results` 不存在 → `dirty` 恒为空 →
弹出「没有改动可提交」。

**而侧边栏显示「有未提交改动 7」**，因为那个计数走 `--check-git-sources`（有 JSON），
两处结论互相矛盾。

### 修复

commit 分支补上与 push 一致的结构：

```python
if as_json:
    print(json.dumps({"kind": "git-commit", "dry_run": dry,
                      "summary": summary, "results": results}, ensure_ascii=False, indent=2))
else:
    print(...)   # 原文本输出
```

### 验证

```json
{
  "kind": "git-commit",
  "summary": {"total": 1, "ok": 1, "failed": 0},
  "results": [{"id": "skills", "status": "dry-run", "message": "将提交 7 个文件",
               "counts": {"modified": 1, "deleted": 6}, "files": [...]}]
}
```

模拟 GUI 解析：`results 条数 1`、`dirty 条数 1`、footer「共 7 个文件将被提交」。

### 顺带排查

扫了 `scan.py` 里所有 `if not as_json` 分支，另外 3 处都走 `emit()` 或已有
`if as_json`，只有 commit 这一处漏了。

### 测试

- 新增 `GitCommandJsonOutputTest`（2 项）：commit 分支必须输出带 kind/results 的 JSON、
  GUI 打开弹框必须请求 `--format json`。
- **反向验证 1 条**：去掉 `if as_json` 立即失败。
- 全量 **1790 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.46.5] - 2026-11-12

当前发布版本（build 198）。

**修横向行线在「用途」列断开。**

用户：「我指的是横向线被断开了」。

### 真因：`td` 被改成 `display: flex`

```
row 0: cellBottoms = [380.38, 380.38, 380.38, 376.28, 380.38, 380.38]
                                            ↑ 用途列，比其他列高 4.1px
```

`td` 一旦 `display: flex` 就不再是 `table-cell`，高度塌到内容高（31px），
同行其它格仍是 35px，**底边框上移 4.1px** —— 横线在那一列断开。

### 修复

| 错的 | 对的 |
|---|---|
| `.skill-table .st-usage { display: flex }` | `.skill-table .st-usage-in { display: flex }`（内层 div） |
| `<td class="st-usage">…</td>` | `<td class="st-usage"><div class="st-usage-in">…</div></td>` |

### 实测

修复后 5 行 × 6 格底边全部一致：

```
row0: 381.57 ×6   row1: 416.66 ×6   row2: 451.76 ×6
row3: 486.85 ×6   row4: 521.95 ×6   连续：true
```

### 测试

- `test_usage_cell_is_flex_container` 改写为 `test_usage_cell_stays_table_cell`：
  断言 `.st-usage` 上**不得**有 `display: flex`，且 `.st-usage-in` 必须是 flex 容器。
- **反向验证 1 条**：把 td 改回 flex 立即失败。
- 全量 **1788 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 补「`td` 不得改成 `display: flex`」与通用规则：
需要 flex/grid 时永远加一层内层容器，`td` 保持 `table-cell`。`DESIGN.html` 同步。

## [v0.46.4] - 2026-11-12

当前发布版本（build 197）。

**Skills 表补竖线 + 修 flex 容器里截断失效导致的溢出。**

用户：「Skill 错位了，和之前 Agent 的问题一样，线没有连续，断开了」。

### 两处独立缺陷

| 缺陷 | 原因 | 修法 |
|---|---|---|
| 线断开 | `.skill-table` 只画横线，**从未画过列分隔线** | 与 Agent 表同方案：`separate` + 每格 `::after` |
| 内容压到下一列 | 把 `.st-usage` 改成 `display:flex` 后，`text-overflow` **写在容器上不生效** | 截断落到子元素：`min-width:0 + overflow:hidden + text-overflow:ellipsis` |

第二处是上一版（v0.46.3 修行高）改出来的——为统一行高把单元格改成 flex，
但没检查这个改动对截断的影响。

### 实测（真实 7 条数据）

```
行高：33.5 ×6 + 32.5（全中文行，子像素取整）
bleedsIntoNext：全部 false
竖线：五列全部贯通
```

### 测试

- 新增 `SkillTableVerticalRulesTest`（3 项）：竖线伪元素、collapse 已禁用、
  截断必须落在 flex item 上。
- **反向验证 2 条**：去掉竖线伪元素、去掉子元素截断属性，各自失败。
- 全量 **1788 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 补「Skills 表补竖线 + flex 下的截断位置」，并写明通用规则：
`text-overflow` 只对块级容器的直接文本生效，flex/grid 容器必须包一层子元素。
`DESIGN.html` 同步。

## [v0.46.3] - 2026-11-12

当前发布版本（build 196）。

**修 Skill / MCP 两张表的行高不一致。**

用户：「两个 top 中，不同样式、不同情况下行高不一样，很不好看」。

### 根因：行内盒高度，不是换行

| 单元格内容 | 盒模型 | 高度来源 |
|---|---|---|
| 纯文本 `<span>` | `inline` | 字体 line-height |
| 官网链接 `<button>` | `inline-flex` + 11px 图标 | 图标与内边撑起，**更高** |

同一行盒取较高者。**165 个 skill 里只有 3 个有官网** —— 恰好那 3 行比别的行高 2-3px。

第一次修只看表面（`r.home ? "has-home" : "wrap"` 让无官网的行两行截断），
删掉后仍是「有高有低」，因为没动到这个行内盒差。

### 修复

| 表 | 改法 |
|---|---|
| Skill 用途列 | 单元格改 `display: flex; align-items: center`，子元素都是 flex item |
| Skill 用途列 | 官网按钮 `flex: none`，不参与伸缩 |
| MCP 条目列 | `.mcp-items` flex 容器 + 标签统一 `height: 20px`、`align-items: center` |
| MCP 条目列 | 明细标签 `DETAIL_MAX = 1`，超出折叠为 `+N` |

### 实测（真实数据）

```
ai-memory-write  hasHome=true   33.5
last30days       hasHome=true   33.5
_core            hasHome=false  33.5
affirmations     hasHome=false  33.5
hermes-memory    hasHome=true   33.5
api-review       hasHome=false  33.5
agent-email      hasHome=false  33.0   ← 全中文行，子像素取整，肉眼不可见
```

6 行完全一致。

### 测试

- 新增 `RowHeightConsistencyTest`（4 项）：用途列必须是 flex 容器、官网按钮
  `flex: none`、MCP 标签固定 20px 高、明细折叠存在。
- **反向验证 2 条**：usage 改回非 flex、去掉标签固定高度，各自失败。
- 全量 **1781 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 补「行高一致性：同一列不得混用 inline-flex 与 inline」与
「MCP 条目列明细收敛」；`DESIGN.html` 同步。

## [v0.46.2] - 2026-11-12

当前发布版本（build 195）。

**WorkBuddy 只登记一个约束文件：SOUL.md。**

用户：「那这里就应该只把 soul.md 作为约束文件，这里应该只有一个吧？」——对。

### 改动

| 项 | 改前 | 改后 |
|---|---|---|
| `rules_paths` | `[SOUL.md, USER.md]` | **`[SOUL.md]`** |
| `rules_roles` | `[["behavior"], []]` | **无**（单文件不需要分流） |
| 界面显示 | `2/2` | **`1/1`** |

`USER.md` 是 WorkBuddy **自己从交互中维护的用户档案**（姓名 / 角色 / 技术栈 / 沟通偏好），
不是「约束文件」。把它登记成约束文件，等于把它拉进审计与写入流程，也让界面显示 2/2，
用户以为有两个要维护，而实际我们从没写过它。

> 判断标准：**它规定 Agent 怎么做事**（SOUL.md）还是**记录 Agent 认识的我**（USER.md）。
> 前者才算约束文件。

`rules_roles` 分流机制保留（将来若出现真正的多约束文件客户端仍可用），只是 WorkBuddy
不再需要。

### 验证

```
--list-rules  → WorkBuddy paths: ['~/.workbuddy/SOUL.md']
--shared-rules-apply --dry-run → ~/.workbuddy/SOUL.md => absent
```

### 测试

- `test_workbuddy_has_single_constraint_file`：只登记 SOUL.md、不再声明角色。
- 清理了两处重复的测试定义（同名函数导致 ruff F811）。
- 全量 **1781 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「WorkBuddy 只登记一个约束文件」对照表与判断标准；
`DESIGN.html` 同步。

## [v0.46.1] - 2026-11-12

当前发布版本（build 194）。

**只有 SOUL.md 接收共享约束，USER.md 不再修改。**

用户：「这里比较重要的还是应该只是 SOUL.md 对吧，不需要修改 USER.md」。

### 为什么

`USER.md` 是 WorkBuddy **自己**从交互中维护的用户档案（姓名、角色、技术栈、沟通偏好），
而共享约束是**跨 13 个 Agent** 的通用规则。把档案类内容也同步进去，只会让「我是谁」
在两个地方各写一遍、格式还可能打架。跨 Agent 的约束本就不该进某个 Agent 的私有档案。

### 改动

| 文件 | 角色 | 是否接收 |
|---|---|---|
| `~/.workbuddy/SOUL.md` | `["behavior"]` | **是** |
| `~/.workbuddy/USER.md` | `[]` | **否** |

路径仍登记（界面展示 + 健康检查），只是不接收内容；文件里若有旧的共享块会被清掉。

### 顺带修掉一个真 bug

「该文件不接收」的判断此前排在 `_path_state` **之后**，而不接收时传给它的 body 是空串，
`_covered([], "")` 恒为 `True`（「没有要检查的条目 = 全都覆盖了」）→ 状态被判成
**`covered`（「已经写好了」）**，于是既不清旧块、也不报 `skip`。dry-run 里给出的结论
完全是误导。

修法：先判「不接收」→ 清旧块或报 `skip` → 再对接收的文件算状态。

### 实测（dry-run）

```
~/.workbuddy/SOUL.md  => absent | 文件里没有共享块，且缺少部分约束
~/.workbuddy/USER.md  => skip   | 该文件职责不接收共享约束
```

### 测试

- 更新 `test_workbuddy_registered_roles`：SOUL 接收、USER 不接收、两条路径仍登记。
- 新增 `test_empty_role_path_is_skipped_not_covered`、`test_non_receiving_file_gets_old_block_cleared`。
- **反向验证 1 条**：撤掉「skip 前置」立即失败。
- 全量 **1781 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 更新职责表（三列，标明谁接收），并补「一个必须注意的顺序问题」；
`DESIGN.html` 同步。

## [v0.46.0] - 2026-11-11

当前发布版本（build 193）。

**多约束文件按职责分流，不再把同一份内容塞进每个文件。**

用户：「对于这种有多个约束文件的，是否真的需要多个，还是只需要改一个就可以了？
修改的方案是什么？优先写到哪个里面？」

### 一、是否真的需要两个：需要，而且职责不同

全仓只有 WorkBuddy 声明了两个用户级约束文件：

| 文件 | 职责 | 本机内容示例 |
|---|---|---|
| `~/.workbuddy/SOUL.md` | 人格 / 行为准则（怎么做事） | Core Truths、Boundaries、Memory-Grid 规则 |
| `~/.workbuddy/USER.md` | 用户档案（我是谁） | 姓名、角色、技术栈、沟通偏好 |

两个都该保留，但**同一份内容不该同时写进两个**——此前就是那样，等于把「怎么做事」
塞进「我是谁」里。

### 二、方案与优先级

注册表新增 `rules_roles`（与 `rules_paths` 一一对应）：

```python
rules_roles=[["behavior"], ["profile", "preference"]]
```

内容逐条分类（优先级 `profile > preference > behavior`），**每类只写一个文件**：

| 类别 | 关键词 | 落到 |
|---|---|---|
| `profile` | 我的名字 / 称呼我 / 我是… | `USER.md` |
| `preference` | 偏好 / 习惯 / 沟通方式 | `USER.md` |
| `behavior` | 回答 / 必须 / 禁止 / 语气 | `SOUL.md` |
| 未命中 | — | 不写（避免污染人格文件） |

**优先写哪个**：看这句说的是「怎么做事」（→ SOUL）还是「我是谁」（→ USER）。

### 三、边界处理

- **没有 `rules_roles` 的客户端保持旧行为**（全部路径都写）——不为一个特例改变 13 个客户端的语义。
- 该文件不接收内容时：若里面有旧块则**清掉**（`state: cleared`），避免残留过期规则。
- 确认弹框会列出每个文件收什么：`· ~/.workbuddy/SOUL.md（行为准则）`。

### 实测（dry-run）

```
~/.workbuddy/SOUL.md  → state: absent, changed: true      （写入行为准则）
~/.workbuddy/USER.md  → state: skip, reason: 该文件职责不接收共享约束
```

### 测试

- 新增 `MultiFileRoutingTest`（6 项）：类别匹配、行为进 SOUL、档案进 USER、
  跨文件不重复、无角色声明保持旧行为、WorkBuddy 角色已登记。
- **反向验证 1 条**：关闭分流立即失败。
- 断言写失败一次才有效：用「含『中文』」判断会把「称呼我时用中文」误判成行为准则，
  改为整条比对后才有意义。
- 全量 **1779 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「多个约束文件按职责分流」整节（职责表 + 类别表 + 边界）；
`DESIGN.html` 同步。

## [v0.45.3] - 2026-11-11

当前发布版本（build 192）。

**修「写入报错」：GUI 读错了 CLI 的结果结构。**

### 真相

CLI 实际**成功了**：

```json
{"ok": true, "applied": [{"ok": true, "client": "Codex", "changed": 0,
  "results": [{"path": "~/.codex/AGENTS.md", "state": "current", "reason": "已是最新"}]}]}
```

GUI 却去读 `payload.rows` —— 那是 `--shared-rules-audit` 的结构。`rowOut` 恒为 `{}`、
`state` 为空、`payload.ok === true` 是唯一能命中的分支……但代码里 `good` 还要求
`state === "current" || payload.ok === true`，**`payload.ok` 为 true 时本该判成功** ——
实际那版跑的是 `--shared-rules-apply NAME`（**没带 `--format json`**），stdout 是
人类可读文本 `✅ Codex：0 处更新`，`JSON.parse` 静默失败成 `{}`，于是 `payload.ok`
是 `undefined` → 判为失败。

两个错误叠在一起：

| 错误 | 后果 |
|---|---|
| 没带 `--format json` | stdout 是文本，`JSON.parse` 失败，`payload` 为 `{}` |
| 读 `payload.rows` | 即使解析成功也取不到 apply 的结果（结构是 `applied[]`） |

### 修复

```js
const res = await runCli(["--shared-rules-apply", name, "--format", "json"]);
const entry = (payload.applied || []).find((r) => r.client === name) || payload.applied[0];
```

结果弹框现在如实报告：

- 有改动 → 「Codex 的共享约束已写入（N 处更新）」
- 无改动 → 「Codex 的共享约束已是最新，无需改动」
- 真失败 → 逐路径列出原因

### 验证（用真实 CLI 输出跑新解析）

```json
{"ok": true, "message": "Codex 的共享约束已是最新，无需改动",
 "detail": "~/.codex/AGENTS.md：已是最新"}
```

### 测试

- 新增 `test_apply_result_reads_applied_not_rows`：必须读 `applied[]`、不得读 `rows`、
  必须带 `--format json`。
- **反向验证 1 条**：改回读 `rows` 立即失败。
- 全量 **1773 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「CLI 结果结构必须对得上」两条命令的 schema 对照；
`DESIGN.html` 同步。

## [v0.45.2] - 2026-11-11

当前发布版本（build 191）。

**约束列去掉文字徽标：状态只由 N/M 的颜色表达。**

用户：「不需要额外的『已写入』『未写入』的框，只需要前面的数字中的颜色就可以展示了。
多文字完全是多此一举」。

### 改动

同一状态被表达了两次：`N/M` 标签的颜色 + 一枚文字徽标。颜色已经能一眼读出，
文字徽标纯属重复，还把约束列撑宽。

| 项 | 改前 | 改后 |
|---|---|---|
| 约束列 | `1/1` + 「已写入」徽标 | **只有 `1/1`** |
| 状态表达 | 颜色 + 文字 | **只有颜色** |
| 细节（差在哪、下一步） | 徽标 title | **并进 `N/M` 的 title** |
| 设置页卡片 | `N/M` + 文字徽标 | **只有 `N/M`** |

颜色语义不变：绿 = 已含 ／ 黄 = 未含 ／ 中性 = 没有约束文件。

悬停 `N/M` 仍能看到具体差异，例如「~/.codex/AGENTS.md｜文件里没有共享块；点「⋯」→ 写入共享约束」。

### 测试

- 新增 `SharedStateIsColorOnlyTest`（3 项）：主表不得再渲染文字徽标、卡片同理、
  状态文案只能进 title。
- **反向验证 1 条**：把徽标加回去立即失败。
- 断言写失败一次才有效：只查 `<span class="tag ${` 全仓范围太宽（别处合法使用），
  收窄到约束单元格后才有意义。
- 全量 **1772 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「同一状态只表达一次」小节；`DESIGN.html` 同步。

## [v0.45.1] - 2026-11-11

当前发布版本（build 190）。

**共享徽标文案改准确 + 确认弹框按破坏性分色。**

用户：「这个无共享是什么意思？这个弹框样式仍然没有按照统一的 UI 规范中定义的来」。

### 一、「无共享」是什么意思——它本来就是个错词

`absent` / `missing` 两种状态都兜底成「无共享」，但实际含义是**文件里还没写进去**，
不是「设置里没填内容」（那种情况根本不显示徽标）。

| `sharedL.state` | 改前 | 改后 | title |
|---|---|---|---|
| `current` | 共享已含 | **已写入** | 共享约束已写入这个文件 |
| `covered` | 共享已含 | **已写入** | 文件里已有同义内容（语义一致） |
| `stale` | 共享过期 | **待更新** | 共享内容改过了，点「⋯」→ 写入共享约束 |
| `absent` | 无共享 | **未写入** | 文件里没有共享块；点「⋯」→ 写入共享约束 |
| `missing` | 无共享 | **未写入** | 文件还不存在；先让该客户端生成规则文件 |

设置页卡片的摘要徽标同步改成同一套文案。

### 二、确认弹框不符合规范

| 问题 | 改前 | 改后 |
|---|---|---|
| 主按钮 | 一律 `.cfm-btn-danger`（红） | `danger` 分色：真 → 红；假 → **`.cfm-btn-primary`**（accent） |
| 图标 | 字面 `!` 字符 | `.cfm-icon` + `NOTICE_META` 描边 SVG |
| 图标底色 | 一律 err 红 | `.cfm-card.cfm-info .cfm-icon` → 中性色 |
| 正文 | `**意思相同**` 星号 | 「意思相同」 |

**红色只给「删除 / 覆盖 不可逆」**。写入约束虽覆盖但有备份、可撤销，属可逆操作。
高风险强确认弹框（`.cfm-danger`）同样换成 SVG 图标。

### 三、实测（浏览器里量）

```
非破坏性确认： cardClass=cfm-card cfm-info   icon=rgb(161,161,170) 主按钮=cfm-btn-primary
破坏性确认：   cardClass=cfm-card cfm-danger icon=rgb(248,113,113) 主按钮=cfm-btn-danger
```

### 测试

- 新增 `ConfirmDialogSemanticsTest`（5 项）+ `SharedBadgeLabelTest`（2 项）。
- **反向验证 3 条**：主按钮改回一律红、info 图标改回 err 色、徽标改回「无共享」，各自失败。
- 徽标断言写失败一次才有效：只查 `|| "无共享"` 会被无关代码满足，改为直接断言映射值。
- 全量 **1771 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c / §2.3d-2 补「确认弹框按破坏性分色」与「共享约束徽标文案」
两张对照表；`DESIGN.html` 同步。

## [v0.45.0] - 2026-11-11

当前发布版本（build 189）。

**表格跟着容器压缩（去掉横向滚动条）+ 操作列只保留「⋯」。**

### 一、不出现横向滚动条

用户：「默认应该跟着外面的框进行压缩，不应该有横向的滚动条」。

原来 10 列写死 px，合计 1036，容器一窄就溢出、右侧被截断。

| 列 | 改前 | 改后 |
|---|---|---|
| 名称 | 220px | **20%**（min-width 150px） |
| 类型 | 240px | **15%**（min-width 96px） |
| 安装 / APP / CLI / CONFIG | 56 / 48 / 48 / 70 | **5.5% / 4.5% / 4.5% / 7%** |
| 技能目录 / 约束 / MCP | 82 / 78 / 78 | **8% / 9% / 8%** |
| 操作 | 116px | **5%** |
| 单元格内边 | `--sp-4`（10px） | `--sp-3`（8px） |

合计 **100%**，`table-layout: fixed` 让浏览器按容器分配。实测：
1048px / 720px / 560px 三种容器宽度下 `scrollWidth === clientWidth`，均无横向滚动。

### 二、操作列只保留「⋯」

用户：「所有的操作按钮都应该在三个点里面，不应该单独有一个展示的内容」。

| 项 | 改前 | 改后 |
|---|---|---|
| 操作列内容 | 详情按钮 + ⋯ | **只有 ⋯**（28×28） |
| 详情入口 | 常驻按钮 | 菜单第一项「查看详情」+ 整行可点 |
| kebab 可见性 | 半隐藏 | **默认始终可见**，hover 加深 |

> 「唯一入口不能藏」：kebab 现在是这一列唯一的操作入口，默认必须可见可点，
> 门禁禁止 `opacity: 0`。

### 测试

- 新增 `NoHorizontalScrollTest`（3 项）：10 列都用百分比、合计不超 100%、
  文本列有省略号兜底。
- 新增 `AllActionsInMenuTest`（3 项）：操作列只有 1 个按钮、详情是菜单第一项、
  kebab 默认可见。
- **反向验证 3 条**：加回详情按钮、列宽改回 px、kebab 默认隐藏，各自失败。
- 全量 **1764 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3d-2 补「表格跟着容器压缩」列宽对照表与「操作列只保留「⋯」」；
`DESIGN.html` 同步。

## [v0.44.4] - 2026-11-11

当前发布版本（build 188）。

**修「操作失败：null is not an object」——删了节点却没删写入代码。**

### 事故链

1. v0.40.7 把共享约束卡片精简为「输入框 + 保存」，`#shared-rules-status` 节点随之删除；
2. 但 `auditSharedRules()` 最后一行仍是无条件写入：

   ```js
   host.innerHTML = `...`;   // host 为 null → TypeError
   ```

3. 以前该函数只在用户点「检查同步状态」时执行，而卡片精简后**那个按钮也删了** →
   这条路径再没被走到，问题一直潜伏；
4. v0.44.3 把审计改成**启动即跑**，隐患立刻显形，被 `unhandledrejection` 兜底
   渲染成「操作失败」弹框。

### 修复

```js
if (host) {
  host.innerHTML = ...;
}
```

状态区已不存在，审计的真正消费方是主表「约束」列的颜色；状态区只是可选可视化。

### 全仓排查

扫了 JS 里所有 `$("id").innerHTML / textContent / className` 写法，与 HTML 静态 id +
模板动态 id 比对：**幽灵节点写入 0 处**（本处是唯一的条件写入漏判）。

### 测试

- 新增 `test_ghost_node_writes_are_guarded`：JS 里写的 id 必须真实存在。
- 新增 `test_audit_host_write_is_guarded`：`auditSharedRules` 写状态区必须判空。
- **反向验证 1 条**：去掉判空立即失败。
- 全量 **1756 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「删节点必须连写入代码一起删」三条规则，其中一条是
**「把函数从手动触发改成启动触发，等于启用了它所有隐含前提」**；`DESIGN.html` 同步。

## [v0.44.3] - 2026-11-11

当前发布版本（build 187）。

**找到真因：`SHARED_AUDIT` 启动时从不加载，判定恒为 false。**

用户第二次反馈「目前还是没有」。

### 真因

`SHARED_AUDIT` 只由「检查同步状态」按钮填充（`auditSharedRules()` 只在点击时调用）。
而 `needFixRulesFor` 里写着：

```js
if (!shared || shared.enabled === false) return false;   // shared 恒为 null
```

于是**菜单里永远没有「写入共享约束」**——不是时序抖动，是启动后就没有数据。

更隐蔽的是**两处口径不一致**：

| 位置 | 缺审计数据时的结论 |
|---|---|
| 约束格 | 走「有共享内容但未达标」→ **黄色** |
| 「⋯」菜单 | `return false` → **当作已达标，不给修复项** |

格子说「有问题」，菜单说「没问题」。两边单独看都「符合代码」，所以前一轮排查
（只验证判定函数本身）全部通过——因为我喂了正确的 `SHARED_AUDIT` 进去。

### 修复

| 项 | 做法 |
|---|---|
| 启动即加载 | `loadManagement()` 成功后 `loadSharedRules().then(() => auditSharedRules())`，与 `loadRules()` 同批 |
| 缺数据同口径 | 审计缺失时 `needFixRulesFor` 返回 `true`，与约束格的黄色分支一致 |

### 验证（用真实 CLI 数据）

| Agent | 审计未加载 | 审计已加载 |
|---|---|---|
| DeepSeek Harness | **true** | **true** |
| Codex | **true** | **true** |
| WorkBuddy | **true** | **true** |
| VS Code | false（文件不存在） | false |
| ima.copilot | false（无约定） | false |

### 测试

- 新增 `test_audit_loaded_at_boot`、`test_missing_audit_means_needs_fix`。
- **反向验证 2 条**：去掉启动加载、把缺数据改回 `false`，各自失败。
- 全量 **1756 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「数据就绪是菜单的前提」与设计原则「两处 UI 读同一份
状态时，缺数据时的默认值必须一致」；`DESIGN.html` 同步。

## [v0.44.2] - 2026-11-11

当前发布版本（build 186）。

**菜单加自检日志，定位「格子黄但菜单没有修复项」。**

用户：「菜单和你描述的不一致」（截图里「⋯」菜单仍是
查看详情 / 重新扫描 / 移出管理）。

### 排查结论

用**真实 CLI 数据**跑源码与构建产物（`gui/dist/app.js`）里的判定函数，五个 Agent
的结果都正确：

| Agent | 约束格 | shared.state | needFixMcp | **needFixRules** |
|---|---|---|---|---|
| DeepSeek Harness | 1/1 | absent | true | **true** |
| Codex | 1/1 | absent | true | **true** |
| WorkBuddy | 2/2 | absent | true | **true** |
| ima.copilot | ·（无约定） | - | false | false（无可写位置） |
| VS Code | 0/1 | missing | true | false（文件不存在） |

直接渲染菜单 HTML 后，`DeepSeek Harness` 的项是：

```
detail, rescan, fix-mcp, fix-rules, remove
```

即源码与产物都应该显示「修复 MCP」和「写入共享约束」。截图中两项都不在，说明
判定的**输入**（`SNAP` / `RULES_DATA` / `SHARED_AUDIT` / `SHARED_RULES`）在当时
未就绪，而不是逻辑错误。

### 改动

菜单打开时打印一行 `[agent-menu]` 自检日志：

```
[agent-menu] DeepSeek Harness {
  needSkills: false, needMcp: true, needRules: true,
  rulesPaths: [{path: "~/.codex/AGENTS.md", exists: true}],
  sharedState: "absent", sharedBytes: 403,
  items: ["detail", "rescan", "fix-mcp", "fix-rules", "remove"]
}
```

有这一行就能直接看出是哪一项判定不成立（没装 / 没约束文件 / 共享内容为空 / 已达标），
不必靠截图猜。

### 测试

- 新增 `test_menu_logs_decision_basis`：日志必须含 5 个关键字段。
- **反向验证 1 条**：改掉日志前缀即失败。
- 全量 **1754 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「菜单自检日志」；`DESIGN.html` 同步。

## [v0.44.1] - 2026-11-11

当前发布版本（build 185）。

**「⋯」菜单新增「写入共享约束」，黄色约束格可以直接在界面里修。**

用户截图：菜单里只有「查看详情 / 重新扫描 / 移出管理」，问「操作里面没有修复的
按钮，然后前面黄色的约束我怎么进行修复？」。

### 问题

约束此前只能靠命令行 `--shared-rules-apply`。Skills 和 MCP 都有菜单入口，
唯独约束没有——用户看到黄色格子，点开菜单找不到任何相关动作。

### 改动

| 项 | 说明 |
|---|---|
| 新增菜单项 | 「写入共享约束」——该行约束格是黄色时出现在「⋯」菜单里 |
| 出现条件 | 已安装、**至少一个约束文件存在**、共享内容非空、该 Agent 未达标（`current`/`covered` 之外） |
| 执行 | `--shared-rules-apply NAME`（写前备份 → 原子写 → 回读校验） |
| 交互 | 先确认（列出会被改的文件、说明会替换同义旧条目、写前备份）→ 进度弹框 → 结果弹框 |
| 刷新 | 写完 `loadRules()` → `loadSharedRules()` → `auditSharedRules()`，格子立即变绿 |

**判定与约束格同源**（都读 `RULES_DATA` / `SHARED_RULES` / `SHARED_AUDIT`），不会出现
「格子是黄的但菜单说不用修」。没有约束文件的客户端不提供该项——没有可写位置，
应先让客户端生成规则文件。

### 测试

- 新增 `AgentMenuRulesEntryTest`（3 项）：菜单项存在、条件判定复用同一份数据、
  分发与写入实现存在且写完会重拉。
- **反向验证 2 条**：删掉菜单项、去掉写完的重拉，各自失败。
- 断言写失败一次才有效：`loadRules(` 被子串 `loadSharedRules()` 满足，
  改为精确匹配独立一行调用后才有意义。
- 全量 **1753 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「约束列怎么变绿（v0.44.1 起可在界面里点）」的三项菜单
对照表与判定说明；`DESIGN.html` 同步。

## [v0.44.0] - 2026-11-11

当前发布版本（build 184）。

**找到「操作列改不动」的真凶：表头内联 `style="text-align:right"`。操作组视觉重做。**

用户：「后面对齐的问题好像还是没有解决……最后的操作却是右侧对齐的。详情和 3 个
点的操作按钮的排版布局也不是很好看」。

### 一、真凶是内联样式

表头实际写着：

```html
<th style="text-align:right">操作</th>
```

**内联样式优先级高于任何样式表选择器。** 于是前三轮修复
（`th:nth-child(10)` → `thead th:nth-child(10)` → `.al-op-cell`）全部被它压住，
无论我怎么改 CSS 都无效。

修复：删掉内联，改用 `.al-op-cell`：

```css
th.al-op-cell, td.al-op-cell { text-align: center; }
```

顺带把向导里客户端对照表的「操作」列也统一过来（那里同样是内联右对齐 + 单元格不跟）。

### 二、操作组视觉重做

| 元素 | 改前 | 改后 |
|---|---|---|
| 详情 | 26px 高、常驻边框胶囊 | **28px** 高、透明底透明边框；行 hover / 自身 hover 才浮现 accent 胶囊 |
| 更多 `⋯` | 24px 裸图标 | **28×28** 方形按钮，与详情等高；hover 浮现 `--panel-2` 底 |
| 间距 | 6px | 6px（不变） |

一胖一瘦并排的问题解决：两者等高、同等交互层级，视觉上成为一个「操作组」。表格里
不再常驻两圈边框，减少框线噪音。

### 三、实测

```
表头 align: center  单元格 align: center
表头中心 1010.3 = 操作组中心 1010.3   delta 0
详情高 28 = 更多高 28
```

### 测试

- 新增 `NoInlineTableAlignmentTest`（2 项）：表格单元格不得用内联 `text-align`、
  操作列必须用 `.al-op-cell`。
- 新增 `test_detail_and_kebab_are_equalsized`：两者必须 28px 等高、详情默认透明边框。
- **反向验证 3 条**：加回内联右对齐、去掉等高、去掉显式类，各自失败。
- 全量 **1750 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3d-2 补「禁止用内联 `text-align` 控制列对齐」与操作组构成
（默认态 / hover 态 / 尺寸）；`DESIGN.html` 同步。

## [v0.43.3] - 2026-11-11

当前发布版本（build 183）。

**找到真正的根因：`.al-type` 类挂到了 `<td>` 上，把单元格改成 `inline-block`。**

用户第三次反馈「并没有，请你直接截图或者用视觉进行查看，目前仍然是异常的，甚至
现在操作按钮和详情按钮发生了干涉和冲突」。

### 根因（这次是量出来的）

在浏览器里逐列量矩形，发现第 2 列：表头右缘 **486.32**，单元格右缘 **483.55**，
而第 3 列两者都是 542.97。按「第 2 列内部塌了」去查 CSSOM，命中规则是：

```
.agent-list-table .al-name, .agent-list-table .al-type => inline-block
```

`.al-type` 这个装饰类**同时挂在 `<td>` 和内部 `<span>` 上**。`display: inline-block`
命中单元格后，`table-layout: fixed` 的计算宽度对该单元格失效，实际塌到 **72.98px**
（设定 240px）——后面整列全部错位。

**为什么前两轮没找到**：我只量表头，而表头一直是对的（表头没有 `.al-type` 类）。
只有把「表头右缘」和「同一列单元格右缘」分别量、再对照，才看得见。

### 修复

| 项 | 改前 | 改后 |
|---|---|---|
| 类型单元格 | `<td class="al-type">` | `<td class="al-type-cell"><span class="al-type">` |
| 单元格 display | 被装饰类改成 inline-block | `display: table-cell` 显式钉死 |
| kebab 覆盖层 | `right: calc(sp-4 + 68px)` 绝对定位 | **删除**，详情与更多并排 |
| 操作列 | 120px + 覆盖层 | 116px + 居中并排（详情右缘与 kebab 左缘不相交） |

### 实测结果

```
修复前：第 2 列 表头 486.32 / 单元格 483.55  ← 差 2.77px，其余列都对
修复后：全部 10 列 th 与 td 右缘完全一致（allAligned: true）
       操作列表头中心 1010.3 = 按钮组中心 1010.3
       详情右缘 1026 < kebab 左缘 1032（不重叠）
```

### 测试

- 新增 `CellDisplayGuardTest`（3 项）：类型单元格不得挂装饰类、单元格 display 钉死、
  不得有装饰类与 `td` 同名。
- 更新 `OperationColumnAxisTest`：覆盖层方案作废，改为「并排 + 居中」。
- **反向验证 4 条**：类型单元格改回 `.al-type`、去掉 `display: table-cell`、
  类型列改回 `auto`、操作列改回裁切，各自失败。
- 全量 **1747 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3d-2 补「单元格 display 必须钉死为 table-cell」与
「装饰类不得与 td 同名」两条护栏，并把覆盖层方案标记为**已废弃**；`DESIGN.html` 同步。

## [v0.43.2] - 2026-11-11

当前发布版本（build 182）。

**主表补上贯通整列的竖线 + 操作列改中心对齐。**

用户第三轮：「好像还是没有对齐，中间的线还是断的。操作的这个标题栏和下面的内容
操作按钮没有居中对齐」。

### 一、竖线是断的：根因是根本没有竖线

前两轮我一直在调「列宽对齐」，但**主表从来没有列分隔线**——只有横线，靠列宽对齐
"看起来"像分隔。表头与表体之间也没有一条连续的竖线。

修复：

| 项 | 改前 | 改后 |
|---|---|---|
| 表格布局 | `border-collapse: collapse` | `separate` + `border-spacing: 0` |
| 列分隔 | 无 | 每个单元格 `:not(:last-child)::after` 画 `absolute; top:0; bottom:0; width:1px` |
| 表头背景 | 无（穿线会露白） | `background: var(--bg-elev)` |
| 末行底边 | 有（与容器边框重线） | 去掉 |

> 为什么不用 `border-right`：`collapse` 会合边、伪元素被裁；单独加右边框，表头与
> 表体之间仍被横向 border 断开。

### 二、操作列：右对齐 → 中心对齐

v0.43.1 用的是右对齐（表头文字右缘 = 按钮右缘）。但两者**盒子宽度不同**，视觉中心
相差 **19px**，所以两轮都被读成「没有居中对齐」。

改为 `text-align: center` + `.al-ops { justify-content: center }`。

### 三、一个测试正则的缺陷

`test_td_overflow_hidden_for_fixed_layout` 用的 `\.agent-list-table td\s*\{` 会先匹配到
`td:nth-child(10)` 那条（`\s*` 允许零宽）——它一直在检查错误的规则。新增
`th, td { position: relative }` 多选择器规则后彻底暴露。修正为**行首锚定**的
`^\s*\.agent-list-table td\s*\{`。

### 测试

- 新增 `ListVerticalRulesTest`（3 项）：竖线伪元素、collapse 已禁用、表头有背景。
- **反向验证 2 条**：去掉竖线伪元素、collapse 改回，各自失败。
- 全量 **1744 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3d-2 补「列间竖线必须贯通」与「操作列中心对齐」；`DESIGN.html` 同步。

## [v0.43.1] - 2026-11-11

当前发布版本（build 181）。

**操作列真正对齐（三层根因）。**

用户：「还是有错位，这里的线没有对齐，连在一起，然后标题栏中操作和下面的按钮没有居中对齐」。

### 三层根因

| 层 | 根因 | 修复 |
|---|---|---|
| 1 | 表头 `text-align: right` 被 `.agent-list-table th { text-align: left }` 覆盖（同特异性、后者在文件更下方） | 提到 `thead th:nth-child(10)` 层级 |
| 2 | 按钮组是 `[详情][kebab]`，以整组右缘对齐时详情按钮中心偏左 **31px** | kebab 改为 `.kebab-row` 绝对定位到右上角、hover 才出现；详情成为轴线唯一基准 |
| 3 | `td` 的 `overflow: hidden` 把按钮 3px hover 光晕削成直角，与相邻列竖线粘连 | 操作列 `overflow: visible` + `position: relative` |

### 顺带修掉的隐藏问题

`table-layout: fixed` 下，所有列 `width` 合计小于表格宽时浏览器会**按比例放大每一列**——
用户写的 px 变成比例值。实测 10 列合计 958px、容器 1061px → 名称 220 被放到 243.6、
操作 128 被放到 141.8，所以「定宽」一直没真正钉死。

修复：**类型列改成 `width: auto`** 吸收剩余，其余列才是真定宽（实测列宽现在
220 / 253 / 56 / 48 / 48 / 70 / 82 / 78 / 78 / 128，与设定一致）。

### 验证

在浏览器里量真实矩形：

| 指标 | 改前 | 改后 |
|---|---|---|
| 表头文字右缘 − 详情按钮右缘 | **31px** | **0px** |
| 行与行之间的列分隔线 | 一致 | 一致（`rowDrift: []`） |

### 测试

- 新增 `OperationColumnAxisTest`（4 项）：表头特异性、操作列不裁切 + 相对定位、
  kebab 为 hover 覆盖层、类型列吸收剩余。
- **反向验证 3 条**：取消 kebab 覆盖层、操作列改回裁切、类型列改回定宽，各自失败。
- 全量 **1741 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3d-2 补「操作列的轴对齐」与「fixed 布局按比例放大」两条；
`DESIGN.html` 同步。

## [v0.43.0] - 2026-11-11

当前发布版本（build 180）。

**操作列错位修复 + 约束列「语义一致即变绿」与旧条目替换。**

### 一、操作列错位

| 问题 | 原因 | 修复 |
|---|---|---|
| 详情/更多按钮被裁 | 列宽 104px，内容需 ~120px（按钮 66 + kebab 28 + gap + 单元格内边） | 加宽到 **128px**，`.al-ops` 加 `min-width: 0` 兜底 |
| 「操作」表头与内容错位 | 表头未设对齐（默认左对齐），按钮组靠右 | 表头 **右对齐** |

### 二、约束列怎么变绿（三条要求）

| 要求 | 实现 |
|---|---|
| (a) 写进每个 Agent 并生效 | `--shared-rules-apply [CLIENT...]`，写前备份 → 原子写 → 回读校验 |
| (b) 意思一样即可，不必一模一样 | `_similar()`：**字符级 Dice 系数**，阈值 0.45；语义覆盖算达标 |
| (c) 把原文件里类似的内容替换掉 | 写入前 `_strip_similar()` 删除相似度 ≥ 阈值**且只占一行**的旧条目 |

实测效果（用临时文件验证）：

```
写入前：  # 我的规则
          - 所有回答都必须使用中文      ← 与共享内容同义
          - 不要删文件

写入后：  # 我的规则
          - 不要删文件                 ← 无关条目保留
          <!-- shared-rules:begin v1 -->
          - 所有回答包括思考过程，都必须使用中文   ← 同义旧条目已被替换
          <!-- shared-rules:end -->
```

### 三、为什么用字符级 Dice

中文 2-gram 稀疏：「必须用中文回答」vs「所有回答都必须使用中文」的 Jaccard 只有
**0.33**，但字符级重叠过半。实测标定：同义改写 0.52~0.79，不同主题 < 0.30，
阈值取 0.45。

### 四、一个必须加的护栏

`covered`（语义已覆盖）**只在没有标记块时生效**。块存在且内容不同 = 用户改过配置，
必须报 `stale` 让用户去同步——否则改完内容界面永远显示「已含」。
这个坑是测试抓出来的：「完全无关的一条」与「完全不相干的一条」相似度 0.67，
第一次实现把 stale 场景判成了 covered。

### 测试

- 新增 `SemanticMatchTest`（4 项）：同义改写判 covered、无关主题判 absent、
  写入时替换旧条目（断言「中文」只出现 1 次且无关条目保留）、阈值在实测区间内。
- **反向验证 2 条**：阈值调到 0.99、关掉旧条目替换，各自让断言失败。
- 全量 **1737 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「约束列怎么变绿」（状态机 + 相似度选型 + 替换边界）；
`DESIGN.html` 同步。

## [v0.42.0] - 2026-11-11

当前发布版本（build 179）。

**全部弹框统一到同一套度量，边界写进规范。**

用户：「请检查一下所有的当前项目，所有的弹框都应该是同样的规范」。

### 审计结果

全仓 29 处 `mountModal`，容器分三类（骨架本来就该不同）：

| 家族 | 容器类 | 标题 | 主体 | 底栏 | 使用数 |
|---|---|---|---|---|---|
| 表单 | `.modal.modal-form` | `.form-title` | `.form-body` | `.form-actions` | 11 |
| 确认 / 通知 | `.modal.cfm-card` | `.cfm-title` | `.cfm-msg` | `.actions` | 13 |
| 详情 | `.modal.ad-modal` | `.ad-name` | `.ad-body` | `.ad-foot` | 3 |

四类已共用 `.modal` 容器样式、`.modal-backdrop`（z-index 50）与 `closeModal`
关闭路径。**漂移的是数字**，共三处：

| 项 | 改前 | 改后 |
|---|---|---|
| 详情弹框标题 | `1.35rem` / 700 | `--fs-md` / 600（与表单同档） |
| 确认弹框按钮内边 | `--sp-8a`（22px） | `--sp-8`（20px，与表单同） |
| 详情弹框主体顶部内边 | `--sp-2`（6px） | `--sp-6`（14px，与表单同） |

**允许保持不同**（家族特性，不是漂移）：标题对齐（通知居中 / 表单左对齐）、
底栏对齐（通知居中 / 表单右对齐）、图标徽标（仅通知与确认有）。

### 测试

- 新增 `ModalFamilyConsistencyTest`（3 项）：标题刻度统一、按钮度量统一、主体内边对齐。
- **反向验证 3 条**：标题改回 1.35rem/700、按钮内边改回 22px、主体内边改回 6px，
  各自让断言失败。
- 全量 **1733 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 新增 §2.5b-4「弹框家族的一致性边界」；`DESIGN.html` 同步。

## [v0.41.0] - 2026-11-11

当前发布版本（build 178）。

**通知弹框的排版与交互统一，写进 UI 规范。**

用户截图「已完成 / 共享约束已保存（403 B）。写进各 Agent 请运行 --shared-rules-apply」，
评语「信息太乱」。

### 三处问题与修复

| 问题 | 现象 | 修复 |
|---|---|---|
| 图标配色与语义矛盾 | 「已完成」配**粉红底绿勾** | `.cfm-icon` 底色/描边跟随 `kind`（ok 绿 / warn 黄 / err 红 / info 蓝），直径 48 → 40px |
| 正文居中折行 | 多行中文居中，每行起止位置都在变 | 通知正文 `.notice-msg` **左对齐**；标题与图标保持居中 |
| 结论与下一步混在一句 | 用句号把两者串起来 | `_splitNotice()` 拆成**结论** + **下一步**（`.notice-action` 强调块，带 `›` 前导） |

### 拆分规则

只在「第一个句末标点后还有内容」**且**后半句像动作时拆（以「请 / 需要 / 可 / 运行 /
执行 / 点击 / 打开」开头，或以 `--flag` 开头，或含这些动词）。

**踩到一个中文正则的坑**：最初写 `/\b运行\b/`，永不匹配——JS 的 `\b` 只认 ASCII
单词字符，中文与 `--` 之间不构成词边界。改成不含 `\b` 的写法后正常。

### 测试

- 新增 `NoticeLayoutTest`（3 项）：图标按 kind 上色、正文左对齐、拆分逻辑存在且
  下一步绑定到 `parts.next`。
- **反向验证 3 条**：去掉 ok 图标配色、正文改回居中、去掉下一步渲染，各自失败。
- 断言写失败两次才有效：`class="notice-action"` 与 `<div class="notice-action">` 都被
  工程里**另一处结构相同的 `o.action` 分支**满足 —— 最后绑定到独有的 `${escapeHtml(parts.next)}`。
- 全量 **1730 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 新增 §2.5b-3（结构示意 + 拆分规则 + 交互）；`DESIGN.html` 同步。

## [v0.40.9] - 2026-11-11

当前发布版本（build 177）。

**全项目禁止吐司/横幅：结果通知一律走 `.cfm-card` 弹框。**

用户：「整个项目都不允许使用这种吐司，都必须使用弹框。弹框的样式必须按照统一的
UI 规范进行设置」。

### 改动

| 项 | 改前 | 改后 |
|---|---|---|
| `showBanner()` | 写 `#banner` 元素（顶部横幅） | **委托 `modalNotice()`** → `.cfm-card` 弹框家族 |
| `#banner` 元素 | 页面常驻 | **删除** |
| `.banner` 样式 | 4 条 | **删除**（无引用死 CSS） |
| 自动发现提示 | `class="banner warn"` | `.agent-notice` 页面内常驻提示块 |

**`showBanner` 保留函数名与签名**：57 个调用点一个都不用改，语义也没变
（「给用户一条结果通知」），只是换成规范弹框。

### 唯一保留的页面内提示

`.agent-notice`（如「自动发现 N 个新客户端待纳入」）。它不是结果通知，而是一条
**必须一直可见到用户处理**的待办状态——弹框会挡住页面、关掉就看不见了。用
`--warn-bg` / `--warn-border` + `.tag` 家族，不引入新视觉语言。

### 一条门禁的措辞要求

规范里提到已删除的类时，必须写成「没有 `.banner` 这一类了」这种**否定式**——
`test_spec_referenced_classes_exist_in_code` 按上下文 40 字符内的
「没有/不存在/不是/非」区分「引用」与「澄清」。写成「`.banner` 已整体移除」会被
当成引用而报红（实测踩到）。

### 测试

- 新增 `NoToastTest`（3 项）：无横幅元素/样式/用法、`showBanner` 必须委托
  `modalNotice`、通知必须是 `.modal cfm-card` 家族。
- **反向验证 2 条**：加回横幅元素、`showBanner` 改回写横幅，各自让断言失败。
- 全量 **1727 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.5b-2 与 §2.3 表格更正「`.banner` 只留给非阻塞告知」的旧口径；
`docs/DESIGN.html` 同步。

## [v0.40.8] - 2026-11-11

当前发布版本（build 176）。

**共享约束：设置里只保存，不同步。**

用户：「设置里应该只保存，不需要同步」。

### 改动

| 项 | 改前 | 改后 |
|---|---|---|
| 按钮 | `保存并同步`（保存后自动 apply） | **`保存`**（只存内容） |
| 保存后的行为 | `--shared-rules-set` + `--shared-rules-apply` | 只 `--shared-rules-set` |
| 说明文案 | 「保存后会写进每个 Agent…」 | 「这里只保存内容。写进各 Agent 需另行执行同步命令…」 |

写进各 Agent 仍是一次独立动作，经 CLI `--shared-rules-apply [CLIENT...]`
（备份 → 原子写 → 回读校验），只是**不出现在设置页的按钮里**。

设置页的职责收回到「维护这段内容」；「这个 Agent 有没有」看同 tab 下 Agent
列表「约束」列的颜色。

### 测试

- 新增断言：卡片里必须有 `shared-rules-save`，**不得有** `shared-rules-apply` /
  `shared-rules-audit`。卡片说明文字也去掉 apply 字样，否则会被断言误判成按钮。
- **反向验证**：卡片里加回同步按钮，断言立刻失败。
- 删除一处与新规则冲突的旧断言（`assertIn('data-action="shared-rules-apply"')`）。
- 全量 **1724 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 改正；`docs/DESIGN.html` 同步。

## [v0.40.7] - 2026-11-11

当前发布版本（build 175）。

**共享约束定稿：只留「约束内容」输入框，归位设置页 IDE / Agent tab。**

用户：「红色框部分保留，其他的删除，然后将保留的部分放到设置的 IDE/agent 的 tab 部分」。

### 最终形态

```
┌ 共享约束 ──────────────────────────────────────────────┐
│ 约束内容   [ textarea（等宽 --mono / --fs-xs，max-width 44rem）] │
│           保存后会写进每个 Agent 的约束文件…  [保存并同步]        │
└────────────────────────────────────────────────────────┘
```

| 保留 | 删除 |
|---|---|
| 「约束内容」输入框 | 同步行（摘要 + 三个按钮） |
| 一个「保存并同步」按钮 | 每个 Agent 的状态一览 |

**位置**：设置页 → IDE / Agent tab 顶部（在「IDE / Agent 默认路径」之上），从概览页搬回。

### 「这个 Agent 有没有共享内容」看哪里

看同一个 tab 下面 Agent 列表的**「约束」列颜色**——绿 = 已含，黄 = 有文件但缺共享内容，
中性 = 没有约束文件。不需要第二套状态表达。

### 一个按钮两件事

「保存并同步」：先 `--shared-rules-set` 存内容，再 `--shared-rules-apply` 写进各 Agent
（沿用备份 → 原子写 → 回读校验）。清空内容再保存 = 停用该功能。

### 五次方向修正的记录

| 版本 | 形态 | 用户反馈 |
|---|---|---|
| v0.40.0 | 全套面板 | 「有点丑」 |
| v0.40.4 | 同上，搬到概览页 | 「不要放在设置里」 |
| v0.40.5 | 整体删除 | 「删过头，输入框也没了」 |
| v0.40.6 | 找回输入框 + 同步行 + 状态一览 | 「红框保留，其他删，放到设置」 |
| **v0.40.7** | **只有输入框 + 保存并同步** | 定稿 |

### 测试

- `test_shared_card_keeps_content_editor` → `test_shared_card_is_content_only_in_settings`：
  输入框必须在；状态一览 / 同步行 / 逐 Agent 开关必须**不在**；卡片必须在
  `data-panel="agents"` 里且**不在** `renderOverview()` 里。
- **反向验证 2 条**：删掉输入框、把卡片挪回概览，各自让断言失败。
- 概览测试撤回卡片装配。
- 全量 **1724 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 定稿（含五次修正的对照表）；`docs/DESIGN.html` 同步。

## [v0.40.6] - 2026-11-11

当前发布版本（build 174）。

**找回共享约束的内容输入框——v0.40.5 删过头了。**

用户：「你配置约束文字的内容的功能和输入框这些怎么不见了？」

### 上一版删错了

v0.40.5 说「整体删除」时，把**配置约束内容的输入框**也一起删了。用户真正要删的是
那张「逐 Agent 开关 + 逐行写入」面板——不是「在哪儿写内容」。

| 保留 | 删除 |
|---|---|
| 约束内容 textarea（`#shared-rules-text`） | 逐 Agent 参与开关（`.switch`） |
| 保存内容 / 同步到全部 / 检查各 Agent | 逐行「写入」按钮 |
| 只读状态一览（每 Agent 一行，仅标签） | —— |

卡片仍在**概览页**「快捷操作」下方，复用 `.settings-card` 的 `.rows/.row` 语言。
逐 Agent 参与开关仍在 CLI：`--shared-rules-toggle CLIENT on|off`。

### 测试

- `test_no_shared_card_anywhere` 作废，替换为
  `test_shared_card_keeps_content_editor`：输入框 / 保存 / 同步三个标识符必须在，
  逐 Agent 开关与逐行写入必须**不在**。
- **反向验证 2 条**：删掉输入框、重新加回逐 Agent 开关，各自让断言失败。
- 概览测试重新补上卡片装配（`_fn("sharedRulesCard")` + `SHARED_AUDIT` 桩）。
- 全量 **1724 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 改正（保留 / 删除两栏对照）；`DESIGN.html` 同步。

## [v0.40.5] - 2026-11-11

当前发布版本（build 173）。

**共享约束的独立卡片整体删除，只留「约束」列的三态颜色。**

用户：「这个完全是不需要的，不需要放在概览里完全删除；只需要在 IDE 和 Agent 的
那个 tab 里，在约束的绿色框中，通过不同的颜色来展示出是否有约束文件，以及约束
文件中是否有设置的内容」。

### 删了什么

独立卡片（编辑框 + 逐 Agent 开关 + 逐行写入 + 状态列表）**整体删除**，包括它
v0.40.0 → v0.40.4 的三次搬家（设置页 → 概览页）。`sharedRulesCard()` /
`bindSharedRulesBox()` / `#shared-rules-card` / `#shared-rules-status` /
`#shared-rules-text` 全部移除。

### 留了什么：一个颜色

「约束」列现在按两件事上色：

| 状态 | 颜色 | 含义 |
|---|---|---|
| 没有约束文件 | 中性 | 这个 Agent 没配规则文件 |
| 有文件，但没有共享内容 | `warn`（黄） | 文件在，你设置的共享约束还没进去 |
| 有文件，且已含共享内容 | `ok`（绿） | 就绪 |

判定：`hit === 0` → 中性；`sharedRow.state === "current"` → ok；共享内容本身为空
（还没配过）→ ok；其余（有文件但缺共享块 / 内容过期）→ warn。

卡片视图的徽标同样收口：共享内容为空时**不显示**「共享已含 / 共享过期 / 无共享」——
没有共享约束这回事，就不该硬造一个状态。

### CLI 能力保留

卡片删了，后端能力没删（写操作安全形状不变）：
`--shared-rules-get` / `--shared-rules-set` / `--shared-rules-audit` /
`--shared-rules-apply` / `--shared-rules-toggle`。

### 测试

- 旧的两个卡片测试（结构语言、位置）随卡片一起作废，替换成：
  `test_no_shared_card_anywhere`（五个标识符一个都不许残留）+
  `test_rules_cell_uses_three_color_states`（三态颜色分支）。
- 撤回 `test_dashboard_overview_stats` 上一轮为卡片加的 node 装配。
- **反向验证 2 条**：重新加回 `sharedRulesCard`、约束列不再给 warn，各自让断言失败。
- 全量 **1724 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 重写（删掉三次搬家的历史与卡片结构描述，只留三态颜色
与 CLI 能力表）；`docs/DESIGN.html` 同步。

## [v0.40.4] - 2026-11-11

当前发布版本（build 172）。

**共享约束从设置页搬到概览页。**

用户：「你还是理解错了，这部分不要放在设置里，也不需要」。

### 为什么该搬

共享约束是一条**业务流水线**（编辑内容 → 检查各 Agent → 同步进去），不是
「配置一次就不动的全局项」。项目自己的纪律（PRD §5.3「通用 / 业务分离原则」）：
通用配置收敛进设置页，业务动作放对应管理页。共享约束属于后者，放设置里是分类错了。

### 改动

| 项 | 改前 | 改后 |
|---|---|---|
| 位置 | 设置 → IDE / Agent tab 顶部 | **概览页**「快捷操作」下方、「全量检查」上方 |
| 产出方式 | `renderSettings()` 里内联 | 独立 `sharedRulesCard()`，由 `renderOverview()` 调用 |
| 设置页 agents tab | 两张卡片 | 只剩「IDE / Agent 默认路径」 |

卡片结构本身不变（仍复用 `.settings-card` 的 `.rows/.row` 语言），只是换了个家。

### 连带修的两处

1. **`tests/test_dashboard_overview_stats.py` 的 node 渲染护栏**：它抽取 `renderOverview`
   到 node 里执行，新增依赖后报 `ReferenceError: sharedRulesCard`。补了
   `_fn("sharedRulesCard")`、`SHARED_AUDIT` 全局桩，以及 `bindSharedRulesBox` /
   `auditSharedRules` 的空桩——**这类护栏的价值就在于此**，它不允许渲染函数悄悄
   引用了没一起带过去的东西。
2. 概览渲染后自动 `auditSharedRules()`（首次），避免用户还得手动点一次才看到状态。

### 测试

- 新增断言：设置页不得再挂 `${sharedCard}`；卡片由 `sharedRulesCard()` 产出且被
  `renderOverview()` 调用。
- **反向验证**：从 `renderOverview()` 里去掉 `sharedRulesCard()` 调用，断言失败。
- 全量 **1725 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 开头补「位置：概览页业务区，不在设置里」；`DESIGN.html` 同步。

## [v0.40.3] - 2026-11-11

当前发布版本（build 171）。

**共享块状态回显到「约束」列：一眼看出哪些 Agent 缺了共享约束。**

用户：「在外面正式功能的上方，没法从约束对应的框中展示出，到底有没有增加进我
要求的这部分约束」。

### 问题

「约束」列此前只回答「**路径存不存在**」（`1/1` / `0/1`），不回答「**共享块在不在**」。
共享约束配好之后，要判断某个 Agent 到底加进去没有，只能去设置页挨个看——而设置页
里那段恰好是「参与开关」，不是「内容在不在」。

### 改动

卡片与主表列表的「约束」处各加一枚并列徽标（同一 `.tag` 家族，不新造样式）：

| 共享块状态 | 徽标 | 类别 |
|---|---|---|
| `current` | `共享已含` | `tag ok` |
| `stale` | `共享过期` | `tag warn` |
| `absent` / `missing` | `无共享` | `tag`（中性） |
| 该 Agent 开关关闭 | 不显示 | —— |

`SHARED_AUDIT` 在 `loadManagement()` 之后自动跑一次，**不必先打开设置页**也能看到。

### 一条失败的门禁教训

第一版断言写的是「文件里出现过 `共享已含` 这几个字」，反向验证时把映射表换成空串，
**测试照样绿**——因为那三个字在我自己的注释里出现了一次。改成从源码抽出
`_agentRulesSummary()` / `renderHomeListView()` 两个函数体、断言其中的**渲染分支**
（`current: "共享已含"`、`${sharedSpan}`），反向验证才真正报红。

同一条教训这轮踩了两次（第一次是改成精确匹配但匹配到了注释）。**断言的对象必须是
被执行的代码路径，不是文本里出现过什么。**

### 测试

- 新增 1 项断言（校验卡片与列表的渲染分支）。
- **反向验证 2 条**：卡片映射表清空、列表不渲染 `${sharedSpan}`，各自让断言失败。
- 全量 **1724 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过（含 ruff）。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「共享块状态回显」小节；`docs/DESIGN.html` 同步。

## [v0.40.2] - 2026-11-11

当前发布版本（build 170）。

**共享约束：逐 Agent 开关，职责收敛成「参不参与 / 要不要同步」。**

用户：「这里只是设置是否检查同步以及是否需要同步进入各个 Agent」。

### 上一版的错位

v0.40.1 把每一行的 `[状态标签] [写入]` 并排放，13 个 Agent × 2 个按钮铺满整张
卡片——看起来像一张待办清单，而不是「设置哪些 Agent 参与」。用户要的是**开关**，
不是逐条修复按钮。

### 改动

| 项 | 改前 | 改后 |
|---|---|---|
| 每行右侧 | `[写入]` 按钮 | 既有 `.switch`（`role="switch"`），语义「参与 / 不参与」 |
| 关闭的 Agent | 状态标签照常显示待修 | 显示「已关闭」，行弱化（`row.is-off` 只降色阶），**仍列出**可随时切回 |
| 同步到全部 | 所有非 missing 的 Agent | **跳过已关闭的** |
| 单行「写入」 | 所有待修的 | 关闭的不渲染 |
| 摘要 | `13 个客户端` | `12/13 个 Agent 参与 · …` |
| 路径明细 | 每行内联（撑高） | 收进状态标签的 `title` |

### 规则在数据层，不只在界面

`--shared-rules-toggle CLIENT on|off` 写 `data/shared_rules_settings.json`（gitignore，
默认参与）。`apply_client` 对关闭的 Agent 直接返回「已关闭共享约束同步」——
即使有人绕过界面直接调 CLI，也写不进去。

### 测试

- 新增 `ClientToggleTest`（5 项）：默认参与、关闭后审计回报、关闭后拒绝写入、
  另一个不受影响、设置持久化。
- **反向验证 2 条**：去掉 apply 里的开关守卫、审计不再回报开关状态，各自让断言失败。
- 全量 **1723 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 补「逐 Agent 开关」语义表；`docs/DESIGN.html` 同步。

## [v0.40.1] - 2026-11-11

当前发布版本（build 169）。

**共享约束卡片重设计：改用设置页既有的 `.rows > .row` 语言。**

用户截图反馈：「这个设计有点丑，请严格按照 UI 规范中定义的控件内容重新设计」。

### 上一版为什么丑

v0.40.0 的卡片是自己发明的一套结构：

- label「约束内容」放在 **textarea 下方**（正常表单是 label 在上或在左）；
- 说明文字拆成两行，按钮散在左右两个角落（「检查同步状态 / 同步到全部」在顶部
  右侧、「保存内容」在底部右侧）；
- textarea 没用任何作用域样式，直接吃浏览器默认外观，**宽度只有 220px**、
  与旁边卡片控件不同族。

等于在设置页里嵌了一个异类表单——设置页其它卡片（外观 / 后台巡检 / 市场源 /
IDE 默认路径）全是「label 左 150px / 控件右 / hairline 分隔」。

### 重设计

| 项 | 改前 | 改后 |
|---|---|---|
| 结构 | 自造的两行说明 + 角落按钮 | `.rows` → `.row.row-block`（正文）+ `.row`（状态） |
| label | textarea 下方 | 左侧 `.k` 列，150px，与其它卡片同宽 |
| textarea | 浏览器默认（220px 宽） | `.settings-card .row .v > textarea`：同边框、同 `--r-control` 圆角、同内边距，`--mono` 等宽、`max-width: 44rem`、`resize: vertical` |
| 按钮 | 散在顶部右侧 + 底部右侧 | `.shared-actions` 靠右成组：检查（`.ghost`）→ 同步（`.btn-soft`）→ 保存（`.primary`），**主操作在最右** |
| 状态摘要 | 单独一行 note | 收进「同步状态」行的 `.v` 里 |
| 状态列表 | 无边框罗列 | `.rows > .row`：名称定宽 150px、状态跟随、写入按钮 `margin-left: auto` 竖成一条线 |

**没有新增按钮样式、没有新增颜色**：三类按钮全是既有 `button.ghost` /
`.btn-soft` / `.primary`，状态标签全是既有 `.tag ok / warn`。

### 测试

- 新增 2 项断言：卡片必须含 `.rows` / `.row.row-block` / 两个 `.k` / `.shared-actions`
  且只用既有三档按钮；textarea 必须有作用域样式（圆角 token、等宽字体、限宽、可纵拉）。
- **反向验证 3 条**：去掉 `row-block`、去掉 `.shared-actions`、textarea 去掉圆角 token，
  各自让断言失败。
- 全量 **1718 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` §2.3c-2c 的「界面」小节重写（含上一版为什么丑的复盘）；
`docs/DESIGN.html` 同步。

## [v0.40.0] - 2026-11-11

当前发布版本（build 168）。

**新功能：共享约束——一段内容同步进所有 Agent 的约束文件。**

用户需求：「可以配置一个需要在所有 Agent 中增加的约束内容，然后可以通过同步管理
（和 skill 一样），检查每一个 Agent 是否都拥有这个约束内容；如果没有，可以点击
强制更新进去」。

### 一、数据模型：标记块，不是整体覆盖

内容存 `data/shared_rules.md`（gitignore），写进各文件时用一对标记包住：

```markdown
<!-- shared-rules:begin v1 -->
（用户配置的内容）
<!-- shared-rules:end -->
```

**为什么不整体覆盖文件**：约束文件里还有用户自己的规则（本机 `~/.codex/AGENTS.md`
就有 2150 B 自己的内容），整体覆盖会把它们全部冲掉。标记让写入变成幂等的
「替换这一段 / 追加这一段」，**块外内容逐字节不动**。

### 二、四种状态 + 一键强制写入

| 状态 | 含义 | 可修 |
|---|---|---|
| `current` | 块存在且内容一致 | 不需要 |
| `stale` | 块存在但内容变了 | ✅「写入」 |
| `absent` | 文件存在但没有块 | ✅「写入」 |
| `missing` | 文件不存在 | ✅「新建并写入」 |
| `dir` | 规则目录（Cline / TRAE） | ➖ 跳过 |

客户端整体状态取「最需要处理」的那一个：`missing > absent > stale > dir > current`。

### 三、入口

| 入口 | 用法 |
|---|---|
| 设置页 IDE / Agent tab 顶部 | 「共享约束」卡片：textarea 编辑 → 保存内容 → 检查同步状态 → 逐行「写入」/「同步到全部」 |
| CLI | `--shared-rules-get` / `--shared-rules-set TEXT` / `--shared-rules-audit` / `--shared-rules-apply [CLIENT...]` |

### 设计取舍

- 按钮全用既有 `.ghost` / `.primary` / `.btn-soft sm` 家族，**没有新造按钮样式**；
- 状态用既有 `.tag ok/warn` 档位，**没有新增颜色**；
- 只给「可以修」的行渲染按钮，已同步与目录跳过不渲染——不留死路。

### 安全形状

`--shared-rules-apply` 逐客户端、逐路径执行，写前经 `write_rules` 的
「备份 → 原子写 → 回读校验」；部分失败如实回报每个客户端的失败原因，不合并成总数。

### 测试

- 新增 `tests/test_rules_shared.py`（19 项）：标记块往返、幂等、块后内容保留、
  四种路径状态、apply 的新建 / 保留用户内容 / dry-run / 空内容拒绝、CLI+GUI+Rust 接线。
- **反向验证 2 条**：替换时吃掉块后内容、追加时冲掉原内容，各自让断言失败。
- 全量 **1716 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 新增 §2.3c-2c；`docs/DESIGN.html` 同步。

## [v0.39.8] - 2026-11-10

当前发布版本（build 167）。

**托盘面板第四格：Hook → DSH 插件。**

用户截图指出：「这里的 hook 还存在，请你修改成 DSH 插件」。

### 根因

Hook 功能已于 **v0.33.0** 整体下线（CLI 参数 / GUI 页 / 配置段 / `core/hooks_*.py`
全部删除），但托盘面板 `gui/popover.html` 的 `DIMS` 里第四格仍是 `["hooks", "Hook"]`。
`totals.hooks` 早已不存在，那一格永远读到 0、恒显灰色——用户会以为「Hook 还在，
只是没配置」，而实际是功能已经没有了。

### 改动

| 位置 | 改前 | 改后 |
|---|---|---|
| `gui/popover.html` `DIMS` | `["hooks", "Hook"]` | `["dsh", "DSH 插件"]` |
| `scan.py` `_snapshot_totals()` | 只返回 agents / mcp / skills | 增加 `dsh`（DSH 插件总数） |
| `docs/DESIGN.md` §2.8 | 无四格说明 | 补四格口径与入口约束 |

DSH 插件数与本工具实际提供的「DSH 插件」页同源，本机实测 `dsh: 16`。

### 一个实测踩到的坑

第一版写成 `scan(os.path.expanduser("~/.dsh"))`，结果 `dsh: 0`——`dsh_plugins.scan()`
收到**未展开**的路径时找不到 profiles，静默返回 0 个插件。改成传 `None` 让
`dsh_plugins` 自己解析默认根目录（与 `--dsh-plugins` 的默认参数同一入口）后得到 16。

统计失败也做了降级：`try/except` 包住，扫描异常时 `dsh: 0`，绝不让一个可选的只读
统计把整个托盘面板搞挂。

### 测试

- 新增 `TrayPanelDimsTest`（3 项）：托盘不得再有 Hook 格、必须有 DSH 插件格、
  `_snapshot_totals()` 必须返回 `dsh` 且不再有 `hooks`。
- **反向验证**：把 `["dsh", "DSH 插件"]` 改回 `["hooks", "Hook"]`，断言立刻失败。
- 全量 **1697 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.39.7] - 2026-11-10

当前发布版本（build 166）。

**主表列宽与空态形态整改（用户评审后，保留原有列结构）。**

用户对主表评审定了三条边界：**不合并 APP/CLI/CONFIG、类型保留独立列、安装列保留**。
在此前提下做视觉与交互改进。

### 一、列宽：文本列定宽，省下的宽度还给表格外缘

此前名称 / 类型两列 `width: auto`，`table-layout: fixed` 下**平分全部剩余宽度**：
1280px 窗口实测名称 347px 装 44px 文字、类型 347px 装 52px 文字——两列吃掉 54% 宽度
却只放 96px 内容。

现在定宽 **名称 220px / 类型 150px**，省下约 370px 变成表格外缘留白。

> **反转了一条旧判据**：`test_text_columns_have_no_fixed_width` 原写「文本列不得设 px
> 定宽」。它的初衷是防紧列被平分，但弹性列的代价更大。改成
> `test_text_columns_are_bounded`：**文本列必须有明确上限（≤ 300px）**，而不是「不设宽」。

### 二、0 值计数用虚线

`.al-metric.dim`（虚线 + 透明底 + faint 色）。此前 0 与 1 都是实线圆环、只差底色调亮
一点，用户得逐行读数字才知道有没有。

### 三、约束列统一 `N/M`

- 「未配置」→ `0/1`（同一列保持数字形态，横向扫视有节奏）
- 「无约定」/ MCP「不支持」→ `.tag.tag-none` 占位（虚线边框，表「没有」而非「未加载」）

> 占位符用的是**中点 `·`**，不是破折号：本项目有一条硬规则「可见字符串里不许出现
> em/en-dash」（`test_no_em_dash_in_visible_strings`）。最初写的 `—` 被门禁拦下。

### 四、整行可点

`tr[data-row-open]` + `tabindex="0"` + `role="button"`，含键盘 Enter / Space。
此前只能瞄准右上角 64px 的「详情」按钮。

「详情」按钮**保留**：`.al-detail` 被 `test_all_panel_buttons_reachable` 等门禁引用，
且键盘用户需要显式的可聚焦目标；两条路径并存不冲突。点行内按钮（计数徽标 / 约束 /
MCP）不触发行跳转（`e.target.closest("button, .kebab")` 守卫）。

### 测试

- 新增 `ListRowAffordanceTest`（3 项）：整行可点 + 键盘、0 值虚线、空态占位共用。
- **反向验证 3 条**：去掉整行可点、0 值改回实线、空态改回实线，各自让断言失败。
- 全量 **1694 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 新增 §2.3d-2；`docs/DESIGN.html` 同步。

## [v0.39.6] - 2026-11-10

当前发布版本（build 165）。

**主表状态列全部可点开明细。**

用户：「后面红色框的几个按钮也需要和绿色框一样是完全可点击的，可以展示出它们
具体的内容」。

### 根因

主表里 APP / CLI / CONFIG 一直是 `<button>`，而**技能目录 / 安装是静态 `<span>`、
约束 / MCP 是静态 `<span class="tag">`**——同一行一半能点一半不能，用户会以为
这几列坏了。

### 改动

| 列 | 元素 | 点击行为 |
|---|---|---|
| 安装 | `button.al-ico` | 列出安装证据（APP + CLI + CONFIG 并集），解答「为什么算已安装」 |
| 技能目录 | `button.al-ico` | 列出技能目录（未安装时标注「注册表声明位置」） |
| 约束（单路径） | `button.tag.tag-btn` | 直接打开只读预览 |
| 约束（多路径） | `button.tag.tag-btn` | 先列出路径，点一条再进预览 |
| MCP（有端点） | `button.tag.tag-btn` | 列出端点 key |

**可点必须有可点的手感**：`button.al-ico` 与 `.tag-btn` 加了 hover（accent 边框 +
3px 光晕）与 `:focus-visible`（焦点环）。静态 span 和按钮长得一样，没有 hover
反馈用户根本不知道能点。

`MCP 0` / `不支持` 保持中性 `span.tag`——是空态、没有可展示的内容，不该假装能点。

### 实现要点

- `togglePathPop(btnEl, kindOverride)` 新增 `install` / `skills` / `rules` 三种 kind；
  `rules` 走独立分支（列路径 + 直接绑 `data-action="view-rules"`）。
- 多路径约束用 `data-action="list-rules"`（而不是裸 `data-popkind`）：全局委托只认
  带 `data-action` 的按钮，否则点击被丢弃（`delegation_contract` 抓到的）。
- `.tag-btn` 圆角用 `var(--r-pill)` 而不是 `inherit`——形状一致性锁要求所有圆角
  来自 `--r-*` 档位（`test_no_off_scale_radius_values` 抓到的）。

### 测试

- 新增 `ListStatusCellsClickableTest`（3 项）：四列可点、`.tag-btn` 三态、
  hover/focus 样式存在。
- **反向验证 2 条**：安装列 / 技能目录列改回静态 span，断言各自失败。
- 全量 **1691 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 新增 §2.3d-1；`docs/DESIGN.html` 同步。

## [v0.39.5] - 2026-11-10

当前发布版本（build 164）。

**对话框统一三段式骨架：操作按钮永远可见。**

用户：「请调整并统一一下所有关于对话框的 UI 规范，让『保存』『取消』这些操作按钮
永远是显示的，滚动部分不应该包括操作按钮」。

### 根因

`.modal` 是 `max-height: 92vh; overflow-y: auto`——**整个弹框一起滚**，底部
`.form-actions` 会跟着内容滚出视口。内容一多（APP/CLI/CONFIG/约束/目录设置五组），
按钮就看不见了。

### 修复

```
┌ .modal.modal-form ─────────────────────────────┐
│ .form-head      标题 + 副标题        flex:0 0  │ ← 固定
│ ─────────────────────────────────────────────  │
│ .form-body      各字段 / 说明 / 列表  flex:1 1 │ ← 唯一滚动区
│ ─────────────────────────────────────────────  │
│ .form-actions   取消 / 保存          flex:0 0  │ ← 固定
└────────────────────────────────────────────────┘
```

- **结构由 `mountModal` 自动重排**（`_normalizeFormModal`）：各 `open*` 函数照旧
  平铺写 `form-title` / 字段 / `form-actions`，挂载时自动包成三段。这样**新增弹框
  不会漏**，也不需要在十几个 `open*` 里各写一遍。
- 只作用于 `.modal-form`；`.ad-modal`（详情）与 `.cfm-card`（确认）保留各自骨架。
- `.form-body` 必须 `min-height: 0`：flex 子项默认 `min-height: auto` 会撑破容器，
  滚动直接失效（这是 flex 布局最常见的坑）。

### 测试

- 新增 `ModalSkeletonTest`（2 项）：`.form-body` 必须 `overflow-y: auto`、
  `.form-actions` 必须 `flex: 0 0 auto`、`mountModal` 必须调用重排。
- **反向验证**：去掉 `_normalizeFormModal(modal);` 调用，断言立刻失败。
- 全量 **1688 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 新增 §2.5b-1「表单弹框的三段式骨架」；`docs/DESIGN.html` 同步。

## [v0.39.4] - 2026-11-10

当前发布版本（build 163）。

**文件选择器定位到当前值所在目录。**

用户：「如果是有内容的选项，点击浏览之后，应该直接打开的默认路径就是对应的地方，
而不是一个统一的 documents」。

### 改动

- 新增 `_pickerStartDir(kind, current)`：从当前值推出起始目录
  - 目录字段（Skills / 扫描目录）→ 值本身
  - 文件字段（APP / CONFIG / 约束文件）→ 值的所在目录
  - `~` 前缀 → 先用 Rust 新命令 `home_dir` 展开（前端拿不到 HOME）
  - 命令名（不含 `/`）→ 推不出，不传 `defaultPath`（系统沿用上次位置）
- `pickPath(kind, current)` 把结果传给 `dialog.open({ defaultPath })`。
- Rust 侧新增 `home_dir` 命令（`HOME` / `USERPROFILE` 回落）并注册到
  `invoke_handler`。

### 效果

| 字段 | 当前值 | 选择器打开位置 |
|---|---|---|
| APP BUNDLE | `/Applications/Cursor.app` | `/Applications` |
| CONFIG | `~/.cursor/mcp.json` | `~/.cursor` |
| 约束文件 | `~/.claude/CLAUDE.md` | `~/.claude` |
| Skills 路径 | `~/.cursor/skills` | `~/.cursor/skills` |
| CLI 命令 | `cursor` | 不指定（系统上次位置） |

### 测试

- 新增断言：`_pickerStartDir` 存在、必须传 `defaultPath`、`~` 必须用
  `home_dir` 展开；**反向验证**：把 `pickPath` 签名改回单参数，断言失败。
- 全量 **1686 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.39.3] - 2026-11-10

当前发布版本（build 162）。

**CLI 命令行补「浏览」+ 编辑弹框整体整理。**

用户：「CLI 的命令也是需要的。请你对整个编辑页面进行优化，在满足 UI 规范的前提下
增加设计感」。

### 一、CLI 命令也能「浏览」

`renderPathFields("cli", ..., "exec")`——点「浏览」选可执行文件，自动取 **basename**
填入（`cursor` 而不是 `/usr/local/bin/cursor`）。理由：`detect_installation` 用
`shutil.which` 查 PATH，塞完整路径会让「命令是否存在」的判定与用户预期不一致。

### 二、编辑弹框整理

| 改动 | 之前 | 现在 |
|---|---|---|
| 空字段 | 只剩一个「+ 添加路径」，整块像漏了字段 | **空数组也渲染一行空输入** |
| 字段说明 | 无（解释塞在 placeholder 里，一输入就消失） | 每组一句 `.agent-settings-hint` |
| 「+ 添加路径」 | 与「浏览/×」同款的 ghost 按钮 | 轻量文字按钮 `.path-field-add`，不与操作按钮抢视觉 |
| 约束文件区块 | 无值时空着 | 空行 + 说明「留空则回落到内置默认值」 |

### 设计取舍

这是产品表单弹框，不是 landing page——没有加渐变、玻璃、动画。设计感来自
**分组节奏**（标题 → 说明 → 输入行 → 轻量添加）和**对齐**：每组同构，
浏览/删除按钮固定在右侧同一列。taste-skill 的「Motion must be motivated」
在这里的结论是：表单不需要动效。

### 测试

- 新增断言：CLI 行传 `exec`、`agent-settings-hint` 存在、`path-field-add` 存在、
  空数组渲染空行；**反向验证**：去掉 CLI 的 `exec` 参数，断言立刻失败。
- 全量 **1686 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.39.2] - 2026-11-10

当前发布版本（build 161）。

**路径字段加「浏览」按钮，可用系统文件选择器选路径。**

用户要求：「在编辑的对话框中，需要增加类似浏览的按钮，可以通过 GUI 去选择电脑上的
文件而不是只能通过输入路径的方式」。

### 改动

- 新增 `pickPath(kind)`：调 Tauri dialog 插件的
  `window.__TAURI__.dialog.open({ directory })`——文件字段 `false`、目录字段
  （Skills 目录 / 默认扫描目录）`true`。
- 客户端编辑弹框（`openAgentSettings`）里**所有路径字段**都带「浏览」：
  APP BUNDLE / CONFIG / 约束文件（多值行，含「+ 添加路径」新加的行）、
  Skills 路径 / MCP 配置文件 / 默认扫描目录（单值字段）。
- CLI 命令名不给「浏览」——它是可执行名不是路径。
- 浏览器预览态没有 `__TAURI__`：`pickPath` 返回 null，输入框保持原值，不报错。

### 测试

- 新增断言：`pickPath` 存在、必须走 `__TAURI__.dialog`（不是 `input[type=file]`）、
  多值行有 `pf-browse`、单值字段有 `as-skills-pick`。
- **反向验证**：把 `pickPath` 改名，断言立刻失败。
- 全量 **1686 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.39.1] - 2026-11-10

当前发布版本（build 160）。

**客户端编辑弹框补「约束文件」字段 + 注册表补 Claude Desktop / Roo Code 规则路径。**

用户截图指出：`VS Code · 设置` 弹框里只有 APP BUNDLE / CLI / CONFIG / 目录设置，
**没有约束文件（RULES）**——规则路径改不了。

### 一、编辑弹框补「约束文件」

`openAgentSettings()`（「XX · 设置」弹框）新增「约束文件」区块，与其它路径字段同构
（多值、可增删行）。保存走 `--set-tool-path NAME rules_paths`（路径覆盖层），
清空 = 清除覆盖、回落内置默认值。

> 为什么不用 `--update-client`：它写的是 `data/discovered_tools.yaml`，
> 而注册表的 `rules_paths` 是另一份数据。两条通道混用会让「改了没生效」变成常态。

### 二、注册表补全

| 变更 | 内容 |
|---|---|
| Roo Code | 补 `rules_paths = ~/.roo/rules`（全局规则目录） |
| Claude Desktop | **新增条目**（39 条）：`/Applications/Claude.app` + MCP 配置 `~/Library/Application Support/Claude/claude_desktop_config.json`。与 Claude Code 是两套（后者用 `~/.claude.json`），桌面端无用户级规则文件，不声明 `rules_paths` |

约束文件覆盖：**13 个客户端 / 14 个路径**（新增 Roo Code）。

### 三、调研结论（2026-11）

- **TRAE**：官网现为 TraeCode（编码 IDE）+ TraeWork（工作台）两条产品线，**不是**
  合并到豆包；TRAE 补 `traecode` 别名，TraeWork 摘掉共用的 `traecode`。
- **千问工作**：对应 `QwenWork`（已在册），补「千问工作」别名。
- **豆包工作**：给「豆包」补别名。
- **通义灵码**：官网仍在（lingma.aliyun.com），保留。
- **无用户级规则文件的**（Cursor / Aider / JetBrains / Claude Desktop）刻意不登记，
  理由写进 `DESIGN.md` §2.3c-2。

### 测试

- PRD 的注册表条数断言 38 → 39（新增 Claude Desktop），`test_registry_count_is_39_not_22`。
- 全量 **1686 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.39.0] - 2026-11-10

**路径修正功能（此前确实缺失）+ Agent 别名按官网现状更新。**

用户两点：「路径识别不正确时我该怎么修改？这个功能是否缺失了？」
「有些 Agent 已被更新产品替代，请按厂商官网整理」。

### 一、路径覆盖（新功能）

内置注册表的 APP / CLI / CONFIG / SKILLS / MCP / RULES 都是**厂商默认值**，
此前**没有任何修正入口**——用户本机装到别处时只能看着错误的路径。确认缺失，补上：

| 层 | 内容 |
|---|---|
| 数据 | `data/local_overrides.yaml` 的 `tool_paths` 段（gitignore，不进版本库） |
| 合并 | `register_mainstream_tools()` 内 `apply_overrides(copy.deepcopy(...))` |
| CLI | `--set-tool-path TOOL FIELD VALUE` / `--reset-tool-path TOOL [FIELD]` / `--list-tool-paths` |
| GUI | 详情弹框「编辑路径」按钮 → 六个字段的 textarea（每行一个值，清空 = 恢复默认） |

可覆盖字段：`app_bundles`、`commands`、`config_paths`、`skills_path`、
`mcp_config_path`、`rules_paths`。**只覆盖路径**，工具名 / 类型 / 别名不动——
否则覆盖层会变成第二个注册表。

### 二、Agent 别名按官网现状更新

查了官网（2026-11）：

- **TRAE**：官网现在是 **TraeCode**（编码 IDE）+ **TraeWork**（工作台）两条产品线，
  不是「合并到豆包」。给 TRAE 补 `traecode` 别名；同时把 TraeWork 上原本共用的
  `traecode` 别名摘掉——两条产品线不该共用一个别名。
- **千问工作**：`QwenWork` 已有「千问办公」别名，补「千问工作」。
- **豆包工作**：给「豆包」补「豆包工作」别名。
- **通义灵码**：官网仍在（lingma.aliyun.com，Lingma IDE 公测），保留。

### 测试

- 新增 `tests/test_tool_path_overrides.py`（12 项）：写入/生效/重置闭环、多值换行、
  `mcp_config_path` 标量、未知字段拒绝、坏 YAML 不炸、保留其它键、注册表接线、
  GUI 入口、Rust 白名单、CLI 可调用。
- **反向验证 2 条**：注册表不接覆盖层、GUI 去掉编辑入口，各自让断言失败
  （第一条断言先写成子串 `openToolPathEditor`，改名成 `openToolPathEditorX` 仍通过，
  已改成精确匹配函数定义）。
- 全量 **1686 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

### 文档

`docs/DESIGN.md` 新增 §2.3c-2b「路径覆盖」；`docs/DESIGN.html` 同步（含导航）。

## [v0.38.9] - 2026-11-10

当前发布版本（build 158）。**约束文件覆盖补全 + 长路径缩写。**

用户两点：「这里仍然有很多显示不全的问题」「对于 rule 规则的文件，只要是 AI Agent
其实都应该是存在的，请深入调研」。

### 一、约束文件：9 客户端 / 10 路径 → 12 客户端 / 13 路径

查官方文档后补了 3 个（都只认文档明确写出的用户级路径）：

| 客户端 | 新增路径 | 官方依据 |
|---|---|---|
| VS Code | `~/.copilot/copilot-instructions.md` | VS Code 文档「User instructions」 |
| Zed | `~/.config/zed/AGENTS.md` | Zed「Personal Instructions」 |
| Goose | `~/.config/goose/.goosehints` | goose「Global hints file」 |

**刻意没登记的三个**（避免猜一个看起来对、实际不生效的路径）：

- **Cursor**：User Rules 存在设置/数据库里，官方文档没给文件路径；项目级
  `.cursor/rules/*.mdc` 不是用户级。
- **Aider**：`CONVENTIONS.md` 是项目级，用户级要靠 `.aider.conf.yml` 的 `read:`
  自己指路，没有官方默认位置。
- **JetBrains AI Assistant**：官方帮助文档没有用户级规则文件路径。

### 二、长路径缩写

`~/Library/Application Support/Trae/User/mcp.json` 这类路径在 480px 卡片里会被
ellipsis 截断。新增 `_shortPath()`，只缩写**带 `…` 的固定长前缀**：

```
~/Library/Application Support/Trae/User/mcp.json → ~/Library/…/Trae/User/mcp.json
~/AppData/Roaming/Block/goose/config.yaml        → ~/AppData/…/Block/goose/config.yaml
```

完整路径仍在 `title`（悬停）与预览弹框里。**没有**做 `/Applications/` 这类
「看起来更短但改变字面含义」的替换——那会让用户以为真实路径就是缩写后的样子。

### 测试

- 新增断言：`_shortPath` 存在、`~/Library/…/` 规则、路径胶囊与 RULES 行都必须
  经过 `_shortPath`；**反向验证**：让路径胶囊绕过缩写，断言立刻失败。
- 全量 **1674 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.8] - 2026-11-09

当前发布版本（build 157）。**路径行改为基线对齐（标签与值的文字不再错位）。**

用户截图红框：「左边的字比右边的字高一点」——同一行里 `CLI` / `CONFIG` 标签比
右侧的 `cursor` / `~/.cursor/mcp.json` 高出一截。

### 根因

标签与值的**行盒高度不同**：

| 元素 | 字号 | line-height | 额外 |
|---|---|---|---|
| `.ac-path-label` | 11px | 1.9（20.9px） | 无 |
| `.ac-path-val` | 12px | 1.5（18px） | 胶囊 padding 2px + border 1px（共 24px） |

`.ac-path-row` 用 `align-items: start`，两列**顶对齐**，于是标签文字中心比值的
文字中心高约 1.5px——在 2x 屏上就是 3px，肉眼可见。

### 修复

`.ac-path-row` 与 `.ac-meta-row`（SKILLS / MCP 同构）都改为 **`align-items: baseline`**。
实测（浏览器 `Range.getBoundingClientRect()`）：

| 指标 | 改前 | 改后 |
|---|---|---|
| 标签底 / 值底（基线）差 | **1.55px** | **0.00px** |
| 标签顶 / 值顶差 | 0 | 1px（字号 11 vs 12 的正常差异） |

基线对齐后两边文字落在同一条基线上；顶部 1px 差是字号本身的差异，不是错位。

### 测试

- 新增 `RowBaselineAlignmentTest`（2 项）：路径行、能力摘要行都必须 `baseline`。
- **反向验证**：把路径行改回 `align-items: start`，断言立刻失败。
- 全量 **1674 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.7] - 2026-11-09

当前发布版本（build 156）。**标题到首行的间隙与行间隙对齐。**

用户反馈「好像还是明显偏下」。上一版把「标题中心到首行中心」调到 32.8px
（行间距 30px），差值只剩 2.8px，但**真正的观感来自「间隙」而不是「中心距」**：

| 指标 | 改前 | 改后 |
|---|---|---|
| 标题底 → 首行顶（间隙） | **12.8px** | **8.8px** |
| 行间隙（行到行） | 6px | 6px |
| 间隙差 | 6.8px | 2.8px |
| 标题距卡片顶 | 15.8px | 15.8px（左右 16px） |

标题下方空了 12.8px、而内容行之间只空 6px，内容整体就像被推下去一截。
把路径区顶部内边从 10px 收到 6px（`--sp-2`）后，两处间隙同档。

### 测试

- `CardTitleAlignmentTest` 的断言同步改为 `var(--sp-2) var(--sp-7) var(--sp-5)`；
  **反向验证**：改回 10px 会让断言失败。
- 全量 **1672 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.6] - 2026-11-09

当前发布版本（build 155）。**卡片标题与内容行的垂直节奏修正。**

用户反馈：「请检查标题和内容是否对齐，我感觉好像都没有完全对齐，有往下偏的趋势」。

### 实测数据（620px 宽卡片，用浏览器量 boundingRect）

| 项目 | 改前 | 改后 |
|---|---|---|
| 标题左边缘 | 17px | 17px |
| 标签列左边缘 | 17px | 17px |
| 标题中心 → 首行内容中心 | **36.8px** | **32.8px** |
| 行间距（行到行中心距） | 30px | 30px |
| 差值（越大越像「往下偏」） | **6.8px** | **2.8px** |

左对齐本来是对的（17 = 17），问题在**垂直**：标题到首行的间距比行间距多 6.8px，
所以内容看起来整体下沉。

### 修复

- `.ac-head` 内边由 `15px 16px 2px` 改为 **`12px 16px 0`**：顶部与左右视觉起点一致，
  底部不留内边（交给路径区控制）；
- `.ac-paths` 内边由 `12px 16px` 改为 **`10px 16px 12px`**：标题到首行 10px，
  中心距随之接近行间距。

### 测试

- 新增 `CardTitleAlignmentTest`（2 项）：左右内边同档、标题与路径区的内边档位。
- **反向验证 2 条**：把标题内边改回旧值、路径区顶部改回 12px，各自让断言失败。
- 全量 **1672 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.5] - 2026-11-09

当前发布版本（build 154）。**修复约束预览弹框内容贴边（内边距被清零）。**

用户截图：「这个弹框的样式还是有问题，边框直接在边上，没有间隔」。

### 根因

弹框用了 `class="modal modal-form ad-modal"`。`.ad-modal`（宽详情弹框）自带
**内边距清零 + 溢出隐藏**，而它定义在 `.modal-form`（28px 内边距）之后——
两者特异性相同，**后定义的胜出**，于是 28px 内边距被吃掉，内容区直接贴到弹框边缘。

上一版只调了间距与边框，没意识到根因在类复用上。

### 修复

- 不再借用 `.ad-modal`：改为 `modal modal-form rules-modal`；
- `.rules-modal` 自己声明宽度（`--modal-w: min(880px, 94vw)`，沿用宽详情弹框的上限）；
- 内边距回归 `.modal-form` 的 28px，标题 / 路径 / 内容区 / 底栏全部与弹框边缘留出间隔。

### 一个门禁细节

修复注释里原本写了「`padding:0 + overflow:hidden`」，被 `NoLiteralSpacingTest`
当成真实声明扫出来（该门禁会扫描全文件包括注释）。注释已改写为文字描述。

### 测试

全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.4] - 2026-11-09

当前发布版本（build 153）。**约束预览弹框的视觉收紧。**

用户截图指出弹框「太丑」。三处具体问题：

1. **状态 / 规模两行 kv 间距过大**：`.rows` 在弹框里是 `gap: --gap-4`，两行之间
   空了近 40px，读起来像两组无关信息；
2. **未配置态用虚线框**：那是「占位符」语言（`.empty` 的样式），放在弹框里
   像是还没做完；
3. **底部没有分隔线**：左侧说明与右侧按钮浮在同一行，缺少收口。

### 改动

- 状态与规模**并排一行**（`.rules-meta` / `.rules-meta-k` / `.rules-meta-v`）：
  标签 mono 大写 faint、值 `--fs-sm`，两者基线对齐，间距 `--gap-7`。
- 未配置态改用 `.rules-missing`（**实线**边框的说明块，`--sp-9` 内边距）。
- `.form-actions` 加 `border-top` + `padding-top`，把「只读预览说明 + 关闭」
  收成弹框的独立底栏。
- 弹框加 `.rules-modal` 修饰类，间距规则全部限定在它下面，不影响其它弹框。

### 文档

`docs/DESIGN.md` §2.3c-2 登记 `.rules-modal` / `.rules-meta` / `.rules-missing`
及三处修正的原因；`docs/DESIGN.html` 同步。

### 测试

全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过
（`ComponentRegistrationTest` 确认 `.rules-modal` 已登记）。

## [v0.38.3] - 2026-11-09

当前发布版本（build 152）。**约束行并入 Agent 配置区，改为只读预览。**

用户四点反馈：「约束好像应该是 Agent 本身的内容，不应该和 skill 和 MCP 放在一起，
应该和 Agent 本身的配置在一起」「没有和整体的展示对齐，而且好像字体也不一样」
「这些如果配置不对，都应该是可以修改的，但是目前好像都无法进行修改」
「展示部分只需要只读就好了，在这里不需要提供直接修改文件的功能；点击之后的
展示框仍然没有边框，没有相应的间隔」。

### 1. 位置：约束行并入路径区

从能力摘要区（SKILLS / MCP）移到**路径区**（APP / CLI / CONFIG 之后），标签
`RULES`。约束是「Agent 本身配了什么」，与技能挂载、MCP 端点不是同一层语义。

### 2. 对齐与字体：复用 `.ac-path-val` 胶囊

之前约束行用的是纯文本 + 自定义样式，与上面三行的**胶囊路径**（mono、`--fs-xs`、
`panel-2` 底、圆角）不一致——所以既没对齐、字体也不一样。现在每枚路径都是
`.ac-path-val`（同款胶囊），标签列同为 58px，徽标走 `.ac-path-badges` 贴右。

### 3. 交互：去掉按钮，点击胶囊打开只读预览

- 不再有独立「查看」按钮，点击路径胶囊即打开预览；
- **预览是只读的**：没有 textarea、没有保存按钮（用户定案「展示部分只需要只读
  就好了，在这里不需要提供直接修改文件的功能」）；
- 预览区 `.rules-preview`：**有边框、有内边距、可滚动**（`max-height: 55vh`），
  不再是之前那个贴边的裸文本框（用户：「展示框仍然没有边框，没有相应的间隔」）。

### 4. 修改入口

约束文件内容本身不再提供内联编辑（只读预览 + 路径可复制）。需要改内容时用
编辑器打开该路径——预览弹框底部明确写出这一句，避免用户找不到入口。
（Agent 的 APP / CLI / CONFIG 路径仍可在「详情」弹框里查看。）

### 文档

`docs/DESIGN.md` §2.3c-2 重写为「并入路径区 + 只读预览」，并删掉旧的
`.rules-editor` / `--write-rules` 描述；`docs/DESIGN.html` 同步。

### 测试

- 断言更新：`data-k="rules"`（在路径区）、`rules-preview`（只读预览）、
  `assertNotIn("rules-editor")`（不再有编辑器）、`assertNotIn("--write-rules")`
  （GUI 不再调用写接口）。
- **反向验证 2 条**：把约束行移出路径区、加回编辑器 textarea，各自让断言失败。
- 全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.2] - 2026-11-09

当前发布版本（build 151）。**约束行的操作语言与上面几行统一：去掉「查看」按钮，
路径本身可点。**

用户指出：「这里的整体交互逻辑和 UI 规范都应该统一：点击上面好像没有按钮，
那么这个『查看』也不应该有按钮，应该点击文字就可以展示。目前看也没有完全对齐。」

### 改动

- **约束行去掉「查看」按钮**：SKILLS / MCP 行都是纯文本，单独一行长出按钮会破坏
  同一张卡片内的操作语言。改为**路径文字可点**（`.rules-path`：无边框、
  `cursor: pointer`、hover 才出现下划线、`:focus-visible` 有焦点环），点击直接
  打开编辑弹框。
- **顺序与对齐**：路径在前（值区首个子元素自适应）、状态徽标贴右，与
  `MCP  ~/.codex/config.toml  2 个端点` 完全同构。之前徽标在最左，它的内边距
  让文字起点比上面几行偏右 7px。
- **多路径**：用 `.rules-sep`（`·`）分隔，每个路径各自可点（WorkBuddy 两个路径
  两个可点文字），不再出现「查看 1 / 查看 2」两个按钮。

### 文档

`docs/DESIGN.md` §2.3c-2 重写该条规则并记录用户定案原话；`docs/DESIGN.html` 同步。

### 测试

- 断言改为精确类名 `class="rules-path"` + `assertNotIn("rules-view-btn")`；
  **反向验证**：去掉可点路径、加回查看按钮，各自让断言失败
  （第一版只查子串 `rules-path`，改名成 `rules-path-REMOVED` 仍能通过，已修正）。
- 全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.1] - 2026-11-09

当前发布版本（build 150）。**约束行与编辑弹框的视觉修正。**

用户反馈四点：「样式需要和上面一样，不要单独出现一种新的样式」「如果有多个就
显示多个，左右尽可能保持一致的大小」「展示的这个页面也需要和 UI 规范保持一致，
目前太丑了」。

### 约束行（`.ac-rules-v`）

- **徽标不再被拉宽**：卡片值区的规则是「首个子元素 `flex: 1 1 auto`」（为
  Skills / MCP 的自适应文本设计），但约束行的首个子元素是**状态徽标**，被拉伸后
  与旁边的按钮比例失衡。改为 `.ac-rules-v`（inline-flex）：徽标定宽、按钮
  `flex: 0 0 auto`。
- **多路径按钮等宽并排**：`.rules-view-btn { min-width: 64px }`，WorkBuddy 的
  「查看 1 / 查看 2」不再一大一小，换行时也保持同宽。
- 行结构与 Skills / MCP 完全一致（`.ac-meta-row` 的 `k` / `v`），没有新造行样式。

### 编辑弹框

从「标题 + 路径 + 裸文本框」重排为五段层次：

```
WorkBuddy · 约束文件          ← form-title
~/.workbuddy/USER.md          ← form-sub（mono，可复制）
状态   [已配置]                ← kv 行（与卡片同一套）
规模   42 行 · 1037 B
文件内容                       ← form-field label
[ 等宽编辑器，50vh，可纵向拉伸 ]
保存前自动备份…    [取消] [保存]  ← form-actions（左说明右按钮）
```

- 状态与规模复用卡片的 `kv` 行语言，不引入新组件；
- 底部左侧常驻备份说明，右侧两个按钮，与 §2.5b 的 `.modal-form .form-actions` 一致。

### 文档

`docs/DESIGN.md` §2.3c-2 登记 `.ac-rules-v` 与 `.rules-view-btn`（新增语义类必须
登记，`ComponentRegistrationTest` 强制），`docs/DESIGN.html` 同步。

### 测试

全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.38.0] - 2026-11-09

当前发布版本（build 149）。**约束文件合并进 Agent 卡片/列表，不再单独开卡。**

用户截图指出：「这个约束文件也应该同步到上面的卡片或者列表中，而不是一个
单独的展示。」上一版把它做成了设置页里一张独立卡片，与「IDE / Agent 默认路径」
卡片分家——同一批客户端被拆成两处，读起来仍然是「又一个列表」。

### 改动

- **设置页 Agent 卡片**：约束作为**第三行能力摘要**接在 Skills / MCP 之后
  （`.ac-meta-row` 的 `k=约束`），内容是 `N/M` 徽标 + 一个或多个「查看」按钮
  （WorkBuddy 有两个路径就两个按钮，`title` 给完整路径）。
- **设置页列表视图**：约束跟 Skills/MCP 一起放进「能力摘要」列。
- **无官方约定的客户端不出现这一行**——不是显示「无约定」占位。
- **移除独立卡片** `#settings-rules-card` 与 `renderSettingsRules()`；
  `loadRules()` 改为刷新设置页的 Agent 表格。
- 主表的「约束」列保持不变（那是总览，只给状态）。

### 过程中修掉的三个问题

1. **删除独立卡片时留下 26 行残码**：`renderSettingsRules` 函数体没删干净，
   顶层出现 `return` → `Illegal return statement`，整个脚本不执行、所有按钮无反应。
   被 `test_braces_parens_brackets_balanced` 与 `test_all_panel_buttons_reachable` 抓到。
2. **反向验证发现断言不够精确**：断言 `assertIn("_agentRulesSummary", ...)` 时，
   把函数改名成 `_agentRulesSummaryXxx` 仍会命中（子串匹配）。改为断言
   `function _agentRulesSummary(t) {` + 两处调用计数 ≥ 2，再反向验证才真正失败。
3. **`loadRules()` 的错误分支仍引用已删除的函数**——已改为只记录 `RULES_ERROR`，
   由两处消费方各自渲染空态。
4. **设置页没触发加载**：用户直接进「设置 → IDE / Agent」时从没走过主页的
   `switchPage("agents")`，`RULES_DATA` 为空 → 卡片里静默不出现「约束」行。
   已在 `loadManagement()` 初始化时拉一次（与 `loadDshNavCount()` 同模式，不 await），
   并在 `renderAgentsTable()` 里保留按需兜底（有 `RULES_ERROR` 时不重试）。

### 文档

`docs/DESIGN.md` §2.3c-2 改为「主表状态列 + Agent 卡片/列表内联」，
`docs/DESIGN.html` 同步。

### 测试

全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.37.9] - 2026-11-09

当前发布版本（build 148）。**约束文件改为「主表状态列 + 设置页逐行配置」。**

用户截图指出：「这个约束文件应该合并到上面的列表中，而不是单独展示。然后下面
每个 Agent 的具体配置，应该在设置里单独有一行。」原实现是一块独立面板，
与主表分家，且路径与编辑入口挤在同一张表里。

### 改动

- **IDE / Agent 主表加「约束」列**（第 8 列，技能目录与 MCP 之间）：只给状态，
  与安装/技能目录/MCP 同一表达方式——`N/M` 徽标，`title` 列出各路径；
  全配置 `tag ok`、部分 `tag warn`、都没有「未配置」、无约定「无约定」。
- **设置页 IDE / Agent tab 加「约束文件」卡片**（`#settings-rules-card`）：
  **每个 Agent 一行**——客户端名 + 路径（`code.mono`）+ 状态 + 规模（行数/文件数）
  + 「查看」按钮；WorkBuddy 两个路径就出两行。
- **移除独立面板** `#rules-panel` 与它的渲染函数 `renderRules()`。
- **一次加载两处消费**：`--list-rules` 结果存 `RULES_DATA`，主表列与设置页行共用。

### 顺带修掉的两个真 bug

1. **`loadRules()` 依赖已删除的容器**：独立面板移除后它仍在找 `rules-body`，
   找不到就直接 return——数据永远加载不出来，两处都停在「加载中…」。
2. **`RULES_DATA` 声明在错误作用域**：声明留在被删函数的旧位置，而主表渲染在
   另一处引用；已移到全局状态区（与 `GIT_SOURCES` 同级）。主表渲染另加
   `typeof RULES_DATA` 防御——`renderHomeListView` 会被测试单独抽到 node 里执行。

### 文档

`docs/DESIGN.md` §2.3c-2 重写为「主表状态列 + 设置页逐行配置」两处职责，
`docs/DESIGN.html` 同步。

### 测试

- `tests/test_rules_files.py` 的 GUI 契约改为断言「主表有约束列 + 独立面板已移除
  + 设置页卡片存在」，并**反向验证**：去掉列、去掉卡片各自让断言失败。
- 列宽治理测试期望更新为 8 个紧列（`{3:56, 4:48, 5:48, 6:70, 7:82, 8:78, 9:78, 10:124}`），
  居中列扩到 3/7/8/9。
- 全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.37.8] - 2026-11-09

当前发布版本（build 147）。**约束文件路径按各客户端官方文档校正，补上 WorkBuddy。**

用户指出「WorkBuddy 应该也有配置，其他的请读取官网上标准的定义」。查证结果：

### 修正

| 客户端 | 修正前 | 修正后 | 依据 |
|---|---|---|---|
| **WorkBuddy** | 未登记 | `~/.workbuddy/SOUL.md` + `USER.md` | 本机实测的人格/用户规则体系 |
| **Cline** | `~/.clinerules` | `~/Documents/Cline/Rules`（目录） | 官方 Rules 文档「Global Rules Directory」：macOS 为 `~/Documents/Cline/Rules`，另搜 `~/.cline/rules` 与 `~/Cline/Rules`；`~/.clinerules` 是**项目级** |
| **Cursor** | `~/.cursor/rules` | **移除** | 官方 Rules 文档：用户规则存在 Cursor 设置里（不落盘），`~/.cursor/rules` 是**项目级** `.mdc` 目录；登记成用户级只会显示一个永远「未配置」的假路径 |

### 官方确认（未改动的）

- **OpenCode**：`~/.config/opencode/AGENTS.md`（官方 Rules 文档「Global」段明确）；项目级 `AGENTS.md`，并兼容 `~/.claude/CLAUDE.md`
- **Cline**：还识别 `AGENTS.md` / `~/.agents/AGENTS.md`（跨工具标准）、`.cursorrules`、`.windsurfrules`
- **Cursor**：项目级 `.cursor/rules/*.mdc`（必须 `.mdc` 扩展名，`.md` 被忽略）+ 支持 `AGENTS.md`
- **Aider**：`CONVENTIONS.md`（项目级，用 `read:` 加载）

### 统计口径

面板底部文案改为「N 个客户端有约定（M 个路径），K 个已配置」——WorkBuddy 有 2 个路径，
原来写成「N 个客户端，K/M 个已配置」会让人以为客户端数与路径数是一回事。

### 本机实测

```
约束文件：9 个客户端有约定（10 个路径），4 个已配置
  ✓ Codex              ~/.codex/AGENTS.md      60 行
  ✓ WorkBuddy          ~/.workbuddy/SOUL.md    66 行
  ✓ WorkBuddy          ~/.workbuddy/USER.md    42 行
  ✓ DeepSeek Harness   ~/.dsh/AGENTS.md        41 行
  · 其余 6 个          未配置
```

### 文档

`core/mainstream_registry_data.py` 顶部新增路径依据表（客户端 / 路径 / 依据），
`docs/DESIGN.md` §2.3c-2 说明「为什么 Cursor 不登记」。

### 测试

全量 **1670 项通过、2 项既有跳过**；`ci_parity.sh` 全部门禁通过。

## [v0.37.7] - 2026-11-09

当前发布版本（build 146）。**新增「约束文件」管理：按每个 Agent 的主要规则文件
统一查看与编辑。**

用户提出：「根据每个应用不同的主要约束文件，对每个 Agent 的约束进行管理」。
此前本工具只管 skills / MCP / DSH 插件，**完全不管各客户端的规则文件**——
Claude Code 的 `CLAUDE.md`、Codex 的 `AGENTS.md`、Gemini CLI 的 `GEMINI.md`、
Cursor 的 `.cursor/rules/` 目录……要确认「这台机器上每个 Agent 的约束到底配了
什么」，只能逐个翻目录。

### 新增

- **注册表 `rules_paths`**：9 个有官方约定的客户端登记了约束文件路径
  （Claude Code / Codex / Gemini CLI / OpenCode / DeepSeek Harness / Cursor /
  TRAE / Cline / Windsurf）。**没声明的客户端不猜路径**——猜一个路径去读，猜错
  会让用户以为「这里就是它的配置」，比不显示更糟。
- **`core/rules_files.py`**：
  - `discover()`：文件看行数/字节/mtime，目录看文件数，缺失标 `exists=False`；
  - `read_rules()`：只读预览，超过 512 KiB 截断并标 `truncated`；
  - `write_rules()`：备份 → 原子写 → 回读校验；目录形态拒绝整体写入。
- **CLI**：`--list-rules`（只读）、`--read-rules <client>`、
  `--write-rules <client> --rules-content <文本>`（或 `--rules-file`）。
- **GUI**：IDE / Agent 页新增「约束文件」面板（`#rules-panel`）——表格列
  「客户端 / 约束文件 / 状态 / 规模 / 查看」，点「查看」弹编辑框（等宽、50vh、
  可纵向拉伸），保存后自动刷新。

### 本机实测

```
约束文件：9 个客户端有约定，2/9 个已配置
  ✓ Codex              ~/.codex/AGENTS.md      60 行 · 2150 B
  ✓ DeepSeek Harness   ~/.dsh/AGENTS.md        41 行 · 5856 B
  · 其余 7 个          未配置
```

### 文档

`docs/DESIGN.md` §2.3c-2 + `docs/DESIGN.html` 同步登记面板：结构图、数据来源、
查看/编辑流程、目录形态与未配置态，以及「为什么放在 IDE / Agent 页而不是新开一页」。

### 测试

- 新增 `tests/test_rules_files.py`（15 项）：发现口径（文件/目录/缺失/未声明）、
  只认注册表路径、预览截断、写入备份与回读校验、目录拒绝、CLI 端到端、GUI 契约。
- **4 条反向验证有效**：去掉写入备份、去掉 GUI 面板、去掉 Rust 白名单、
  去掉目录拒绝，各自让对应断言失败。
- 全量 **1670 项通过、2 项既有跳过**。

## [v0.37.6] - 2026-11-09

当前发布版本（build 145）。**升级备份：内容去重 + 份数上限 + 清理入口。**

用户实测 `data/skill_backups/find-skills/` 攒了 **327 份**备份，其中 **326 份
字节完全一致**——升级每次都无条件复制一份，纯粹占盘。用户要求「备份前比对
内容、每技能保留上限、给一个清理入口」。

### 改动

- **备份前比对内容**（`backup_skill()`）：要备份的内容与最近一份备份指纹相同
  时返回 `skipped`，不再复制。指纹按「相对路径 + 文件字节」计算，**与 mtime
  无关**（`copytree` 之后备份目录里的文件时间会变，内容其实一样）。
- **份数上限**：`DEFAULT_BACKUP_KEEP = 10`。备份成功后顺手淘汰超出上限的旧
  版本（同内容更早的也一并清掉），保留最近 10 份**不同内容**。
- **清理入口**：
  - `--prune-skill-backups`（写，支持 `--dry-run` / `--format json`）；
  - `--skill-backup-stats`（只读：技能数 / 份数 / 占用 / 可清理份数）；
  - 设置页 Skill tab 新增「技能备份」卡片（`#skill-backups-card`）：统计行 +
    「清理备份」按钮，点击先 dry-run 再确认，结果弹框给条数与释放空间。
- **契约变更**：`backup_skill()` 由返回 `Optional[str]` 改为结构体
  `{"status": "ok"|"skipped"|"failed", "path": ..., "reason": ...}`。
  `execute_plan` 与既有测试同步更新（`skipped` 时沿用已有备份路径，仍可回滚）。

### 本次实测清理结果

- 技能备份：355 份 / 36M → **20 份 / 33M**（删 335 份重复）
- 应用备份（`~/.skill-mcp-studio-backups/`）：43 个 / 475M → **3 个 / 34M**
  （保留最近三个版本）
- 合计释放约 **443 MB**

### 文档

`docs/DESIGN.md` §2.10 新增「技能备份卡片」：结构、数据来源、交互（先 dry-run
再确认）、清理规则，以及「为什么放设置页而不是 Skills 页」。

### 测试

- 新增 `tests/test_skill_backup_prune.py`（18 项）：指纹与 mtime 无关、同内容
  `skipped`、内容变化产生新备份、超上限淘汰最旧、去重保留最新、dry-run 不删、
  统计口径、CLI 端到端、GUI 契约（卡片 / 按钮 / 命令 / Rust 白名单 / 规范登记）。
- **4 条反向验证有效**：去掉内容去重、去掉上限淘汰、去掉 GUI 按钮、去掉 Rust
  白名单，各自让对应断言失败。
- 全量 **1655 项通过、2 项既有跳过**。

## [v0.37.5] - 2026-11-09

当前发布版本（build 144）。**修复「升级后仍显示可升级」的永久误报。**

用户截图问：「这个 skill 我刚刚已经完成了更新，但是为什么我重新检查更新仍然是
有的？」查证结果比预期严重——**这个技能从来没被真正更新过**：

- 本地文件与统一库 git 提交都是 **2026-07-17**；
- lock 的 `updatedAt` 却停在 **2026-01-28**（安装时写入，之后从未变过）；
- 远端 `packages/playwright/src/mcp/terminal/SKILL.md` 最后提交 **2026-01-31**；
- `data/skill_backups/playwright-cli/` 里有 **10 份**升级前备份（10-23 到今天
  13:41），每份的 `SKILL.md` sha256 **完全相同**（`bdd272a7…`）。

### 根因

更新判定在「本地无版本号」时回退到时间比对，基准取的是 **lock 的
`updatedAt`**。而 lock 只在「经 npx 安装 / 升级」时写——用户用 git 同步统一库
或手工替换文件时它不会变。于是拿「1-28 vs 远端 1-31」判成 `outdated`，而本地
内容其实比远端新 5 个多月；npx 升级同样认为已是最新、什么都不改，形成
「备份 → 升级 → 内容没变」的死循环：**永远显示可升级，升级永远无效**。

### 修复

`core/skill_market._local_skill_time()`：本地时间改为按内容判定，回退链为

1. **统一库 git 里该技能路径的最后提交时间**（`git log -1 --format=%ct`，
   转 UTC ISO8601）；
2. `SKILL.md` 的 mtime；
3. 最后才回退 lock 的 `updatedAt` / `installedAt`（测试夹具与目录缺失时仍可用）。

取 `%ct` 而不是 `%cI`：后者带本地时区偏移，与远端 GitHub 的 `...Z` 直接做
字符串比较会在「同年同月、不同时区」时错位。

### 验证

修复后该技能由 `outdated` 变为 `current`，检查汇总从
`outdated: 1 / current: 173` 变为 **`outdated: 0 / current: 174`**。

### 测试

- 新增 `LocalSkillTimeTest`（4 项）：git 时间优先于 lock、无 git 时回退 mtime、
  目录缺失回退 lock、以及集成场景（lock 旧 / 内容新 / 远端更旧 → current）。
- 两条反向验证有效：退回「只用 lock」、去掉 git 优先级，各自让对应断言失败。
- 全量 **1637 项通过、2 项既有跳过**。

## [v0.37.4] - 2026-11-09

当前发布版本（build 143）。**修复 WorkBuddy 原生连接被误判为「客户端自带」。**

用户截图问「为什么 MCP 中多了一个 WorkBuddy 的已挂载」。查下来不是多了一个
客户端，也不是重复挂载：WorkBuddy 客户端的 `~/.workbuddy/mcp.json` 里有一个
server 条目，键名就叫 `WorkBuddy`，指向 `https://hermes-mcp.pd-h.top/mcp`
（统一端点 hermes-home）。这是 2026-11-06 原生 MCP 接入时的**有意设计**
（`docs/NATIVE-MCP-IDENTITY.md`：「连接键使用 WorkBuddy，从而保留其原生
Agent 名称」），把原来的 `hermes` 条目改名为 `WorkBuddy`。

### 根因

`core/mcp_entry_risk.is_high_risk_entry()` 的 R3 规则是「条目 key 归一化后
等于客户端名或其 alias → 疑似客户端自带」。WorkBuddy 的键名恰好等于客户端
名，于是被误判为 `high_risk`；而 MCP 页最后一列的过滤逻辑是
「`attached` 且 `high_risk` → 保留」，导致同一条挂载事实在表头 `hermes-home`
列与最后一列各显示一次，读起来就像「多了一个 WorkBuddy」。

### 修复

- `is_high_risk_entry()` 新增 `is_attached` 参数：**attached 条目跳过 R3（同名）**，
  因为原生接入客户端会刻意用自己的名字当连接键。
- **R1 / R2 不豁免**：命令落在客户端 app bundle 内仍判高危——即使 key 命中
  端点库，命令来自宿主 app 仍说明它是客户端自带能力。
- 两处调用点同步传参：`management_snapshot._mcp_inventory_payload()` 与
  `mcp_entry_removal._annotate()`（后者同时让删除保护不再平白挡住正常清理）。

### 验证

实测数据从 `{'key': 'WorkBuddy', 'classification': 'attached',
'endpoint_key': 'hermes-home', 'high_risk': True}` 变为 `high_risk: False`，
前端过滤随即把它从最后一列移除。

### 测试

- `tests/test_mcp_entry_risk.py` 新增 4 项：attached 同名豁免、豁免不波及 R1、
  未挂载同名仍判高危、**两处调用点必须传 `is_attached`**（只改函数签名不改
  调用点等于没修）。
- 两条反向验证有效：去掉 `and not is_attached`、去掉调用点传参，各自让对应
  断言失败。全量 **1633 项通过、2 项既有跳过**。

## [v0.37.3] - 2026-11-09

当前发布版本（build 142）。**设置页「市场源」卡片排版重做。**

用户截图指出这一页「有一些排版和视觉上的问题」。评审确认四处：

1. **源行没包 `.rows`**：`.settings-card .rows .row` 才给行内边距与 hairline
   分隔线，此前直接把 `.row` 拼进 body，整块看起来像散落的表单；
2. **新增表单与源列表连排**：没有分组标题，用户看不出「下面是新增入口」；
3. **按钮不同族**：源行与「添加源」用 `.ghost.sm`（透明无边框、26px 高），
   与卡片里 `.btn-soft` 的「清理登记残留」不是一套，读起来像文字链接；
4. **字段宽度参差**：四个字段各自内联 `min-width: 8rem / 16rem`，四行不齐；
   长仓库 URL 还会把操作按钮挤走。

### 改动

- **分区**：卡片内分三块——已配置源（`.rows`）／添加源（`.settings-group`
  + 标题）／登记表维护（`.settings-group`，「清理登记残留」从说明文字中间
  移到独立分组）。
- **按钮统一 `.btn-soft`**：源行「停用 / 删除」与「添加源」都用它；`ghost`
  只留给真正的纯文字动作。
- **字段撑满**：新增 `.settings-card .row .v > input[type="text"] / > select
  { width: 100%; max-width: 24rem }`，并给值列补 `flex: 1`——`.row .v` 默认
  由内容决定宽度，漏掉它 `width: 100%` 只等于内容宽度（实测仍停在 180px，
  看起来像没生效）。去掉每个字段的内联 `min-width`。
- **URL 单独一行**：新增 `.market-source-url`（`flex: 1 0 100%`，超长省略、
  `title` 给全文），不再与按钮抢宽度。
- **`.settings-group`** 与既有的 `.agent-settings-section` 共用同一套样式规则
  （上边线 + mono 大写小标题），不另造视觉。

### 文档

`docs/DESIGN.md` §2.10 新增「市场源卡片」结构图与三条结构规则（源行必须包
`.rows`、新增表单独立成组、同卡片动作按钮统一 `.btn-soft`），并登记字段
撑满与 URL 单独一行的做法。

### 测试

`tests/test_design_spec_contract.py` 新增 4 项版面不变量断言（`.rows` 包裹、
添加源分组、按钮族、字段无内联宽度 + 撑满规则存在）。**4 条全部反向验证过**：
去掉包裹、退回裸表单、改回 `ghost.sm`、加回内联 `min-width`，各自让对应断言
失败。全量 **1629 项通过、2 项既有跳过**。

## [v0.37.2] - 2026-11-09

当前发布版本（build 141）。**Git 技能源自动接管统一目录。**

用户截图追问：「既然已经发现了，为什么不可以自动扫描或者自动获取？我的目录和
统一默认的目录是一致的，而且页面上的 skill 也扫描到了 170 多个。」问题成立：
统一目录早在 `config.yaml` 里配好、磁盘上确实是 git 工作区（远端
`my-agent-skills`、分支 `master`），但 `data/git_sources.yaml` 是空的——同一张
卡片里「统一技能目录」显示已设置、「Git 技能源」却说「尚未登记」，四个同步
按钮全在空转。用户无法判断配没配好，只能把同一个路径手输一遍。

### 新增

- **`core/git_sources.adopt_unified_dir()`**：把当前统一技能目录自动登记为主源
  （`primary: true`）。判据三条：登记表非空 → `already-configured`（绝不覆盖）；
  目录不存在或缺 `.git` → `not-git-repo`（附原因）；成功则原子写 + 备份。
- **`--adopt-git-source`**：CLI 出口，支持 `--dry-run` / `--format json`。
- **设置页自动接管**：`loadGitSources()` 发现登记表为空时自动调用，成功后
  重新加载并在卡片顶部显示「已自动接管统一技能目录为 Git 源：<路径>（分支 X）」，
  刷新页面后该提示消失，但源行带「主源 · 统一目录」标签，状态仍自解释。

### 为什么可以自动写

这不是替用户做决定，而是把一个**已经成立的事实**（目录已配置、技能已在用、
目录就是 git 工作区）记进登记表：不改变任何客户端指向、不动仓库内容，且随时可
「移除」撤销。要求用户手输同一个路径，等于让他证明一个已知事实。

### 失败不静默

`not-git-repo` 的原因写进空态文案（「未登记 Git 技能源：统一目录不是 Git 工作区…」），
不再退化成笼统的「尚未登记」——后者会让人以为功能没做。

### 文档

`docs/DESIGN.md` §2.10 新增「Git 源自动接管」：触发条件、后端判据、ASCII 结构、
为什么可以自动写、为什么不需要再点「设为主源」。

### 测试

- 新增 `tests/test_git_sources_adopt.py`（11 项）：接管为主源、已有登记不覆盖、
  非 git 目录/不存在目录拒绝且不落盘、dry-run 不写、主源语义闭环
  （`unified_dir_from_sources()` 派生同一路径）、CLI 端到端、GUI 契约。
- **反向验证 4 条**：删自动接管调用点、删重入解锁、删 Rust 白名单、去掉
  `already-configured` 保护，各自让对应断言失败。其中「只断言函数名与命令名」
  最初确实没拦住删调用点——补上调用点与「解锁紧邻重载」两条精确断言后才有效。
- 全量 **1625 项通过、2 项既有跳过**。

## [v0.37.1] - 2026-11-09

当前发布版本（build 140）。**登记残留有了清理出口。**

用户问「116 个登记残留是什么意思，能否清理」。查下来是两件事叠在一起：
`~/.agents/.skill-lock.json` 里有 187 条来源登记，统一库磁盘上只有 174 个
目录，差的 116 条是「技能已卸载、登记没跟着消失」的条目。检查更新的弹框把
它们单列为 `missing`，并提示「可在技能行删除」——**这句提示是错的**：技能
表按磁盘目录渲染，残留行根本不出现；`--delete-skill` 又要求目录存在，实测
对残留行直接报「未找到 skill 目录」。用户被指向了一个做不到的操作。

### 新增

- **`--prune-skill-lock`**：清理来源登记表里「统一库已无此目录」的条目。
  支持 `--dry-run` 与 `--format json`；无残留时返回 `nothing-to-prune`。
- **`core/skill_market.prune_missing_registrations()`**：判据与
  `check_updates()` 的 `state == "missing"` 同源（都取 `list_installed()`
  的 `registered` / `on_disk`），保证「检查弹框报的条数」与「清理按钮删的
  条数」不会对不上。配套只读的 `missing_registrations()`。
- **设置页「清理登记残留」按钮**（市场源卡片内，`data-action="prune-skill-lock"`）：
  先跑 dry-run 拿清单，`confirmModal` 展示将删条数、保留条数与前 8 个示例，
  确认后才执行；结果弹框给出备份路径。

### 安全边界（写操作，三条）

1. **先备份再改**：整份 lock 复制为 `<原名>.bak-<时间戳>`；备份失败即中止，
   不做半途修改。
2. **只删磁盘上确实没有的**：`dismissed` / `lastSelectedAgents` 等非 `skills`
   字段与仍然存在的登记原样保留，不做归一化重排。
3. **dry-run 不落盘、也不生成备份**：否则会留下「备份了但没改」的误导性文件。

登记表缺失或 JSON 损坏时**如实报错**，不静默当成「没有残留」——后者会让
用户以为清理成功，实际什么都没发生。

### 文档

`docs/DESIGN.md` §2.10 登记该控件：位置、ASCII 结构、为什么先 dry-run 再
确认、三条安全边界，以及「为什么放在市场源卡片」（残留登记是市场安装的
副产物，与「源」同一域）。

### 测试

- 新增 `tests/test_skill_lock_prune.py`（16 项）：dry-run 不落盘、只删磁盘
  无目录的条目、非 `skills` 字段保留、备份内容等于改前原文、无残留不造空
  备份、登记表缺失/损坏如实报错、CLI 端到端 JSON 与退出码，以及 GUI 契约
  （按钮落在市场源卡片、事件分发接上、Rust 白名单同步、DESIGN.md 已登记）。
- **反向验证过**：删掉按钮、删掉 Rust 白名单项、让 dry-run 也落盘，三种
  违规各自让对应断言失败，恢复后全绿。
- 全量 **1614 项通过、2 项既有跳过**；`scripts/ci_parity.sh` 全部门禁通过
  （`skipped=2` 与 CI 基线 3 的差异已用 `CI_ALLOW_SKIP_DRIFT=1` 豁免，原因是
  本机 node 在 PATH、CI 缺 node 会多跳过一个用例）。

## [v0.37.0] - 2026-11-09

当前发布版本（build 139）。**Git 技能源补上「提交」能力。**

用户截图指出：设置页只有「检查更新 / 拉取 / 推送」，缺了「提交」。这不是漏个
按钮的问题——脏工作区会让拉取直接拒绝（不 stash、不覆盖），而推送又没有本地
提交可推，用户卡在中间**无路可走**。截图里的「有未提交改动 78」正是这种死结。

### 新增

- **`--commit-git-sources`**：把各 Git 源的工作区改动提交为一个 commit
  （`git add -A` + `git commit`）。配合 `--git-commit-message` 自定义提交信息，
  支持 `--dry-run` 与 `--format json`。
- **`core/git_sync_ops.commit_status()`**：只读列出待提交清单，按
  added / modified / deleted / renamed / untracked 分类计数。提交前把
  「删除了 N 个文件」摆到明面——删除比新增更需要确认。
- **管理台「提交改动」按钮 + 确认弹窗**：先跑 dry-run 列清单（每源一块、
  性质点数、文件清单默认折叠），用户填可选提交信息后再确认。

### 三条约束（提交是不可逆的本地写操作）

1. **空工作区不制造空提交**：直接返回 `nothing-to-commit`。
2. **作者身份缺失时如实报错**（`no-identity`），**不动用户的 `git config`**。
3. **提交信息不得为空**：留空则用自动生成的文案，而不是生成无法解释的 commit。

### 修复

- **`--git-commit-message` 静默失效**：`scan.py` 算出了 message 却没传给
  `run_on_all`，导致表单里填的信息被一律丢弃、全用默认文案。ruff 的「未使用
  变量」抓到了它，但那个提示读起来像代码卫生问题，实际是**功能缺陷**。
  已修复并加回归守卫（`test_custom_message_reaches_run_on_all`）。

### 文档

`docs/DESIGN.md` §2.3f 新增「提交确认弹框（`.git-commit-modal`）」：登记
`.git-commit-src` / `.git-chg` / `.git-commit-files` 等类，并写明两条设计理由——
清单默认折叠（几十条会把确认按钮挤出视口）、删除单独计数（一次「删除整个技能
目录」不该和「改了 78 行」看起来一样重）。

### 测试

- `tests/test_git_sources.py` 由 39 项增至 **47 项**：提交清单与计数、dry-run
  不落 commit、提交后工作区干净、删除必须被提交、空改动不制造空提交、空信息
  用默认文案、缺身份清楚报错且不改配置、自定义信息透传。
- 全量 **1598 项通过、2 项既有跳过**；`scripts/ci_parity.sh` 全部门禁通过。

### 测试基建（同期改动，无产品代码变更）

- **GUI 测试的函数抽取改为大括号配平**（`tests/_js_fn.py`）。13 个测试文件各自
  写的 `_fn()` 有两种缺陷且**都不报错**，只让断言静默检查错东西：`\n\}` 只匹配
  零缩进收尾（管理台函数缩进两格，于是正则一路吃到下一个顶格函数，实测
  `renderMarketProgress` 真实 221 字节被抽成 43,723 字节、把 28 个函数裹进断言）；
  `\n  }` 则切在第一个内部块上，抽出的函数体残缺。改为扫描时跳读字符串与注释
  里的括号。
- 新增 `tests/test_js_fn_extraction.py`（9 项）做变异测试：内注入必须抓到、
  外注入必须不影响、字符串里的花括号不干扰配平、相似名不误匹配。

## [v0.36.0] - 2026-11-08

当前发布版本（build 138）。**结果弹框正文结构化：计数不再串成一行。**

用户截图反馈「检查完成（缓存）」弹框「没有排版」：四个计数
（`有更新 1 · 最新 149 · 未知 24 · 已卸载但登记残留 7`）挤成一行同权重小字，
建议段落夹在中间，扫不出重点。

### 变更

- **`modalNotice` 新增可选第四参 `opts`**：`stats: [{label, value, tone}]`
  渲染成 key/value 网格（数字大号 `--mono`、标签小字），`action: "..."` 渲染成
  独立强调块。两个都不传时行为与从前逐字一致。
- **排布顺序固定**：图标 → 标题 → 结论 → 计数 → 动作 → 出口按钮。
- **「检查更新」调用方改为结构化传参**：计数按实际有值的项动态生成
  （可升级 / 已最新 / 未知 / 登记残留 / 仓库待同步），`tone` 只标需要处理的项。
- **结论句只写需要留意什么**：有 `missing` 时写「有 N 个技能已卸载但登记残留，
  可在技能行删除」；没有异常项就留空，不写废话。

### 设计规范

`docs/DESIGN.md` §2.3f 补充「结果弹框的三层结构」：登记 `.notice-stats` /
`.notice-stat` / `.notice-action` / `.notice-action-icon` 四个类，写明
「计数不得串成一行」的理由与 `tone` 只允许 `todo` / `warn` 两档。
规范 §2.9 早已要求结果弹框是「结论 + 动作，而不是一串计数」，这次是把
那个要求真正落到实现上。

### 测试

全量 **1581 项通过、2 项既有跳过**；`scripts/ci_parity.sh` 全部门禁通过
（含设计契约的类登记与间距 token 校验）。

## [v0.35.0] - 2026-11-08

当前发布版本（build 136）。**优化结果弹框：不再把原始 JSON 当正文给用户看。**

用户截图反馈「检查 Git 源更新」的弹框里是一屏 `--format json` 原文，而「拉取」
的弹框只写「操作未完成」——两处都是把程序契约当成了给人看的话。

### 修复

- **弹框正文结构化渲染**：新增 `renderGitSourceResult`，把 CLI 的
  `{summary, results[]}` 渲染成「一行一个源」：色点 + 源名 + 状态，下面一行弱化
  提示「落后 3 个提交，可点拉取」。原始 JSON 不再出现在正文里；解析不出结构化
  结果时才回退到纯文本。
- **色点按「需要你做什么」着色，不按退出码**：新增 `todo`（黄）一档。
  `check` 发现落后 3 个提交时**退出码是 0**，但那时什么都没同步——用绿色会
  让用户以为已经好了。`behind` / `ahead` / `dry-run` / `no-remote` 归 todo；
  `current` / `pulled` / `pushed` 归 ok；`dirty` / `conflict` / `diverged` 归 err。
- **失败正文可行动**：原来成功和失败共用「操作未完成」，标题已经写了「未完成」，
  正文再重复等于什么也没说。现在取首个失败源的具体原因与下一步，例如
  「有 2 个未提交改动，先提交或清理再拉取」。
- **通用通知正文排版**：`modalNotice` 的正文由整块文本改为「首行引子 + 明细列表」
  （`renderNoticeBody`），解决「结论和原因糊成一段」的问题。

### 文档

- `docs/DESIGN.md` §2.3f 新增「结果正文的结构化排版」：三档正文容器
  （`.cfm-msg` 单句 / `.notice-lead`+`.notice-list` 结论+明细 / `.git-result`
  逐条结果）、`.git-res-row` 系列类登记，以及色点语义表与「不按退出码着色」的
  理由。规范 §5 要求新增组件必须回写，这里同步。

### 测试

全量 **1581 项通过、2 项既有跳过**；`scripts/ci_parity.sh` 全部门禁通过
（含设计契约的类登记校验与间距 token 校验）。

## [v0.34.1] - 2026-11-08

当前发布版本（build 135）。**把「统一技能目录」与「Git 技能源」合并为一个概念。**

为什么合并：二者实践里总指向同一个目录——那既是技能聚合的地方，也是一个 git
工作区。分成两处配置维护必然漂移，用户在设置页看到两张卡也容易困惑。

### 变更

- **统一技能目录 = 主 Git 源**：登记表里标 `primary: true` 的那条即统一目录。
  `unified_skills_dir` 不再单独配置，由主源**派生**——`scanner.load_config` 在装配
  生效配置时注入，下游 38 处 `config["unified_skills_dir"]` 读取点一行未改。
- **新 CLI**：`--set-primary-git-source <id>`，把某个已登记的源设为统一目录
  （同一时刻只有一个主源；设为主源会强制启用该源，否则统一目录会被当成禁用源跳过）。
- **管理台合并两张卡**：原「Skills 统一目录」卡并入「统一技能源」卡，每行显示
  「主源 · 统一目录」标记，其余源提供「设为主源」按钮。换统一目录 = 选另一个源，
  保证统一目录永远是一个真实存在的 Git 工作区。
- **无主源时的行为**：退回 `~/.skills-manager/skills` 并在状态里标注
  `primary_missing`，CLI 输出提示用 `--set-primary-git-source` 指定，不静默假装已配置。

### 修复

- **`apply_primary_to_config` 未转发 `config_path`**：早先实现一律读生产的
  `data/git_sources.yaml`，导致自定义配置与多实例场景会串（测试即暴露）。已按
  config 所在目录推导 ledger 路径。
- **登记表损坏不锁死配置**：`data/git_sources.yaml` 解析失败时保留配置原值，
  只让 Git 源功能单独报错，避免一个坏文件让整个 CLI 起不来。

### 测试

- `tests/test_git_sources.py` 由 30 项增至 **39 项**，新增 `PrimarySourceTest`
  9 项：主源唯一性、目录跟随主源、设主源强制启用、未知 id 拒绝、已有值不被抹掉、
  缺键填兜底、损坏 ledger 不锁死配置。
- 全量 **1581 项通过、2 项既有跳过**；`scripts/ci_parity.sh` 全部门禁通过。

## [v0.34.0] - 2026-11-07

当前发布版本（build 134）。新增 **Git 技能源**：把「一个 Git 目录」当技能来源来登记、
发现与同步。

为什么需要：此前的仓库形态能力只认「统一库本身是 git 仓库」这一种情况。实际使用中
技能来自多个 Git 目录——有人从远端 clone，有人把一直在用的本地目录加进来。二者在
数据模型上是同一件事（都是一个 git 工作区），过去却没有地方统一管理。

### 新增

- **`core/git_sources.py`（只读半）**：登记表读写（`data/git_sources.yaml`）、技能发现、
  状态检查。**永不联网**——全部是只读 git 子命令，`fetch` 也不做，保证「看一眼状态」
  不会改变任何东西。
- **`core/git_sync_ops.py`（写入半）**：clone / fetch / pull / merge / push 的唯一入口。
  与只读模块分开，是沿用 `skill_repo_source` 的三条纪律。
- **CLI 12 个参数**：`--list-git-sources`、`--add-git-source`、`--remove-git-source`、
  `--git-source-id`、`--git-source-label`、`--clone-git-source`、`--git-source-target`、
  `--git-branch`、`--check-git-sources`、`--pull-git-sources`、`--push-git-sources`、
  `--git-merge`、`--git-discover`。除 `--git-discover` 外均支持 `--format json`。
- **管理台「设置 → Skill → Git 技能源」卡片**：列出各源的分支/提交/技能数/状态，
  提供登记、移除、检查、拉取、推送入口。写操作一律经 `run_cli` 转发 CLI。

### 安全语义

- **拉取默认只快进**：`--pull-git-sources` 用 `merge --ff-only`；分叉时拒绝并提示用
  `--git-merge`。分叉不会静默产生合并提交。
- **脏工作区一律拒绝**：有未提交改动时**不 stash、不覆盖**，直接返回 `status=dirty`。
  实测确认用户改动与未拉入的内容都保持原样。
- **冲突不猜**：合并冲突时返回 `status=conflict` 与冲突文件列表，**不自动 abort**，
  保留现场让用户处理，也不谎报成功。
- **推送前先判断**：落后远端时拒绝推送（`status=behind`），避免制造需要 force 的局面。
- **登记不等于删目录**：`--remove-git-source` 只移除登记表条目，磁盘目录原样保留。
- **配置损坏不静默**：`data/git_sources.yaml` 解析失败时抛错并点名文件，绝不返回
  「没有任何源」——那会让用户以为配置丢了。

### 技能发现口径

与统一库**完全一致**，否则同一技能在两个页面会算出两个数：

- 仓库根下的直接子目录（含 `SKILL.md`）→ 计入 `skill_count`；
- 更深的目录 → 进 `nested` 单独列出，**不计入**数量；
- `.git` / `node_modules` / `__pycache__` / `.venv` 与所有 `.` 开头目录跳过；
- **`_trash` 跳过**：它是 `--delete-skill` 的软删除回收站，里面的 `SKILL.md` 是已删除
  技能的残骸。实测不排除会凭空多出 17 个「嵌套技能」。

### 测试

- 新增 `tests/test_git_sources.py` 共 **30 项**，全部用真实临时 git 仓库（bare 远端 +
  两个工作副本）跑，不 mock git：覆盖技能发现、登记校验（非 git 目录/重复 id/坏配置）、
  current/behind/ahead/diverged 四态、快进拉取、**脏工作区拒绝且改动不被删除**、
  分叉拒绝与显式合并、推送 dry-run 与落后拒绝、clone 非空目标拒绝。
- 全量 **1572 项通过、2 项既有跳过**；`scripts/ci_parity.sh` 全部门禁通过。

### 修复（过程中发现）

- **`test_dashboard_usage_ui` 的静态守卫长期空转**：`_strip_strings_and_comments` 在处理
  模板串 `${...}` 时只按花括号计深度，不感知引号，遇到 `${fn("x")}` 这类就失步，把后面
  **成百上千行真实代码吞成字符串**。后果是 `MARKET_DATA` / `USAGE_DATA` / `ADVICE_DATA`
  等声明从未被该守卫看见——它一直在只检查文件前半段。已改为感知引号，覆盖面恢复。
  这是既有缺陷（HEAD 上同样存在），不是本次功能引入。

## [v0.33.0] - 2026-11-07

当前发布版本（build 133）。**移除生命周期 Hook 能力**：管理台由八页回落为七页。

这是一次**不兼容的功能下线**（按语义化版本应为 major，但本项目尚未发 1.0，按 minor 处理）。
移除而非隐藏的原因：Hook 与其余四块能力（Skills / MCP / DSH 插件 / 变更追踪）没有
共享的数据模型，长期维护成本高于其价值；且它会把「配置是否合规」与「写入了哪些
第三方命令」耦合在一起（见 `docs/DECISIONS` 的历史讨论）。

### 移除

- **CLI 的 9 个 Hook 参数**：`--hooks`、`--list-hooks`、`--fix-hooks`、`--remove-hooks`、
  `--list-hook-templates`、`--set-hook-template`、`--apply-hook-preset`、
  `--hooks-config-path`、`--client-hooks-config-path`。
  `--full` 的语义同步收窄为 Skills + MCP + 端点探测 + 报告。
- **`core/hooks_checker.py` / `hooks_fixer.py` / `hooks_inventory.py`** 三个模块整体删除，
  连带清理 14 个 core 模块中的引用（见下方「修复」中两条静默失效）。
- **管理台 Hook 页**：导航项、`<section id="page-hooks">`、设置页的「Hook 事件」勾选卡
  与「Hook 命令模板」卡、IDE/Agent 列表的 Hook 列、客户端详情里的 Hook 配置区块、
  变更面板的「修复」按钮（其唯一实现是 `--fix-hooks`）。**页面总数 8 → 7**。
- **`config.yaml` 的 `hooks:` 段**（47 项规范事件词表、`hooks.clients` 能力声明、
  `default_command`）、各 `mcp_tools[].hooks_config_path`、`settings.hook_events`。
  文件由 652 行降至 280 行。
- **快照 diff 的 hooks 维度**：4 维度 → 3 维度（agents / mcp / skills），
  全量检查、变更详情页与托盘巡检的口径同步调整。

### 修复

- **合规判定静默降级**（移除过程中发现，非既有缺陷）：`combined_checker` 与
  `dashboard_states.classify_record` 都有一处 `record.get("hooks_required", True)`。
  record 不再产出该字段后，默认值 `True` 会让**所有原本合规的客户端被判为不合规**
  （GREEN 降级成 YELLOW），且不抛任何异常、测试也不会红。两处判定逻辑已整体移除，
  颜色与 `result_ok` 恢复一致。
- **`multi_profile_reporter` 的 CSV 列错位**：`FIXED_COLUMNS` 去掉 `hooks_configured`
  后表头与数据行同步修正；对应的测试期望由 10 字段改为 7 字段。
- **`cli_modes.resolve_modes` 崩溃**：该函数直接读 `args.hooks`，参数删除后会抛
  `AttributeError`，导致 `scan.py --version` 直接不可用。已改为只依据
  `args.skills` / `args.mcp` 等现存属性分派各模式。

### 文档

- `README.md`：能力清单由「3 类问题 + 4 块横切」改为「3 类问题 + 3 块横切」，
  删除 Hook 命令模板命令组与 `--hooks` 示例，管理台描述改为七页。
- `docs/DESIGN.md`（1583 → 1437 行）与 `docs/DESIGN.html`（2120 → 2039 行）：
  删除 Hook 列判据、`.al-scope` 分层作用域徽标、Hook tab、`.hook-group-row` 等
  界面规范；IDE/Agent 表格列序由 10 列改为 9 列，状态列居中规则由
  「第 3 / 7 / 8 / 9 列」改为「第 3 / 7 / 8 列」。
- `docs/product/PRD-产品需求文档.md`（v1.8）：§5.3 页面结构改为七页，
  §6.6「Hook（生命周期事件）」标记为**已作废**并保留说明，历史版本记录不动。
- `docs/product/prd_impl_matrix.json`：删除 5 条 Hook 相关条目（80 → 75），
  `PRD-实现对照清单.md` 状态计数同步（已实现 66 → 61）。

### 测试

- 删除 3 个纯 Hook 测试文件（`test_hook_capability_data` / `test_hook_events_config` /
  `test_hook_interpolation`）；清理 24 个测试文件中的 hook 断言与夹具。
- 三处不降强度的改写：`test_mcp_na_cells_are_tags` 按 GUI 实际产出收窄取值；
  `test_al_scope_is_deboxed` 改为「规则在则查去盒化、规则不在则反查死引用」的双向断言；
  `test_no_ai_memory_in_trunk_sources` 由只查 `hooks_fixer.py` 扩大为全量 `core/*.py` + `scan.py`。
- 全量 **1542 项通过、2 项既有跳过**；`scripts/ci_parity.sh` 全部门禁通过。

### 已知影响

- **已写入客户端配置的 hook 条目不会被自动清除**。本机 Cursor（`~/.cursor/hooks.json`）、
  WorkBuddy（`~/.workbuddy/settings.json`）、TRAE（`~/.trae-cn/hooks.json`）中此前由
  本工具写入的 hook 配置会**原样保留并在客户端继续生效**。如需清除，须手工编辑这些
  文件；本工具不再提供任何 hook 写入或移除入口。
- 历史文档（`docs/superpowers/specs/*hook*`、`docs/research/hook-capability-*.json`、
  `docs/方案-托盘常驻与Hook管理.md`）作为当时的设计与取证留档保留，不代表当前产品。

## [v0.32.0] - 2026-11-07

当前发布版本（build 132）。两条主线：**原生 MCP 接入与身份治理**（让「谁以什么身份
调用了远端 MCP」变成可预览、可回滚、可复核的证据链）与**端点凭据来源**
（token 不再只能明文落盘）。

### 新增

- **原生 MCP 接入与身份治理（`--native-*`）**：把原生接入整改抽象成**版本限定的宿主
  适配器**，首批支持 macOS WorkBuddy `5.9.3` 与 DeepSeek Harness `0.2.2-rc.1`；
  宿主版本不匹配时**停止写入**，不尝试兼容未知基线。
  - **控制面不联网**：本模块只做本地检查 / 计划 / 备份 / 写入 / 回读，不实现 MCP
    网络客户端，不用终端代连，不触发 Hook、桥接、worker 或旧队列。CLI 原生分支在通用
    审计与探测之前返回，既有通用端点探测**不属于**原生验收证据。
  - **五步安全链**：只读检查 → 计划哈希（`--native-if-match`，计划过期即拒绝）→
    私有备份 → 原子写 → 读回校验；回滚先校验全部受影响文件的**修复后哈希**，遇到
    后续编辑一律拒绝覆盖。
  - **身份四维核验**：设备（服务端 device key 映射）、Agent（原生 `clientInfo`，标注
    `source=client_info` 且**不当作密码学认证**）、当前对话（由宿主现取，不能由本工具
    生成）、项目（`project_resolve_identity` 返回 `matched` 且在授权名单内）、任务
    （`session_binding_get` 显式会话参数；`unbound` 合法，**不自动创建或绑定**）。
  - **双真实对话验收**：`--native-start` 生成 A/B 两份带随机 challenge 的指令 →
    在两个真实对话里各加载专用技能、现取自身原生 session ID → `--native-capture`
    以该 ID 作**精确历史选择器**读取宿主原始工具历史（WorkBuddy 读 JSONL，DSH 读
    zstd 压缩 JSONL）→ `--native-verify` 再次回读两个源文件核对。不接受模型最终回答、
    手工导入 JSON、旧 challenge 或错误工具回执作为证据；配置或应用版本变化即要求重验。
  - WorkBuddy：连接键用 `WorkBuddy` 以保留原生 Agent 名称；5.9.3 不按根 env 声明替换
    `Authorization`，故仅在明确 apply 且缺失有效 Header 时解析既有安全凭据，写入 0600
    配置；已有 Header 原样保留，输出不含凭据。当前会话 ID 由原生技能加载时替换
    `${CODEBUDDY_SESSION_ID}`，普通文件读取不算证明。
  - DeepSeek Harness：主配置为 `~/.dsh/profiles/desktop/cordis.patch.yml`，识别
    `insert` 及禁用父节点，保留原生 HTTP 插件、Cordis 表达式与原有 Header；使用外置
    原生插件适配副本**仅**替换 `clientInfo.name`，9 个依赖仍引用原 App 同一模块实例
    以免重复加载 scope 状态。**不修改 App ASAR**、不复制依赖、不构建第三方源码；适配前
    校验原始入口 SHA-256 并保存补丁清单。
  - **通用入口互斥**：`--fix-mcp` 对这两个已注册原生适配器只提示使用专用入口，避免
    重新写入占位 Header 或重复连接。
  - 本地状态目录 `~/.local/share/skill-mcp-studio/native-mcp`（0700），回执与备份
    0600。管理台「MCP」页新增原生接入面板（预览 / 应用 / 回滚 / 历史验收恢复 / 双会话
    证据比较），与 CLI 共用同一服务。
  - **不主张**：不主张所有通用 MCP 调用都会自动携带对话 ID；本次验收证明的是显式
    `native_session_id` 参数正确到达远端；读到 `unbound` 不能说明历史上从未绑定；一次
    验收也不证明未来应用升级或凭据撤销后仍有效。
- **端点凭据来源（`auth_mode`）：钥匙串 / 环境变量 / 凭据文件**（用户反馈：token
  此前只能明文存进端点库再抄进每个客户端的 `Authorization` 头，已经存进 macOS
  「登录」钥匙串的凭据在本工具里无处可用）。端点现在可声明凭据从哪来：
  `token`（默认，行为与从前逐字节一致）/ `env` / `keychain` / `file`。
  - 引用型只把**引用**写进客户端配置：Claude Code / Cursor / VS Code 等 JSON、YAML
    写 `Authorization: "Bearer ${env:VAR}"`；Codex（TOML）改用官方
    `bearer_token_env_var` 字段并清掉旧的明文 `http_headers`；DSH cordis patch
    写同样形态的占位符（`!!js` 写法会被本项目的 PyYAML 校验拒绝，实测过）。
  - 探活在连接时按引用取真值：钥匙串经 `security find-generic-password -w`
    （Linux 为 `secret-tool`），文件读 0600 凭据文件。取不到时报「凭据不可用：
    <原因>」而不是拿错误 token 去撞鉴权，也不再静默回落到环境变量。
  - 新 CLI：`--endpoint-auth-mode/-env/-keychain/-keychain-account/-file`、
    `--auth-secret-status <key>|all [--check-credential]`、
    `--set-auth-secret <key>`（写钥匙串 / 文件，空值=移除）。`--list-endpoints`
    增加 `auth=` 摘要列。
  - 管理台：端点弹窗加「认证方式」选择器与来源输入行（带「检测来源」）；端点库表格
    新增「认证」列，只显示来源元信息；「设置 → MCP」新增「MCP 端点凭据」卡片
    （模式 / 来源 / 状态表 + 检测 + 存入）。
  - **安全边界**：状态查询默认**不读**凭据内容（读钥匙串会弹系统授权，GUI 子进程 /
    后台巡检里没人点「允许」，实测挂到 10 秒超时才失败并误报），只有用户主动点
    「检测」才加 `--check-credential` 真读；任何输出与日志都只给脱敏值。
  - **客户端 env 注入（让敲定式真能连上）**：客户端可在 `config.yaml` /
    `discovered_tools.yaml` 里声明 `mcp_root_env_style`（真实键名：`env` 用于
    Claude Code / Cursor / WorkBuddy / VS Code / OpenCode，`process_envs` 用于 Goose），
    `--fix-mcp` 会把从钥匙串 / 文件取到的真值写进该配置根的 env 块，客户端启动时
    注入自身环境 —— `${env:VAR}` 插值这才真正生效。已为上述客户端声明该字段。
  - **变量名合法且稳定**：`${env.X}` 的 X 必须匹配 `[A-Za-z_][A-Za-z0-9_]*`；钥匙串
    服务名常含连字符、文件路径必含斜杠，都不能直接当变量名。引用型统一改用**由端点名
    派生**的名字（`hermes-home` → `HERMES_MCP_TOKEN`），同一端点在所有客户端同名。
  - **能力边界如实告知**：Codex 的 `bearer_token_env_var` 会被客户端解析；声明了
    `mcp_root_env_style` 的客户端由我们注入真值；其余（DSH cordis、Reasonix）写的是
    占位符。引用型的修复结果因此不复用「updated and verified」，而是分别写出
    「真值已注入客户端 env 块」或「需把真值注入环境变量 X」，避免把「写了占位符」
    误报成「已接入」。
  - **钥匙串失败的诊断**：读取超时 / 被拒（exit 161）/ 写入 `Operation not permitted`
    三种情况分别给出可执行处置（点「总是允许」、改用 `--endpoint-auth-mode file` 等），
    不再只抛一句 `Timed out`。

### 安全

- **管理台快照不再下发明文 `auth_token`**：`--management` 的端点库此前把明文令牌原样
  交给前端，页面又把它写进编辑按钮的 `data-auth_token` 属性 —— 等于把一个长期有效
  的令牌放进了 DOM。现在后端在快照里脱敏为 `<redacted>`，编辑按钮只携带 `data-key`，
  凭据值仅在「编辑 / 存入」弹窗里由用户在 password 输入框输入后当次传给 CLI。
- **切到引用型时清除旧的明文头**：JSON / YAML / TOML / cordis 四个渲染器的写后校验
  保证旧 token 不残留（TOML 的子表形式也会连带删除空的 `[X.http_headers]` 表）。

### 修复

- **DSH 插件表按插件名去重**（用户反馈「同一插件出现两次」）：16 条记录里只有
  14 个唯一插件，`@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-web-app` 在 desktop 与
  web 两个 profile 里都声明。改为按插件名聚合成一行一个插件，`profile` 列标出归属。
  状态跨 profile 不一致时取最严重者（`broken` > `installed` > `enabled`）并显式
  标注「各 profile 不一致」，不静默取其一。「来源」列并入「类型」列（该列此前
  16 个插件无一有值却固定占宽）。
- **DSH 插件导航项补计数徽标**：与同组四项口径对齐，取 `summary.plugins`（总数，
  非启用数）；读取失败或无 profile 时显示普通连字符 `-`（非 em-dash、非 `0`）。
- **DSH 插件从「系统」组移入「管理」组**：它是可管理对象，不是系统信息。
- **浅色主题两个阴影 token 自引用修复**：`--shadow-accent-hover` 与 `--shadow-knob`
  此前写成 `var(...)` 指向自身，计算值无效，导致主按钮悬停光晕与开关旋钮阴影在
  浅色下完全消失（深色主题反而是正确值）。补上真实取值。
- **`.sr-only` 的 `margin: -var(--sp-0a)` 语法非法**：CSS 不允许负号前置 `var()`，
  整条声明被丢弃。改为 `calc(-1 * var(--sp-0a))`。
- **深色主题补 `--err-strong`**（此前漏定义、继承浅色深红值，配 `--on-accent` 近黑
  字对比度极低）；并删掉深色块里 `--shadow-err` / `--shadow-err-hover` 的重复声明。
- **`prefers-reduced-motion` 覆盖率补齐**：规范承诺「所有动画/过渡都关闭」，实测
  53 个含过渡的选择器里只覆盖了 14 个。改用通配兜底 + 具体补偿，不再逐个列举。

### 文档

- **`broken` 状态判据勘正**（`DESIGN.md` §2.3g、`core/dsh_plugins.py` docstring、
  本节 v0.31.4 段）：此前三处都写「`broken` 独立判 `link:` 目标存在性、不以
  version 缺失兜底」，与实现不符——实现是**两条并存**：`classify_plugin` 以
  `version is None and kind != "builtin"` 为主路径（覆盖「清单声明了却没装」），
  `scan_profile` 再对 `link:` 目标缺失强制置 `broken`（覆盖「源码删了但
  `node_modules` 还留旧副本」）。按旧表述去「修正」代码会漏掉第一类静默失效。
- **`DESIGN.md` 撤回虚构的版本号**：上一版误写「按插件名去重（v0.31.5 调整）」，
  项目并无 v0.31.5（`version.json` = 0.31.4、无该 tag），改为「v0.31.4 之后、尚未发版」。

## [v0.31.4] - 2026-10-25

当前发布版本（build 131）。新增**第八页「DSH 插件」**：把 DeepSeek Harness 的
插件体系接进管理台。

为什么需要：本工具的 Skills / MCP 是自己的模型（符号链接 + 端点库），而 DSH 的
插件是**另一套**——cordis 载入器的 bundle 体系：装什么写在 `package.json` 的
`dependencies`，启用什么写在同文件的 `dsh.profile.bundles`，改什么写在
`cordis.patch.yml`。用户在 DSH 里装插件、改补丁层，却没有任何地方能一眼看清
「现在到底会加载什么」。这与此前七页无关，故独立成页。

### 新增

- **`--dsh-plugins` 只读出口 + `core/dsh_plugins.py`**：扫 `~/.dsh/profiles/*`，
  合并三处真相判一个插件的真实状态：
  - `enabled`（在 `dsh.profile.bundles` 里，**会被真正加载**）；
  - `installed`（在 `dependencies` 里但不在 bundles 里，装了不用）；
  - `broken`（`link:` 依赖目标已不存在，DSH 载入会失败）。

  **三态不合并计数**——「装了」不等于「在用」，合并会让用户对「现在加载了几个
  插件」判断错误。`broken` 的判据是**两条并存**（本节原写「独立判 link 目标存在性、
  不以 version 缺失兜底」，与实现不符，已勘正——详见 [Unreleased] › 文档）：
  ① `classify_plugin` 以 `version is None and kind != "builtin"` 为主路径，覆盖
  「清单里声明了、但根本没装进 `node_modules`」这种静默的配置不一致；②
  `scan_profile` 再对 `link:` 目标缺失强制置 `broken`，因为 pnpm 的 link 在源码
  目录删除后 `node_modules/<name>` 常还留着（旧副本或指过去的符号链接），此时
  version 读得到却被放行，必须单独判。
- **插件类型三分类**：`builtin`（`@deepseek-ai/*`）/ `local`（`link:` 本地源码）/
  `registry`（npm 第三方）。身份用中性 tag，不与状态语义色抢。
- **`--dsh-home`**：DSH 配置根目录可指定（默认 `~/.dsh`），便于测试与多实例。
- **GUI 第八页 `page-dsh`**：导航项、`PAGES` 映射、命令面板均可达；进页按需拉一次
  并缓存，「重新读取」强制重拉；顶部三计数各自独立，下方每 profile 一张卡片
  （插件 / 类型 / 状态 / 版本 / 来源）。
- **Rust `run_cli` 白名单**加入 `--dsh-plugins`：不登记的话界面一点就撞安全边界。

### 安全

- **patch 层的 config 值一律不回显**：`cordis.patch.yml` 的 `config` 段里有**明文
  apiKey**（本机实测存在）。因此只输出结构统计（条目数 / 禁用数 / 插入数），
  连 `baseURL`、`provider` 这类「看着不算密钥」的字段也不输出——一旦开始挑选
  哪些能显示，就必然有新敏感字段漏网。输出带 `secrets_redacted: true` 作显式承诺，
  页面固定显示「patch 值已脱敏」并说明原因。
- 全程只读：不写任何 DSH 文件、不执行 `pnpm install`、不碰 lock 文件。

### 文档

- `DESIGN.md` / `DESIGN.html` 双向同步新增 §2.3g（DSH 插件页）：三态判据表、
  `broken` 为何独立判定、安全约束、布局与数据来源。
- PRD v1.7：新增 §6.9（DSH 插件页需求 + DoD + 刻意不做的边界）；§5.3 页面结构
  七页 → **八页**；§5.1 形态图与 §10 勘正表同步。
- 对照清单 73 → **80 条**（新增 6 条已实现 + 1 条刻意不做），总览计数与
  PRD 版本号同步；`test_prd_v15_review` 的页面集合断言由七页改为八页（页面一变
  必须回来改文档，这正是该断言的用途）。

- **PRD v1.6：补齐三页需求 + 建立「PRD ↔ 实现」对照清单**。v1.5 修的是「写错的」，
  本版补的是「没写的」：§6 此前只覆盖 IDE/Skills/MCP/设置四块，**Hook、变更详情、
  概览三页有页面名、没有需求表**——页面存在而需求缺失，属漏写。新增 §6.6 / §6.7 /
  §6.8 分别补齐三页能力、口径与「为什么这么设计」。同时改正 §5.3：概览的
  「MCP 探活」KPI 实际已被移除（代码注释明确记录「探活统计已整体移出本函数」），
  现在概览只放六项配置侧 KPI，端点连通性在下方独立「端点状态」区呈现——配置审计
  与连通性探测不混在一个数字里。

- **新增 `docs/product/PRD-实现对照清单.md`（73 条逐项对照）**：每条列出 PRD 章节、
  能力、类型、状态、**可机器核验的证据**与备注。状态分布：已实现 60 / 部分实现 1 /
  未实现 8 / 刻意不做 4。证据形态三种——CLI 参数（必须在 `scan.py` 里真实存在）、
  代码符号（必须在指定文件里出现）、GUI 选择器（必须在 `dashboard.html` 里出现）。
  单一数据源是 `docs/product/prd_impl_matrix.json`，markdown 表格由它派生。

  这份清单的核心结论：**主干能力全部落地**。缺口集中在两处——① §6.2.1「技能关闭」
  整条需求未实现（8 条子需求），② 跨平台只做到「能构建」没做到「真机可用」。
  另附实施顺序建议（R1+R2+R3 纯只读先行）与「与缺口看板的 ID 对应关系」。

- 断言 15 条（`tests/test_prd_impl_matrix.py`）守两件事：**证据是真的**（代码改名、
  flag 删除、GUI 选择器改动都会报红）、**文档是自洽的**（markdown 与 JSON 行数/状态
  一致、矩阵引用的 PRD 章节真实存在、未实现项必须在缺口看板登记、部分实现必须写明
  缺什么）。另有 3 条反向断言：只有文档证据的条目不得标「已实现」、`§6.6~6.8`
  必须还在、概览不得再声称含探活 KPI。负向验证 3 处（flag 证据写错、代码符号写错、
  部分实现偷改成已实现）均确认报红后复原。

- **PRD 综合整理与深入评审（v1.5）**：把 PRD 与 v0.31.3 实况对齐，修正 6 处
  过时/自相矛盾表述，补入 7 项已交付但未入表的能力，并新增评审记录章。
  评审方法不是「读一遍觉得没问题」，而是每条声明都回到事实源核对（`core/*.py`
  实现、CLI 实际参数、`.github/workflows/*.yml` 的 CI 矩阵、本机真机跑一遍）。

  修正的过时表述（均为「文档说 A、代码是 B」）：
  - §1.1「Windows/Linux 支持为空白」→ 实际 `core/mainstream_registry_data.py`
    已有 `_current_os()` + `by_os`（20 处 windows / 21 处 linux），且 CI 三平台
    构建全绿；真正没做的是**真机冒烟**，单列为缺口 #6。
  - §1.3 字段名 `paths_by_os` → 实现叫 `by_os`。
  - §1.4「内置清单共 22 个」→ 注册表实测 **38 条**（Agent 16 / IDE Plugin 12 /
    AI IDE 8 / AI Assistant 2）；并写明「注册表条数 ≠ 本机受管客户端数 ≠
    Skills 挂载数」三者不得混用。
  - §6.2 更新检查「三态」→ 实为**五态**（v0.31.1 加 `missing`、v0.31.3 加
    `repo_outdated`），并补「后两态必须单独报数」的用户可见口径。
  - §6.4 WebDAV「留后续版本」→ v0.31.1 已交付并接出 GUI。
  - §8「不做技能市场 / 商店」→ 与已交付的 `--market search/install/upgrade`
    打架。**不是违例，是原表述太粗**：拆成「做消费方 / 不做分发方」并给出可操作
    判据；同理拆开「不做云端同步」与 WebDAV 配置同步、「按需加载未立项」与
    已交付的逐技能启停 + 启停矩阵 + 形态迁移。

  补入的已交付能力（此前 PRD 完全没写）：技能使用统计（`--skill-insight`）、
  备份与回滚（`--skill-rollback` / `--list-skill-backups`）、启停矩阵与形态迁移
  （`--list-skill-states` / `--audit-skill-states` / `--migrate-skill-links`）、
  市场搜索安装升级、GitHub token 通道、WebDAV 同步、仓库形态检查。

  新增 §12 评审记录：问题表（9 条）、**本轮没有改的部分及原因**（七页结构、
  退出码语义、§1.2 扫描路径、§6.1 能力表——逐项给出核对结论，证明不是漏看），
  以及 3 条**产品层**问题（形态差异缺少可见引导 / 使用统计可信度未量化 /
  五态里有两态无法在本工具内修复）。

- 断言 15 条（`tests/test_prd_v15_review.py`）守住这次勘正，分三类：已勘正的
  事实不得回退、边界表述必须是拆分后的版本、评审记录必须留档。另有 3 条
  「PRD 声称的能力 CLI 里必须真有」的交叉断言（含注册表条数与页面集合），
  防止文档写了而代码没有。负向验证 3 处（五态改回三态、市场边界改回粗表述、
  38 条改回 22 个）均确认报红后复原。

### 测试

- 新增 17 条断言（`tests/test_dsh_plugins.py`）：三态分类用**真实临时目录树**跑
  （mock 掉文件系统等于把判定删了）；含伪造 `apiKey` 的样本断言 JSON 与文本
  两种出口都查不到密钥（含 `sk-` 前缀与 baseURL）。负向验证 3 处：把
  「装了未启用」算成启用（2 条红）、把 config 原文带进输出（1 条红）、不判 link
  失效（首轮**未报红**——说明断言不够强，补了「有 version 也要判 broken」的用例后
  才红）。第 3 处是我自己写弱了，记在此处以免重犯。

## [v0.31.3] - 2026-10-25

当前发布版本（build 130）。补上「153 个技能永远查不到更新」这个缺口：
检查覆盖从 39/192 提升到 192/192，并新增第五态 `repo_outdated`（仓库待同步）。

### 新增

- **仓库形态技能源的更新检查（检查结果第五态 `repo_outdated`「仓库待同步」）**：
  实测本机 192 个技能里只有 39 个在 `~/.agents/.skill-lock.json` 有来源登记，
  其余 153 个在检查结果里一律落 `unknown` —— 那个巨大的「无法检测」桶不是结论，
  是**缺口**：它们不属于任何「单技能来源」，而是**整仓库形态**，统一库目录本身
  就是一个 git 工作区（`origin` 指向 `my-agent-skills`，分支 `master`）。新增
  `core/skill_repo_source.py` 按「本地 `HEAD` 与 `origin/<branch>` 之间该技能
  目录有无差异」判定：上游有新提交 → `repo_outdated`，一致 → `current`，本地有
  未提交修改 → `unknown`（同步必冲突，不能笼统报「可同步」），git 缺失 / 非工作
  区 / detached HEAD / 缺上游 ref / 子命令非 0 → `unknown` + 原因（绝不静默算
  `current`）。检查总覆盖从 39/192 提升到 192/192。

  三条纪律：**只读**（只跑 `rev-parse` / `diff` / `status` / `log`，绝不 pull、
  fetch、checkout）；**不发网络请求**（比对基准是本地已有的 `origin/<branch>`
  ref，由 `--sync` 或手动 fetch 更新，基准提交时间随 `note` 与 `remote_time`
  透出，否则「很久没 fetch」会被读成「远端没变」）；**路径只收敛到已知技能
  目录**（仓库根的 `README.md`、`LICENSE`、`_core`、`_trash` 不是技能，不收口
  就会凭空多出「待同步」条目）。

  **为什么单列而不并进 `outdated`**：两者的升级通道完全不同——`outdated` 走市场
  升级（`npx` 重装单技能），`repo_outdated` 只能同步整个仓库。若合并，「一键
  升级」会拿 npx 去重装仓库形态的技能并得到假失败，且「可升级 N」与技能列表又
  会开始对不上（v0.31.1 同类缺陷）。因此 `summary.repo_outdated` 单独计数、不进
  `summary.outdated`、不进「可升级」筛选段，市场页与技能表都不提供「升级」按钮
  （市场页显示「仓库待同步」，技能表远端列显示不可点击的 `tag warn`「待同步」）。

### 文档

- `DESIGN.md` / `DESIGN.html` 双向同步新增第五态口径表（适用条件 / 比对基准 /
  有更新判据 / 判不成的处理）与「为什么必须是独立状态」的论据。
- 新增 19 条断言（`tests/test_skill_repo_source.py` 7 条用**真实临时 git 仓库**
  跑，不 mock 命令；`tests/test_skill_market.py` 5 条守计数口径；
  `tests/test_dashboard_repo_updates.py` 7 条守 GUI 渲染分支与双轨规范），并对
  四处做负向验证后复原：① 把 `repo_outdated` 并回 `outdated` → 2 条红；
  ② 给待同步 tag 加可点击升级入口 → 1 条红；③ 删掉规范里的「不发网络请求」→
  1 条红；④ 去掉「只认已知技能目录」的收口 → 2 条红。
- 既有用例 `test_unregistered_skills_are_skipped` 更名并改写为
  `test_unregistered_skills_are_not_single_source_checked`：它断言的是 v0.31.2
  之前「无登记即跳过」的旧行为，本次属于有意的行为变更，改名是为了让后来者
  一眼看出口径换了，而不是偷偷放宽断言。

## [v0.31.2] - 2026-10-24

当前发布版本（build 129）。修复 v0.31.1 自带的一个用户可见计数矛盾：
技能列表显示 2 个「有更新」，点「一键升级」弹框却是 4 个。

### 修复

- **一键升级的条目数与技能列表不一致**：`--market check` 的判定候选原先只要
  lock 里 `registered=True` 就纳入，不看该技能目录是否还在。本机 lock 残留了
  两条 2026-04 装过、目录早已删除的登记（`data-visualization`、
  `logo-design-guide`），它们没有本地版本，于是走「按上游提交时间」兜底被判成
  `outdated`。技能列表按磁盘目录生成、画不出这两行（所以只有 2 个「有更新」
  标签），而「一键升级」取检查结果全量过滤 `state == "outdated"`，把 4 个都算
  进去——两个数字的差异就来自这里，用户看到的是「列表说 2 个、弹框说 4 个」。
  这正是「检查更新的候选该不该包含已经不在磁盘上的技能」这一口径缺失。

### 变更

- **检查结果新增第四态 `missing`（登记失效）**：lock 有登记、统一库中无目录的
  技能不再混进 `outdated`，单列 `missing` 且不发任何网络请求（没有本地内容可
  比对，查了也无处落地），`note` 说明为何不可升级。`summary` 增加 `missing`
  计数，`_recount` 改为按需累加（将来再加状态不会 `KeyError` 把检查炸掉）。
  未提供 `on_disk` 字段的调用方按「已安装」处理——少一个字段不该被误判成
  安装失效。
- **GUI**：市场页「登记失效」tag + `.list-meta.is-err` 语义色，且**不提供**
  「升级」按钮（无内容可覆盖，点了只会得到一条失败）；检查完成的 toast 与汇总
  行单独报 `missing` 数；「一键升级」再按 `SNAP.skills.skills` 过滤一次作为第二
  道防线，被剔除的条目用 toast 说明原因，避免将来后端口径再变时界面又出现
  自相矛盾。

### 文档

- `DESIGN.md` / `DESIGN.html` 记录检查结果四态与「**计数口径纪律**」：任何
  「有多少个可升级」的呈现（toast、汇总行、弹框标题与表格）必须同源取
  `summary.outdated`，`missing` 单独报数、不混入前者。
- 新增 11 条断言（后端 4 / GUI 4 / 语义类与规范 3），并对三处都做了负向验证：
  故意还原 bug 与删掉规范段落，确认测试确实报红后再恢复。

## [v0.31.1] - 2026-10-23

（build 128）。路线图 P0 #3 后半：**WebDAV 远程同步**，补上 v0.31.0
弹框承诺却从未实现的「升级前自动备份」，并把回滚与远程同步接出 GUI 入口；
另含两处门禁失真修复与设计规范的双轨同步。

### 新增

- **WebDAV 远程同步**（`core/webdav_sync.py`）：个人配置在多设备间同步。
  同步范围只含 `data/local_overrides.yaml`（端点拓扑）、`data/market_sources.yaml`
  （市场源偏好）、`data/skill_versions.json`（版本基准）；**不同步** `github_token`
  与技能包本体，`config.yaml` 的只读纪律不变（同步走 overlay 层）。
  冲突**不做自动合并**：push 先把远端旧值存 `<file>.remote-<时间戳>`、pull 先把本地
  旧值存 `<file>.bak-<时间戳>`，两端都改时不替你选，但两边的旧值都留着。
  凭据沿用 `data/github_token` 的文件通道模式（GUI 从 launchd 启动读不到 shell 环境
  变量）：`--set-webdav-url` / `--set-webdav-credential`（0600）/ `--webdav-status`
  （脱敏，只读）/ `--sync-webdav-push` / `--sync-webdav-pull`（写操作需 `--yes`）。
- **升级前自动备份**（`core/skill_market_ops.backup_skill`）：升级弹框一直承诺
  「本地内容会被上游覆盖，升级前自动备份」，但 `execute_plan` 此前只跑 `npx` 与
  安装后校验、**从未备份**。现在升级（install 无旧内容可留，故不备份）逐个技能整目录
  复制到 `data/skill_backups/<技能>/<时间戳>/`；备份失败不阻断升级，但会在结果里
  如实体现（调用方不得当作「已备份」）。
- **技能回滚**（`--list-skill-backups` / `--skill-rollback` / `--rollback-to`）：
  把技能回滚到最近一次升级前的备份，或指定某个备份路径。
- **GUI 入口**：技能 kebab 菜单「回滚到升级前」（无备份时给出可解释的空态，而不是
  一条点了没反应的路）；设置页通用 tab 新增「WebDAV 同步」卡片（远端 URL、凭据、
  状态、push / pull）。

### 修复

- **CI 单元测试失败（本地全绿、CI 挂）**：3 个 `execute_plan` 用例依赖本机真实存在的
  `~/.skills-manager/skills/<name>` 目录（`execute_plan` 内会调 `verify_installed`
  读文件系统），本机有目录所以通过、CI 干净环境没有所以失败。改为在测试内自建夹具，
  并新增 `scripts/ci_clean_env_check.sh`（临时 HOME 跑全量单测，显式保留原
  site-packages 搜索路径，否则连 PyYAML 都会因 HOME 变化 import 失败）接入门禁。
- **本地门禁误报 `skipped=3 ≠ CI 基线 2`**：10-21 新增 `tests/test_config_porter.py`
  引入一对 icloud 别名的互补用例（`on_macos` / `rejected_off_macos`，按 `sys.platform`
  恰好跳 1 条），skip 总数由 2 变 3，但 `CI_BASELINE_SKIPPED` 仍停在旧值，导致干净
  工作区上门禁变红。三个 skip 均为设计上的环境耦合（无 `~/.dsh`、icloud 平台互补、
  `SMS_SLOW_TESTS` 慢用例），非覆盖缺口；基线改为 3（Linux 与 macOS 下该总数恒为 3）。

### 重构

- **弹框宽度统一到 `--modal-w`**：此前五套弹框（`cfm-card` / `modal-form` /
  `task-card` / `ad-modal` / `upg-modal`）各自写死宽度，长期维护面大。改为统一走
  `--modal-w` 变量 + 修饰类覆写（§2.9 登记，改代码必须同步改规范表）。类名归并的
  可行性结论记录在 HANDOFF §3a。

### 文档

- HANDOFF v0.31.0（交付内容 + 版本比对教训 + 「本地过、CI 挂」防复发）、
  评审清单补 v0.31.0 十项修复的验收记录。
- **设计规范双轨同步**：`docs/DESIGN.html` 此前明显落后于 `DESIGN.md`（MD 改过 46 次、
  HTML 仅 14 次，最近 5 次 MD 改动一次都没同步）。本次补回缺失的 §2.3d（图例放置与
  对齐）、修正 §2.9 中 `.ad-modal` 属性记成 `width`（实际为 `--modal-w`）的事实错误
  与四处「token 写成已解析字面值」的隐患、§5 检查清单补 5 条、TOC 补 6 条锚点，
  并修正头部过期的章节/检查项计数。
- **补上承诺已久的反向门禁**：规范附录写着「两侧都不许单方面新增章节、由门禁双向
  比对」，但代码只实现了 HTML→MD 一条，于是 §2.3d 这种「MD 单方面新增整节」的情形
  门禁全绿。新增 `HtmlMdReverseMirrorTest.test_every_md_section_appears_in_html`，
  并做了反向验证（删掉章节标题后测试确实报错）。

## [v0.31.0] - 2026-10-23

（build 127）。路线图 P0 #4 前半：**技能版本管理 + 市场源可配置**，
外加 GitHub Token 配置通道、一键升级、概览页全量检查，以及 12 轮 UI 迭代与
多项计划外修复。

### 新增

- **技能版本管理**（`core/skill_state.py` / `core/skill_market.py`）：
  - 解析 SKILL.md frontmatter 的 `version`（本地与远端共用
    `parse_frontmatter_text`，含 `metadata.short-description` / `metadata.homepage`
    兜底，数值型 YAML 归一为字符串）
  - 升级成功后写 `data/skill_versions.json`（为后续回滚铺路）
  - 更新检查支持三态（有更新 / 最新 / 未知）+ 1h 缓存，**限流结果不写缓存**
  - 无版本号技能回退「上游 commit 时间 vs 本地安装时间」比对（按 `skillPath`
    过滤，不受同仓库其他技能提交干扰）
- **市场源可配置**（`core/market_sources.py`）：`skills-sh` / `github-repo` 两类源，
  默认回落 `[skills-sh]`，可增删改（`data/market_sources.yaml`，带备份）。
  按用户定案，QwenWork 与企业 MCP 不视为市场源。CLI：`--list-market-sources` /
  `--set-market-source` / `--remove-market-source`。
- **GitHub Token 配置通道**（`data/github_token` + `--set-github-token` /
  `--get-github-token`）：环境变量优先、文件回落（解决 GUI 从 launchd 启动读不到
  shell 环境变量的问题），配额 60 → 5000 次/小时。设置页 Skill tab 新增卡片，
  脱敏显示（前 4 后 4）+ password 输入 + 保存/清除。
- **技能升级**（`core/skill_market_ops.py` `plan_upgrade` / `execute_plan` +
  `--market-upgrade`）：单个升级（更新列 tag 可点击 / kebab 菜单）与**一键升级**
  （工具栏按钮，按顺序逐个）。
- **升级过程单一弹框三阶段**（确认 → 进度 → 完成）：批量确认用版本对比表格
  （四列定宽 + 分页），单个确认用版本对比条；进度阶段有进度条 + 逐技能状态行；
  完成阶段展示**版本变迁**（从什么版本到什么版本）与**失败原因**（换行缩进）。
- **概览页全量检查**：与托盘后台巡检同源（`--snapshot` + `--endpoint-status`），
  4 维度配置审计与端点连通性分组呈现。

### 修复

- **版本比对基准错误**（架构级）：原先拿 repo release tag 比技能 SKILL.md 版本。
  多技能 monorepo（如 `larksuite/cli`）的 tag 是**工具**版本（v1.0.98），技能包
  版本长期是 1.0.0，导致 27 个 lark-* 技能永久误报「有更新」——`npx skills
  update` 明确回 "All global skills are up to date" 而界面仍显示 22 个有更新。
  修复后比对链改为「远端 SKILL.md version → repo tag → commit 时间」，
  真机 outdated 22 → 1。
- **升级「exit 0 假成功」**：`npx skills update` 对上游迁移的仓库会输出
  "cannot be checked automatically" 却 exit 0，旧逻辑只校验目录存在 → 假成功。
  现在解析输出诚实报告；若上游在输出里给了重装命令，则**自动回退重装**
  （用户定案：重装也属于升级，结果一致即可）。
- 「可升级」筛选在未检查过时自动触发检查，并区分「尚未检查」与「确实没有」两种空态。
- 升级确认按钮文案「确认删除」→「确认升级」（danger 样式保留，文案可自定义）。
- 升级流程的 CLI 调用不再触发全局 busy 遮罩（会遮挡升级进度模态）。
- 版本列/更新列在无版本号时显示最后更新时间（三层兜底：lock `updatedAt` →
  SKILL.md mtime → `-`）。
- `profile_sources` 相对路径按 config.yaml 所在目录解析（此前按 cwd，GUI 子进程
  下 overlay 整体失效）。
- `renderEndpointStatus` 运行时错误（TDZ / 结构残留）。

### 变更

- 更新列 tag 直接显示远端版本号或日期（去掉「有更新 / 最新」文字前缀，语义移入
  `title`）。
- 技能表列名语义化：「版本 / 更新」→「**本地 / 远端**」（两列都可能显示 MM-DD
  日期，必须点明归属方）。
- 表格密度统一（升级确认表与主技能表同档 `sp-2`）。
- 升级模态 `min-width` 改用 `--modal-w` 变量体系。
- 补齐 `prefers-reduced-motion` 覆盖（进度条填充、行状态、弹框按钮过渡）。
- 装饰性内联 SVG 统一加 `aria-hidden="true"`（避免读屏器当独立节点播报）。
- 全量检查空态文案改为覆盖 4 维度 + 端点的完整表述。

### 已知限制

- 无版本号技能的时间比对是概率性判断（上游有提交不代表内容变更），note 已标注
  「按上游提交时间判定」。
- 技能升级依赖 `npx skills`（外部 CLI）；上游仓库迁移/删除时无法升级，仅能按
  npx 建议重装。
- `--skill-rollback` 回滚尚未实现（`data/skill_versions.json` 已就绪）。

## [v0.30.0] - 2026-10-21

当前发布版本（build 126）。Hook 命令变量插值补齐（v0.29.0 设计承诺）+ 配置导入/导出
（本地 + iCloud，路线图 P0#3 前半）+ 两项计划外修复（auto_discover overlay 断链、
default_command 引号加固）。

### 新增

- **Hook 命令写入时变量插值**（`core/hooks_fixer.py`）：补齐 v0.29.0 设计 §4.1
  承诺但未实现的 `{event}` / `{agent}` / `{server_url}` 插值——此前 template 命令
  原样写入，用户应用「日志记录」预设后客户端执行的是字面 `{event}`（坏命令）。
  `{event}` → canonical snake_case 事件名；`{agent}` → `agent_slug`（缺省客户端名
  slug 化）；`{server_url}` → 活动 profile URL（取不到保留占位符原样）。字面
  `str.replace` 实现：未识别 `{xxx}` / `${VAR}` 天然保留、无占位符 no-op（旧命令
  零影响）；dry-run 消息附插值样例。`tests/test_hook_interpolation.py` 15 例。
- **配置导入/导出**（`core/config_porter.py` + CLI + GUI，路线图 §4c P0#3 本地+iCloud）：
  - `--export-config <path|icloud>`：导出为单 JSON（生效视图 + 端点库
    `auth_token` 脱敏 + 自动发现清单）；`icloud` 别名解析为 iCloud Drive 固定路径
    （仅 macOS）；`--skip-discovered` 省略发现清单；dry-run 不落盘。
  - `--import-config <path|icloud>`：合并导入（导入值优先、不删除本地已有键），
    **按各键正典通道分流**（overlay 键写 overlay、settings/hooks 走 text-rewrite
    trunk 保注释、discovered 按 name 去重）；遇 `<redacted>` 占位的密钥跳过并
    保留本地值；导入前对将改文件各生成真实备份（`shutil.copy2`）；语义值相同
    不写盘不虚报。`tests/test_config_porter.py` 20 例（含 CLI 端到端与隔离断言）。
  - 设置页通用 tab 新增「配置导入 / 导出」卡片（`#cfg-port-card`）：路径输入 +
    导出/导入按钮；导入前 confirmModal 说明合并语义；行内控件 flex 布局
    （不写 inline `width:100%`，v0.29.1 裁剪教训）。DESIGN.md §2.10 增补规范，
    `ConfigPortCardContractTest` 3 断言（含反向验证）。
  - Rust `run_cli` 白名单加 `--export-config` / `--import-config` /
    `--skip-discovered`。
- **text-rewrite 函数抽取**（`core/config_text.py` 新模块）：把 scan.py 的 6 个
  保注释改写函数抽到 core（config_porter 复用正典通道；同 B 轨 config_codec
  先例），scan.py import 引用，调用点与既有测试零改动。

### 修复

- **`apply_profile_sources` 合并 overlay 的 `auto_discover`**（v0.28.0 断链）：
  `--set-auto-discover` 写 overlay 后 `load_config` 读回的仍是 trunk 值（本函数
  此前不合并该键），开关形同虚设——本机恰好 trunk/overlay 同值才未暴露，v0.28.0
  测试只验「写入打印」没验「写后生效」。修法与 `unified_skills_dir` 的 B3 fix
  同构（浅合并、overlay 键覆盖、未声明键保留 trunk 值）；补
  `test_written_value_takes_effect_on_reload` 全链路回归。
- **`_set_default_command_in_text` 引号风格加固**：旧正则只认双引号值，单引号
  （`''`）或裸值风格的行会静默不匹配（sub 无效果返回原文）；现支持三种既有
  风格 + `json.dumps` 转义命令内引号；补 6 例单测（此前零覆盖）。

## [v0.29.2] - 2026-10-19

当前发布版本（build 125）。v0.29.1 的文档/规范/测试收口版：补全 PRD 文档同步、
README 命令清单、DESIGN.md 规范字面规则、v0.29.1 修复的测试轨断言，以及设置页
「关于」卡片挂载；无功能代码（`scan.py` / `core/` / `src-tauri/src/lib.rs`）变更。

### 新增

- **设置页「关于」卡片**（`gui/dashboard.html`）：设置页 appearance tab 末尾挂载关于
  卡片（应用名 / 版本 / 许可 / 说明），版本号与页脚同源（`SNAP.app.full`）。此前
  `.about-card` CSS 已预留但未挂载、版本信息仅散落页脚；现复用预留样式落地。
- **v0.29.1 布局修复的可失败断言**（`tests/test_design_spec_contract.py`）：
  新增 `HookTemplateLayoutGuardTest` 两条断言，守住 `#hook-tmpl-body .row .v` 的 8 项
  flex 修复属性齐全 + 控件用 `flex:1 1 auto` 填充（不回归 inline `width:100%` 缺陷
  根因）。经反向验证（临时改 `overflow: visible`→`hidden` 即精确失败）。

### 变更（文档同步）

- **PRD §8 缺口#1 关闭**（`docs/product/PRD-产品需求文档.md`）：
  `--set-auto-discover` / `--set-active-profile` 两条写命令早于 v0.28.0 落地
  （DESIGN.md §2.10 标 2026-10-15 补齐），但 PRD §8 缺口表仍标「🟡 待实现」、
  §6.4 仍写「编辑待后端命令」。现同步为「✅ 已关闭 / v0.28.0」，§6.4 改为写、
  P-3 定案段重写为「v0.28.0 落地」。
- **README 命令速查补全**（`README.md`）：新增「Hook 命令模板（v0.29.0）」与
  「设置（通用配置）」两组，列出 `--list-hook-templates` / `--set-hook-template` /
  `--apply-hook-preset` 与 `--get-setting` / `--set-setting` / `--set-active-profile`
  / `--set-auto-discover`（此前速查表零命中）。
- **DESIGN.md §2.10 兜底 CSS 字面规则补全**（`docs/DESIGN.md`）：v0.29.1 修复规则
  在 `dashboard.html:1271` 全 8 项，但 DESIGN.md:694 仅回写 6 项；现补全
  `flex: 1 1 auto` / `min-width: 0` / `flex-wrap: wrap`，规范↔代码字面级镜像对齐。

## [v0.29.1] - 2026-10-18

当前发布版本（build 124）。v0.29.0 的补丁版：只修 §3.7b「写入命令模板」卡片的一处渲染缺陷，
无新增功能。

### 修复

- **「写入命令模板」卡片把同一行的兄弟节点裁掉 —— 按钮与提示「排布了、但不绘制、也点不到」**
  （`gui/dashboard.html`，v0.29.0 引入）。受影响三处：「应用预设」按钮、「默认命令」输入框后的
  「（全局兜底，应用到所有客户端；空=跳过未定义事件）」提示、旧命令行的 `.tag.warn`「旧」标。
  三者在无障碍（AX）树里都有真实 frame、`AXEnabled=true` 且可触发 `AXPress`，但对应像素区
  全白 —— 用户看得到输入框，却找不到也用不了这三样。根因：这些行渲染时给控件加了 inline
  `width:100%`，而控件所在的 `.row .v` 是 **max-content 定宽 + `overflow:hidden`**，控件撑满后
  其后的兄弟节点落到 `.v` 之外被裁掉（是**布局裁剪**，不是透明或 display 隐藏）。
  修法：控件改为 flex 填充（inline `min-width:8rem;…`，由作用域规则驱动布局），并新增规则
  `#hook-tmpl-body .row .v { display:flex; align-items:center; gap:var(--gap-2); flex:1 1 auto;
  min-width:0; flex-wrap:wrap; overflow:visible; white-space:normal; }` —— `.v` 自己填满整行，
  下拉不伸长、输入框吃掉剩余宽度、提示可收缩换行；「默认命令」另用 24rem 下限（`isWide`），
  故窗口收到最小宽 900pt 时提示换行到独立一行而不是溢出卡片。
  缺陷取证、CDP 独立复验（含变体 V1/V2/V3 实测与窄宽度边界）见
  `docs/superpowers/HANDOFF-v0.29.0.md` §7f；组件约束已回写 `docs/DESIGN.md` §2.10。

## [v0.29.0] - 2026-10-17

当前发布版本（build 123）。

### 重大变更：剥离 ai-memory + Hook 写入命令可配置

ai-memory 是早期绑定的外部 MCP 服务，其命令被硬编码进 `config.yaml` 的 hook
template。v0.29.0 全面剥离：Hook 写入命令完全由用户自定义，产品不再内置任何
特定工具的命令。详见 `docs/superpowers/specs/2026-10-16-hook-write-configurable-design.md`。

#### 新增

- **Hook 命令模板可配置**（`config.yaml`）：`hooks.default_command`（全局默认，
  空 = 不写兜底、跳过该事件）+ `hooks.clients[].agent_slug`（用于 `{agent}` 变量插值）。
- **profile 显式声明 `hooks_required: true`**：解耦 —— hook 是否 required 不再寄生
  在能力组键名上（`combined_checker` 改读 `expected.get("hooks_required")`）。
- **反向守护断言** `test_no_ai_memory_in_trunk_sources`：把 §6b 强 grep 升级为 CI 门禁。

#### 变更

- `hooks_inventory.HookEntry.is_ai_memory` → `is_configured`（命令非空即 True，
  不区分来源）；`hooks_fixer._default_hook_command` 返回空（不写兜底）；写入去重
  改命令级（要写的命令字面已存在才跳过）；移除 Hook 改为清除全部 hook 条目（含第三方）。
- `fix_supported` 运行时重算：`declared and (has_agent_slug or has_template)`，
  template 清空且无 slug 时降为 effective false。
- `config.yaml` 各客户端 `template` 清空为 `{}`；OpenCode 配置路径中性化。
- 提取公共解析原语 `_load_toml_file` / `_find_in_dict` / `_extract_hook_commands`
  到 `core/config_codec.py`（一处定义、两处复用）。

#### 删除

- `core/ai_memory_checker.py`（ai-memory 专属检查器，566 行）
- `scripts/unified_mcp_server.py`（ai-memory HTTP 网关代理，827 行）及 `_redact` 脱敏机制
- `core/legacy_checker.AI_MEMORY_DETECTION` 常量（`DEFAULT_DETECTIONS` 退化为只检 hermes）
- `combined_checker` 的 `ai_memory_available` 字段 + `CAPABILITY_DISPLAY_NAMES` 的 ai_memory 键
- 测试 `test_ai_memory_section_guard.py` / `test_unified_mcp_server.py`（共 28 用例）

#### CLI（保留别名，向后兼容）

- `--ai-memory` / `--fix-ai-memory` 保留为纯别名，help 标已废弃；
  `--ai-memory` 等价 `--mcp --hooks`，`--fix-ai-memory` 转发到 `--fix-mcp`。

## [v0.28.0] - 2026-10-15

v0.28.0（build 122）。

### 新增

- **Hook 事件词表扩容 + 客户端能力集**（`config.yaml` / `core/hooks_*` / `gui/dashboard.html`）。
  事件从 4 个标准事件扩到 **47 个规范事件**（Claude Code 33 / WorkBuddy 29 / Cursor 21 /
  Codex 12 / TRAE 6 官方集的并集，逐客户端以官方文档为准、本机配置为旁证）；
  每个客户端声明自己的**能力全集**（`hooks.clients[].events`）与**分层作用域**
  （`scopes`：用户级 / 项目级 / 本地级 / 托管级）。GUI 的 Hook 事件表按 `group` 分组渲染。
- **「客户端事件命名规范」并入 IDE / Agent 详情**（用户要求）：新增「Hook 配置」区块，
  展示配置文件、分层作用域、事件命名、支持事件数与清单（已写入的用 `.tag.ok` 标注）。
  客户端清单/路径/命名规范只此一处维护，不再与 Hook tab 双份漂移。

### 变更

- **Hook 检查改为「只看有没有配置，不看配置内容」**（用户要求）。某事件下只要存在任意
  hook 条目即算「已配置」——命令写的是什么、是不是 ai-memory、是不是第三方工具，一概不
  参与判定。此前只统计「命中 ai-memory 命令签名」的事件，于是同一事件被别的工具占着时
  报「未配置」，而客户端**其实配了这个 hook**；更根本的是该判据与「写入什么内容」耦合，
  而写入内容尚未定案，判据不该依赖未定的东西。相应地，「缺关键事件」= 该客户端支持但
  完全没有配置的事件。GUI 文案同步：`已写入` → `已配置`（列表列、图例、卡片摘要、详情
  事件清单），规范 §2.3b/§2.3c 已更新。
- **移除仓库内全部第三方桥接工具（codeisland）信息**：`core/checker.py` 里它曾作为
  Codex 的安装探测路径之一（实测本机不存在该 app，且 Codex 经 `ChatGPT.app` 正常识别，
  删除无影响）；注释、CHANGELOG、两份取证 JSON 中的具名引用一并改为中性说法。


- **IDE / Agent 列表视图新增 Hook 列（与 MCP 同待遇）**：用户要求「在 IDE 的 tab 中增加 hook 的
  配置和 scale，和 MCP 一样」。列序变为 `名称 | 类型 | 安装 | APP | CLI | CONFIG | 技能目录 |
  MCP | Hook | 操作`，并补一条与 MCP 图例同款的 Hook 图例（复用既有 `.skill-legend`）。
  四态：全部已写入 `N/M`（ok）/ 部分已写入 `N/M`（中性）/ 未写入（warn）/ 仅审计（na）。
  另加**分层作用域徽标 `.al-scope`**（形如 `4 档`，与 `.al-metric` 同族但更弱：虚线边框 +
  `--faint`、不做 accent 高亮），`title` 给出作用域含义。
- **Hook 列区分「未收录」与「不支持」**：未登记 Hook 配置路径的客户端显示 **`未收录`**，
  **不得**显示「不支持」。依据：22 个已安装客户端里只有 6 个登记了 `hooks.clients`，
  一律写「不支持」等于断言"该客户端没有 Hook 能力"，属过度断言；与 Hook 业务页
  `_hooksEntries` 只列"有 `hooks_config_path`"的客户端同口径。规范新增 §2.3c 登记列序、
  四态、以及这条口径分界。


- **修掉分隔线残留的 3px 错位（实测定位，非目测）**：卡片的 `.ac-path-none`（「未收录 Hook 配置」）
  与 `.ac-path-val` 度量不一致 —— 空态少 1px 字号，且缺那条 `border: 1px solid transparent`
  （值胶囊为 hover 不抖动而留），合计 3px。于是"HOOK 未收录"的卡片 meta 带矮 3px；而分隔线用
  `margin-top: auto` 锚定卡片底部、**前提是 meta 带高度恒定**，所以整条线上移 3px、跨卡片错位。
  这正是用户三次反馈"没对齐"的真因。修法：统一 `font-size` / `line-height` / `padding` /
  `border` / `font-family`。实测（真实数据 2/3/4/5/6 条路径共 8 张卡片）meta 高度恒为 109、
  两条分隔线 Δ=0（`metaTop 194/194`、`600/600`、`949/949`、`1271/1271`）。
  规范 §2.3b 已登记该根因，护栏为 `test_value_and_empty_have_identical_metrics`。


- **分隔线恢复并定案对齐机制：锚定底部**（用户第三次反馈：分隔线很重要、上一版不好看）。
  卡片内有两条整宽分隔线（能力区上沿、底栏上沿），两者都必须对齐。机制改为**自底向上**：
  `.ac-meta` 用 `margin-top: auto` 把 meta+foot 整块贴底，故线① y = 卡片底 − (meta 高 + foot 高)；
  `.ac-foot` 用 `margin-top: 0` 且不伸缩，线② y = 卡片底 − foot 高。两者都是与路径条数无关的
  常量 ⇒ 必然对齐。路径区保持 `flex: 0 0 auto`（不伸缩、不裁切）。实测两条线 y 完全相同
  `[205, 314]`。代价：路径少的卡片在线①上方留一段空白。
- **修正 Skill 与 MCP/Hook 样式不一致**（用户提问「为什么 Skill 的样式和 MCP、hook 不一样」）：
  根因是淡化变体 `.is-dim` 设了 `border-color: var(--line)`，而默认胶囊是透明无边框 —— 于是
  同一张卡片里 Skills 显示成方框、MCP/Hook 是纯文本。现规定 `.is-dim` **只改颜色不改形状**
  （border-color 改 transparent），并让三行（Skills / MCP / Hook）在未安装时**统一淡化**。


- **分隔线对齐定案：卡片内只保留一条线**（用户两次反馈后改机制）。上一版让路径区
  `flex: 1 1 auto`「吸收」路径条数差异，实测两个问题：① 内容超出时路径区收缩，**末行被
  裁进分隔线里**（截图可见）；② 分隔线位置仍随条数错开。原因是整宽内部分隔线的 y 位置
  **结构性地**取决于上方路径条数（Cursor 3 条 vs VS Code 4 条），拉伸只能掩盖。
  现改为：能力区去掉整宽分隔线（改用 `--gap-3` 留白分组）；卡片内唯一的分隔线是底栏上沿，
  其位置恒定靠三件事：`.agent-cards` `align-items: stretch` + `.ac-foot` `margin-top: auto`
  + `.ac-foot` `flex: 0 0 auto`。路径区恢复 `flex: 0 0 auto`（不再裁切、不再留空白）。
  代价：内容少的卡片在底栏上方留一段空白（等高 + 贴底的必然结果）。规范 §2.3b 已改写。


- **卡片分隔线跨卡片对齐**（用户要求「分隔线永远是对齐的」）：同一行卡片等高，但路径条数
  可能不同（Cursor 3 条 vs VS Code 4 条），路径区高度随内容时，其后的能力区上沿与底栏上沿
  会错开一整行。修法三条缺一不可：`.agent-cards` 显式 `align-items: stretch`（前提）、
  路径区 `flex: 1 1 auto`（吸收条数差异）、`.ac-meta` / `.ac-foot` `flex: 0 0 auto`（不跟着变高）。
  实测（headless 渲染 + 逐行像素扫描）3 条与 4 条路径的两张卡片内部分隔线 y 坐标完全一致
  `[204, 217, 240, 313, 360]`；改回不伸缩即错位。规范 §2.3b 已登记该规则与代价。


- **设置页 Agent 卡片排版精修**（用户反馈「不够精细好看」，按 taste 规则择取适用项）：去掉每行
  常驻的**装饰性 6px 圆点**（不表意，「空」已由「未收录」文案说明，`.is-empty` 改为标签
  `opacity:.72` 保留语义）；值区改 **flex nowrap + 首元素自适应**，状态标签恒贴右成一条竖线
  （此前长路径会把标签挤到第二行并缩进，TRAE 卡片实测）；路径列表改**单列网格**使路径等宽
  （消除右边界锯齿）；路径**默认无底色**、悬停才浮出胶囊（一张卡片近十个灰块会读成表单输入框）；
  区间距对称化、底栏去灰底、内边改用标准档；`已写入 N/M` **仅全部写入才用 ok 色**（部分写入
  报绿属状态色语义错误）。规范 §2.3b 已同步这些规则与理由。


- **未安装客户端的 skills 目录改为淡化显示**（用户选方案 A）：未安装时该路径来自内置
  注册表的「默认位置」，不代表本机状态，却与同行右侧的「不适用」标签同样醒目，读起来
  自相矛盾（Cursor 卡片实测）。新增 `.ac-path-val.is-dim` 变体（`--faint` +
  `transparent` 底）：状态语义交给「不适用」，路径退为背景信息，但仍保留胶囊形态以支持
  点击复制；**已安装时不得淡化**。规范 §2.3b 已登记该变体与判据。


- **卡片标签列对齐修正**（用户截图反馈「最好保持对齐」）：设置页 Agent 卡片的
  「路径区」（APP/CLI/CONFIG）与「能力摘要区」（Skills/MCP/Hook）此前是**两套几何** ——
  路径区 `grid` + 58px 标签列且无竖线，摘要区 `flex` + `.k` 宽 74px 且带 `border-right`，
  于是值区起点差 16px、字体族与分隔线也不一致，一眼看出错位。现统一为同一套标签列
  （58px + `--gap-4`，标签同族 mono/`--fs-2xs`/大写/`--faint` + 6px 圆点，两组都不加竖线），
  并把「支持 N」并进「已写入 N/M」的分母，使 Hook 行胶囊从 3 个减到 2 个、不再换行错位。
  对齐不变量由 `CardLabelColumnAlignmentTest` 逐属性比对，规范新增 §2.3b 与 §2.9 硬数字行。


- **设置页「保存 Hook 事件」只保存选择，并改用弹框反馈**（用户三项反馈）。此前用页面级
  `.banner` 展示结果，失败时把 CLI 的整段 stdout（技能扫描报告，实测 1600 字符）直接铺在
  页面上；文案还写成「保存后按各客户端命名规范写入其 hook 配置文件」，让人以为保存即写入 IDE。
  现在结果走 `runTaskModal`（`.task-card` + 可折叠详情，错误详情先过 `cliFailLines`），
  文案明确「只保存要写入哪些事件的选择；真正写入请在「Hook」页点「写入 Hook」」。
- **`--set-setting` 改为独立早返回出口**（上一条的根因）：它此前排在 11 阶段主流程末尾，
  一次纯设置写入会顺带跑完整个审计并**继承审计退出码** —— 本机 6 个技能目录缺失，写入明明
  成功却以 1 退出，GUI 据此判「保存失败」。现在退出码只反映写入本身（0/2），输出仅 6 行；
  `resolve_modes` 同步把它标为显式模式。
- **设置页 IDE/Agent 卡片与列表直接展示能力摘要**（用户三项反馈之三）：卡片新增
  Skills / MCP / **Hook** 三行（复用 `.ac-meta` / `.ac-meta-row`），列表新增「能力摘要」列
  （分层作用域档数 / 支持事件数 / 已写入数），不必点开「详情」。引擎侧为 `mainstream_tools`
  补齐 `skills_*` / `mcp_*` 摘要字段（经 `_agent_entry` 复用，与 agents 面板同源，避免口径漂移）。
- **规范明确「数据区错误」与「操作结果」的分界**：数据区自身状态就地显示；一次操作的结果
  走弹框（`runTaskModal`）；`.banner` 只留给非阻塞的页面级告知。


- **Hook 事件默认全选，并新增「全选 / 清空」**（用户要求）：此前
  `settings.hook_events: []` 意味着开箱即**一个都不勾**（`--fix-hooks` 直接判
  「已选择不写入任何 hook 事件」），与预期相反。现出厂即列出全部 47 个规范事件；
  卡片头部新增 `.ghost.sm` 的「全选」/「清空」—— 二者只改本地勾选态，仍需点
  「保存」才经 `--set-setting` 落盘。
- **IDE / Agent 详情完整显示**（用户要求）：弹窗宽度 `min(680px, 94vw)` →
  `min(880px, 94vw)`（已登记 §2.9）；Hook 分层作用域路径改用新的
  `.ad-e-loc-full` —— `white-space: normal` + `word-break: break-all`，
  **不再用省略号截断**（路径本身就是信息）。MCP 条目的长 URL 仍保留省略号 + title。
- **「缺关键事件」审计基准再收一道**：改为「选中 ∩ 能力 ∩ `template` 键」。
  默认全选后若直接取「选中 ∩ 能力」，Claude Code 会一次报 33 个「缺失」——
  那是默认状态而非异常，会把页面淹没成假警报。
- **IDE / Agent 列表视图 UI 排版优化（六批迭代，均走规范登记 + 断言 + 反向验证）**：
  ① 图例色点补 `neutral` 变体（「部分已配置」原为零宽无色）；图例标签列定宽 31px，
  消除 MCP/Hook 两条图例色点 2px 错位。
  ② 图例位置：曾把 5 处图例移到内容最下方，用户看实际渲染后定案「还是放在上面好看」，
  回退；断言反向为 `test_legends_come_before_their_content` 钉住。
  ③ 行内状态统一：安装 / 技能目录列从纯着色文字（`.ok-true` 族）改为图标徽标
  （`.al-ico`，20px 与 `.al-metric` 同族）；新增 `link` / `folder` / `minus` 图标；
  MCP / Hook 的「不支持 / 未收录 / 仅审计」改中性 `.tag` 胶囊。每枚徽标带 `title`
  + `.sr-only`（WCAG 1.4.1）。规范 §2.3c 新增「行内形态」映射表。
  ④ 图例撤销：IDE / Agent 页两条图例整块删除（用户：全部有图例太多太长），语义移入
  列头 `data-help` 自绘气泡（`.th-tip`，`showThTip` 渲染到 `#pop-root`）。原生 `title`
  在 WKWebView 实测不弹出，故必须自绘；图例行（`#` 前缀）渲染与表内同款的图标徽标 /
  色点。列头带 `.th-help` 问号图标 + `tabIndex` 键盘可达。规范 §2.3c 新增气泡组件
  登记与图例行格式说明。
  ⑤ 列宽治理：`table-layout: fixed` + 8 个紧列定宽（headless Chrome 实测内容并集 +
  20px 内边，向上取 4 的倍数），名称 / 类型文本列弹性。三窗口宽度实测零溢出、零横向
  滚动，整表余量 917→574px；状态列（3 / 7 / 8 / 9）`th` / `td` 居中（实测偏差 0.0px）。
  规范 §2.3c 新增列宽表与治理说明；护栏为 `ColumnWidthGovernanceTest`。
  ⑥ Hook 列去盒化：`.al-scope` 档数注记去掉虚线描边，降为 `--faint` mono 裸文本，
  消除「同格两种盒子」的视觉噪音（taste-skill §4.4：盒子只承载主信息）；Hook 列宽
  122→104px。规范 §2.3c 登记；护栏为 `test_al_scope_is_deboxed`。
  以上六批均同步更新 `docs/DESIGN.md`、`tests/test_design_spec_contract.py`（含反向
  验证）、`tests/test_dashboard_mcp_ui.py`；幽灵类基线收紧（`mcp-badge-legend` 移除）。
  全量 1194 tests OK，CI 四 workflow 全绿。

### 修复

- **写入端不再硬写客户端不认的事件**：此前「勾了就一定写得上」（用兜底命令硬写），
  会把 Cursor 独有的 `BeforeTabFileRead` 写进根本不认识它的 Claude Code。现按客户端
  能力集过滤并回报 `skipped`。
- **Cursor 的 hook 条目结构写错**：本机实测 `~/.cursor/hooks.json` 是**扁平**
  `{type, command, matcher}`，而写入端一律按 Claude/TRAE 的嵌套
  `{matcher, hooks:[...]}` 写 —— 产物 Cursor 不认。现按客户端 `entry_style` 分别渲染。
- **TRAE 事件命名规范配错**：`event_format` 原为 `camel_case`，与官方文档（6 类
  PascalCase 事件）不符；本机 camelCase 键实为第三方桥接工具写入。已改为 `pascal_case` 并按官方六类收录。
- **「缺关键事件」审计假警报**：改为由**写入意图**（`settings.hook_events` ∩ 能力，
  或回落 `template` 键）推导，而不是由能力全集推导 —— 否则 Claude Code 会把 29 个
  「支持但本次没打算写」的事件全报成缺失。

## [v0.27.1] - 2026-10-11

当前发布版本（build 121）。

### 修复

- **Hook 设置表格溢出（用户截图反馈「超过边界」）**（`gui/dashboard.html`）。两层原因：
  ① 我用 `<div class="table-wrap">` 包表格，而**该类在 dashboard 的 CSS 里没有规则**
  —— 页面不报错、门禁全绿，却没有 `overflow` 容器，表格宽到撑破卡片
  （`.table-wrap` 只存在于 DESIGN.html；dashboard 的真实容器是 `.table-scroll`）；
  ② 「写往」列把 6 个 `客户端:事件名` 内联成一格，本身必然过宽 —— 按规范 §2.2 的
  既有先例改为「N 个客户端」+ `title` 详情。
- **`.dot-ok/-warn/-idle` 平行实现删除**：上一轮替换 emoji 时新增的这套类，与既有的
  `.dot.ok/.warn/.err/.faint`（更完善，带 `box-shadow` 环）并存成两套，违反规范
  「先找现成组件」→ 统一用既有组合类。
- **`.btn-sm` 无样式**：规范登记的是 `button.sm`（`btn-soft sm`），代码里写的是
  `btn-sm` → 改为 `sm`。

### 新增

- `ComponentRegistrationTest` 扩充三条门禁：**幽灵类棘轮**（markup 用的类必须在 CSS
  有规则；存量 11 个冻结在 `GHOST_BASELINE`，只许减少）、**状态点必须用既有组合类**
  （禁止 `.dot-ok` 平行实现回归）、规范引用的类必须真实存在。
  两条新判据均经变异验证（注入 `.table-wrap` / `.dot-ok` 即失败）。

## [v0.27.0] - 2026-10-11

当前发布版本（build 120）。

### 变更

- **设置页的 Hook tab 改为「管理要写入哪些生命周期事件」**（`gui/dashboard.html`、
  `scan.py`、`core/hooks_fixer.py`、`core/hooks_inventory.py`、
  `core/management_snapshot.py`、`docs/DESIGN.md`）。此前该 tab 展示的是各 IDE/Agent 的
  接入状态 —— 那是 **Hook 业务页**的职责；Skill / MCP 两个 tab 管的都是**配置本身**，
  Hook 应当一致。现列出 `config.yaml` 的 `hooks.events` 全部标准事件（勾选框 + 事件名 +
  说明 + 写往哪些客户端），保存写入 `settings.hook_events`；另加只读的
  「客户端事件命名规范」表。

### 修复

- **「写哪些 hook 事件」此前散落在各客户端 `template` 里，导致 Codex 的
  `UserPromptSubmit` 永远补不上**。`hooks_fixer` 只读 `hooks.clients[].template`，
  而 Codex 声明支持 `UserPromptSubmit` 却在 template 里没有它 → 审计报
  「缺 UserPromptSubmit」，写入却永远不补（假警报）。
  现改为：`settings.hook_events` 给出标准事件名，`--fix-hooks` 按各客户端
  `event_format` 转成规范名（pascal/camel）后写入。新增 `event_name_for_client()`
  承担这套映射（此前靠 template 的 key 手写，无法统一管理）。
  全局列表选中某客户端 template 没有的事件时用 `ai-memory hook --event <snake_case>`
  兜底 —— **不允许静默漏写**。实测 Codex 的该事件终于写入，且与既有的第三方
  hook 并存不冲突（审计 `missing_key_events` 由 `['UserPromptSubmit']` 变为 `[]`）。
- **`--set-setting` 支持列表值**：`_render_scalar` 渲染块序列，`_set_setting_in_text`
  支持多行插入/替换；空列表显式写 `[]`（第一版返回空串走单值分支，导致**清空时旧元素
  残留**，实测发现并修复）。config.yaml 的注释全程未丢。
- **区分「未配置」与「空列表」**：键不存在 → 回落 template（向后兼容）；键存在但为
  `[]` → 用户明确的**停用**选择，不得回落，返回 `unsupported` 并给出明确文案
  （而非含糊的 `missing`）。
- **`management_snapshot` 补 hook 事件三字段**（catalog / selected / clients），
  GUI 才有数据可渲染。

### 测试

- 新增 `tests/test_hook_events_config.py`（7 例）：命名转换、全局列表覆盖 template、
  camel 客户端拿到 camel 名、未配置时回落 template、空列表不写入、非 ai-memory hook
  保留。其中「空列表」一例抓到并修掉了上述语义缺陷。

## [v0.26.1] - 2026-10-11

当前发布版本（build 119）。

### 变更

- **设置页的 Hook 从「IDE / Agent」内的一张卡独立成一个 tab**（`gui/dashboard.html`、
  `docs/DESIGN.md`）。设置页由四个 tab 变为五个（通用 / Skill / IDE·Agent / **Hook** /
  MCP）；Hook tab 承载完整能力而不再只是「只读总览 + 跳走」：卡①接入状态
  （客户端 / 状态 / 已接入事件 / 缺关键事件 / 写入·移除 + 一键写入），卡②配置依据
  （客户端 / Hook 配置文件 / 是否可写入 / 映射事件）。写入动作复用既有
  `--fix-hooks` / `--remove-hooks`，不复制逻辑。
- 数据源与 Hook 页共用 `_hooksEntries()`（合并 `mainstream_tools` +
  `_agentsForPanel()` 并按 `name|path` 去重）—— 各写一份过滤会出现两页数量不一致。

### 修复

- **`missing_key_events` 从未透传到 GUI**（`core/management_snapshot.py`）。
  `hooks_inventory.inventory_for_tool` 早就产出该字段，快照函数也调用了它，但只透传了
  `hook_events` / `hooks_inventory` 等，**漏了 `missing_key_events`** —— 于是 GUI 读到的
  恒为 `undefined`，Hook 页的「缺关键事件」列**一直是空的**（空列不像 bug，所以长期
  未被发现）。已在 `agents` 与 `mainstream_tools` 两处补传。补传后该列有了真实内容：
  Claude Code 缺 4 个事件、Codex 缺 `UserPromptSubmit`、WorkBuddy 缺 3 个。

## [v0.26.0] - 2026-10-11

当前发布版本（build 118）。

### 新增

- **设置页补「后台巡检（定时检查）」与「生命周期 Hook 配置」**（`gui/dashboard.html`、
  `docs/DESIGN.md`）。用户报告「设置里少了定时检查的配置和 hooks 的配置」；核查确认
  两项的**功能层都已完整，只是 GUI 设置页没有入口**：
  - **定时检查**：`config.yaml` 的 `settings.patrol_enabled` /
    `patrol_interval_minutes` 已存在，CLI `--get-setting` / `--set-setting` 已支持，
    Rust 托盘也有「后台巡检」勾选项（读同一份值），但设置页无入口。现于**通用 tab**
    新增卡片（开关 + 5/15/30/60/120 分钟）。取值**不用 localStorage**，而是经 CLI
    写进 `config.yaml` —— 与托盘开关同源，否则会出现托盘显示"已开"而实际没跑。
    写后**回读 CLI 落盘值**再重渲染（CLI 会把间隔钳到 ≥5 分钟，不回读会显示未生效的值）。
  - **Hook 配置**：Hook 页已能看接入状态并写入/移除，但**没有一处能看到配置依据**
    （标准事件、各客户端目标文件与事件映射），只能打开 `config.yaml`。现于
    **IDE / Agent tab** 新增只读总览卡片，数据直接取 `--management` 快照已有的
    `mainstream_tools[].hooks_*`（不额外发请求）；写操作仍集中在 Hook 页并提供跳转，
    避免两处写入入口语义分叉。

### 文档

- 规范新增 **§2.10 设置页**：登记设置页四个 tab 与各卡片的归属、两项新配置的取值来源，
  并写明「取值来源必须与唯一事实来源一致：偏好类用 localStorage，跨进程共享类用
  `config.yaml` 并经 CLI」。MD 与 HTML 双向镜像同步。

### 修复

- 开发过程中由既有门禁抓到的两处自身错误（记录以备后鉴）：
  - 新代码用 `—`（em-dash）作空值占位符，被 `test_dashboard_design_tokens` 拦下
    （规范 §3 明令禁用）→ 改为连字符。
  - `let _patrolInterval = PATROL_INTERVAL_DEFAULT` 写在常量声明**之前**，触发
    TDZ（`Cannot access … before initialization`），**整个顶层脚本抛错、所有按钮
    失效**。由 `test_dashboard_scope` 的 node harness 真跑脚本时抓到 —— 静态检查与
    54 条设计门禁都看不出这类问题。

## [v0.25.5] - 2026-10-11

当前发布版本（build 117）。

### 修复

- **组件登记门禁：规范的核心承诺此前没有任何门禁**（`tests/test_design_spec_contract.py`、
  `tests/_component_baseline.txt`）。规范 §2.1 写着「新增按钮变体时必须回来登记到
  本表」、§5 清单写着「若新增组件或变体，已回写本文件对应章节」—— 这两条**此前没有
  门禁**；既有的 token 完整性断言只覆盖 `:root` 的 CSS token，完全不覆盖类名。
  后果实测：上一轮把 emoji 换成 CSS 类时新增了 `.dot-ok` / `.dot-warn` / `.dot-idle` /
  `.th-ico`，**一个都没回写规范**，而 51 条门禁全绿。
  新增 `ComponentRegistrationTest`（3 条判据）：① 幽灵引用（规范引用的类必须存在于
  代码，否定式提及豁免）；② 新增语义类必须先登记（与冻结基线比对，粒度遵循规范
  §附「只守有独立语义的顶层组件」）；③ 必登项不得从规范消失。三条均经变异验证。

- **规范幽灵引用与归属错误**（`docs/DESIGN.md`、`docs/DESIGN.html`）：
  - §2.6「工具条（`.toolbar`）」—— 该类的代码出现次数为 **0**，改为真实存在的
    4 个类（`.mt-toolbar` / `.agent-toolbar` / `.market-toolbar` / `.insight-toolbar`）；
    顺带发现 4 个工具条间距不统一（2 个 `--gap-4`=10px、2 个 `--gap-3`=8px），
    **统一为 `--gap-3`**（代码 2 处 + 规范定死）。
  - §3b「已知的例外」把 `.status-dot` 描述为管理台的提示，但它只在 `popover.html`
    （管理台 0 处）—— 改为标注属于 §2.8，并指向 §2.5 的 `.dot` 三态。
  - §2.3 补真实场景卡片类名（`.skill-card` / `.agent-card` / `.settings-card` /
    `.about-card` / `.adv-card`），说明它们不是 `.card` 的变体。
  - §2.5b 澄清「代码里没有名为 `.backdrop` 的类；`--backdrop` 是颜色 token」。

### 新增

- 规范补登本轮新增的组件：§2.5「行内状态点（`.dot` 三态）」、§2.4「表头内联图标
  （`.th-ico`）」。

## [v0.25.4] - 2026-10-11

当前发布版本（build 116）。

### 修复

- **stdio 与 url 互斥：目标 key 被 stdio 条目占用时如实报冲突，不再静默破坏**
  （`core/mcp_fixer_render.py`、`core/mcp_fixer.py`）。
  v0.25.3 只做到「目标 key 是 stdio 时不写 url、原样保留」，并让调用方报
  「endpoint X is already configured」—— **那是谎报**：该条目接入方式与期望的
  url 型端点不同，审计仍判未配置，GUI 会一直显示「修复 MCP」而点了没反应。
  同时发现**同一类缺陷的另一处更严重形态**：JSON 型客户端的 `_render_json` 用
  `servers[name] = entry` 整条替换，会把用户的本地 stdio 桥**静默删掉**
  （`{"command":…,"args":…}` → `{"url":…}`）且返回 `updated`、毫无提示 ——
  这正是主干 `config.yaml` 注释里描述的「命中同名桥并把它改写成 HTTP 形态」，
  此前只是改用独立 key 绕开了它，根因一直在。
  现新增 `McpEntryConflict`，两处渲染路径都在**动用户配置之前**先判类型，冲突时
  **一个字节都不改**，并由 `fix_mcp_tool` 映射为 `unsupported`（scan.py 记为 ⏭️、
  不计入 `repair_errors`），消息里给出可执行的处置办法（`--remove-mcp-entry`
  或为该端点改用其它 key）。

- 回归护栏（`tests/test_mcp_fixer.py`，44 → 47 例）：JSON stdio 条目不得被静默覆盖、
  JSON 反向护栏（非 stdio 仍正常写入）、冲突必须走 `unsupported` 而非 `error`
  （后者会让 GUI 报「修复失败」）。另有 4 例旧测试按新语义更新 —— 它们断言的是
  「谎报 unchanged」这一有缺陷的旧行为。变异验证：JSON 不判 stdio → 1 例失败；
  TOML 冲突不抛异常 → 5 例失败。

## [v0.25.3] - 2026-10-11

当前发布版本（build 115）。

### 修复

- **stdio 条目的残留 `url` 未清除 + 校验层不感知条目类型**（`core/mcp_fixer_render.py`、
  `core/mcp_fixer.py`）。v0.25.2 只挡住了「给 stdio 条目**新增** `url`」，实测还有两条
  同源路径都能产出客户端拒绝的 stdio+url 混用：
  - **渲染层**：条目已是 stdio、但残留旧的 `url` 行时，修复器走「更新 url」分支并
    保留 `command`/`args`，混用照旧（历史证据：`bak-20261010-234804` 里该表只有
    `['url']`，说明形态曾从 URL 型翻转为 stdio 型且未清理旧键）。
  - **校验层**：即便渲染层清掉了 `url`，写后校验用的是 **URL 判据**，而 stdio 条目
    没有 `url` → 必然判失败 → 回滚。表现为「渲染修好了、却仍然写不进去」。
  现把类型判别提到 url 分支之前（stdio 一律清除残留 `url`），并让
  `_validate_written_config` 支持 `expect_stdio`，校验「仍是 stdio 且不含 `url`」
  这一真正写出的不变量；URL 型条目判据不变。

- 回归护栏（`tests/test_mcp_fixer.py`，+3 例）：残留 `url` 被清除、清除后必须能过
  校验（不得回滚）、**反向护栏**（URL 型仍走 URL 判据，写错必须回滚）。变异验证：
  渲染层不判类型 → 4 例失败；校验层不感知 stdio → 2 例失败。

## [v0.25.2] - 2026-10-11

当前发布版本（build 114）。

### 修复

- **stdio 型 MCP 条目不得写入 `url`**（`core/mcp_fixer_render.py`）。
  v0.25.1 修好了「写入越界」，但把 `url` 写进了 stdio 条目，Codex 随即拒绝整份配置：
  `invalid configuration: url is not supported for stdio in \`mcp_servers.hermes-unified\``
  （GUI 表现为「提交消息时出错」）。即**修好一个报错、引入一个更严重的** —— 前者是
  工具自检拦截（配置未被写坏），后者配置真的写坏、直接影响客户端可用。
  根因：`_render_toml` 找不到 `url` 行时**无条件插入** `url`，从不判别条目类型。
  新增 `_toml_section_is_stdio()`（只认表内顶层 `key =` 行里的 `command` / `args`，
  不把 `args = [..., "--url", "..."]` 误判成 url 声明）；stdio 条目改为保持原样
  （对方已通过桥接入同一 URL），URL 型条目仍照常写入。

- 回归护栏（`tests/test_mcp_fixer.py`，+3 例）：stdio 条目不写 `url`、`args` 里的
  `--url` 不算声明、**反向护栏**（URL 型条目仍必须正常写入 `url`，防止「不写 `url`」
  被过度泛化而让真正的 HTTP 端点永远修不好）。变异验证：把 stdio 判别改为恒假即失败。

## [v0.25.1] - 2026-10-11

当前发布版本（build 113）。

### 修复

- **Codex MCP 修复失败：TOML 段落切片把表头前的空行算作段落起点，导致写入越界**
  （`core/mcp_fixer_render.py`）。`~/.codex/config.toml` 里目标表
  `[mcp_servers.hermes-unified]` 紧跟在 `[mcp_servers.K8s]` 之后、中间只隔一个空行；
  表头正则写成 `^\s*\[`（`\s` 含换行）时匹配从**上一个表尾部的空行**开始，段落切片
  起点随之前移，于是「在段落头插入 `url`」实际插进了上一个表 —— 而那个表已有 `url`
  键，渲染结果非法（`Cannot overwrite a value`），整个修复失败并让退出码变成 2。
  同一文件里 `_toml_subtable_range` 早已用正确的 `^[ \t]*\[`，其余 7 处不一致，
  本次统一为不跨行写法。

- **错误归因：渲染器自身失败被报成「用户配置无法解析」**（`core/mcp_fixer.py`）。
  上述失败的真实原因是 TOML 渲染产物非法，但上游 `except` 把 TOML 解析异常与
  「读文件失败」一并吞掉、统一报成 `configuration could not be parsed safely`，
  把「工具写坏了自己」误报成「用户配置文件有问题」，排查方向被引向完全合法的用户配置。
  现拆分为三种归因：读文件失败 → `could not be read`；渲染失败 →
  `renderer could not produce a valid configuration (<根因>)`，并在消息里带上根因首行。

### 新增

- 回归护栏（`tests/test_mcp_fixer.py`，+4 例）：表头前空行不得并入上一表、
  前表含同名字段时的通用性、渲染失败与读取失败分别归因。全部经变异验证
  （把正则回退为 `^\s*\[` 即失败）。

- **UI 规范与门禁补全**（`docs/DESIGN.md`、`docs/DESIGN.html`、
  `tests/test_design_spec_contract.py` 等）。对界面规范做了一次评审，修复其与代码的
  系统性漂移，并把此前没有门禁的条款全部补上：
  - 硬数字对齐（`.modal` / `.sheet` 宽度、z-index 档位、`.switch` 尺寸、`main` 内边距）
    并新增 §2.9 登记表 + 逐行比对 CSS 的契约门禁；
  - token 清单补登在用 token（含 11 个 `--sp-*` 扩展档），新增「`:root` 的 token
    必须在规范中登记」的完整性断言；
  - 消除规范内部矛盾（`primary` 粒度改为「同一操作区」；删除死 token `--r-popover`）；
  - HTML 可读版与 MD 改为**双向**镜像，并删除过期的用例数；
  - 修掉 4 处 emoji 当 UI 图标（状态点改语义色 `.dot-*`，表头改 SVG）；
  - 新增 emoji 禁用、`cursor: pointer`、触达目标 32px、弹层 Esc、mono 用法门禁。

- **间距字面值清零**（`gui/dashboard.html`）。为 `:root` 缺档的 6 个值补登记扩展档
  （`--sp-1a`/`--sp-5c`/`--sp-8a`/`--sp-9d`/`--sp-9e`/`--sp-9f`）与 `--gap-6`，然后把
  483 处声明（`<style>` 块 265 条 + 内联 `style=` 18 条）**值等价替换**为同值 token，
  全量比对确认 503 条声明解析后取值 0 处差异，渲染结果不变。棘轮门禁退役，换成
  零容忍（`<style>` 块与内联均在口径内）。

### 变更

- `scripts/ci_parity.sh` 改为**失败累加**：工具门禁（ruff / node / cargo / 卫生自检等）
  失败不再立即 `exit 1`，而是记录后继续跑完，末尾统一汇总。此前漏装 ruff 会导致
  **一条 Python 单元测试都不执行**，输出被误读成「测试失败」。覆盖缺口（node/cargo
  缺失）也从「静默 warn」改为「计为失败」。新增
  `tests/test_ci_parity_gate.py`（静态断言 + 与 workflow 的基线交叉校验）。

## [v0.25.0] - 2026-10-09

### 新增

- **Hook 管理：生命周期 hook 配置的审计、写入与移除**（`config.yaml`、`core/hooks_inventory.py`、
  `core/hooks_fixer.py`、`core/management_snapshot.py`、`scan.py`、`src-tauri/src/lib.rs`、
  `gui/dashboard.html`）。此前 ai-memory 的生命周期 hook（SessionStart / SessionEnd / Stop 等）
  配置散落在 `ai_memory_checker.AI_MEMORY_HOOKS_PATHS` 的硬编码字典里，且只读不写——
  「写入标准 hook 模板」从未实现。现按 MCP / Skill 的配置驱动管理范式重构：
  - **配置层**：`config.yaml` 新增 `hooks:` 顶层段（`events[]` + `clients[]` + `template`），
    5 个客户端（Claude Code / Cursor / WorkBuddy / Codex / OpenCode）各声明 `config_path` /
    `format` / `hook_key_path` / `events` / `fix_supported` / `template`；`mcp_tools[].hooks_config_path`
    保留为兼容回落。
  - **审计层**：`hooks_inventory.inventory_for_tool` 从 `config["hooks"]["clients"]` 按名匹配，
    读取各客户端 hook 配置（JSON / TOML / 插件文件），产出 `{hooks_config_path, hooks_configured,
    hook_events, hooks_fix_supported, hooks_inventory, missing_key_events}`；`management_snapshot`
    的 `_agent_entry` 与 `mainstream_tools` 块均透传这些字段。
  - **写入层**：`hooks_fixer.fix_hooks_tool` 按 `template` 渲染标准 ai-memory hook 条目
    （`{matcher:"*", hooks:[{type:"command", command:...}]}`），走 backup → atomic_write →
    re-parse validate → rollback 安全链；`remove_hooks_tool` 移除 ai-memory hook 但保留
    非 ai-memory hooks。
  - **CLI**：新增 `--list-hooks` / `--fix-hooks` / `--remove-hooks`（支持 `--client` 过滤、
    `--dry-run` 预演、`--format json`）；`lib.rs` 的 `run_cli` ALLOWED 白名单已登记。
  - **GUI**：新增「Hook」独立 tab（导航栏 + `page-hooks` section），`renderHooks` 从
    `SNAP.mainstream_tools` + `_agentsForPanel()` 提取有 `hooks_config_path` 的条目，
    展示状态 / 已接入事件 / 条目数 / 缺关键事件，行内按钮触发 `fixHooksFor` /
    `removeHooksFor`（confirmModal + runTaskModal + runCli 三段式），顶部「一键写入 Hook」
    批量执行 `--fix-hooks`。
- **变更检测：4 维度快照对比与持久化**（`core/snapshot_diff.py`、`scan.py`、
  `src-tauri/src/lib.rs`）。此前 `change_tracker` 只比 skills 工具增减，维度极窄且
  不持久化 management_snapshot。新增 `core/snapshot_diff.py`，对比 4 个维度：
  - **IDE/Agent**：安装状态翻转、新增/消失客户端
  - **MCP**：端点挂载变化、inventory 条目增减
  - **Skill**：新增/删除技能、客户端启用数量变化
  - **Hook**：hooks_configured 翻转、hook_events 变化
  新增 CLI 出口 `--snapshot`（复用 `build_management_snapshot`，`live_probe=False`，
  只读不探活），产出持久化快照 `data/last_snapshot.yaml` 并与上次对比；
  `lib.rs` 的 `run_cli` ALLOWED 白名单已登记。
- **托盘常驻：系统托盘图标与菜单**（`src-tauri/Cargo.toml`、`src-tauri/src/lib.rs`）。
  此前关闭窗口只隐藏不退出（`EXITING` 标志位），但无系统托盘入口——用户隐藏窗口后
  无法重新打开（只能靠 Dock 图标）。现启用 tauri `tray-icon` feature，在 `setup` 里
  构建托盘图标 + 菜单（显示主窗口 / 退出）：
  - **左键点击**切换窗口显隐（可见则隐藏，隐藏则显示并聚焦）
  - **右键菜单**「显示主窗口」「退出 Skill MCP Studio」
  - 关闭窗口仍只隐藏不退出，退出走托盘菜单或 Cmd+Q
- **后台巡检：定时快照对比与托盘状态联动**（`config.yaml`、`scan.py`、
  `src-tauri/src/lib.rs`）。此前变更检测只能手动触发 `--snapshot`。
  现新增：
  - `config.yaml` 的 `settings` 段：`patrol_enabled`（默认 false）、
    `patrol_interval_minutes`（默认 15，最小 5）
  - CLI 出口 `--set-setting KEY=VALUE` / `--get-setting KEY`（走 backup →
    atomic_write 安全链，白名单键 patrol_enabled / patrol_interval_minutes）
  - `lib.rs` 后台线程：每隔 60 秒检查 `patrol_enabled`，若启用则运行
    `--snapshot`，检测到变更时更新托盘 tooltip 为「检测到变更，点击查看」
  - 托盘菜单新增「切换后台巡检」项，一键开关巡检
- **变更通知：系统通知与变更详情面板**（`src-tauri/Cargo.toml`、
  `src-tauri/src/lib.rs`、`gui/dashboard.html`）。此前后台巡检检测到变更
  只更新托盘 tooltip，用户不易察觉。现新增：
  - `tauri-plugin-notification` 依赖：后台巡检检测到变更时弹系统通知
    「检测到配置变更，点击查看详情」
  - GUI 新增「变更详情」tab（`data-page="changes"`）：`renderChanges()`
    初始占位 + `runSnapshot()` 调用 `--snapshot --format json` 解析 diff
    并渲染 4 维度变更列表（agents / mcp / skills / hooks）

### 修复

- **桌面端：操作收尾不再触发整份重扫**（`gui/dashboard.html`）。`runTaskModal` 有 9 个
  调用点（移出客户端、删除客户端、修复 Skills、修复 MCP、清理旧 MCP、删除 MCP 条目、
  清理通道、还原配置、一键修复）把收尾刷新参数传成了 `undefined`，于是回落到兜底
  `loadInternal(false)` —— 整份 `--management` 重扫全部技能与客户端，操作一结束就弹出
  「更新审计：扫描全部技能与客户端」并阻塞等待。现改为按操作实际影响的数据块精确刷新
  （`refreshBlocks`），兜底默认值也改为局部刷新：漏传时最多少刷一块，不再罚等半分钟。
- **引擎：修复 `repo_skill_names` 缓存装饰器错装导致的重复扫描**
  （`core/skill_state.py`、`core/skill_merge_exec.py`、`scan.py`）。`lru_cache` 装饰器
  被误装在 `invalidate_repo_skill_names` 上而非 `repo_skill_names`，后果是双重的：后者
  完全没有缓存，而它位于「客户端数 × 技能数 × 嵌套层级」的内层循环中，每次都要
  `listdir` + 逐条目 `isdir` —— 单次快照构建触发 10291 次调用、约 453 万次
  `posix.stat`；前者承担「清缓存」职责却反被缓存，第二次调用直接返回而不再清理，且其
  内部的 `repo_skill_names.cache_clear()` 必然抛 `AttributeError`。装饰器现装回缓存实现
  层并以展开后的绝对路径为缓存键（避免 `~/.skills` 与展开路径形成两把键），同时补上
  `merge_group` 与 `--delete-skill` 的写后失效。
  - **实测（209 个技能 × 20 个客户端）**：`--management` 全量 18s → 1.4s，
    `--management --only agents,mcp` 16s → 1.4s；缓存命中 20581 次、实际扫描 1 次。
  - **正确性**：修复前后快照逐字节对照，除 `generated_at` 时间戳外完全一致
    （均为 616701 字节）。
  - 该修复无需重新构建桌面 App：CLI wrapper（`~/.local/bin/skill-mcp-studio`）直接
    `exec` 源码树的 `scan.py`，引擎改动即时生效。


- **MCP：修 TOML 子表重复声明、jsonc 起始模板，Codex 改用独立统一端点名**
  （`core/mcp_fixer_render.py`、`core/mcp_fixer.py`、`config.yaml`）。三个独立缺陷让
  「一键修复所有 Skills 与 MCP」在 Codex 与 OpenCode 上必然失败（实测报 4 处错）。
  - **TOML 鉴权头被重复声明（主因）**：Windows 系客户端把鉴权头写成**子表**
    （`[X.http_headers]`）而非内联表，而 `_render_toml` 用的 `_toml_section_ranges`
    只匹配父表本身，子表被留在切片区之外 —— 改完父表 url 又插入一行内联
    `http_headers`，与段外子表重复声明，产出非法 TOML：
    `Cannot declare ('mcp_servers', 'K8s-uat', 'http_headers') twice`。
    切片改用一直没被接上的 `_toml_section_tree_ranges`，并新增
    `_toml_subtable_range` / `_set_toml_subtable_field` / `_apply_toml_headers`：
    按文件原有声明形式维护鉴权头（原来是子表就继续写子表，原来没有才用内联，
    两种形式永不并存），端点不再带 token 时清掉子表里的旧 `Authorization`。
    触发条件是「该端点带 auth_token」—— 这正是 K8s-uat（有 token）失败、
    无 token 端点不受影响的原因。
  - **jsonc 缺少起始模板**：`initial = "{}\n" if config_format == "json" else ""`
    让 jsonc 落到空串分支，空串无法被 JSON 解析，配置文件根本建不起来。jsonc 与
    json 同为 JSON 超集（`_render` 里二者本就共用 `_render_json`），必须共用 `{}`。
  - **Codex 缺 `unified_name`，会改写用户的本地桥**：Codex 已有指向 NAS 网关的
    本地 stdio 桥条目 `hermes`，工具回落到 profile 名就命中并改写它，改写后 url
    校验不过，整条修复回滚并报 `validation failed; original configuration was
    rolled back`。现给予独立 `unified_name: hermes-unified`（与 OpenCode 同一处理）。
  - 新增 6 个回归测试；反向验证时还原两处修复，其中 3 个立即失败
    （`'error' != 'updated'`），确认测试守在缺陷上而非空转。
- **MCP：`unified_name` 只作用于统一端点，修「修复后仍显示 1/2」**
  （`core/combined_checker.py`、`core/mcp_fixer.py`、`core/mcp_inventory.py`、
  `core/management_snapshot.py`、`core/mcp_entry_removal.py`、`scan.py`）。
  上一项修好了「修复过程报错」，这一项修好「修复看似成功但判定不认」。
  - **根因**：`unified_name` 在 config.yaml 里的定义是「**统一 Hermes 端点**在该
    客户端里的条目别名」（OpenCode 条目注释：「统一端点用独立 key 写入，避免覆盖
    本地桥」），但它是**客户端级**字段，而端点库通常不止一个端点（本机：K8s-uat
    与 hermes-home）。三处代码都无条件套用了这个别名：
    1. 审计侧把 K8s-uat 也拿去查 `hermes-unified`，读到 hermes 的 URL，与
       K8s-uat 的 `expected_url` 不等 → URL 校验必然失败 → 把**已正确接入**的
       端点判成「未配置」（实测 `mcp_configured=False` 而
       `configured_url=https://hermes-mcp.pd-h.top/mcp`，正是「拿错条目」的铁证）。
    2. 写入侧遍历端点库时每个端点都写进同一个 key、互相覆盖，最终只剩最后一个
       端点的 URL（实测配置里根本没有 K8s-uat 条目）。
    3. 清单侧 canonical 分支只标 `attached`、漏设 `endpoint_key`，而
       `observed_endpoint_keys` 只读该字段 → 用别名写入的条目对附件审计不可见，
       误报「声明要挂却没挂」（实测 OpenCode 报 `missing=[K8s-uat, hermes-home]`，
       其中 hermes-home 是误报）。
  - **修复**：判定统一端点为「端点库 key == `active_profile`」；`endpoint_key` 为
    None（检查默认端点）时同样适用别名。`fix_mcp_tool` 增 `use_unified_name` 形参由
    `fix_mcp_clients` 按上述判据传入，后者增 `profile_key` 供 `--profile` 单端点路径
    使用；`classify_entries` / `inventory_client` 增 `canonical_endpoint_key`，
    三个调用点传入 `active_profile`。
  - ⚠️ **注意**：不可写成 `active_key = endpoint_key or config["active_profile"]`
    —— `endpoint_key` 非空时该表达式恒等于它，比较永远相等，别名会被误用到所有
    端点上（第一版即如此，实测仍然 1/2，已改掉并把坑写进注释）。
  - **效果（真实配置端到端）**：Codex `1/2 → 2/2`（K8s-uat=OK hermes-home=OK）；
    OpenCode 的 dry-run 变为 K8s-uat「would be updated」+
    hermes-unified「already configured」，两个端点各写各的名字、不再互相覆盖。
  - 新增 `tests/test_unified_name_scope.py`（7 个用例）与
    `tests/test_check_model_attach.py::UnifiedNameScopeTest`（3 个用例）。
    反向验证：临时还原三处修复后，这批测试有 6 个立即失败。
- **报告：分离「MCP 修复结果」与 Skills 变更报告，并修 dry-run 待写计数**
  （`scan.py`、`core/change_tracker.py`）。修复看似写盘成功，收尾却打印
  「变更报告：✅ 无变化」，用户据此以为空跑。
  - **根因是「两个维度的结论被印在相邻位置」**：`compute_changes` 只比对
    **skills 扫描**维度，与本次 MCP 写入无关，却紧跟在 MCP 修复段之后，读起来像
    是对刚才那次操作的总结。
  - MCP 修复段现在**补印自身结论**（`MCP 修复结果：已写入 N，unchanged M（共 X 项）`），
    并在确有写入时加一行提示把两件事在输出上分开；`format_change_report` 的标题改为
    **「变更报告（Skills 扫描维度）」**（GUI 折叠区取自同一函数，界面同步受益）。
  - **顺带修掉一个自测发现的真实缺陷**：dry-run 下 `fix_mcp_tool` 返回的状态是
    `"dry-run"` 而非 `updated`/`created`，旧公式只累加后两者，会把**真实待写项算成
    0** —— 又是一句失真提示。现按 `args.dry_run` 分支分别取 `"dry-run"` 与
    `updated+created`。
  - 新增 `tests/test_mcp_summary_report.py`（10 个用例，含源码级契约）。反向验证：
    把标题与 dry-run 计数还原成事故代码后，3 个用例立即失败。
- **技能库：把 `_backup/`、`_trash/` 从技能枚举中排除**
  （`core/paths.py`、`core/skills_analyser.py`、`core/skill_state.py`、
  `core/skill_market.py`、`core/skill_merge_advisor.py`）。这两个目录是
  `skill_ops` 的操作落地目录（前者存备份副本、导出还会产生同名 `.zip`，后者存软删除
  后的目录），内部带着 `SKILL.md`（备份的就是真实技能），而各处一级枚举只筛「是不是
  目录 / 有没有 `SKILL.md`」，于是它们被当成技能：实测本机 209 个技能清单里混着
  `_backup` 与 `_trash`，各自的 4 个备份副本还被算成嵌套技能（管理快照里 `_backup`
  出现 69 次、`_trash` 53 次）。
  - **修法是在路径解析的单一入口加精确名单**：`core/paths.py` 新增
    `RESERVED_SKILL_DIRS = {"_backup", "_trash"}` 与判据 `is_reserved_skill_dir()`，
    5 处一级枚举统一接入，避免同样的漏筛在别处复发。
  - **为什么用精确名单而不是「下划线前缀」这类规则**：`_core` 同样以下划线开头，但它是
    **真实技能**（带规范前言的 `SKILL.md`，内容是核心规范文档），必须保留。名单式还能让
    「新增保留目录」成为一次显式决定，而不是被一条宽规则悄悄带过。
  - **效果（本机实测）**：技能数 `209 → 207`；`_backup`/`_trash` 从技能清单、
    `skill_meta`、`skill_nesting` 三处全部消失，`_core` 保留。未删除任何文件 ——
    这两个目录是软删除/备份机制的一部分（技能误删可由此恢复），只做「不当作技能」。
  - 新增 `tests/test_reserved_skill_dirs.py`（9 个用例 + 5 个子测试），覆盖判据本身、
    5 处枚举点的端到端排除、以及「`_core` 不得误伤」。反向验证：把
    `RESERVED_SKILL_DIRS` 置空模拟缺陷后 6 个用例立即失败；其中嵌套用例特意在备份副本里
    再造一层嵌套技能，否则空结果会让它假通过。
- **MCP：修 OpenCode「配置无效却显示已接入」的假阳性**（`config.yaml`、
  `core/mcp_fixer_render.py`）。OpenCode 的 `mcp` 段是**判别联合** —— 官方 schema
  （`opencode.ai/config.json`）里 `McpRemoteConfig` 的 `required` 是 `[type, url]`、
  `McpLocalConfig` 是 `[type, command]`。缺 `type` 时 OpenCode **不是忽略该条目，而是
  把整份配置判为无效**：
  - **实测报错**：`opencode debug config` →
    `Error: Configuration is invalid at ~/.config/opencode/opencode.json` /
    `Expected { "type": "local", ... } | { "type": "remote", ... }, got {"url": ...}
    mcp.hermes-unified` / `Missing key mcp.hermes-unified.enabled`。后果是**所有** MCP
    端点一起失效，而面板仍按「URL 字符串匹配」显示 `2/2` —— 这是「以设置中的 MCP 为准」
    口径下最危险的一类假阳性：**字符串对上了，配置其实加载不了**。
  - **根因**：`_render_json` 一律只写 `entry = {"url": url}`，而它被 `json` 与 `jsonc`
    两种格式共用，服务 4 个客户端。
  - **修法是按客户端声明连接类型**（`config.yaml` 新增 `mcp_entry_type: remote`，
    `_render_json` 新增 `entry_type` 形参，键序 `type → url → headers`），**而不是在渲染
    层统一硬编码** —— 因为 `mcpServers` 型客户端（Claude Code / Cursor / WorkBuddy）的条目
    **只需 `url`**，多写 `type` 是多余字段（用户手写的 WorkBuddy 条目就是 `{"url": ...}`）。
    默认空 = 不写，故这三个客户端的输出**保持字节级不变**。
  - **效果**：修复后 `opencode debug config` 退出码 `0`，实际加载 4 个端点，
    `hermes-unified` / `K8s-uat` 均为 `type=remote, enabled=true`。
  - 新增 `tests/test_mcp_entry_type.py`（8 个用例 + 7 个子测试）。反向验证：把
    `entry_type` 处理去掉还原成旧行为后，5 个用例立即失败。
- **文档：`src-tauri/BUILD.md` 与 `.gitignore` 的统一**
  （`src-tauri/BUILD.md`、`.gitignore`）。BUILD.md 第 44-45 行仍写「根 .gitignore 已排除
  `.cargo-home/` `.rustup-home/` `src-tauri/target/`」，而 `git check-ignore` 实测前两者
  **未忽略** —— 该句与同文档顶部第 18-25 行的更正**自相矛盾**。现改为与实际一致，并把
  「本机工具链落在仓库内」的现状与回归 `$HOME` 布局的步骤交叉引用。
- **MCP：候选配置的同名条目不得用「另一种方式」抹掉真实接入**
  （`core/combined_checker.py`）。DeepSeek Harness 长期停在 `1/2`，根因是
  `_load_tool_servers` 的合并顺序**覆盖**掉了真实接入的 URL：
  - **两处同名但不同方式**：主配置 `cordis.patch.yml` 的 `hermes` 是
    `transport: streamable-http` + 正确 url（真实接入统一端点 `hermes-home`）；候选
    `~/.dsh/mcp.json` 的 `hermes` 是本地 **stdio 桥**（`command` + `args`，**无 url**）。
    旧实现一律 `servers.update(candidate_servers)`，候选的无 url 条目把主配置的 url
    覆盖成空，交出的 `hermes` 无 url ⇒ `hermes-home` 被判 `configured=False`。
  - **这与该函数自己文档声明的「任一位置命中即算」自相矛盾**（原文：*report the client
    as configured whenever the canonical endpoint is present in any of the expected
    locations*）—— 是**假阴性**，把已正确接入的端点报成未接入。
  - **正是「以设置中的 MCP 为准」口径的反面**：同名条目走了另一种方式（stdio 桥），
    不能据此把 HTTP 接入判成未接入。
  - **修法**：新增 `_prefer_url_entry(existing, incoming)`，合并候选时**有 url 的胜出**。
    两者都有 url 时仍以候选（后合并）为准，保持「候选是更权威覆盖层」的既有意图；
    候选的正当用途（补上主配置没有的端点）未受影响，已加用例锁定。
  - **证据（本机实测）**：`cordis.patch.yml` 顶部自述 *patch layer ... applied after
    every bundle layer*；`cordis.yml` 无 MCP 配置；`~/.dsh/mcp.json` 未被任何 DSH 配置
    引用，且 DSH 应用包内 `mcp.json` 命中 **0 次**（`strings app.asar`）—— 即它是遗留
    文件，不是活跃配置。
  - **效果**：DSH `hermes-home` `False → True`，DSH `2/2`；真实 `scan.py --management`
    实测 6 个客户端（Codex / DSH / OpenCode / Reasonix / VS Code / WorkBuddy）**全部
    2/2**，其余 5 个未受影响。
  - 新增 `CandidateMergeTest`（5 用例）与 `CandidateMergeEndToEndTest`（3 用例）。
    反向验证：把 `_prefer_url_entry` 短路成恒返回 `incoming`（等价旧语义）后，
    `test_stdio_does_not_clobber_http` 与端到端用例立即失败。
- **技能市场：`npx` 同目录必须提到 `PATH` 首位**
  （`core/skill_market.py` 的 `_npx_env`）。文档说「必须让其同目录可见」，实现却只在
  该目录**完全不在** `PATH` 时才插到首位：
  - `if npx_dir not in parts: parts.insert(0, npx_dir)` —— 目录已在 `PATH` 中（本机即
    如此）时**不移动**，语义弱于文档意图。
  - `npx` 是 `#!/usr/bin/env node` 脚本，`env node` 取 `PATH` 里**第一个** node，而 `npx`
    同目录那个才是配套版本。若前面的目录里存在另一个 node（nvm / fnm / volta 常见），
    `npx` 会解析到**错误的 node 版本**。
  - 本机实测：`/opt/homebrew/bin/node`（26.11.0）落在 `PATH` **第 9 位**，首项
    `~/.mimocode/bin` 下没有 node —— 属**侥幸可用**。
  - **修法**：无论是否已存在都移到首位；已存在时先摘除再插入，避免重复项。
  - 这同时修掉了既有用例 `test_npx_env_exposes_node_next_to_npx` 的失败 —— 该用例本来
    就是对的（断言首项 == npx 目录）。
  - 新增 3 个用例覆盖三个分支（已在但不在首位 / 不在 / `PATH` 为空），并断言提升后不留
    重复项、其余顺序不变。反向验证：还原成 `if npx_dir not in parts` 后，上述两个用例
    立即失败。
  - 至此全量测试 **1053 passed / 1 skipped / 0 failed**，不再有已知失败项。

## [v0.24.1] - 2026-09-29

### 变更

- **macOS 构建改用本机自签证书签名**：`src-tauri/tauri.conf.json` 新增
  `bundle.macOS.signingIdentity = "oswaldhill Local Development"`。本地
  `cargo tauri build` 产出的 `.app` 由此**默认由本机自签证书签名**，不再是
  Tauri 的 ad-hoc 兜底。
  - **动机**：ad-hoc 签名无 TeamIdentifier，macOS 只能用 **cdhash** 表述其身份，
    而 cdhash 每次重建都变 ⇒ 依赖签名身份的记录（Gatekeeper 信任、以及若将来
    申请 TCC 权限时的授权条目）在每次重建后全部指向失效身份。改为自签证书后
    designated requirement 变为
    `identifier "io.skillmcp.studio" and certificate root = H"e2f6d1a5…"`，
    **绑定证书指纹而非 cdhash**：同一证书下跨版本重建身份稳定。
  - **实测（2026-09-29，本机）**：`codesign --force --sign "oswaldhill Local Development"`
    在**非交互**会话中直接成功（退出码 0），与 `src-tauri/BUILD.md` §3.3 此前记录的
    「Agent 会话内签名必然失败（unknown exception）」相反 —— 该结论已就地更正并标注日期。
  - **CI 无回归**：runner 上没有该证书，`.github/workflows/build-macos.yml` 新增一步，
    仅在**未配置 `APPLE_CERTIFICATE`** 时把 `APPLE_SIGNING_IDENTITY` 覆盖为 `-`
    （ad-hoc），与改造前行为一致；已配置正式证书时该步不执行，正式身份链路不变。
    依据是 tauri-cli 实测语义：`APPLE_SIGNING_IDENTITY` 环境变量优先于 config。
  - **未改变的部分**：产物仍是**未公证**（无 Apple Developer ID 证书），首次打开
    需右键「打开」放行；本次解决的是**签名身份的稳定性**，不是 Gatekeeper 分发问题。

## [v0.24.0] - 2026-09-27

当前发布版本（build 110）。

### 变更

- **审计只判配置，端口连通性独立检查**：审计的职责收敛为「**配置是否正确**」，
  端点是否可达属运行时状态，改由**独立的连通性检查入口**负责。
  - **引擎**：`classify_record(record)` 只看配置（`installed` / `skills_compliant` /
    `mcp_configured` / `hooks` / `legacy_channels`），探活字段不再参与结论；
    `result_ok()` 同样忽略 probe。
  - **MCP 模块**：新增 `core/mcp_endpoint_status.py`，复用既有 `probe_mcp` 与
    `classify_endpoint_probe`，**不另写一套探活**（避免两套实现各自漂移）。
  - **CLI**：新增 `--endpoint-status`（默认 table；支持 `--format json`、`--profile`）。
    退出码**只反映连通性**：`failed → 1`，`ok`/`not_run → 0`，与审计退出码完全无关。
  - **GUI**：审计总览区**移除**「MCP 探活正常 x/y」卡片；新增独立的「端点状态」区，
    **手动触发**检查，未检查用中性色（「没测过」既不是通过也不是故障）。
  - **安全边界**：Tauri `run_cli` 白名单登记 `--endpoint-status` —— 漏登记会让前端
    按钮直接撞安全边界，该缺口由 `tests/test_run_cli_boundary.py` 抓出。
  - **实测**：`--endpoint-status --format json` → `exit=0`、`state: ok`、
    `initialize_ok: true`、`tools_list_ok: true`、`tool_count: 16`、`elapsed_ms: 64`。
    审计刷新由 28.3s 降至 12.56s；配置合法但不可达的端点不再让审计显示异常。
  - **取舍（须知）**：端点故障**不再出现在审计结论里** —— 配置完全合规但所有端点
    都不通的客户端，审计仍为绿色。若要用它做 CI 门禁，需**另外**跑
    `--endpoint-status` 并看它自己的退出码。

- **操作后只刷新该操作产生的内容，不重跑整份审计**：此前 GUI 里 13 处写操作成功后
  一律重跑 `--management` 全量快照（实测 **8.02s**、快照约 556KB，其中 skills 215KB +
  mcp 211KB）—— 最刺眼的是**改一个端点的 URL 会连带重扫整棵技能树**。
  - **后端**：`--management` 新增 `--only <blocks>`（`endpoints`/`mcp`/`agents`/
    `skills`/`mainstream`/`settings`；不传 = 全量，行为与改造前逐字段一致）。
    复用**同一份组装逻辑**按块裁剪，故局部快照与全量快照天然同构。
  - **依赖事实**：`agents`/`skills`/`mainstream`/`mcp`/`settings` 的数据来源都是
    `run_scan()`，**跳不掉扫描**；只有 `endpoints`（`endpoint_entries(config)`）
    是纯配置读取，可完全跳过 —— 实测 **8.02s → 0.26s**（约 31 倍）。
  - **前端**：新增 `refreshBlocks()` + `BLOCK_RENDERERS`（只重渲染受影响面板）
    与 `mergePatch()` **深合并**。深合并是必须的：`--only endpoints` 只返回
    `mcp.endpoints`，整块覆盖 `SNAP.mcp` 会把未请求的 `endpoint_status`/`clients`
    一起抹掉，面板会突然空掉。
  - **13 处映射**：端点三处 → `["endpoints"]`；客户端/统一目录 →
    `["agents","mainstream"]`；技能启停 → `["skills","agents"]`；
    合并 → `["agents","mainstream","skills"]`。保留全量的只有启动加载、
    命令面板「刷新快照」、「重新扫描」按钮（用户显式要重扫全部）。
  - **护栏**：新增 `tests/test_partial_refresh.py`（10 用例）双向锁死该契约，
    其中 **monkeypatch 计数断言「只取 endpoints 不得触发 `run_scan`」** ——
    保证「快」不是偶然。

- **版本号 0.23.0 → 0.24.0（build 109 → 110）**：按语义化版本以 `minor` 递增，
  由 `scripts/bump_version.py --bump minor` 同步 `version.json`、`pyproject.toml`、
  `src-tauri/Cargo.toml`、`src-tauri/Cargo.lock`、`src-tauri/tauri.conf.json`
  与文档/预览层版本引用（单源真相仍是 `version.json`）。


### 变更

- **引入 ruff 静态检查（P1-11，可审计终态）**：`pyproject.toml` 新增 `[tool.ruff]`，
  并新增 CI job `lint-ruff`（`ruff==0.16.9` 固定版本；ruff 的诊断集合随版本变化，
  不锁版本会让门禁时红时绿）。规则集分阶段开启，现已达 **`ignore` 仅剩 `E402`**：
  - `F401` 已启用：清理 53 处并逐处判定（多数是 `from typing import ...` 的多余名字）；
    清前先反查「被外部引用」的名字（`patch("mod.name")` 字符串锚点与跨模块 `mod.name`
    访问是 ruff 看不到的），实测 53 处无一被引用 —— 因为 P2-16 拆分时已把再导出写成
    `import X as X`，而带冗余别名的导入本就不被 `F401` 标记，两件事正好互补。
  - `F811` 两处**性质相反**，不可一把 `--fix`：`config_store.py:88` 是与顶层重复的
    `import re`（真冗余，删除）；`tool_registry.py:402` 是**刻意的惰性导入**
    （避免顶层互 import 成环 + 保证 `patch("config_store.load_discovered")` 生效），
    加 `# noqa: F811` 保留并注明原因。
  - 首批另修 20 处：13 处自动修（`F541`/`E401`/`F841`）、6 处死赋值、`E741` 改名。
  - **经量化论证不采用**：`I001`（76 处中 45 处落在含 `sys.path` 引导的文件 ——
    33 个测试文件 + `scan.py`，自动重排会在 `sys.path` 未设置时执行 import，
    **结构上不可行**）、`ruff format`（114/135 文件需重排、单文件可达 243 行；
    纯排版变更会淹没本仓库的有语义改动，**收益不匹配成本**）。二者理由不同，
    均已写入清单「附二」待确认。
- **修复 `core/workspace_cleaner.py` 丢失的 `import shutil`**：由上述 ruff 的 `F821`
  （未定义名）抓出 —— P2-16 拆分该模块时 `import shutil` 被整个丢失，三处
  `shutil.rmtree`（目录型临时目标的删除路径）抛 `NameError` 并被 `except` 吞掉，
  表现为「清理失败」而非崩溃，**943 个用例全绿却无人发现**。已修复并反向验证
  （修复前目录删不掉，修复后真正删除）。

- **新增脚本卫生自检（P2-18）**：`scripts/ci_parity.sh` 与 CI 的 `text-hygiene` job
  各新增两条断言 ——（1）`scripts/*.sh` 的 git mode 必须为 `100755`；
  （2）不得出现「`$var` 紧跟全角标点」（须写 `${var}`）。
  两条都对应**会伪装成测试失败**的缺陷：可执行位丢失时 bash 直接执行仍正常、
  但 Python subprocess 调用会 `PermissionError`，表现为 `exit != 0` 且日志无
  `Ran N tests`；`$var` 紧跟全角标点则在部分 locale 下直接 `unbound variable` 中止脚本。
  自检落地后立即抓出此前未发现的 4 处真实缺陷（`release.sh` 2 处、
  `verify_gui_consistency.sh` 变量写法 1 处 + git mode 1 处），均已修正。

- **`core/mcp_fixer.py` 拆分为 渲染/写安全链 两模块**（P2-16 第四刀）：900 行按「纯渲染」与
  「写安全链 + 编排」分界拆为 `mcp_fixer_render.py`（558 行，29 个纯渲染/纯文本函数）与
  `mcp_fixer.py`（400 行，validate/写安全链/编排 + 逐名再导出）。归属依据是 AST 实测：
  全模块真正落盘的只有 `fix_mcp_tool` 与 `remove_mcp_entries_tool`，其余命中的「写盘调用」
  是 `str.replace` 与 `yaml.safe_dump`（生成文本、不落盘）。三处约束保持不动：`os`
  （`patch("mcp_fixer.os.replace")` 依赖）、`_validate_written_config`（同文件有 patch）、
  以及 9 个外部导入名。验收：公开名 67 → 67，943 用例全绿。

- **`core/workspace_cleaner.py` 拆分为 只读/写 两模块**（P2-16 第二刀）：698 行按
  「只读检查」与「写操作」分界拆为 `workspace_cleaner_read.py`（322 行：分类谓词、
  `check_workspace_cleanliness`、`scan_temp_files`、`classify_untracked`、两个格式化函数）
  与 `workspace_cleaner.py`（387 行：`_ask_user` 与 4 个写操作）。`_ask_user` 归写侧是
  查出来的（仅被写侧两处调用）。写侧以 `from workspace_cleaner_read import X as X`
  逐个再导出 9 个只读名字 —— 因为 `tests/test_highrisk_modules.py` 与 `scan.py`
  通过本模块访问它们（含私有谓词 `_is_temp_file` / `_is_suspicious_file`）。
  验收：公开名字集合 20 → 20（缺失 0、多出 0），`TEMP_PATTERNS` 仍 14 项，943 用例全绿。

- **文本卫生检查把「末尾缺少换行」纳入 CI 门禁**（评审清单 P2-17 的验收标准后半句）：
  存量文件已一次性补齐，CI 的 `text-hygiene` 步骤因此从「只查 BOM/CRLF」扩到
  「BOM / CRLF / 末尾换行」三项，此后新增文件若缺末尾换行会被直接拦下。
  实测本地等价跑：检查 202 个文本文件，全部合规。

### 修复

- **测试运行时的裸噪音**（评审清单 P2-15）：`tests/test_exit_codes.py` 的 4 个负例
  直接调 `scan` 内部函数，其 `print` 的错误文案直通终端（实测全量跑里 **stdout 4 行**、
  stderr 0 行），在 unittest 汇总中极易被误读成「有失败」。新增 `_captured_output()`
  上下文管理器把输出收进断言，并把文案本身纳入校验（`--all-profiles 与 --profile
  互斥`、`扫描失败: boom`、`profile 'bad' 加载失败` + 底层原因等）—— 既消音，也把此前
  从未验证过的输出变成回归保护。全量跑噪音 **4 → 0 行**。

- **90 个被跟踪文本文件末尾缺少换行**（评审清单 P2-17）：仓库内近半数文本文件
  （`tests/*.py` 40 个、`core/*.py` 21 个，以及 `docs/**`、`src-tauri/**`、
  `gui/dashboard.html`、`SECURITY.md`、`setup.py` 等）末尾无换行符。作为独立批次
  一次性补齐（每个文件恰好只多一个换行，diff 为 90 增 90 删），避免与其它改动混在
  一起淹没真实差异。清单原记 96 个，其中 6 个已在此前几轮归一化时顺手修掉。

- **「怎么跑测试」三处说法不一**（评审清单 P1-8 + P1-10，方案 B）：`pyproject.toml`
  曾声明 `[test]` 依赖组（pytest / coverage）与完整的 pytest、coverage 配置，但 CI
  从不安装它们、也从不产出覆盖率数据；README 与产品 PRD 还写着 `python3 -m pytest`
  并建议写死 `/usr/local/bin/python3`（Apple Silicon 上该路径根本不存在，前缀是
  `/opt/homebrew`）。现已**全项目统一为标准库 unittest**：删除 `pyproject.toml` 的
  `[test]` 组与全部 pytest/coverage 配置并就地注明理由；README 与 PRD 改指
  `scripts/ci_parity.sh` / `python3 -m unittest discover -s tests -p 'test_*.py'`；
  两份历史 plan 存档加时效性横幅（保留原文不改写，避免篡改已执行计划的记录），
  并把那句误导性的解释器建议改为「交给 `ci_parity.sh` 自动挑选，不要写死绝对路径」。

- **技能库根路径在 `import` 时被定死**（评审清单 P0-4，「改了要重启」类问题的共同
  根源）：`skill_market` / `skill_merge_advisor` / `skill_market_ops` 三处
  `_SKILLS_DIR = Path.home() / ...` 模块级常量在 import 期求值并缓存，运行期无法
  改变 —— 「技能市场源只在首次打开时探测、环境变化后刷不掉」与「用例读死开发机
  技能库」都是这一族的症状。新增 `core/paths.py` 提供访问器
  （`home_root()` / `skills_dir()` / `agents_dir()` / `default_lock_path()`），
  **每次调用重新解析、不缓存**；优先级为「显式注入 > 环境变量
  `SKILL_MCP_STUDIO_HOME` > 真实 home」，并提供 `override()` 上下文管理器供测试
  临时切换。四个消费点全部改为跟随访问器。附 `tests/test_paths.py` 锁定验收标准
  （不重启进程即可切根），并已反向验证：退回模块级常量语义即 4 个用例失败。

- **`probe_stdio` 的 stderr 管道从未排空**（评审清单 P0-5，`test_stdio_probe` 那次
  「偶发、复跑不复现」超时的根因）：`stderr=subprocess.PIPE` 打开后整个握手期间无人
  读取，子进程一旦向 stderr 写满管道缓冲（POSIX 通常 64 KiB）就阻塞在 `write` 上，
  不再读 stdin、不回握手，外部只能看到一句 `stdio handshake timed out`。新增
  `_StderrDrain` 守护线程按块排空 stderr（只保留末尾 2000 字符），失败时把 stderr
  尾部附到错误信息使超时可归因；`Popen` 增加 `errors="replace"`，避免解码失败让排空
  线程提前退出。附两个回归用例，并已反向验证：去掉排空即稳定失败。
  （实测：200 KiB 无换行 stderr → 修复前 8.01s 超时，修复后 0.07s 通过。）

## [v0.23.0] - 2026-09

当前发布版本（build 109）。

### 新增

- **界面统一规范（docs/DESIGN.md）**：把散落在样式表里的取值收敛成可查的规范，
  并补齐组件层。
  - **token 收敛**：圆角由 12 种取值（2/3/4/5/6/7/8/9/10/12/14/16/99px）收敛到四档
    （`--r-hair` 3 / `--r-control` 8 / `--r-card` 12 / `--r-pill` 999，弹窗容器单列 16）；
    字号 18 处硬编码清零，全部改用 `--fs-*`；颜色 30 处硬编码清零，新增 `--on-solid`
    （实体白：开关滑块/logo 描边）与 `--err-strong`（危险按钮悬停底色），
    强调色上的文字统一走 `--on-accent`。
  - **补齐组件层**：新增列表行组件（`.list-row` 系列）与空状态（`.list-empty`），
    补 `--r-hair` 档位，按钮体系（基础按钮 + 场景化变体 + 非按钮控件）登记成表。
  - **规范边界**：本项目是管理台（dense product UI），明确不套用落地页配方
    （hero / bento / marquee / 滚动编排），只采用与界面类型无关的质量规则。

### 修复

- **技能市场结果列表无样式**（用户反馈"这个页面也太丑了"）：`market-result` 类在 JS 里
  创建但**样式表里从未定义**，于是每行是裸文本与按钮上下堆叠；同时搜索结果被
  `appendMarketProgress` 重复输出一遍，同一屏出现两份列表。改为按规范用列表行渲染，
  去掉重复输出，并把上游英文原文的安装量（`368.7K installs`）中文化为「36.9 万次安装」。
  更新检查结果同样统一到列表行，状态进元信息行、操作固定右侧。
  市场来源读取失败时给出原因与出路（此前只有「读取失败」四个字），空状态容器不再占位。


- **技能市场接入（FEAT-9）**：接入 skills.sh 社区技能库，Skills 页新增「技能市场」面板，
  提供只读的源可用性、已装清单（含来源仓库与装/更新时间）、搜索与版本更新检测，以及
  经二次确认的在线安装/升级；进度按**逐技能**粒度展示。
  检查更新是纯只读实现——**不调用 `npx skills check`**：该命令名为检查、实为升级
  （实测一次调用即更新 41 个技能，且未出现在 `--help` 中），`npx skills update` 亦无
  `--dry-run`。改为 GitHub API 按 `skillPath` 取最新提交时间与 `.skill-lock.json` 的
  `updatedAt` 比对，纯 HTTP GET，不写盘；命中限流（未鉴权每小时 60 次）时区分于
  「仓库不存在」并立即短路，提示设 `GITHUB_TOKEN`。
  **归一无须额外机制**：装到 `~/.agents/skills` 即已落在统一库，因为它是
  `~/.skills-manager/skills` 的符号链接（`ls -ldi` 实测），四项客户端目录同理。

- **技能使用统计（FEAT-10）**：Skills 页新增「使用统计」面板，回答「这个技能到底有没有被
  用过、最近一次是什么时候」，为后续的合并与清理提供事实依据。数据取自各客户端落盘的
  会话日志（当前唯一可靠通路是 Codex：`~/.codex/archived_sessions` 与按日期嵌套的
  `~/.codex/sessions`，实测后者比前者还多 500+ 个文件，必须递归收集）。全程只读、不写盘。
  **判据只认工具调用记录**（`response_item.payload.type ∈ {function_call, custom_tool_call}`）
  里出现的技能路径：每个会话都会把全量技能清单注入 developer message（`host_skills`），
  工具返回内容也会回显别家技能的 `SKILL.md` 路径，若按技能名直接 grep，命中数会虚高到
  **100% 误报**。按动作强度分三档：`load`=触达 `<skill>/` 下具体文件（读取或被 `spawn_agent`
  显式派给子 agent，是「在用」的强信号）、`browse`=仅目录级引用（`ls` 浏览）、
  `edit`=`apply_patch`/`write` 改写（维护动作，不计入使用）。
  两个实测踩过的解析坑：`arguments` 是**二次编码的 JSON 字符串**，匹配前须把 `\/` 还原成
  `/`；`skills/hermes/`（带尾斜杠但无后续段）是浏览而非加载，早期用 `(\/)?` 前瞻会把
  `ls skills/hermes/` 误判成 `load`。CLI 出口 `scan.py --skill-usage [--usage-since ISO_DATE]
  [--format json]`。**本机实测结论**：202 个已装技能中，全时段仅 74 个被真正加载过，
  127 个零触达 —— 这是清理与合并的首要目标集。

- **技能整理建议（FEAT-11）**：Skills 页新增「整理建议」面板，回答「哪些技能是同一目标的
  双重存在、该归并；哪些只是看着像、其实是有意的变体」。全程只读，不删、不改、不移任何
  技能目录（执行能力另立 FEAT-12）。判据按强度分四条：T1 描述归一后逐字相同、T2 描述自述
  「仅当…显式指定…统一交由 X 处理」、T3 名称词干归一相同、T4 高相似且名称差异仅为噪声后缀。
  **为什么不采用纯文本相似度**（真实数据给的决定性反例）：`sensteed-java17-standard` 与
  `sensteed-java8-standard` 的描述 token 相似度为 **1.00**，但它俩是按 Java 版本分工的平行
  规范分册，合并会毁掉版本路由；`sensteed-*-review` 8 个两两 0.80~0.90，它们是
  `sensteed-review-hub` 的路由目标。真重复与有意变体的区别不在"像不像"，而在名称差异部分是
  噪声后缀还是**实质限定词**，故设两张词表且实质限定词优先（`java8`×`java17` 的名称里不含
  任何噪声词，只有靠它才拦得住）。三张清单互斥并全部留痕：`actionable`（可执行合并）/
  `upstream_only`（仅标注，升级会拉回，合并无效）/ `rejected`（被护栏否决 + 跨来源需选边 +
  悬空转发）。**上游是运维口径而非作者归属**：定义 = 在 `.skill-lock.json` 有登记（只有登记项
  会被 `npx skills update` 复原）；实测 10 个带 LICENSE 的技能不在 lock、`grafana`/`wecomcli`/
  `sensteed` 三族 lock 覆盖 0%，它们仍归 `actionable`，因为归并不会被拉回。
  顺带发现 **4 个死壳指向不存在的技能**：`lark-minutes`/`lark-note`/`lark-vc`/`lark-vc-agent`
  均声明"统一交由 `lark-meeting` 处理"，但库中无该目录，且四者零触达；这类判为悬空引用缺陷
  而非合并机会。CLI 出口 `scan.py --merge-advice [--usage-since ISO_DATE] [--format json]`。
  **本机实测**：202 个技能中 3 组可安全合并（涉及 7 个，其中 5 个零触达），
  24 对高相似被实质限定词正确否决，4 条悬空转发被抓出。

- **慢操作进度对话框**：「使用统计 / 整理建议 / 修复链接预览与实写 / 更新审计 / 市场
  检查·搜索·安装·升级」等 30 秒级的 CLI 调用，此前只有一行灰色小字或根本没有反馈，
  点了像没反应。现在 `runCli(args, progress)` 传入标签即弹出与 `runTaskModal` 同风格的
  居中对话框：转圈 + 文案 + **已用秒数计时**，完成自动关闭；`hideBusy` 放在 `finally`，
  异常路径也保证收框。三块面板展开时补 `scrollIntoView`——面板在长页面底部，
  不滚动到视野里同样像"没反应"。

- **使用统计面板视觉重设计**：面板从"纯文本墙"升级为结构化数据面板，判据与数据流零改动。
  统计窗口改用应用既有的 `segmented` 分段控件（新增 7 天档，当前窗口以 `active` 高亮，
  与 `USAGE_DAYS` 状态同步）；原先一行竖线拼接的状态长句拆为**指标条**（已装 / 被加载 /
  零触达 / 技能相关调用 / 通读会话文件五格，复用 `--display` 数字与 ok/err 语义色）
  加一行窗口说明；使用排行从 `1. 名称 加载 N｜浏览 N…` 文本行改为对齐网格行
  （序号 / 名称 / 相对强度条 / 三档计数 / 最近日期，表头一行，默认前 30 条 +
  「展开全部」）；零触达清单从顿号连排改为 chip 网格（默认 24 个 + 展开全部）。
  顺带补上 `.market-toolbar / .market-line(.ok/.warn/.err) / .market-results` 的 CSS
  ——这些类此前**没有任何样式定义**，整理建议与市场面板同样受益。全部颜色取自既有
  token，浅色 / 深色双主题经 headless Chrome 真实数据截图验收。

- **统计结果改用弹窗承载**：使用统计与整理建议属于「临时要看的内容」，常驻在页面流里会
  把技能页撑得又长又吵。两个面板改为遮罩弹窗，点遮罩即关闭，入场动效与既有弹窗一致。
  结果不再是打开页面就必须面对的主内容。
  浮层实现用**原生 `<dialog>` + `showModal()`**：浏览器会把它放进 top layer，这是
  「一定在最前端」的规范保证——`.shell` 与 `main` 都带 `z-index`（各自形成层叠上下文），
  普通 `position: fixed` 浮层会被困在祖先的层叠上下文里，还可能被 `overflow: hidden`
  裁剪或受 `transform`/`filter` 包含块影响；top layer 不受这三者任何一条约束。
  遮罩交给 `::backdrop`，弹窗与进度框都走 top layer（按打开顺序堆叠，后开者在上），
  所以扫描进行中进度框天然压在弹窗之上。

- **市场改为独立弹窗，且只列可用市场**：市场原先是以 `<div>` 内嵌在 Skills 页里的
  一段区域（自带搜索框、源探测、结果列表），把页面撑成了一个迷你应用。现在它和
  统计/建议一样是独立 `<dialog>` 弹窗，Skills 页下方只留技能列表。
  市场源也只显示可用的：可用性由后端 `s.available` 判定，前端只做呈现过滤，不再罗列
  "未检测到"的源（本机 QwenWork 与企业市场都未接入，列出来只会让人以为能点）；
  全不可用时给一行"未检测到可用的技能市场"兜底，避免弹窗顶部空白。

- **统计改为后台定时任务（不再弹「正在计算」）**：统计要通读约 2400 个会话日志
  （实测 30 秒以上），把它做成"打开弹窗才跑"的前台动作是错的。现在：
  APP 启动后延迟 8 秒补一次，之后按设置间隔静默刷新；打开弹窗只呈现当前结果，
  没有缓存时用行内"统计中…"提示，**不再弹全屏进度框**，用户不必先关掉一个对话框
  才能看数据。有前台任务在跑（进度框开着）时跳过该轮，避免和用户正等的操作抢 IO。
  只有用户主动点「重新统计」才显示可取消的进度框。

- **设置新增「自动统计间隔」**：设置 → Skill 子页新增卡片，档位
  `关闭 / 5 / 15 / 30 / 60 分钟`，默认 15 分钟，存 localStorage 并即时重排定时器。
  选「关闭」后只有手动点「重新统计」才执行。

- **交互规范审计**：Skills 页原先承载 20 个控件 / 11 个区块，而概览 / IDE / MCP 页
  都只有 1 个区块、0-4 个控件。单页过载的根源是"查看类内容"（统计、建议、市场）
  被塞进列表页；三者改为弹窗后，Skills 页只负责"技能清单 + 逐技能状态"这一件事。

- **重跑建议接入标准进度展示**：合并完成后要重跑一次建议才能核对结果，这同样
  要通读会话日志（约一分钟）；此前它自己调 `runCli` 且不传进度参数，整整一分钟
  静默等待，看起来就是"卡死了"。现在重跑改走 `runSkillInsight(null, { busy: true })`，
  用的是与「强制重新统计」完全相同的标准进度——可取消进度框、真实扫描进度、
  已用时间；进度框在结果框之上，结束后回到结果框并弹出核对结论。
  同时把「重跑建议核对」从合并阶段列表里去掉：它实际发生在结果之后，留在列表里
  会让最后一项永远停在原地，正是用户截图里那个"停在重跑阶段不动"的样子。
  阶段框现在只描述归并本身（复核判据 / 备份 / 移入 _trash）。

- **修复「点击合并没反应、只闪一下」**：结果面板（使用分析）是 `showModal()` 的
  `<dialog>`，按规范进入 **top layer**，会绘制在所有普通浮层之上；而确认框当时挂在
  普通 `<div id="modal-root">` 里，于是被面板整个盖住。用户点「执行合并」后确认框
  确实创建了——但屏幕上一片空白，看起来就是"闪了一下、什么都没发生"。
  修复：`modal-root` 改为 `<dialog class="modal-layer">`，`mountModal` 走
  `showModal()`（与既有的 `busy-root` 同一模式），并让 `confirmModal` 改走
  `mountModal`（它此前直接写 `innerHTML`，绕过了 `showModal()`）。
  排查过程中还修掉一个相关隐患：切换统计窗口且无缓存时会清空 `ADVICE_DATA`，
  却没清视图，留下上一次渲染的卡片——那些"幽灵按钮"点下去只会弹一句提示。
  现在清数据同时清视图，并且按钮参数一律取自按钮自身（不读全局快照）。
  教训：只断言 DOM 里存在 `cfm-card` 的测试抓不到这个 bug，必须断言挂载方式，
  并用 `elementFromPoint` 验证"这一点上最顶层的是谁"。

- **整理建议从"只给建议"变成"能直接执行"（FEAT-12）**：此前面板全程只读，底部
  还写着"本面板不会替你执行"，用户看完建议仍需自己动手删技能。现在每张合并卡片
  都有「执行合并」，面板顶部有「全部合并（N 组）」，点一下就走完。
  安全设计：归并方先备份到 `_backup/` 再移入 `_trash/`（复用既有
  `soft_delete_skill`，可恢复，不新造删除机制）；写操作前二次确认并写明去向；
  **执行前重新跑一遍判据**，只在这组此刻依然成立时才动手 —— 界面上的建议来自
  缓存，可能已经过期，照着旧结论改新世界的盘就是误删。保留方与组外技能一律不动。
  执行后自动重跑建议并核对该组是否真的消失，核对不通过会提示人工介入，而不是
  执行完就报成功。

- **修复面板 tab 点击无效**：合并后的「整理建议」tab 点了没反应。原因是按钮只写了
  data-insight-tab、漏了 data-action，而事件委托的入口是
  \`e.target.closest("[data-action]")\`，拿不到就直接 return —— 点击被静默丢弃，
  不报错、不告警。新增 tests/test_delegation_contract.py 固化这条规律：委托链里
  通过 act.dataset.X 读取的字段，其按钮必须带 data-action，否则就是走不进委托的
  死按钮。该测试已用注入原始缺陷的方式双向验证过（会红）。

- **修复 run_cli 安全边界漏登记**：新增的组合出口  未加进
  Rust 侧  白名单，界面一点就被拦（"子命令不在白名单内"）。同时
  发现同类问题： /  也从未登记（它们走的是
  独立 flag，而非  的取值），市场的安装与升级从界面触发同样会被拦。
  两者均补入白名单； 还需挂进度文件（否则长任务进度条不动），
  一并修好。新增 tests/test_run_cli_boundary.py 把前端实际调用的 flag 与白名单、
  进度文件注入绑定校验，避免以后新增出口再漏登记。

- **使用统计与整理建议合并为一次扫描、一个入口**：两者本来共用同一份会话日志
  汇总（整理建议的保留者打分依赖 load/sessions，零触达判定也来自它），却各自
  调一次 CLI，等于把同一份约 2400 个日志文件的扫描做两遍。后端新增组合出口
  `--skill-insight`，只跑一次 `scan_usage` 并把结果注入 `scan_advice`
  （该参数本就是为复用预留的，此前一直没人用），一次返回两份结论。
  前端随之合并：页头两个按钮变成一个「使用分析」，两个弹窗合并成一个面板，
  内部用 tab 切换「使用统计 / 整理建议」，窗口档位两者共用。

- **打开面板直接看结果，不再等 30 秒以上**：面板打开一律读缓存即时渲染
  （统计与建议同存一条缓存，避免出现"统计是新的、建议是旧的"这种自相矛盾状态），
  不发扫描、不弹进度框。缓存过期只做后台静默补。面板顶部显示「N 分钟前统计」，
  让"直接看结果"这件事对用户可见。

- **强制重新统计**：面板内新增按钮，是唯一绕过缓存重跑的入口，也只有它会显示
  可取消的进度框（用户主动发起、愿意等）。后台定时任务改为跑合并出口，一次同时
  保持两份结论新鲜。

- **修掉两个真实缺陷**：合并后 `loadUsageCache()` 成为孤儿调用，页面加载即
  `ReferenceError`；启动预热缓存会在顶层调用 `applyInsight`，而 `ADVICE_DATA`
  的 `let` 声明在它之后，有缓存的老用户一开 APP 就命中 TDZ 崩溃。两处都由
  端到端哨兵与截图验收抓出并修复。

- **整理建议排版结构化**：原先整块内容是纯文本流（一路 `usageLine` 拼接），
  可读性差：技能名、加载数、会话数、最近时间、状态全挤在一行里，有列结构却读不出列，
  三组建议之间也没有分隔，看上去像一段 dump。现在改为：
  规模进指标条（沿用使用统计的 `.us-cell`，两处读法一致）；
  每组可执行合并一张卡，组头是规则徽标 + 加粗的保留技能名 + 归并项；
  成员信息落进表格，技能/加载/会话/最近/状态五列，标识符用等宽字体、
  数字右对齐并启用 tabular-nums，零触达/含脚本/保留/上游改用语义色标签；
  已否决与上游两段降为次级列表（留痕性质，不该占卡片视觉重量）。

- **统计弹窗滚动错位修复**：`.insight-toolbar` 与表格 `thead th` 都写了
  `position: sticky; top: 0`，把弹窗滚到表格中部时两者抢同一个位置，表头盖住工具条
  （表现为"表头跑到工具条上面、按钮被压住"）。改为标准的弹窗内两级滚动：
  卡片自身不滚（`overflow: hidden` + flex 列），工具条固定在卡片顶部（不再是 sticky），
  只有结果区 `.market-results` 内部滚动，表头的 sticky 从此只相对结果区生效，
  两者不再争位。

- **统计指标口径拆开**：原先把「通读会话文件 2,393」与「已装技能 202」并排放在同一个
  指标条里，两者根本不是同一口径（202 个技能与 2393 个会话日志没有对应关系），
  会被读成"2000 多个技能记录"。现在指标条只放技能口径的四个数（已装 / 被加载 /
  零触达 / 技能相关调用（次）），扫描规模降级到说明行，写成
  「统计窗口：…｜已通读 N 个会话日志｜判据由后端给出」，带上完整语境。

- **统计结果本地缓存**：全量统计要通读约 2400 个会话文件（实测 30 秒以上），每次打开都
  重扫纯属浪费。结果按窗口天数缓存（`localStorage`，10 分钟 TTL）：打开弹窗**先秒出上次
  结果**，仅当缓存缺失或过期才重新扫描，且过期时走**后台静默刷新**（不再闪一条"统计中"
  打断阅读）；切换 7/30/90/全部时间同样先吃缓存。用户主动取消时保留已有结果，不替换成报错。

- **进度框支持取消，且给出准确进度**：进度框新增「取消」按钮，关闭即**真正终止子进程**
  （Rust 侧 `cancel_cli` 对子进程组发 `SIGTERM`，子进程以 `process_group(0)` 独立成组，
  连子孙一起收掉），不是「眼不见为净」。同时不再只显示「已用 N 秒」：会话文件是先收集完
  再逐个读的，**总量在开扫前就已知**，所以 Python 侧把 `{phase, done, total, pct, ts}`
  原子写入进度文件（`--progress-file`，路径由 shell 决定，webview 不能指定任意写盘目标），
  前端每 400ms 轮询 `read_scan_progress`，显示 `扫描会话文件 1436/2393 · 60%` 并带进度条；
  进度条宽度同样走 CSSOM。目录收集阶段总量未知时不伪造百分比，退回显示已用时间。

### 修复

- **使用统计的「强度」条全部一样长（CSP 静默吃掉 `style` 属性）**：现象是统计表里 13 条
  强度条长度完全相同（逐像素实测均为 236px、极差 0），而百分比算得没错（100/52/39/38/29…）。
  根因不在样式，在 CSP：`tauri.conf.json` 声明了 `style-src 'self' 'unsafe-inline'`，但
  Tauri 构建期会调用 `inject_nonce_token` 给**每个 `<style>` 元素**注入 nonce
  （`dangerousDisableAssetCspModification` 默认 `false` 时启用）。运行时 CSP 因此变成
  `style-src 'self' 'unsafe-inline' 'nonce-…'`，而按 CSP 规范，**指令里一旦出现 nonce/hash，
  `'unsafe-inline'` 即被忽略**：`<style>` 块靠 nonce 活着（所以整站样式看着完全正常），
  而所有 `style="…"` 属性被静默拦截——宽度失效后 `<i>` 退化成撑满整列。这类缺陷最阴险的
  地方是「看起来没坏」：样式还在、数字还在，只有尺寸语义悄悄丢了。修复分两层：
  ① 配置层显式设 `dangerousDisableAssetCspModification: true`，让声明的 `'unsafe-inline'`
  真正生效（全站 75 处 `style` 属性一并复活）；② 代码层不再把关键尺寸交给 `style` 属性，
  强度条改为 `data-pct` + CSSOM 赋值（`el.style.width`）——CSSOM 不受 `style-src` 约束，
  实测在「已注入 nonce 的旧形态 CSP」下依旧渲染正确（246.3/128.0/96.0/93.6/71.4），
  属双保险。新增 `tests/test_gui_inline_style_csp.py` 锁死配置开关与 CSSOM 写法。

- **使用统计 / 整理建议 / 技能市场三个按钮上线即静默失灵**：FEAT-9/10/11 的面板块曾被
  整体误插进 `reprobeEndpoints()` 的函数体内，其中的 `toggleUsagePanel` 等函数全部变成
  嵌套闭包，顶层事件委托查不到它们——每次点击只留一行控制台 `ReferenceError`，界面毫无
  反应。`node --check` 与全部单测拦不住：语法合法，而切片式测试是把代码段**单独取出来
  跑**的，看不见外层嵌套。修复是把 `reprobeEndpoints` 的收尾复位到面板代码之前；并新增
  **整脚本端到端哨兵**（`tools/dash_crash_harness.js` + `HarnessE2ETest`）：把仪表盘装进
  vm、对每个按钮**真实派发点击**，断言「委托 → toggle → runCli → 进度框」整条链路可达。
  这类作用域 bug 只有执行整份脚本才暴露，静态检查一律无效。

- **「修复链接」预览仍把 `non_agent` 客户端算进总路径（7 → 6）**：FEAT-7 把 CC Switch
  从 IDE/Agent 列表与技能面板统计中排除的口径，没有同步到 `--fix-skills`——它的
  `~/.cc-switch/skills` 照样进预览清单，卡片显示"总路径 7"，而用户实际只有 6 个
  IDE/Agent。现新增共享过滤器 `_drop_non_agent_rows`，**预览与 Phase 6 实写同源**：
  预览显示 6 项、实写也按 6 项执行，不再各说各话。预览的过滤并挪到了 `fix_all` **之前**
  （修复计划与表格同源）。技能审计链路（`run_scan` → `combined_checker`）不受影响，
  CC Switch 的技能行照常接受检查，监督不丢。回归测试见 `tests/test_fix_skills_scope.py`。

- **「一键合并技能」按钮名不副实**：它实际调用 `--fix-skills`，只把各客户端 skills 目录
  重建为指向统一仓库的链接，**与"合并重复技能"完全无关**。新增真正的整理建议后，两个
  按钮并排必然误导，故改名 **「修复链接」** 并加 title 说明其真实作用。只改文案，
  `data-action="merge"`、`--fix-skills` 参数与行为不变。

- **T4 弱相似规则对中文技能永久失效**：分词起初用 `[\u4e00-\u9fff]{2,}`，会把
  「创建和操作电子表格」整串收成一个 token，两段措辞略有出入的中文描述 Jaccard 实测只有
  **0.2**（真实相似度约 0.8）。本库中文描述占多数，等于 T4 形同虚设。改为**中文按字符
  二元组（bigram）切**后，被护栏拦下的对数从 18 升到 24（新增的都是中文近重复对），
  而 `actionable` 三组不变 —— 说明改动只增加召回，没有放松护栏。

- **市场面板打开后源状态永不加载**：`toggleMarketPanel()` 引用了全文件从未声明的
  `MARKET_DATA`，一执行到该行就抛 `ReferenceError`，导致面板显示为空白。`node --check`
  与全部单测都是绿的——因为没有任何测试真正执行这段 JS。补上声明与写入，并新增一条
  **静态守卫**（`UndeclaredStateRefTest`）：剥离字符串/注释后，扫描「全大写对象被引用
  却从未声明」的差集；配套一条植入样本的守卫自检，防止守卫本身空转。

- **技能面板与 IDE/Agent 表口径统一（FEAT-7）**：技能面板列 7 个客户端、IDE/Agent 表
  列 6 个，同一界面里两个数字对不上——差异来自 CC Switch：它按 FEAT-6 标了
  `non_agent`，前端 IDE/Agent 面板经 `_agentsForPanel()` 排除了它，但它同时在
  `config.yaml` 注册了 `skills_paths`，于是仍然出现在技能面板里。用户无从判断该信哪个。
  现让非 IDE/Agent 客户端（`non_agent`）不再进入技能面板的 `clients_states`，两处统一为
  「本机安装的 IDE/Agent」这同一批 6 个。
  **边界**：只改 GUI 渲染数据源，技能**审计**不减弱——审计走
  `combined_checker` → `run_scan` 的 `managed_names`，与 `clients_states` 是两条
  独立数据链，故 CC Switch 的技能行（`~/.cc-switch/skills`，`status=correct`）照常
  被检查，186 个技能的监督不丢。已用测试分别锁定「不进面板」与「审计仍覆盖」两侧。

## [v0.22.0] - 2026-09

当前发布版本（build 108）。

本次为 **minor** 升级：含 2 项新功能（MCP 面板改为单表覆盖矩阵、漂移识别与一键回流）、
4 项缺陷修复、1 项非 IDE/Agent 客户端身份定案、1 项 CI 基础设施升级。
本版同时是 `0.21.1` 的**首次正式发布**——`0.21.1` 此前只进过 `develop`，
从未打 tag、从未发布，其内容一并包含在此版本中（见下方 `v0.21.1` 段落）。

### 修复

- **备份列表的顺序不再依赖 mtime（真实缺陷，非仅测试脆弱）**：`list_config_backups`
  原先只按 `mtime` 倒序，而 `mtime` 会被「同一秒内连续写入」或文件系统的时间分辨率
  抹平——此时排序退化成 `os.listdir` 的任意顺序，**列表里「最上面」的未必是最新备份**，
  用户据此还原就会选错版本。备份文件名后缀（`.bak-YYYYMMDD-HHMMSS-ffffff`，定长零
  填充）才是单调递增的权威序号，现在它以主键参与排序（`suffix` → `mtime` → `path`
  稳定裁决），任何输入下顺序唯一确定。该缺陷由 CI 暴露（本地因 mtime 恰好不同而侥幸
  通过）：`test_lists_only_own_backups_newest_first` 在 GitHub Actions 上稳定失败。
  已补两例测试（其中之一把 mtime 全部压平、并让目录顺序与时间序相反），并做过反证
  ——把实现改回旧写法时两例均失败。

- **CC Switch 不再是「一个 AI Agent」（FEAT-6）**：CC Switch（`com.ccswitch.desktop`）
  是**供应商切换器 + 本地代理**，给 Claude Code / Codex / Gemini / OpenCode 切换配置
  （其库中 `providers` 按 app_type 分 claude/codex/gemini/opencode；`mcp_servers` 带
  `enabled_claude`/`enabled_codex`/`enabled_gemini`/`enabled_opencode`/`enabled_hermes`
  标志）。它自身不做推理、不跑 agent 循环，也不消费 MCP——它是把 MCP **注入**别的
  客户端。同时它带技能管理功能（282 条技能 / 10 个远端仓库），故 `~/.cc-switch/skills`
  是统一技能库的挂载点。它既不是 IDE 也不是 Agent。
  此前它被自动发现登记成带点的目录名 `.cc-switch`、类型推断成「AI Agent」、
  安装状态因发现条目缺 `install` 段而误判为 `none`，再被 UI 的
  `install_state !== "none"` 过滤掉——于是「看不见」，但那是**安装判定失败导致的
  巧合**，一旦修好安装判定它就会冒出来并被算成一个 Agent。
  现在在 `config.yaml` 中给它正规身份（`name: CC Switch`、`type: 配置工具`、
  `install.app_bundles`、`skills_paths`、`non_agent: true`）。因 `effective_tools`
  按归一化名去重（`.cc-switch` 与 `CC Switch` 同归一为 `ccswitch`），该声明与发现
  条目**字段级合并**，幽灵条目随之消失、名字与类型被修正。可见范围明确为：
  **技能审计里可见**（185 技能，`skills_compliant` 亦转正，审计退出码 0），
  **IDE/Agent 表与统计里不可见**（`is_agent: false`，前端统一经
  `_agentsForPanel()` 取数），**MCP 面板里不出现**（它不消费 MCP）。
  同时把 `cc-switch` 从 `scanner.py` 的「AI Agent」类型关键词中移除，
  消除与 `config.yaml`「非 AI Agent」注释的自相矛盾。

- **新增「被外部工具改写」识别与一键回流（DATA-8）**：`~/.codex/config.toml` 这类
  文件是**多写者竞争**的。实测：CC Switch 每次切换通道都用它自己的两个片段
  （当前 provider 的 `config` + `codex` 通用配置）重新生成整份文件，而这两个片段里
  **不含任何 `[mcp_servers]`**；把活文件去掉 `mcp_servers` 后与二者合并结果比对，
  12 个键与值完全一致。因此凡是不被它登记的端点（如 `K8s-uat`、`hermes`）都会被
  静默抹掉，而它自己登记的（`hermes-nas`：活文件里的块与它数据库里的配置逐字节一致）
  与客户端自带的（`node_repl`、`computer-use`）则存活。现场复现：16:03:15 修复写入
  成功，**34 秒后**即被写回旧状态。
  快照新增 `drift`（`suspected` / `lost` / `backup_count` / `last_backup` /
  `last_backup_at`），判据只用一个客观事实：`<config>.bak-*` 兄弟备份是**本工具写入
  前**留下的，故「有备份 + 期望端点不见」= 写入成功过、之后被别人改掉（疑似外部
  改写）；「无备份 + 端点不见」只是「尚未应用」。面板据此在客户端标签位说明**原因**
  并就地给出 `回流` 按钮（复用既有 `fix-mcp` 动作，写入前自动备份），图例汇总
  「N 个疑似被外部改写」；`缺失` 仍表达端点状态，原因与状态分开表述。

- **「不支持 MCP」被误报成「缺失」**：注册表未声明 `mcp_config_path` 的客户端
  （实况 `ima.copilot`，已安装但没有 MCP 配置文件）根本没有 MCP 能力，
  却仍被按默认「全部端点」套上期望，于是判成「声明要挂却没挂」的异常，
  在异常计数里多出一个虚假故障。快照新增 `supports_mcp`，不支持时期望与缺失
  均为空（`core/management_snapshot.py`），能力缺失不再计入异常。
  界面上「不支持」与「缺失」双维度区分：缺失 = 橙色空心环 + 左侧 2px 警示条
  （真异常）；不支持 = 灰色横杠 + 整行去强调（不适用，非故障），端点列显示
  「不适用」、挂载列显示「不支持」，且不计入异常数。首页 MCP 列的「无配置」
  一并统一为「不支持」，与面板共用一套词汇。

### 变更

- **MCP 面板改为单表覆盖矩阵**：P2 修复之后，「端点挂载状态」列（端点键 + 状态 +
  来源长文案）与下方「端点 × 客户端 覆盖矩阵」表达的是同一份数据，界面出现两张等价表，
  且单元格里重复端点名，既冗余又难纵向扫读。现合并为一张表
  （客户端 / 各端点状态列 / 挂载 / MCP 条目），端点名只在表头出现一次，
  端点库之外但实际观测到的端点仍会补出列，不会静默丢状态。
- **状态改为形态 + 色彩双编码**：实心点 = 配置里已有；空心环 = 声明要挂却缺失；
  浅灰环 = 未纳入期望；灰色横杠 = 不支持 MCP。异常行用左侧 2px 警示条标注，
  不再用与客户端名争权重的 `⚠ N` 角标；端点表头保留大小写（此前被 `thead` 的
  `text-transform: uppercase` 改写成 `K8S-UAT`）；「来源」由每行长文案改为
  `手动` / `自动` 微标签 + tooltip，语义在页面提示与图例里解释一次。
- 图例复用 Skills 面板的 `.skill-legend` 形态，右侧汇总「N 客户端 · M 端点 ·
  K 个不支持 MCP · K 个存在缺失」；新增空端点库、零客户端、显式声明、
  库外端点等边界处理。

### 测试

- 新增 `tests/test_dashboard_mcp_ui.py` 20 例：源码结构护栏（单表、端点名仅在表头、
  表头大小写、形态/色彩双编码、不支持与缺失的形状区分、警示条只给异常、
  语义只解释一次、首页与面板词汇一致）与 node 渲染快照（对齐后的表头/行内容、
  仅异常客户端被标注、不支持行读作不适用、两类计数分离、旧快照回退、
  输出无 `⚠`/`✓` 图形字符、空库/库外端点/零客户端/手动来源）。
- `tests/test_management_snapshot.py` 新增 DATA-7 用例，锁定「不支持 MCP 不得报成
  缺失异常」，并与「声明要挂却没挂仍判缺失」的对照组一并断言；新增 `DriftDetectionTest`
  5 例锁定漂移判据（有备份+缺失=外部改写、无备份=尚未应用、无缺失不报、文件不存在不抛）。
- `tests/test_dashboard_mcp_ui.py` 13 → 26 例。
- `tests/test_management_snapshot.py` 新增 `NonAgentClientTest` 4 例，锁定
  「技能审计可见 / IDE/Agent 表不可见 / MCP 面板不可见」三条边界。
- 新增 `tests/test_dashboard_agents_panel.py` 7 例：静态锁定所有 IDE/Agent 面板
  必须经 `_agentsForPanel()` 取数（防回归），并用 node 驱动真实
  `renderHomeListView` 断言非 IDE/Agent 既不入行也不计数、旧快照缺字段时不丢行。
- 全量 **608 passed, 28 subtests**（含备份排序缺陷新增的 2 例）。

> 以下为合入 `master` 前累积的未发布记录。

## [v0.21.1] - 2026-09

当前发布版本（build 107）。

### 修复

- **P0（数据损失）TOML 嵌套子表被当成独立 MCP 条目**：`parse_toml_mcp_servers` 只特判了
  `.env` 子表，其余子表一律落成新 server。Codex 用
  `[mcp_servers.<name>.tools.<tool>]` 记录 `approval_mode` 审批设置，于是真实 4 个 server
  被解析成 **11 条**，多出的 7 条被归类为「未纳管」并出现在「清理未纳管」清单里——点击即
  删掉这些审批设置。现按 TOML 语义只取**第一个点分段**为 server 名，更深子表归属该 server
  且不贡献字段（`env` 仍折叠进 `env`）；只有子表、没有父表时不再凭空造出 server。
  顺带修正两处泄漏：段头可带 `# 注释`（此前导致该段字段写入**上一个** server）、非
  `mcp_servers` 段结束当前上下文（此前跨段字段会混入上一个 server）。
- **P1（假阳性）「已配置 MCP 端点」把期望当事实**：端点列原本直接渲染 `mcp_attach`，而未
  显式声明时 `resolve_client_attach` 返回**端点库全集**，因此一个 `config_path` 为空、
  inventory 为 0 的客户端也显示为「已配置两个端点」。快照新增
  `has_explicit_attach` / `observed_attach` / `missing_attach` / `undeclared_attach`
  （`mcp_inventory.attachment_consistency`），把「期望」与「实际观测」分开，使
  **声明要挂却没挂**可被判为异常。实况：`ima.copilot` 由「已配置 K8s-uat, hermes-home」
  修正为 **⚠ 2 个端点未挂载**。
- **P2（冗余与误标）界面两列语义重叠**：第二列改为**端点视角的挂载状态**（已挂载 ✓ /
  未挂载 ⚠ / 未配置），并标注期望来源（手动指定 vs 自动默认全部端点）；第三列保留
  「配置文件里的真实条目」并在 tooltip 里给出 `端点：<key>` 映射，消除两列命名错位
  （端点键 `hermes-home` vs 配置键 `hermes`）。覆盖矩阵同步改为按**实际观测**着色，修掉
  同一假阳性，并修正把 `attached`（已挂载但未声明）显示成「未纳管」的误标。

### 测试

- `tests/test_config_codec.py` 9 → 20 例（嵌套子表、跨段字段泄漏、真实 Codex 形状回归、
  两条解析链路一致性）；新增 `tests/test_mcp_attachment_consistency.py` 12 例
  （观测端点、期望/缺失/未声明、快照字段护栏）。全量 **538 passed, 28 subtests**。

## [v0.21.0] - 2026-09

该版本构建号 build 106。

### 新增

- **MCP 条目删除与清理**：管理台可按条目或按分类（`attached` / `legacy` /
  `unmanaged`）清理任意客户端的 MCP 条目，**包含以往只能查看、不能删除的「未纳管」
  条目**。新增 CLI：`--remove-mcp-entry`、`--remove-mcp-class`、`--list-config-backups`、
  `--restore-config-backup`，以及高风险门 `--force-high-risk` / `--include-high-risk`
  （共 6 个参数，均支持 `--dry-run`，新命令支持 `--format json`）。
- **高风险分级确认**：识别「疑似客户端自带」的条目（命令落在该客户端 `app_bundles`
  内、路径含 `.app/Contents/`、或条目名与客户端同名/别名），默认拒绝删除；GUI 需
  **手输条目名**方可解锁。本机实测恰好命中 Codex 的 `node_repl` 与 `computer-use`。
- **配置备份回滚**：可列出某客户端配置的历史备份并从任意一份还原（整文件覆盖，
  还原前自动再备份当前文件）。

### 修复

- **JSONC 配置无法删除条目/还原备份**：`json.loads` 不接受 JSONC 注释，带注释的
  `opencode.jsonc` 在删除时报 `error`、还原报 `refused`。改为**按字节范围定点删除
  成员**（不使用「解析→改 dict→序列化」），注释、缩进、键序逐字保留；校验路径改为
  「注释屏蔽后再解析」。新增 `core/jsonc_text.py`（含 34 个用例）。
- **删除原语的假成功**：JSON/YAML/Reasonix 分支在**没有命中任何待删条目**时仍会
  重新序列化，把「无操作」误报成 `updated` 并顺手改写用户配置、生成备份。现统一
  满足「无命中则原样返回」不变式（与既有 cordis 分支对齐）。
- **测试跨用例状态污染**（长期存在的顺序依赖失败）：`SetUnifiedDirTest.setUp` 把
  `config_store._local_overrides_file` / `_overlay_target` 两个**模块级函数**替换为
  指向自身临时目录的 lambda，`tearDown` 却只清理目录、未还原函数。污染因此在同
  进程内持续存活，后续 `OverlayRegistrationTest` 拿到的「原函数」已是污染版本，
  其 `_overlay_target` 返回前一个用例已销毁的临时目录。表现为
  `test_overlay_target_reuses_first_existing_profiles_local` **单独运行通过、按文件
  或全量运行失败**。已在 `setUp` 记录原函数、`tearDown` 还原。全量测试
  `1 failed, 514 passed` → **`515 passed`**。

### 变更

- **六维度深度评审整改**：按 `docs/reviews/评审报告-v0.20.0-六维度深度评审.md`
  完成 54 项整改——CLI 契约单源（A-1）、探测三态退出码（A-2）、注册表收敛（A-3/A-4）、
  无环 import（A-5）、config_codec（A-6）、`main()` 拆分 `build_parser()` 与 Phase 7 编号
  补齐（A-7）、active_profile 只读定案（P-3）、后端 `state` 契约落到每条 record（U-2）；
  auth_token 0o600（D-3）、open_url 注入加固 + CSP 收紧（D-4）、除死代码与裸 except
  （D-2/D-9）、TOML 转义（D-8）、原子写（D-6）、退出码 2 分层（D-7）；GUI 键盘可达性 /
  CLI 未装透出 / 语义色 / 模态可及性（U-1/U-3/U-4/U-5）；CI 测试门禁（Python unittest +
  cargo test + node:test）+ 签名/公证验证 + SHA256SUMS + 平台 bundle.targets +
  concurrency（T-1/B-2/B-3/B-4/B-6）；Rust `#[cfg(test)]`（spawn 路径解析 + open_url
  注入）+ node:test 纯函数（T-3）；pytest/coverage 配置 + wheel 形态守护 + 跨平台路径 +
  flaky/文件句柄/环境耦合修正（T-4..T-10）；QwenWork/TraeWork 注册表（P-5/B-8）；arm64
  按需立项文档化（B-9）。测试 381 → 448（Python 440 + Rust `cargo test` 3 + node:test 5）。
- **Tauri 白名单**：`run_cli` 的允许参数新增上述 4 个命令（壳只透传 argv、写盘仍在
  CLI 的安全链内）。
- **构建文档**：修正 `src-tauri/BUILD.md` 中仓库本地工具链的 `PATH` 写法——原写法
  `$CARGO_HOME` 含 `..`，会导致 `cargo: command not found`。

## [v0.20.1] - 2026-09

build 105。

### 修复

- **安装探测**：GUI 壳（Finder / Dock 启动）继承 launchd 的最小 PATH，使经
  Homebrew / npm / pipx 安装的 CLI 探测落空，在用客户端被误判为 `config_only`
  「仅配置」——该状态会开放「删除客户端」清理入口（备份后删除其配置文件）。新增
  `tool_registry.which_with_fallback`：PATH 优先，未命中再兜底常见 bin 目录
  （Windows 按 `PATHEXT` 补后缀），成为 `detect_installation` 的默认实现；调用方
  注入 `command_exists` 时仍完全接管该逻辑，测试契约不变。
- **注册表**：`DeepSeek Harness` 的 app bundle 更正为 `/Applications/DeepSeek
  Harness.app`（旧名 `DeepSeek AI Assistant.app` 保留兜底），`commands` 补
  Homebrew 绝对路径，并修正过期的 bundle id 注释；主流默认注册表条目同步补
  `app_bundles`，三平台一致。附带效果：`Claude Code` 等仅声明裸名 CLI 的客户端
  也从漏判中恢复。

### 工程化

- `scripts/bump_version.py` 同步范围扩展：新增 README 版本 badge、`SECURITY.md`
  「当前版本」、架构图版本标注、控制台浏览器预览兜底、Issue 模板版本示例与
  CHANGELOG 链接块，消除文档版本与 `version.json` 的漂移。
- 新增 `CliFallbackTest` 回归用例：裸名兜底命中、路径形态不扫描、默认走兜底、
  注入语义不变。

## [v0.20.0] - 2026-09

build 104。

### 变更

- **跨平台**：新增 Windows / Linux 构建支持——`mainstream_registry` 引入 `by_os`
  + `sys.platform` 路径分派，`tool_registry` 新增 `expand_path` 统一展开 `%VAR%`
  与 `~`，Rust 壳 `cli_candidates` 三平台适配；新增 `build-windows.yml`
  （NSIS + MSI）与 `build-linux.yml`（deb + rpm + AppImage）。

### 修复

- 修复 Windows / Linux 跨平台构建失败。

### 工程化

- tag（`v*`）触发时把 `.exe` / `.msi` 与 `.deb` / `.rpm` / `.AppImage` 追加到同一
  GitHub Release；非 tag 触发仍只上传 artifact（与 `build-macos.yml` 对齐）。
- 新增 GitHub 推送门禁 `pre-push` hook 模板：推送到 GitHub 需显式放行
  （`GITHUB_PUSH_ALLOW=1`）。

## [v0.19.0] - 2026-09

build 103。
### 变更

- **隐私加固**：主干中硬编码的真实端点域名与 IP 全部改用占位符；`ai-memory` 默认服务
  地址改用 `127.0.0.1` 占位。
- **UI**：浏览器预览示例改为「未配置」初始态（不预置端点）；合并预览口径统一；端点
  测试；设置子页持久化。
- **MCP**：鉴权改为明文 `Bearer` 头落库；修复覆盖所有纳管端点并支持鉴权落库。
- **Skills**：新增 `SKILL.md` frontmatter 契约审计。
- **修复**：一键修复失败详情改用 `cliFailLines` 提取关键行；修复「失败被误报为成功」的
  退出码与错误提示缺位；端点 overlay 复用与注册双重缺陷。

## [v0.18.0] - 2026-09

build 101。

### 变更

- **管理台**：统一三面板客户端口径，修复幽灵客户端与 MCP/skills 误报；彻底删除客户端
  （注册条目 + 残留配置 + skills 链接）；补全修复/清理能力。
- **Skills**：嵌套子技能展示描述 + 技能级操作（备份/导出/重命名/删除）。
- **MCP**：旧通道清理改为纯删除，统一列表与卡片页口径。
- **配置**：客户端删除改本机停用，恢复主干注册表三客户端；移除未安装客户端注册条目。

## [v0.16.1] - 2026-09

build 96。

### 变更

- **GUI**：设置页分区重构、IDE/Agent 双视图与 MCP 端点功能；主页 IDE/Agent 面板重构。
- **MCP**：端点测试连接、认证 Token 与 stdio 本地命令支持。
- **注册表**：分类重构为 AI IDE / IDE Plugin / AI Agent 三类并补齐 MCP 写入。
- **路径**：修正 Trae / Windsurf / DeepSeek Harness 默认路径为标准路径。

## 早期里程碑（v0.x 之前）

以下为阶段一至阶段五过程中的关键能力落地：

> **命名迁移（P-10）**：项目自历史名 `skills-mcp-unifier` 更名并迁移为
> `skill-mcp-studio`（仓库 `github.com/oswaldhill/skill-mcp-studio`）。代码内 CLI
> `--help`、MCP `clientInfo.name`、报告头均使用新名；旧名仅作为符号链接别名目录
> （`skills-unifier`/`skills-mcp-unifier`）与历史文档中的演进记录保留。

### 阶段五 · 通用管理台重塑

- 五页信息架构（概览 · IDE/Agent · Skills · MCP · 设置）与视觉重构。
- rebuild `.app`（Tauri P4/P5）、客户端添加与统一目录写命令（P7）、端点库 CRUD 与 MCP
  清单命令（P3）、按客户端挂载过滤端点（P2）、管理快照重建。
- 阶段五管理台完整评审 + 整改报告。

### 阶段一~四 · 核心能力

- **endpoint profile 抽象**：端点库 CRUD、每客户端多挂载、逐端点活体探活。
- **CLI 通用化**：`--all-profiles` 跨 profile 汇总、退出码约定、能力组模板库。
- **Tauri 图形层**：macOS 桌面 `.app` 壳，`run_audit` / `run_cli` 双命令桥接。
- **按需加载与启停（L5）**：每「客户端 × 技能」三态启停矩阵、漂移审计、回滚幂等。
- **打包**：pipx/pip 可安装发行、产品 README。

### 仍未发布：合入 `master` 前的累积记录

### 变更

- **分支合并（2026-09-21）**：`master` 原为 `develop` 的**祖先**（两条线并非分叉），
  `develop` 比它多 4 个提交（`8dc646e` 注册表 / `517ed72` 六维度整改 / `137006e` 文档
  同步 / `d7795f7` 测试污染修复）。以 `--no-ff` 将 `develop` 合入 `master`
  （`807b80d`），合并后两分支 **tree 哈希一致**（`4d0ac637`），全量测试 `515 passed`。
- **本机构建与安装**：合并后重新 `cargo tauri build`（`0.21.0` build 106，28.7s，
  `BUILD_EXIT=0`），安装到 `/Applications/skill-mcp-studio.app`，产物与安装后二进制
  sha256 一致（`e253763e…`）；旧版备份至
  `~/.skill-mcp-studio-backups/skill-mcp-studio-0.21.0-premerge.app`。步骤与权限、
  TCC 授权失效须知见 `src-tauri/BUILD.md` §3.2；**DSH 本体更新**（ad-hoc 签名、
  无 TeamIdentifier，cdhash 变更即失效）导致授权丢失的完整判据与根治手段见 §3.3。
- **安装数变化**：`8dc646e` 使「空壳 CLI 启动器」不再被计为安装证据，管理台
  `IDE / Agent` 计数由 **7 → 6**（预期行为修正，非回归）。

### 跨平台支持（Windows / Linux）

- **CLI 路径矩阵**：`core/mainstream_registry.py` 引入 `by_os` + `sys.platform` 分派
  （决策 A），为全部内置 IDE/Agent 补充 Windows（`%APPDATA%`/`%USERPROFILE%`/
  `%LOCALAPPDATA%`）与 Linux（XDG `~/.config`）路径，依据
  `docs/design/跨平台路径矩阵-Windows-Linux.md`；
- **路径展开**：`core/tool_registry.py` 新增 `expand_path()`，统一展开 `%VAR%` 与
  `~`，`detect_installation` 兼容注入的 `expanduser`（既有测试契约不变）；
- **python3 解析**：`core/ai_memory_checker.py` 移除硬编码 `/usr/local/bin/python3`，
  改为 `sys.executable` → `shutil.which("python3")` → `"python3"` 的跨平台解析；
- **模板目录**：`capability_templates._default_user_dir()` 平台感知（Windows 走
  `%APPDATA%\skill-mcp-studio`，POSIX 走 `~/.config/skill-mcp-studio`）；
- **Rust 壳**：`lib.rs::cli_candidates()` 三平台适配（Windows 补 `.exe` 与
  `%USERPROFILE%\.local\bin`、`%APPDATA%\Python\Scripts`；Linux 补 `/usr/bin`）；
- **CI 构建**：新增 `.github/workflows/build-windows.yml`（NSIS + MSI）与
  `build-linux.yml`（deb + rpm + AppImage），产物以 workflow artifact 形式产出，
  暂不发布 GitHub Releases（遵循「仅 codeup」门禁）。

### 工程化 / 开源准备

- **CI/CD（GitHub Actions）**：新增 `.github/workflows/build-macos.yml`，macOS
  universal 二进制（`universal-apple-darwin`，Tauri 自动 `lipo` 合并 `x86_64` +
  `arm64`），单一 `.app`/`.dmg` 原生覆盖 Intel 与 Apple Silicon；
- **签名与公证（可选）**：配置 Apple 证书 secrets 时自动导入证书并启用正式签名 +
  公证，未配置时回退 ad-hoc 签名（构建不中断）；
- **自动发布**：push `v*` tag 时用 `softprops/action-gh-release` 自动创建 GitHub
  Release（自动生成 release notes），上传 `.dmg` 与 `.app.zip`；
- **双远端与分支保护**：`origin` 接管 codeup + github 双 pushurl（`git push origin
  master` 一次推两处）；github `master` 设 PR-only 保护（需审批、禁 force push）；
- **开源仓库**：公开仓库 `github.com/oswaldhill/skill-mcp-studio`，清理历史敏感信息
  （真实端点域名/IP/密钥在 HEAD 中全部占位符化）。

### 文档

- 根目录产品/设计/决策/评审文档归档至 `docs/` 分层目录；
- 新增 `CONTRIBUTING.md` / `SECURITY.md` / `CHANGELOG.md` 与 `.github/` Issue/PR 模板；
- README 增加 badges、仓库结构树、文档索引与管理台 UI 截图；
- README「开发」章节补充 CI/发布说明与 Apple 签名 secrets 配置表。

[Unreleased]: https://github.com/oswaldhill/skill-mcp-studio/compare/v0.47.13...HEAD
[v0.47.13]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.13
[v0.47.12]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.12
[v0.47.11]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.11
[v0.47.10]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.10
[v0.47.9]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.9
[v0.47.8]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.8
[v0.47.7]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.7
[v0.47.6]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.6
[v0.47.5]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.5
[v0.47.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.4
[v0.47.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.3
[v0.47.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.2
[v0.47.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.1
[v0.47.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.47.0
[v0.46.9]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.9
[v0.46.8]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.8
[v0.46.7]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.7
[v0.46.6]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.6
[v0.46.5]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.5
[v0.46.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.4
[v0.46.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.3
[v0.46.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.2
[v0.46.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.1
[v0.46.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.46.0
[v0.45.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.45.3
[v0.45.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.45.2
[v0.45.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.45.1
[v0.45.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.45.0
[v0.44.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.44.4
[v0.44.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.44.3
[v0.44.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.44.2
[v0.44.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.44.1
[v0.44.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.44.0
[v0.43.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.43.3
[v0.43.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.43.2
[v0.43.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.43.1
[v0.43.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.43.0
[v0.42.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.42.0
[v0.41.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.41.0
[v0.40.9]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.9
[v0.40.8]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.8
[v0.40.7]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.7
[v0.40.6]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.6
[v0.40.5]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.5
[v0.40.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.4
[v0.40.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.3
[v0.40.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.2
[v0.40.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.1
[v0.40.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.40.0
[v0.39.8]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.8
[v0.39.7]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.7
[v0.39.6]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.6
[v0.39.5]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.5
[v0.39.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.4
[v0.39.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.3
[v0.39.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.2
[v0.39.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.1
[v0.39.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.39.0
[v0.38.9]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.9
[v0.38.8]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.8
[v0.38.7]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.7
[v0.38.6]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.6
[v0.38.5]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.5
[v0.38.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.4
[v0.38.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.3
[v0.38.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.2
[v0.38.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.1
[v0.38.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.38.0
[v0.37.9]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.9
[v0.37.8]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.8
[v0.37.7]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.7
[v0.37.6]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.6
[v0.37.5]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.5
[v0.37.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.4
[v0.37.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.3
[v0.37.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.2
[v0.37.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.1
[v0.37.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.37.0
[v0.36.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.36.0
[v0.35.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.35.0
[v0.34.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.34.0
[v0.33.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.33.0
[v0.32.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.32.0
[v0.31.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.31.4
[v0.31.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.31.3
[v0.31.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.31.2
[v0.31.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.31.1
[v0.30.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.30.0
[v0.29.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.29.2
[v0.29.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.29.1
[v0.29.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.29.0
[v0.28.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.28.0
[v0.27.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.27.1
[v0.27.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.27.0
[v0.26.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.26.1
[v0.26.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.26.0
[v0.25.5]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.25.5
[v0.25.4]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.25.4
[v0.25.3]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.25.3
[v0.25.2]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.25.2
[v0.25.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.25.1
[v0.24.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.24.1
[v0.24.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.24.0
[v0.23.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.23.0
[v0.22.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.22.0
[v0.21.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.21.1
[v0.21.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.21.0
[v0.20.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.20.1
[v0.20.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.20.0
[v0.19.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.19.0
[v0.18.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.18.0
[v0.16.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.16.1
