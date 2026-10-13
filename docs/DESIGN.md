# 界面规范（Skill MCP Studio 管理台）

本文件是 `gui/dashboard.html` 的唯一设计依据。所有页面与弹窗都必须遵守；
新增界面时先在这里找现成组件，找不到再补，并把补的那条写回来。

---

## 0. 设计判断（Design Read）

**定位**：桌面端开发者工具管理台（dense product UI / admin panel），
面向同时使用多个 AI Agent、需要统一管技能与 MCP 的开发者。

**三档标尺**（本项目取值，非通用默认）：

| 标尺 | 取值 | 理由 |
|---|---|---|
| `DESIGN_VARIANCE` | 3 | 管理台要可预测。左右对齐、栅格稳定，不做非对称艺术排版。 |
| `MOTION_INTENSITY` | 3 | 工具界面。只保留 hover / active / 展开收起的状态反馈，不做入场编排。 |
| `VISUAL_DENSITY` | 6 | 数据密集但仍需呼吸感。信息分区块、留白分层，不排成电子表。 |

**与 taste-skill 的关系**：taste-skill 第 13 节把 dashboard / admin panel 列为
out of scope，并将此类界面指向 Fluent / Carbon / Polaris 等设计系统。本项目
不引入外部框架，沿用自身 token 体系；只采用 taste-skill 中与界面类型无关的
质量规则：颜色一致性锁、形状一致性锁、按钮与表单对比度、完整状态覆盖、
卡片克制、内容密度、禁用 em-dash。

---

## 1. Token 体系（唯一取值来源）

所有颜色、字号、圆角、阴影、缓动**必须**取自 `:root`，不得写字面值。

| 类别 | Token | 用途 |
|---|---|---|
| 表面 | `--bg` `--bg-elev` `--panel` `--panel-2` | 页面底 / 抬高面 / 卡片 / 次级卡片 |
| 描边 | `--line` `--line-strong` | 分隔线 / 控件描边 |
| 文字 | `--text` `--muted` `--faint` | 主文 / 次要 / 弱化元信息 |
| 强调 | `--accent` `--accent-strong` `--on-accent` `--accent-bg` `--accent-border` | 唯一强调色，全站只用这一个 |
| 语义 | `--ok` `--warn` `--err` + 各自 `-bg` / `-border` | 成功 / 注意 / 失败 |
| 字号 | `--fs-2xs` `--fs-xs` `--fs-sm` `--fs-base` `--fs-md` `--fs-lg` `--fs-xl` | 11 / 12 / 13 / 14 / 16 / 22 / 30 |
| 圆角 | `--r-control`(8) `--r-card`(12) `--r-pill`(999) `--r-hair`(3) | 控件 / 卡片 / 胶囊 / 徽标 |
| 阴影 | `--shadow-card` `--shadow-card-hover` `--shadow-modal` | 卡片 / 悬停 / 弹窗 |
| 缓动 | `--ease` | 所有 transition |
| 字体 | `--sans` `--display` `--mono` | 正文 / 弹窗标题（= sans） / 数字与代码 |
> `--display` 当前等于 `--sans`（同族），保留是为了将来标题可能换字重或字形时不改引用处。
| 遮罩 | `--backdrop` | 模态背板 |
| 间距(gap) | `--gap-0`(0) `--gap-1`(4) `--gap-2`(6) `--gap-3`(8) `--gap-4`(10) `--gap-6`(14) `--gap-5`(16) | flex/grid 间距 |
| 间距(sp) | `--sp-1`(4) `--sp-2`(6) `--sp-3`(8) `--sp-4`(10) `--sp-5`(12) `--sp-6`(14) `--sp-7`(16) `--sp-8`(20) `--sp-9`(24) | padding/margin 竖直分量 |
| 间距(sp) 扩展档 | `--sp-0a`(1) `--sp-0b`(2) `--sp-0c`(3) `--sp-1a`(5) `--sp-3a`(7) `--sp-3b`(9) `--sp-5a`(11) `--sp-5c`(13) `--sp-5b`(15) `--sp-7a`(18) `--sp-8a`(22) `--sp-9d`(26) `--sp-9a`(28) `--sp-9b`(32) `--sp-9e`(36) `--sp-9c`(40) `--sp-9f`(64) | 落在主档之间的取值；**已全部在用**（含 2026-10-10 为「间距字面值清零」新登记的 6 档），不得再写字面值 |
| 焦点环 | `--ring-ok` `--ring-warn` `--ring-err` | 语义态 focus 外环 |
| 强调投影 | `--shadow-accent` `--shadow-accent-hover` | 主按钮悬停光晕 |
| 语义投影 | `--shadow-err` `--shadow-err-hover` `--shadow-knob` `--shadow-sheet` | 危险态光晕 / 开关旋钮 / 侧拉面板 |
| 语义加强色 | `--err-strong` | 失败态悬停/实心 |
| 实体白 | `--on-solid` | 实心块上的白（独立 token，禁止裸写 `#fff`） |

> `--ok-bg` / `--warn-bg` / `--err-bg` 与各自的 `-border` 由上面「语义」一行的
> 「+ 各自 `-bg` / `-border`」统一涵盖，不再单列。

> 圆角四档都要用：`--r-hair` 专给 10-11px 的小徽标（如变更面板的维度标签），
> 它比 `--r-control` 更贴合小尺寸；不要用字面值 `4px` 凑合。
>
> ⚠️ **圆角只有四档，没有第五档**：popover 有它自己的 `--pop-r-*` 体系（见 2.8），
> 管理台页面不得为它另开圆角 token（曾有一个死 token `--r-popover`，已删）。

