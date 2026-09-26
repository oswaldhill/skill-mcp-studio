# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 约定，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 注：项目早期历史未按版本逐次发布，以下按可识别的版本里程碑汇总。

## [Unreleased]

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

[Unreleased]: https://github.com/oswaldhill/skill-mcp-studio/compare/v0.23.0...HEAD
[v0.23.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.23.0
[v0.22.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.22.0
[v0.21.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.21.1
[v0.21.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.21.0
[v0.20.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.20.1
[v0.20.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.20.0
[v0.19.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.19.0
[v0.18.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.18.0
[v0.16.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.16.1