**颜色一致性锁**：强调色只有 `--accent` 一个。任何新界面不得引入第二强调色。
**形状一致性锁**：圆角只用上表四档（hair/control/card/pill）。控件 8px，卡片 12px，胶囊用 pill。
**主题锁**：浅色与深色两套 token 同步维护，不得只改一侧。
**字体锁**：正文用 `--sans`；数字、路径、包名、代码用 `--mono`。

---

## 1b. 可视化样例

本文档是**唯一设计依据**，但它只写规则、不给样子。可视化样例在 HTML 可读版里：

| 样例 | 内容 |
|---|---|
| 字号阶梯 | `--fs-2xs` ... `--fs-xl` 各档实际字形与行高 |
| 按钮全系 | `primary` / `btn-soft` / `ghost` / `danger` / `sm` 及各场景变体 |
| 控件 | 列表行、卡片、开关、分页、路径字段行、弹窗容器 |
| 尺寸与圆角 | 四档圆角（hair / control / card / pill）的实际观感 |
| 语义色 | `--ok` / `--warn` / `--err` 及各自 `-bg` / `-border`、焦点环 |

打开方式：`open docs/DESIGN.html`（深浅两套主题可切换）。
**改规范时先改本文档，再同步 HTML 的样例区** —— 两边的章节由门禁双向比对。

---

## 2. 组件规约

### 2.1 按钮

**基础按钮**（全局 `button` 元素样式已提供：面板底、描边、圆角 `--r-control`、悬停变色、按压回落）：

| 类 | 用途 | 规则 |
|---|---|---|
| `button.primary` | 一屏一个主操作 | `--accent` 底 + `--on-accent` 字 |
| `button.btn-soft` | 次级操作（最常用） | 面板底 + `--line-strong` 描边 |
| `button.ghost` | 三级/文字按钮 | 无底无边，悬停才显形 |
| `button.danger` / `.btn-soft.danger` | 破坏性操作 | `--err` 字与边，悬停实心红 + `--on-accent` 字 |
| `button.sm` | 紧凑场合（表格行内） | 与基础按钮叠加使用，如 `btn-soft sm` |

**场景化变体**（只在特定容器内使用，不跨场景复用）：

| 类 | 限定场景 |
|---|---|
| `btn-save` / `btn-cancel` | 表单弹窗底部的主/次操作 |
| `cfm-btn-danger` / `cfm-btn-cancel` | 确认框的两个出口 |
| `ad-clean-btn` / `ad-clean` | 整理建议卡的清理动作 |
| `adv-all-btn` / `adv-merge-btn` | 整理建议的批量合并动作 |

**不是按钮的控件**（不要按按钮规范要求它们）：
`seg-btn`、`view-btn`、`settings-tab`、`nav-item`、`pm-item`、`pal-item`。
这些是分段控件 / 视图切换 / 导航项 / 菜单项，各有自己的选中态表达。

**硬规则**：
- **同一操作区**只允许一个 `primary`。
- 破坏性操作必须用 `danger` 变体，不得用 `primary` 伪装。
- 按钮文字不得换行；对比度满足 WCAG AA。
- 新增按钮变体时必须回来登记到本表。

### 2.2 列表行（`.list-row`）
用于"多条同类条目 + 每行一个操作"的场景。**这是市场、更新检查、技能列表的统一形态。**

```
┌──────────────────────────────────────────────┐
│ 主标题（--text, --fs-base, mono 用于包名）         [操作] │
│ 元信息（--faint, --fs-xs）                                          │
└──────────────────────────────────────────────┘
```

- 行与行之间用 `--line` 分隔，**不用每行一个卡片**（卡片会撑高列表）。
- 主标题可截断（`text-overflow: ellipsis`），完整值放 `title` 属性。
- 操作按钮右对齐，纵向居中；同一列表内按钮文案一致。

### 2.3 卡片（`.card` 及场景卡片）

只在需要表达"独立实体"时使用（技能卡、MCP 服务卡）。
**不要**用卡片堆一长串同类条目，那是列表行的职责。

**场景卡片是各自独立的类**，不是 `.card` 的修饰变体；新增卡片先看下表能否复用：

| 卡片类 | 场景 |
|---|---|
| `.skill-card` | 技能卡（主页技能网格） |
| `.agent-card` | Agent / 客户端卡 |
| `.settings-card` | 设置分组卡 |
| `.about-card` | 关于页 |
| `.adv-card` | 整理建议卡 |
| `.card` | 通用容器（表格/区块外壳，`--r-card` + `--shadow-card`） |

所有卡片共用同一套取值：底色 `--panel`、描边 `--line`、圆角 `--r-card`、内边距 `--sp-7`。

### 2.3b 卡片标签列对齐（`.ac-path-row` / `.ac-meta-row`）

Agent 卡片里有两组「标签 + 值」行：**路径区**（APP / CLI / CONFIG）与
**能力摘要区**（Skills / MCP / Hook）。两组必须**逐项同构**，否则值区起点会差十几像素，
一眼看出错位（2026-10-12 用户截图反馈「最好保持对齐」）。

| 维度 | 规定值（两组相同） |
|---|---|
| 行布局 | `grid`，`grid-template-columns: 58px minmax(0, 1fr)`，`gap: var(--gap-4)`，`align-items: start` |
| 标签字体 | `var(--mono)` / `var(--fs-2xs)` / 字重 600 / `text-transform: uppercase` |
| 标签颜色 | `var(--faint)`；**不加前缀圆点**（装饰性状态点默认零，见下） |
| 分隔线 | **两组都不加竖线**（单边 `border-right` 是错位感来源之一） |

> 不变量由 `tests/test_design_spec_contract.py` 的 `CardLabelColumnAlignmentTest`
> 逐属性比对（列宽 / gap / 对齐 / 字体族 / 字号 / 字重 / 大小写 / 颜色）。
> 只改一侧必然失败 —— 要改就两边一起改，并同步 §2.9 的那行硬数字。

**值区排版（2026-10-12 精修）**：

| 规则 | 取值 | 为什么 |
|---|---|---|
| 值区容器 | `display: flex` + `flex-wrap: nowrap` | 长路径不再把状态标签挤到第二行 |
| 首个值 | `flex: 1 1 auto; min-width: 0` | 自适应并允许省略号 |
| 其余（状态标签） | `flex: 0 0 auto` | 恒贴右，所有行右边界成一条竖线 |
| 路径列表 | `display: grid` 单列 | 路径**等宽**，消除右边界锯齿 |
| 路径底色 | 默认 `transparent`，`:hover` 才浮出胶囊 | 一张卡片近十个灰块会读成表单输入框；高密度界面里信息文本应安静 |
| 状态色 | 仅「全部配置」用 `.tag.ok`；部分配置用中性 | 绿色表示「已就绪」，`8/21` 不是就绪 |

> 为什么不是「两栏 grid」：Hook 行有「路径 + 2 个标签」共 **3** 个子元素，两栏 grid 会把
> 第 3 个挤到第二行第一列并撑满宽度（渲染实测）。`nowrap` + 首元素自适应对 1~3 个子元素
> 都稳定成立。作用域限定 `.agent-card:not(.home-card)`：主页卡片是另一套渲染，不跟着变。

**分隔线跨卡片对齐（2026-10-12 用户三次反馈后定案：两条线都要，且必须对齐）**：

卡片内有**两条**整宽分隔线：① 能力区上沿；② 底栏上沿。两条都必须跨卡片对齐。

对齐机制是**锚定底部**，而不是"吸收内容差异"：

| 规则 | 取值 | 作用 |
|---|---|---|
| `.agent-cards` | `align-items: stretch` | 同组卡片等高（前提） |
| `.agent-card:not(.home-card) .ac-meta` | `margin-top: auto` | meta+foot 整块贴底 ⇒ 线① y = 卡片底 − (meta 高 + foot 高) |
| `.agent-card:not(.home-card) .ac-foot` | `margin-top: 0`、`flex: 0 0 auto` | **不争** auto 外边距、高度恒定 ⇒ 线② y = 卡片底 − foot 高 |
| `.agent-card:not(.home-card) .ac-paths` | `flex: 0 0 auto` | 路径区不伸缩（拉伸会在内容超出时裁切末行） |

线① 的位置是**从卡片底部往上算**的常量（meta 恒为 3 行且值区 `nowrap`、foot 内容固定），
因此与上方路径条数无关 ⇒ 必然对齐。

> **走过的弯路（不要重犯）**：曾让路径区 `flex: 1 1 auto` 去"吸收"路径条数差异。
> 结果 ① 内容超出时路径区收缩，**末行被裁进分隔线里**（渲染实测可见）；② 线① 位置
> 依旧随条数漂移。又曾干脆**去掉线①**只留底栏线 —— 用户明确「分隔线很重要」，不好看。
> 靠拉伸凑对齐是掩盖；**锚定底部**才是解。
>
> 代价：路径少的卡片会在**线① 上方**留一段空白（卡片等高 + 底部锚定的必然结果）。
> 实测（headless 渲染 + 逐行像素扫描）：3 条与 4 条路径的两张卡片，两条线 y 完全相同
> `[205, 314]`。不变量由 `CardLabelColumnAlignmentTest.test_dividers_align_across_cards`
> 逐声明比对。

**值胶囊与「未收录」空态必须度量一致（2026-10-12 实测抓到的 3px 错位根因）**：

`.ac-path-none`（如「未收录 Hook 配置」）必须与 `.ac-path-val` 在**决定行高的每个属性**上
完全相同：`font-size`、`line-height`、`padding`、`border`、`font-family`。

> 为什么这条至关重要：分隔线用 `margin-top: auto` **锚定卡片底部**，前提是 **meta 带高度恒定**。
> 实测两处不一致：① 空态少了 1px 字号；② 空态缺那条 `border: 1px solid transparent`
> （值胶囊为 hover 不抖动而留）。合计 **3px** ⇒ "HOOK 未收录"的卡片 meta 带矮 3px
> ⇒ **分隔线整体上移 3px**，跨卡片错位。用户三次说"没对齐"，肉眼几乎看不出是 3px。
>
> 实测（真实数据、2/3/4/5/6 条路径共 8 张卡片）：修好后 meta 高度恒为 **109**、
> 两条分隔线 Δ=0（`metaTop 194/194`、`600/600`、`949/949`、`1271/1271`）。
> 不变量由 `CardLabelColumnAlignmentTest.test_value_and_empty_have_identical_metrics` 守住。

**淡化变体 `.ac-path-val.is-dim` 只改颜色，不改形状**：

`color: var(--faint)` + `background: transparent` + `border-color: transparent`。

> 根因（2026-10-12 用户提问「为什么 Skill 的样式和 MCP、Hook 不一样」）：`.is-dim` 曾设
> `border-color: var(--line)`，而默认胶囊是**透明无边框**。于是同一张卡片里 Skills 那格
> 显示成方框、MCP/Hook 是纯文本 —— 同一类元素出现两种形态。
> 现规定：**淡化只表达"这是注册表默认值、非本机状态"，绝不改变胶囊形状**；并且
> **三行（Skills / MCP / Hook）在未安装时统一淡化**，不允许只淡化其中一行。

**装饰性状态点默认零**：标签行**不加**前缀圆点。此前每行都有 6px 圆点，却不传达状态
（「空」已由值区的「未收录」文案说明），属纯装饰。`.ac-path-row.is-empty` 的状态语义
改为标签 `opacity: .72`（保持该状态类有意义，而不是留下死类）。

**未安装客户端：路径胶囊用淡化变体** `.ac-path-val.is-dim`
（`color: var(--faint)` + `background: transparent`）。

> 为什么（2026-10-12 用户选方案 A）：未安装时卡片上的路径来自**内置注册表的默认位置**，
> 不代表本机状态；它与同行右侧的「不适用」标签并列却不加区分，读起来自相矛盾
> （Cursor 卡片实测：`~/.cursor/skills` 与「不适用」同样醒目）。
> 淡化后：**状态语义交给「不适用」承担**，路径退为背景信息 —— 但仍保留胶囊形态，
> 因为路径本身仍可点击复制。**已安装时不得淡化**（那是本机真实目录）。

### 2.3c IDE / Agent 列表视图的列与图例（`.agent-list-table`）

列表视图（`.agent-list-table`）的列序固定为：

```
名称 | 类型 | 安装 | APP | CLI | CONFIG | 技能目录 | MCP | Hook | 操作
```

**每个状态列都必须配一条同名图例**（`.skill-legend`），且图例的四态与列内取值一一对应：

| 列 | 四态 | 图例 |
|---|---|---|
| MCP | `ok` 全部已设置 / `warn` 部分 / `err` 未设置 / `na` 不支持或无端点 | `.mcp-badge-legend` |
| Hook | `ok` 全部已配置 / 中性 部分已配置 / `warn` 未配置 / `na` 未收录配置或仅审计 | 复用 `.skill-legend` |

**Hook 列判据：只看有没有配置，不看配置内容（2026-10-13 用户要求）**。某事件下只要存在任意 hook 条目即算「已配置」——命令写的是什么、是不是 ai-memory、是不是第三方工具，一概不参与判定；「缺关键事件」同理 = 该客户端支持但完全没有配置的事件。为什么改：此前只统计「命中 ai-memory 命令签名」的事件，于是同一事件被别的工具占着时（本机实测确实存在）报「未配置」，而客户端其实配了这个 hook；更根本的是该判据与「写入什么内容」耦合，而写入内容尚未定案，判据不该依赖一个未定的东西。

**Hook 列的口径（务必与 Hook 业务页一致）**：

| 情形 | 显示 | 说明 |
|---|---|---|
| 已登记且全部配置 | `N/M`（`.tag.ok`） | N=已配置事件数，M=该客户端支持的事件数 |
| 已登记且部分配置 | `N/M`（**中性** `.tag`） | 绿色表示「已就绪」，部分配置不是就绪 |
| 已登记但未配置 | `未配置`（`.tag.warn`） | |
| 已登记但插件型（`fix_supported=false`） | `仅审计` | 不支持模板注入 |
| **未登记 Hook 配置路径** | **`未收录`** | **不是「不支持」** |

> ⚠️ **「未收录」与「不支持」必须分开**：未登记只表示"我们还没收录它的 Hook 配置路径"，
> 不等于"该客户端没有 Hook 能力"。实测 22 个已安装客户端里只有 6 个登记了 `hooks.clients`，
> 若一律显示「不支持」，这一列对多数行都是过度断言。这与 Hook 业务页 `_hooksEntries`
> 只列"有 `hooks_config_path`"的客户端是同一口径。

**分层作用域徽标** `.al-scope`：紧跟在状态标签之后，形如 `4 档`，`title` 给出
"分层作用域 N 档（用户级 / 项目级 / 本地级…）"。它与 `.al-metric` 同族（同字号/同圆角/同内边）
但**更弱**：`--faint` 字色 + 虚线边框 + 透明底、**不做 accent 高亮、不加 hover** ——
它是元信息（该客户端的 Hook 配置分几档），不是可点的计数徽标。

### 2.4 元信息与数字
- 数字、包名、路径、版本号一律 `--mono` + `--faint` 或 `--muted`。
- 数量单位用中文（"3.6 万次安装"），不直接透出上游英文原文。
- 不得展示假精确数字；来自上游的原始值如实标注。

**表头内联图标（`.th-ico`）**：表格 `<th>` 里跟在文字前的 SVG 图标容器。
内联 flex、12px 见方、与文字基线对齐、右侧 `--gap-1`(4px) 间距。
用于 `.merge-table`（移除工具 / 状态变化 / 统计变化）。
**不得用 emoji 代替**（见 3b「图标用 SVG」）—— 这是 2026-10-11 从
`🗑 / 🔄 / 📊` 收敛过来时新增的类。

### 2.5 状态覆盖（每个数据区都必须有）
| 状态 | 要求 |
|---|---|
| 加载中 | 有明确文案说明在做什么、大概多久 |
| 空 | 说明"为什么空"以及"怎么让它不空"，不留白屏 |
| 错误 | 就地显示原因，不弹窗、不吞掉（**仅限数据区自身状态**，见下方区分） |

**「数据区错误」与「操作结果」必须分开**（2026-10-12 用户截图反馈后明确）：

| 类别 | 例子 | 展示方式 |
|---|---|---|
| 数据区自身状态 | 某个面板/表格加载失败、清单为空 | **就地**在数据区内说明原因与出路（上表） |
| **一次操作的结果** | 保存设置、修复 Skills/MCP、写入 Hook | **弹框**：`runTaskModal` 的 `.task-card`（`.task-result` ok/err + `.task-fold` 折叠详情） |

> 为什么：把 CLI 的整段 stdout 铺成页面级 `.banner` 会变成一大片文本（实测保存设置
> 失败时贴了 1600 字符的技能扫描报告，用户截图反馈）。操作结果本就该是一次性的、
> 需要用户确认的**弹框**；`.banner` 只留给「非阻塞的页面级告知」（如自动发现新客户端）。
>
> 另：错误详情一律先过 `cliFailLines`（挑失败行）或 `cliErrDetail`（去 ANSI、截断），
> 不要把原始 stdout 直接抛给用户。

**行内状态点（`.dot` 三态）**：`.dot.ok`（`--ok` + `--ring-ok` 环）/
`.dot.warn`（`--warn` + `--ring-warn`）/ `.dot.err`（`--err` + `--ring-err`）/
`.dot.faint`（透明底 + `--line-strong` 内描边）。9px 圆点，`--r-pill`。
用途：表格或列表里一行一个语义状态（如 Hook 接入情况）。
**颜色只是辅助**：同一行必须有文字列说明状态（不靠颜色单独表意），
点上加 `aria-hidden="true"` 让读屏跳过装饰。
图标一律 SVG（见 3b），**不用 emoji 当状态图标**。
> ⚠️ 这四种是**既有写法**，不要另造 `.dot-ok` / `.dot-idle` 之类的平行类
> （2026-10-11 实测发生过：替换 emoji 时新增了弱化版重复实现，造成两套并存）。
> 新增状态点前先在上表里找现成的。

### 2.5b 弹窗容器（`.modal` / `.cfm-card` / `.sheet`）

| 类 | 用途 | 结构要点 |
|---|---|---|
| `.modal` | 表单弹窗（添加端点、编辑客户端） | 居中浮层 + `.modal-backdrop` 遮罩；标题用 `--display` + `--fs-md`；宽度 `var(--modal-w, min(560px, 92vw))` |
| `.cfm-card` | 确认弹窗（删除前二次确认） | 比 modal 更窄：覆写 `--modal-w: min(400px, 94vw)`；两个出口按钮用 `cfm-btn-danger` / `cfm-btn-cancel` |
| `.sheet` | 侧拉面板（洞察、市场详情） | 从右侧滑入；宽 `min(560px, 94vw)`；`--shadow-modal`；内部有独立 `.sheet-head` 工具条 |

- **z-index 档位**（实际取值，禁止随手指派）：遮罩 `50`（`.modal-backdrop` / `.sheet-backdrop`）、
  侧拉 `.sheet` `51`、命令面板 `.palette` `60`、模态 `<dialog>` 层 `dialog.modal-layer`、
  忙碌层 `dialog.busy-backdrop` `70`。
- 原生 `<dialog>`（`.insight-backdrop` / `.modal-layer` / `.busy-backdrop`）的背板走 `::backdrop`。
  代码里**没有**名为 `.backdrop` 的类；遮罩是 `.modal-backdrop` / `.sheet-backdrop`
  两个独立元素，加上原生 `<dialog>` 的 `::backdrop`。（`--backdrop` 是**颜色 token**，
  不是类名。）
- 弹窗内表单字段间距用 `--gap-3`(8px)。
- `.sheet` 不影响主区域布局（`position: fixed` 侧拉）。

### 2.5c 开关（`.switch`）

用于布尔设置项（如自动发现开关）。

- 轨道：宽 34px 高 20px，`--r-pill`，关闭态 `--line-strong` 底
- 旋钮：16px 圆点，`--on-solid` 底，`transition: transform`
- 开启态轨道变 `--accent-strong`，旋钮右移

### 2.5d 分页（`.pagination`）

表格底部的分页控件。

- 按钮尺寸：`padding: 4px 9px`，`--fs-xs`（比标准 `.sm` 更紧凑）
- 当前页不可点，用 `--accent-bg` 高亮
- 与表格底边对齐，不悬浮

### 2.5e 路径字段行（`.path-field-row`）

编辑客户端时的多路径输入控件。

- 每行一个 `<input>` + 一个 `×` 删除按钮
- 删除按钮：`padding: 4px 8px`，`--fs-2xs`，`ghost` 风格
- 底部一个「+ 添加路径」按钮

### 2.5f 洞察弹窗（`.insight-dialog`）

技能使用统计的弹窗容器。

- 最大宽 `min(1040px, 100%)`，内部两级滚动（工具条钉顶 + 结果区滚动）
- 不复用 `.modal` 的居中浮层样式，是独立的结构

### 2.6 工具条（`.mt-toolbar` / `.agent-toolbar` / `.market-toolbar` / `.insight-toolbar`）

搜索框 + 操作按钮同排。各区域各有一个工具条类（**不存在统一的 `.toolbar`**，按所在区域选对应类）：

| 类 | 区域 |
|---|---|
| `.mt-toolbar` | 技能市场（含 `.mt-search` / `.mt-sum` / `.mt-spacer`） |
| `.agent-toolbar` | Agent / 客户端面板 |
| `.market-toolbar` | 市场结果区 |
| `.insight-toolbar` | 洞察弹窗（钉顶工具条） |

**硬规则**（2026-10-11 统一）：间距一律 `--gap-3`(8px)；搜索框占满剩余宽度（`flex: 1`）；
按钮固定宽度不换行；输入框必须有 `placeholder` 与 `aria-label`。
新增工具条必须复用上表某一类，不要另起一个只差间距的类。

### 2.7 变更卡片（`.chg-card`）
用于「变更详情」面板：每条变更一行决策（修复 / 保持）。

```
┌────────────────────────────────────────────────┐
│▌[维度] 名称                                       [修复][保持]│
│   详情（旧值 -> 新值）                                          │
└────────────────────────────────────────────────┘
```

- **左侧 3px 状态条**表达变更类型：`added` 绿 / `removed` 红 / 其余橙。
   颜色是**辅助**信息，名称与详情文字必须独立可读（色盲可用）。
- 维度标签用 `--r-hair` 圆角 + `--faint` 字，**不要**做成彩色胶囊
   （那会与 `--accent` 抢注意力）。
- 动作按钮最小高度 32px（触达目标），主操作「修复」用 `.chg-btn.primary`。
- 卡片悬停只改边框与阴影，**不用 scale**，避免列表位移。
- 统计行用 `.chg-pill`：显示**当前数量**；有变更时才追加 `+N` 徽标并转为
   `hot`（`--warn-bg`）。没有变更时也必须显示数量，不能是一排 0。

### 2.8 托盘弹框（`gui/popover.html`）
独立的 macOS 风格浮层，**不复用管理台的 token**，但**有自己的 token 体系**（`--pop-*` 前缀）。
此前所有取值裸写散落在样式里（14px/6px/8px 圆角、13/12/10/22px 字号、
`#1d1d1f`/`#34c759`/`#ff9500` 等颜色），现已收敛为 `--pop-r-*` / `--pop-fs-*` /
`--pop-text` / `--pop-accent` / `--pop-ok/warn/err` 等自有 token，浅深两套同步。
面板叠在系统菜单栏上的
另一套视觉：毛玻璃、无边框圆角窗）。

- 面板：`rgba(248,248,250,.88)` + `backdrop-filter: blur(30px)`，
   圆角 14px，窗口开启 `transparent` 让圆角外真正透明。
- 状态点三态：绿（已同步）/ 橙（有变更）/ **灰 + 呼吸动画（显示的是缓存，
   正在刷新）**。缓存态必须给出提示，不能让用户把旧数据当成实时结果。
- 窗口高度由内容决定（`fitWindow` 量完面板高度再 `setSize`），
   最小 200px；**首屏先用 localStorage 缓存渲染**，再后台刷新。
- 定位由 Rust 侧负责：水平居中对齐托盘图标、垂直贴菜单栏下方；
   没有图标坐标时（菜单触发）退回右上角。

### 2.9 组件硬数字（门禁校验，改代码必须同步改这里）

上表各节的尺寸/层级数字**由测试逐条比对代码**（`tests/test_design_spec_contract.py`）。
新增或调整这类「不可协商的数字」时，在此登记一行；只改代码不改这里会让门禁失败。

| 选择器 | 属性 | 规定值 |
|---|---|---|
| `.modal` | `width` | `var(--modal-w, min(560px, 92vw))` |
| `.cfm-card` | `--modal-w` | `min(400px, 94vw)` |
| `.sheet` | `width` | `min(560px, 94vw)` |
| `.modal-backdrop` | `z-index` | `50` |
| `.sheet-backdrop` | `z-index` | `50` |
| `.sheet` | `z-index` | `51` |
| `.palette` | `z-index` | `60` |
| `dialog.busy-backdrop` | `z-index` | `70` |
| `.switch` | `width` | `34px` |
| `.switch` | `height` | `20px` |
| `.switch .sw-knob` | `width` | `16px` |
| `.switch[aria-checked="true"] .sw-track` | `background` | `var(--accent-strong)` |
| `main` | `padding` | `var(--sp-9) var(--sp-9a) var(--sp-9f)` |
| `.card` | `padding` | `var(--sp-7)` |
| `.list-row` | `padding` | `var(--sp-4) var(--sp-6)` |
| `.pagination button` | `padding` | `var(--sp-1) var(--sp-3b)` |
| `.path-field-row button` | `padding` | `var(--sp-1) var(--sp-3)` |
| `.chg-btn` | `min-height` | `32px` |
| `.insight-dialog` | `width` | `min(1040px, 100%)` |
| `.ad-modal` | `width` | `min(880px, 94vw)` |
| `.agent-card .ac-path-row` / `.agent-card .ac-meta-row` | `grid-template-columns` | `58px minmax(0, 1fr)` |

**触达目标（弹层内动作按钮）**：`.cfm-card .actions button`、`.modal-form .form-actions button`、
`.sheet-actions .btn-soft` 与 `.chg-btn` 必须显式声明 `min-height: 32px`
（分页按钮按 2.5d 刻意更紧凑，不在此列）。

### 2.10 设置页（`.settings-tab` / `.settings-card`）

设置页用左侧分段 tab（`.settings-tab`）+ 右侧卡片分组（`.settings-card`）。
**五个 tab 与各自的卡片归属**（新增设置项必须落到下表的某一 tab，不要新开 tab）：

| tab | 卡片 |
|---|---|
| 通用 `appearance` | 外观（主题 / 缩放）、**后台巡检（定时检查）**、Skills 统一目录 |
| Skill `general` | 技能使用统计（自动统计间隔） |
| IDE / Agent `agents` | IDE / Agent 默认路径；**卡片/列表上的能力摘要**（Skills / MCP / Hook 三行，无需点开详情）；客户端详情内的「Hook 配置」 |
| **Hook `hooks`** | 要写入的 Hook 事件（勾选，按分类分组） |
| MCP `mcp` | MCP 端点库 |

**后台巡检（定时检查）**：开关 + 间隔（5 / 15 / 30 / 60 / 120 分钟）。
取值**不在 localStorage**，而是写进 `config.yaml` 的 `settings` 段
（`patrol_enabled` / `patrol_interval_minutes`）—— 因为 Rust 托盘的「后台巡检」
勾选项读同一份值，两处必须同源，否则托盘显示"已开"而实际没跑。
读写一律经 CLI `--get-setting` / `--set-setting`（后者带备份 → 原子写 → 校验 → 回滚），
GUI 不直接改配置文件。间隔由 CLI 钳到 ≥5 分钟，界面需回读落盘值而不是假定已生效。

**Hook tab（`hooks`）**：**管理「要写入哪些生命周期事件」**，不是展示各 IDE 的接入状态。

> 为什么：Skill / MCP 两个 tab 管的都是**配置本身**（统一目录、端点库），Hook 也应当
> 一致 —— 列出可选项、由用户决定要哪些。各客户端的接入状态与写入/移除是 **Hook 业务页**
> 的职责（那里显示审计结果）。

一张卡：

1. **要写入的 Hook 事件**：列出 `config.yaml` 的 `hooks.events` 全部**规范事件**
   （勾选框 + 事件名 + 说明 + 「写往」几个客户端），保存写入 `settings.hook_events`。
   未勾选任何事件 = 不写入（**停用**，不是"配置缺失"）。
   **默认全选**（`config.yaml` 的 `settings.hook_events` 出厂即列出全部规范事件）；
   卡片头部提供 **「全选」/「清空」** 两个 `.ghost.sm` 按钮 —— 二者只改**本地勾选态**，
   仍需点「保存」才落盘（不在用户没点保存时静默改配置）。计数用 `#hook-selected-count`
   就地更新，不整页重渲染。
   词表已扩到 47 项（各客户端官方事件集的并集），故按 `group` **分组渲染**，
   分组表头用 `.hook-group-row`（`--panel-2` 底色 + `--faint` 字 + `--fs-2xs`）；
   不分组会是一张 47 行的难读长表。

**「客户端事件命名规范」表已移入「IDE / Agent → 详情」**（2026-10-12 按用户要求）。

> 为什么：客户端清单、hook 配置文件路径、命名规范、分层作用域本就是「这个客户端」
> 的属性，与 IDE/Agent 页的 APP/CLI/CONFIG 路径同类。两处各维护一份必然漂移 ——
> 实测 Hook tab 只显示单条 `config_path`，而 IDE/Agent 已有多档作用域（user/project/
> local），口径本就不一致。**不要在 Hook tab 重新加回该表**（回归护栏见
> [`tests/test_design_spec_contract.py`](../tests/test_design_spec_contract.py) 的
> Hook 设置页断言）。

**IDE / Agent 详情新增「Hook 配置」区块**（`.ad-section`，与安装路径 / Skills / MCP 并列）：

```
┌─ Hook 配置 ─────────────────────────────────┐
│ 配置文件   ~/.claude/settings.json            │
│ 分层作用域 [用户级]   ~/.claude/settings.json │  ← 每档一行：标签左 + 路径右
│            [项目级]   <项目根>/.claude/…      │     路径超长省略（同 MCP 条目行）
│ 事件命名   pascal_case                        │
│ 支持事件   33 个，其中已配置 3 个              │
│ 事件清单   [SessionStart][Stop]…              │  ← 已配置用 .tag.ok，其余 .ad-pill
│ 缺关键事件 PreCompact                         │  ← 仅非空时渲染
└──────────────────────────────────────────────┘
```

- 作用域行复用 `.ad-entries` / `.ad-entry` / `.ad-e-key`，路径用
  `.ad-e-loc-full`（**完整显示**：`white-space: normal` + `word-break: break-all`，
  不做省略号截断）—— 详情页的要求是完整可读，路径本身就是信息。
  与之相对，MCP 条目的长 URL 仍用 `.ad-e-loc` 的省略号 + `title`（规范 §2.2 的
  截断做法），因为那里一行可能有很多条、且 URL 不是判决依据。
- 事件清单复用 `.ad-pills` + `.ad-pill`；**已配置**的换成 `.tag.ok`。
  颜色只是辅助，事件名本身可读（§3b：不得只靠颜色传达信息）。
- 数据来自 `management_snapshot._agent_entry` 透传的 `hooks_scopes` /
  `hooks_supported_events` / `hooks_event_format`（`hooks_inventory.inventory_for_tool` 产出）。
- 写入动作复用详情页脚「写入 Hook」按钮（走 `fixHooksFor(name)` → CLI `--fix-hooks`）。

**写入链路（四层，注意别混淆）**：

| 层 | 位置 | 作用 |
|---|---|---|
| 规范事件词表 | `hooks.events` | 可勾选**全集**（47 项，含 `group` 分类），GUI 靠它列出 |
| **要写入的事件** | `settings.hook_events` | **唯一决定写入什么**（规范事件名） |
| 客户端能力全集 | `hooks.clients[].events` | 该客户端**支持**的全部事件（用它自己的命名） |
| 命名 / 条目形态 | `event_format` / `entry_style` | 规范名 → 该客户端名；条目结构（嵌套 / 扁平） |

**硬规则**：
- 「写哪些事件」只看 `settings.hook_events`，**不再读 `template`**。
  `template` 仅：① 键不存在时作为向后兼容的回落；② 提供同名事件的**命令文案**。
- **能力校验（2026-10-12 变更）**：写入前按该客户端 `events` 过滤，**只写它认的事件**。
  此前是「勾了就一定写得上」（用兜底命令硬写），会把 Cursor 独有的 `BeforeTabFileRead`
  写进根本不认识它的 Claude Code。现在跳过并在结果里回报 `skipped` —— 这**不是**
  「静默漏写」：GUI 只在客户端详情里列出它支持的事件，入口上就选不出不支持的项。
- `settings.hook_events` **未配置（键不存在）** 与 **配置为空列表** 语义不同：
  前者回落 `template`，后者是用户明确的停用选择，不得回落。
- **条目形态按客户端声明**（`entry_style`），两套**不可混用**（本机实测）：
  Cursor 是扁平 `{type, command, matcher}`；Claude Code / TRAE / Codex / WorkBuddy
  是嵌套 `{matcher, hooks: [{type, command}]}`。
- 「缺关键事件」审计由**写入意图**推导（`settings.hook_events` ∩ 能力，或回落
  `template` 键），**不是**由能力全集推导 —— 否则 Claude Code 会把 29 个
  「支持但本次没打算写」的事件全报成缺失（假警报）。
- 只增不减：客户端已有的非 ai-memory hook 必须原样保留。

> 设置项的取值来源必须与「谁是唯一事实来源」一致：偏好类（主题/缩放/统计间隔）用
> localStorage，跨进程共享类（巡检开关）用 config.yaml 并经 CLI。

---

## 3. 排版与间距

- 区块间距用 `--gap-5`(16px) / `--sp-8`(20px) / `--sp-9`(24px) 三档，同一页面保持同一节奏。
- 面板内边距：`main` 用 `var(--sp-9) var(--sp-9a) var(--sp-9f)`（上 24 / 左右 28 / 下 64）；
卡片内边距 `--sp-7`(16px)；列表行内边距 `var(--sp-4) var(--sp-6)`(10px 14px)。
- 一行元信息里的分隔符最多一个，优先用换行或留白，不用符号堆砌。
- 中文正文不手动加空格；中英文混排不加空格，靠字体回退处理。
- **禁用 em-dash（`—`）**：正文、标题、标签、按钮文案一律用普通连字符或改写句子。

---

## 3b. 可访问性（硬要求，非可选）

这几条由测试或明确的交互约束兜底，新界面必须满足。

| 要求 | 做法 | 为什么 |
|---|---|---|
| 键盘可达 | 交互元素保留 `:focus-visible` 外环（`2px solid --accent`，偏移 2px） | 无鼠标用户需要知道焦点在哪 |
| 抑制 outline 必须给替代 | 若写了 `outline: none`，同一条规则里必须补 `box-shadow` 焦点态 | 否则键盘用户完全看不到焦点 |
| 尊重减少动效 | 所有 `animation` / `transition` 在 `@media (prefers-reduced-motion: reduce)` 里关闭 | 前庭敏感用户会因动效不适 |
| 触达目标 | 可点元素最小 32px 高（弹框内）/ 44px（移动端） | 误触率 |
| 不靠颜色单独表意 | 状态同时有文字或形状（如变更卡的状态条 + 文字详情） | 色盲可用 |
| 图标用 SVG | 不用 emoji 当 UI 图标；统一 `viewBox="0 0 24 24"` | 跨平台渲染一致 |
| 可点元素有指针 | `cursor: pointer` | 可发现性 |

**已知的例外**（属于 **§2.8 托盘弹框**，不在管理台页面）：`popover.html` 的
`.status-dot` 呼吸动画是"显示的是缓存、正在刷新"的唯一视觉提示；在
`prefers-reduced-motion` 下关闭动画，但 `title` 文案仍在，语义不丢失。
> 管理台页面不使用 `.status-dot`（它 0 处出现）；行内状态请用 §2.5 的 `.dot` 三态。

---

## 4. 落地页配方（不适用于本项目）

以下 taste-skill 条目**本项目不采用**，仅记录以便区分：

- Hero / 首屏构图、bento 网格、marquee、滚动编排、大字号展示标题；
- 图片资产策略（生成图 / Picsum 占位）、logo 墙；
- 落地页文案密度与"每屏一个卖点"。

本项目是常驻工具界面，不做首屏叙事。

---

## 5. 检查清单（改完界面逐条过）

### 取值与一致性
- [ ] 颜色/字号/圆角/阴影全部取自 token，无字面值
- [ ] 强调色只有一个
- [ ] 圆角只用四档且用法一致（小徽标用 `--r-hair`）
- [ ] 间距走 `--gap-*` / `--sp-*`（含扩展档），**零字面值**
      （`<style>` 块与内联 `style=` 都算，由 `NoLiteralSpacingTest` 强制）
- [ ] 按钮对比度达标，**同一操作区**一个 primary
- [ ] 数字/包名用 mono，单位已中文化
- [ ] 若动了 2.9 的硬数字，规范表与代码已同步

### 结构与状态
- [ ] 同类条目用列表行，不是一长串卡片
- [ ] 加载 / 空 / 错误三态齐备
- [ ] **空态也要有信息量**：不要出现「一排全 0」而无说明的界面
- [ ] 无重复渲染（同一信息不在同屏出现两次）
- [ ] 无 em-dash（正文、标题、标签、按钮文案）
- [ ] 图标用 SVG（`viewBox="0 0 24 24"`），**不用 emoji 当 UI 图标**

### 交互与可达性
- [ ] 可点元素有 `cursor: pointer` 与悬停反馈
- [ ] 键盘焦点可见（`:focus-visible`），抑制 outline 处已补替代
- [ ] 动效在 `prefers-reduced-motion` 下关闭
- [ ] 状态不只靠颜色表达
- [ ] 弹层能自然关闭（失焦收起 / Esc）
- [ ] 弹层内动作按钮 `min-height: 32px`（触达目标）

### 主题与验证
- [ ] 深浅两套主题都过一遍
- [ ] 跑 `python3 -m unittest tests.test_design_spec tests.test_dashboard_design_tokens tests.test_design_spec_contract`
- [ ] 若新增组件或变体，已回写本文件对应章节
      （由 `ComponentRegistrationTest` 强制：新增语义类必须先登记，未登记即失败）

---

## 附：双轨强制机制

规范要真正拦住后续功能脱离，靠的是**文档 + 测试双轨**，而不是自觉。

| 层 | 载体 | 有效力 |
|---|---|---|
| 规则 | `~/.dsh/AGENTS.md` 的三条强制规则（语言 / UI 技能 / UI 规范双轨） | 每次会话强制加载 |
| 规范 | 本文件（`docs/DESIGN.md`） | 需主动读 |
| 门禁 | `tests/test_design_spec.py` + `tests/test_dashboard_design_tokens.py` + `tests/test_design_spec_contract.py` | CI 强制 |

**双轨**：任何 UI 改动必须同时更新规范文档与补一条能真正失败的断言，缺一视为未完成。

**反向验证**：加完断言后必须故意制造一次违规，确认测试确实报错，再恢复。
只看到测试通过不算验证通过；永远通过的测试等于没有测试。

**粒度**：只守住有独立语义的顶层组件与不变量。不要为每个内部类名建门禁：
单页内部 CSS 类可达数百个，全覆盖只会产生海量误报，最终被绕过。

> 本文件与 HTML 可读版的章节由门禁**双向**比对：MD 里的每节要能在 HTML 中找到，
> HTML 里的每节也要能在 MD 中找到 —— 两侧都不许单方面新增章节。
