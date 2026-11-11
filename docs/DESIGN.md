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
**能力摘要区**（Skills / MCP）。两组必须**逐项同构**，否则值区起点会差十几像素，
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

> 为什么不是「两栏 grid」：值区那一行会有「主值 + 状态标签」共 **2** 个子元素，而另一行
> 只有 1 个；两栏 grid 会把第 2 个挤到第二行第一列并撑满宽度（渲染实测）。`nowrap` +
> 首元素自适应对 1~2 个子元素都稳定成立。作用域限定 `.agent-card:not(.home-card)`：
> 主页卡片是另一套渲染，不跟着变。

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

`.ac-path-none`（如「未收录 MCP 配置」）必须与 `.ac-path-val` 在**决定行高的每个属性**上
完全相同：`font-size`、`line-height`、`padding`、`border`、`font-family`。

> 为什么这条至关重要：分隔线用 `margin-top: auto` **锚定卡片底部**，前提是 **meta 带高度恒定**。
> 实测两处不一致：① 空态少了 1px 字号；② 空态缺那条 `border: 1px solid transparent`
> （值胶囊为 hover 不抖动而留）。合计 **3px** ⇒ "MCP 未收录"的卡片 meta 带矮 3px
> ⇒ **分隔线整体上移 3px**，跨卡片错位。用户三次说"没对齐"，肉眼几乎看不出是 3px。
>
> 实测（真实数据、2/3/4/5/6 条路径共 8 张卡片）：修好后 meta 高度恒为 **109**、
> 两条分隔线 Δ=0（`metaTop 194/194`、`600/600`、`949/949`、`1271/1271`）。
> 不变量由 `CardLabelColumnAlignmentTest.test_value_and_empty_have_identical_metrics` 守住。

**淡化变体 `.ac-path-val.is-dim` 只改颜色，不改形状**：

`color: var(--faint)` + `background: transparent` + `border-color: transparent`。

> 根因（2026-10-12 用户提问「为什么 Skill 的样式和 MCP 不一样」）：`.is-dim` 曾设
> `border-color: var(--line)`，而默认胶囊是**透明无边框**。于是同一张卡片里 Skills 那格
> 显示成方框、MCP 是纯文本 —— 同一类元素出现两种形态。
> 现规定：**淡化只表达"这是注册表默认值、非本机状态"，绝不改变胶囊形状**；并且
> **两行（Skills / MCP）在未安装时统一淡化**，不允许只淡化其中一行。

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
名称 | 类型 | 安装 | APP | CLI | CONFIG | 技能目录 | MCP | 操作
```

**每个状态列都必须配一条同名图例**（`.skill-legend`），且图例的四态与列内取值一一对应：

| 列 | 四态 |
|---|---|
| MCP | `ok` 全部已设置 / `warn` 部分 / `err` 未设置 / 中性 不支持或无端点 |

> **IDE/Agent 页的图例已整块撤销**（2026-10-14 用户要求：「目前如果全部有图例的话
> 就太多太长了」）。该页图例 4 项 + 一段脚注，合计约 100px 高，且与 chips/表头堆叠。
> **含义没有丢，改由列头说明气泡承载**（见下）。

**列头说明气泡：`data-help` + `.th-help` + `.th-tip`**（图例撤销的配套）

⚠️ **不要用原生 `title`**：实测本应用（Tauri / macOS WKWebView）里 `cursor: help` 会生效
（光标变问号），但**原生 title 气泡不弹出** —— 于是"能不能看说明"完全落空（用户反馈
「提示…没有显示出来」）。故改为**自绘浮层**，不依赖任何平台原生行为。

| 部件 | 作用 |
|---|---|
| `th[data-help]` | 说明文本载体；`\|` 分段成行。行有两种：**文本行**（含 `=` 时排成「键 / 值」两列）与 **图例行**（以 `#` 开头，见下） |
| `.th-help` | 标签后那枚 11px 的问号图标（`ICONS.help`），faint 色；hover 时转 accent |
| `.th-tip` | 气泡本体：`position: fixed`、`max-width: 320px`，复用 `--panel` / `--line-strong` / `--r-control` / `--shadow-modal`，与既有 `.path-pop` 同族 |
| `.th-tip .tt-row` | 气泡内一行：`display: flex` + `gap: var(--gap-3)`，让 `=` 前的键与值分列对齐 |
| `.th-tip .tt-k` | 该行的「键」半部（如 `N / M =`）：`flex: none` + `--muted`，不参与换行挤压 |
| `.th-tip .tt-legend` | 图例行容器：`flex` + wrap，条目间距 `--gap-4` |
| `.th-tip .tt-item` | 图例条目：图标/色点 + 标签，`inline-flex` 对齐 |
| `.th-tip .tt-dot` | 8px 纯色点（MCP 的四态图例用），变体 `.ok` `.warn` `.err` `.na` `.neutral` 与 `.legend-swatch` 同色系 |

**图例行格式**（`data-help` 里以 `#` 开头的段）：条目用 `;` 分隔，每条为
`图标名.颜色类:标签`；**图标名为空则渲染 `.tt-dot` 色点**，非空则渲染 16px 的
`.al-ico` 徽标（与表内单元格同款形态）。

> 为什么图例要画图标而不是文字描述（2026-10-14 用户要求「弹出的内容中最好有图标
> 作为图例」）：文字"绿点 已安装"需要读者在脑中翻译成视觉，而直接渲染那枚徽标，
> 气泡里的图例与列里的实际形态**一一对应**，扫一眼即可对上。

行为：`mouseenter` / `focus` 时由 `showThTip()` 渲染到既有 `#pop-root`（复用层级与定位），
`mouseleave` / `blur` 时 `hideThTip()` 清除；贴右边界自动左移防裁切。
`th` 带 `tabIndex=0` 且气泡是 `role="tooltip"`，**键盘 Tab 也能读到说明**（可达性）。

| 列头 | `data-help` 内容 |
|---|---|
| 安装 | 图例行：`check.ok` 已安装 / `warn.warn` 仅配置 / `cross.err` 未安装 |
| 技能目录 | 图例行：`link.ok` 已指向统一技能目录 / `folder.warn` 独立目录 / `cross.err` 无目录 / `minus` 不适用 |
| MCP | `N / M = 已设置端点数 / 声明挂载的端点总数` + 色点图例行（四态） |

- 可发现性由 `.th-help` 问号图标承担（`cursor: help` 保留为辅助）。
  **不得用 `✓ ⚠ ✕ −` 等符号字符充当图标**（规范 3b：图标一律 SVG，不用字符/emoji），
  图例一律走上面的图标名标记。

**状态列内容居中**（2026-10-14 用户反馈「安装 技能目录等内容，没有和上面的标题栏
居中对齐」）：`.agent-list-table` 的第 3 / 7 / 8 列（安装、技能目录、MCP）
`th` 与 `td` 一律 `text-align: center`。

> 为什么居中：这三列的单元格是**单枚徽标或短标签**，左对齐时徽标贴着单元格左缘，
> 而列头文字 + 问号图标整体更宽，视觉上徽标"偏左"。居中后列头与内容的轴线一致
> （实测三列内容中心与列中心偏差均为 0.0px）。名称 / 类型列保持左对齐（长文本），
> 操作列保持右对齐（按钮组）。

**行内状态列的最终形态：`.al-ico` 图标徽标 + `.tag` 胶囊**（2026-10-14 三轮定案）。

`.agent-list-table` 的一行里，按"表达什么"分三种形态，**不允许混入纯着色文字**：

| 列 | 取值 → 形态 |
|---|---|
| 安装 | **`.al-ico` 图标徽标**：`check`(`.ok`) / `warn`(`.warn`) / `cross`(`.err`) |
| 技能目录 | **`.al-ico` 图标徽标**：`link`(`.ok`) / `folder`(`.warn`) / `cross`(`.err`) / `minus`(中性) |
| MCP | `N/M` `.tag.ok`·`.tag.warn`·`.tag.err` / 不支持·`0` 中性 `.tag` |
| APP / CLI / CONFIG | `.al-metric` 圆形计数徽标（可点，另有 `.hit` 高亮态） |

`.al-ico`：20×20 圆形，与 `.al-metric` **同尺寸、同边框、同底色族**（量级一致），
`svg` 12×12；变体 `.ok`/`.warn`/`.err` 分别取 `--ok-bg`/`--warn-bg`/`--err-bg`。
图标取自 `ICONS`（本文件既有的 lucide 风格集合，为本次新增 `link`/`folder`/`minus`）。

> **为什么这两列最终用图标而不是文字胶囊**（演进记录，三轮都是用户反馈驱动）：
> ① 最初用 `.ok-true/.ok-false/.ok-na` —— 纯着色文字，与同行 MCP 的 `.tag` 胶囊混形态；
> ② 统一成 `.tag` 胶囊后，用户仍嫌「**胶囊里的文字显得也比较突兀**」：这两列在多数行上
>    取值相同（"已安装"、"链接统一目录"），同一串中文逐行重复，又长又抢眼，而同行其它列
>    都是紧凑徽标（数字 / 短标签 `2/2`），长文字让这两列成了整行最重的元素；
> ③ 最终定为**图标徽标** —— 能一眼扫完，与数字徽标同量级。

> **无障碍（不可省）**：每枚 `.al-ico` 都必须带 `title`，并紧跟 `<span class="sr-only">`
> 完整文本；图标本身 `aria-hidden="true"`。理由：WCAG 1.4.1 不以图形/颜色单独传达信息。

> ⚠️ **不要用 `.ok-true` / `.ok-false` / `.ok-na` 表达行内状态**：那三个类只设 `color`，
> 是**纯着色文字**（无边框、无底色）。这三个类**仅允许**用在非表格的密集文本处
> （如弹窗内的 `client-state-row`）。
> 不变量由 `RowStatusCellUniformityTest` 守住。

**列宽治理：`table-layout: fixed` + 紧列定宽 + 文本列弹性**（2026-10-14 量化诊断后整改）。

默认 `auto` 布局下，浏览器把表格**全部宽度**按内容比例分摊给每一列。后果：只装一枚
20px 图标徽标的列（安装、技能目录）被分到 89–125px，
1440px 窗口下整表约 **65% 是横向空白**，徽标孤零零悬在列中央。

解法：`.agent-list-table { table-layout: fixed }`，7 个紧列给定宽，名称与类型两个
文本列不设宽（吸收剩余空间）。

| 列（nth-child） | 定宽 | 依据（内容并集 + `--sp-4`×2） |
|---|---|---|
| 安装 (3) | 56px | 20px 徽标 + 20px 内边 + 余量 |
| APP (4) | 48px | 24px 计数徽标 + 20px |
| CLI (5) | 48px | 同上 |
| CONFIG (6) | 70px | 24px 徽标，表头词更长 |
| 技能目录 (7) | 82px | 20px 徽标，表头含问号图标 |
| MCP (8) | 78px | 54px（`27/27` 胶囊）+ 20px |
| 操作 (9) | 124px | 96px（详情按钮 + kebab）+ 20px |

> 数值来源：headless Chrome 实测各列各行**内容并集包围盒**最大值 + 单元格左右内边
> （`var(--sp-4)` × 2 = 20px），向上取到 4 的倍数。三个窗口宽度（1018 / 1440 / 1680px）
> 均验证：**零溢出、零横向滚动**。
>
> `fixed` 布局下超长内容不会自动换行，故 `td { overflow: hidden }` 兜底裁切，
> `.al-name` / `.al-type` 加 `text-overflow: ellipsis` 保证长客户端名不撑破定宽。
>
> 不变量由 `ColumnWidthGovernanceTest` 守住。

### 2.3c-2 约束文件（主表状态列 + Agent 卡片/列表内联，v0.38.0）

**为什么有它**：不同客户端的「主要约束文件」各不相同——Claude Code 用
`CLAUDE.md`、Codex 用 `AGENTS.md`、Gemini CLI 用 `GEMINI.md`、WorkBuddy 用
`SOUL.md`……用户此前要逐个翻目录才知道「这台机器上每个 Agent 的规则配了什么」。

**两处呈现，都是「客户端的一个属性」，不单独开卡**（v0.38.0 用户定案：
「这个约束文件也应该同步到上面的卡片或者列表中，而不是一个单独的展示」）：

1. **IDE / Agent 主表加「约束」列**（第 8 列，技能目录与 MCP 之间）：只给状态，
   与安装/技能目录/MCP 同一表达方式——`N/M` 徽标，`title` 列出各路径；
   全配置 `tag ok`、部分 `tag warn`、都没有「未配置」、无官方约定「无约定」。
2. **设置页 IDE / Agent tab 的 Agent 卡片与列表**：约束作为**第三行能力摘要**
   接在 Skills / MCP 之后（`.ac-meta-row` 的 `k=约束`），内容是 `N/M` 徽标 +
   一个或多个「查看」按钮（WorkBuddy 有两个路径就两个按钮，`title` 给完整路径）。
   列表视图里它跟 Skills/MCP 一起放进「能力摘要」列。
   **无官方约定的客户端不出现这一行**——不是显示「无约定」占位。

```
┌ .agent-card（设置页卡片视图）─────────────────────┐
│ WorkBuddy  AI Assistant                          │
│ APP / CLI / CONFIG 三行路径                       │
│ Skills  5/5 已启用                                │
│ MCP     2/2                                       │
│ 约束    [2/2] [查看 1] [查看 2]   ← v0.38.0 新增  │
└──────────────────────────────────────────────────┘
```

- **数据来源**：`--list-rules --format json`（只读），一次加载同时喂给主表与
  设置页（`RULES_DATA`）。路径只认注册表（`mainstream_registry_data`）里显式
  声明的 `rules_paths`，**不猜**。当前登记 **13 个客户端 / 14 个路径**。

  | 客户端 | 用户级规则文件 | 官方依据 |
  |---|---|---|
  | VS Code | `~/.copilot/copilot-instructions.md` | VS Code 文档「User instructions」 |
  | Windsurf | `~/.codeium/windsurf/memories/global_rules.md` | Windsurf 文档 |
  | TRAE | `~/.trae/rules` | TRAE 文档 |
  | Zed | `~/.config/zed/AGENTS.md` | Zed「Personal Instructions」 |
  | Claude Code | `~/.claude/CLAUDE.md` | Claude Code memory |
  | Codex | `~/.codex/AGENTS.md` | OpenAI Codex AGENTS.md |
  | Gemini CLI | `~/.gemini/GEMINI.md` | Gemini CLI 文档 |
  | Cline | `~/Documents/Cline/Rules` | Cline 文档 |
  | Roo Code | `~/.roo/rules` | Roo Code 全局规则目录 |
  | OpenCode | `~/.config/opencode/AGENTS.md` | OpenCode 文档 |
  | Goose | `~/.config/goose/.goosehints` | goose「Global hints file」 |
  | WorkBuddy | `~/.workbuddy/SOUL.md` + `~/.workbuddy/USER.md` | WorkBuddy 文档 |
  | DeepSeek Harness | `~/.dsh/AGENTS.md` | DSH 文档 |

  **刻意不登记的**：Cursor（User Rules 存在设置/数据库，无官方文件路径，
  项目级 `.cursor/rules` 不是用户级）、Aider（`CONVENTIONS.md` 是项目级，
  用户级要靠 `.aider.conf.yml` 的 `read:` 自行指路）、JetBrains AI Assistant
  （官方文档未给出用户级规则文件路径）。这些客户端宁可显示「无约定」，
  也不猜一个看起来对、实际不生效的路径。

  路径在卡片里会**缩写固定长前缀**（`.replace(/^~\/Library\/Application Support\//,
  "~/Library/…/")`，Windows 同理 `~/AppData/…/`），完整路径保留在 `title`
  与预览弹框里——长路径在 480px 卡片里会被 ellipsis 截断（用户反馈「显示不全」）。
  **Cursor 不登记**：用户规则存在设置里（不落盘），`~/.cursor/rules` 是项目级。
- **目录形态**（Cline / TRAE）：`--read-rules` 返回文件清单，弹框只读展示，
  **不支持整体写入**——把一段文本写进规则目录会覆盖其中所有文件。
- **路径行 / 能力摘要行一律基线对齐**（`.ac-path-row`、`.ac-meta-row` 的
  `align-items: baseline`）：标签是 11px / `line-height: 1.9`，值是 12px /
  `line-height: 1.5` 再套胶囊 padding，两者行盒高度不同。用 `start` 顶对齐时
  标签文字会比值的文字高 1.5~2px（用户截图：「左边的字比右边的字高一点」）；
  基线对齐后两边文字落在同一条基线上，实测底部差 0.00px，顶部 1px 差是字号差异。
- **约束行并入路径区**（`.ac-paths` 的第四行，标签 `RULES`），与 APP / CLI / CONFIG
  **逐项同构**：同一 58px 标签列、同一 `.ac-path-val` 胶囊、同一 mono / `--fs-xs` 字号。
  用户定案：「约束好像应该是 Agent 本身的内容，不应该和 skill 和 MCP 放在一起」
  「没有和整体的展示对齐，而且好像字体也不一样」。
  路径是胶囊里的可点文字（`.rules-path-btn`，**没有独立按钮**），点击打开只读预览。
- **只读预览**（`.rules-preview`）：有边框、内边距、可滚动（`max-height: 55vh`），
  底部只有「关闭」。**不提供内联编辑**——用户定案：「展示部分只需要只读就好了，
  在这里不需要提供直接修改文件的功能」。
- **预览弹框**（`.rules-modal` 修饰 `.modal.modal-form.ad-modal`）的信息层次：
  标题 → 路径（mono）→ **状态与规模并排一行**（`.rules-meta` / `.rules-meta-k` /
  `.rules-meta-v`，标签 mono 大写 faint、值 `--fs-sm`）→ 内容区 → 底部分隔线
  （`.form-actions` 的 `border-top`）+ 关闭。未配置时用 `.rules-missing`
  （**实线**边框的说明块）——虚线是「占位符」语言，不该出现在这里。
  用户反馈「太丑」的三处：两行 kv 间距过大、未配置态是虚线框、底部无分隔。
- **为什么函数里要 `typeof RULES_DATA` 防御**：`renderHomeListView` /
  `renderAgentsTable` 会被测试单独抽出到 node 里执行，那时全局状态不存在；
  不加防御会直接 ReferenceError。

### 2.3d 图例（`.skill-legend`）的放置与对齐### 2.3d 图例（`.skill-legend`）的放置与对齐### 2.3d 图例（`.skill-legend`）的放置与对齐

**位置：一律放在所说明内容的「上方」**（2026-10-14 用户定案：放上面好看）。页面级图例
涉及 Skills 页、MCP 页、一键合并预览弹窗，共 3 处。

> 走过一次弯路（记录以免重犯）：曾按要求把这 3 处全移到内容**最下方**，理由是"图例是
> 读数据之后的对照说明、放顶部会挤掉首屏数据"。用户看到实际渲染效果后判定
> **「还是放在上面好看」**，于是全部回退。教训：这类"放上还是放下"的取舍，
> 语义上两边都讲得通，**必须看实际渲染再定**，不要只凭理由推断。
> 不变量由 `LegendPlacementAndAlignmentTest.test_legends_come_before_their_content` 钉住。

**标签列必须定宽**：`.skill-legend .legend-label { min-width: calc(var(--sp-9) + var(--sp-3a)) }`（31px）。

> 同一页可能出现多条图例（一键合并预览弹窗里就有多条），标签名字长短不一。
> 不定宽时各自的第一个色点会**错开 2px**（实测）。
> 定宽后色点列严格对齐。这与卡片标签列定宽（§2.3b 的 58px）是同一思路。

**每条 `.legend-swatch` 都必须带语义 class**（`ok` / `warn` / `err` / `na` / `neutral`）：

| class | 颜色 token | 用于 |
|---|---|---|
| `.ok` | `--ok` | 全部就绪 |
| `.warn` | `--warn` | 缺失 / 未配置 |
| `.err` | `--err` | 未设置 / 不可用 |
| `.na` | `--faint` | 不适用（未收录 / 仅审计 / 跳过） |
| `.neutral` | `--muted` | 中间态（部分已配置）——既非就绪也非缺失 |

> ⚠️ **漏 class 是个隐蔽陷阱**：`<span class="legend-swatch"></span>` 仍会命中基类拿到
> 9px 宽高，但没有 background 规则 → 渲染成**看不见的占位**；同时零宽度的它会把**后面的
> 条目整体左移**，造成同页多条图例错位。实测踩过（"部分已配置"那条）。
> 不变量由 `LegendPlacementAndAlignmentTest` 守住：色点必须有语义 class、各变体必须有
> background、标签列必须定宽、图例必须排在内容之后。

### 2.3e 技能表列（`.skill-table`，v0.31.0 增两列）

七列：名称 / 分类 / **本地**（`st-ver`，8%，mono，`skill_meta.version` 或
最后更新时间日期；无版本与时间显示 `-`）/ 用途 / **远端**（`st-upd`，9%，
检查后三态 tag（技能行内只可能出现这三态——`missing` 的技能不在列表里）：
有更新
`tag warn`（title 含本地→远端版本）/ 最新 `tag ok` / 未知中性 `tag`，
未检查显示 `-`）/ 启用 / 操作。嵌套展开行 `colspan="7"`。

**列合并纪律（2026-11-06 用户反馈修正）**：原先的「本地 / 远端」两列已合并为
单列「同步」（`st-sync`）。

为什么合并：用户看到本地 `07/17`、远端 `11/02` 后指出「两者完全没有关系」——
他是对的。这两列本就是**两个不同的量**：

| 列 | 实际取值 |
|---|---|
| 本地 | 该技能 `SKILL.md` 的 mtime（文件最后修改时间） |
| 远端 | 上游仓库基准的提交时间（仓库形态技能全部是同一个值） |

并排显示成同样的 MM/DD，读者必然把「07/17 vs 11/02」读成「本地旧、远端新」，
而它们根本不可比。现在只回答一个问题：**这个技能和上游谁新**。

**框内显示内容 = 数据，框色 = 结论**（2026-11-06 用户要求）。

用户原话：「这里不应该直接显示"一致"，而是应该显示最新的版本信息；没有版本
信息的，就显示最新提交的日期信息」，以及「"是否一致"应该用框的颜色来展示，
不然框和里面的文字展示同一个内容有点累赘了」。

| 状态 | 框色 | 框内文字 |
|---|---|---|
| 一致 | `tag ok`（绿） | 远端版本号；无版本号则提交日期 MM/DD |
| 远端较新 | `tag warn`（黄）+ `tag-upgradable` | 同上（可点击升级） |
| 未知 | 中性 `tag` | 「未知」 |
| 未检查 | 中性 `tag` | 「未检查」 |

**框内不得出现「一致」「远端较新」这类状态词**——那与框色重复。只有
「未知」「未检查」这两个**没有数据可显示**的态才用文字。

精确时间降级到 `title`：悬停显示「本地：… / 上游…：…」外加状态说明；
后端标记 `stale`（没拉到真实远端）时追加「基准可能过期」。
检查结果持久化在 localStorage（`sms-skill-updates`，含 `checkedAt`），
启动时回填 —— 否则每次重启 App 整列都变「未检查」，用户只会以为工具又坏了。更新数据来自
`--market check`（版本比对，只读），结果缓存于前端 `SKILL_UPDATES`
（刷新页面后需重查）。工具栏「检查更新」按钮（`skill-check-updates`）
异步跑检查并 toast 四态汇总。

**检查结果四态（v0.31.1 用户实测缺陷修复）**：`outdated`（有更新）/
`current`（已最新）/ `unknown`（无法检测）/ **`missing`（登记失效）**。
前三态是「已装技能与上游的差异」；`missing` 是另一类事实——**lock 里有登记、
但统一库中已无该目录**（装过又被删，登记残留）。它必须单列，理由是原先把
它并入 `outdated` 会直接产出用户可见的矛盾：技能列表按磁盘目录生成、画不出
这一行（没有「有更新」tag），而「一键升级」取检查结果全量，把它也算进去，
于是**列表说 2 个、弹框说 4 个**。该态不提供「升级」动作（无本地内容可覆盖，
点了只会得到一条失败），文案用 `.list-meta.is-err` 承载。

**结果图标的语义（2026-11-06 用户反馈）**：`检查完成` 弹框的图标只表达
「你是否需要处理」，**不表达「检查是否成功」**（检查要么成功要么报错，不会「部分失败」）。

| 情况 | 图标 | 理由 |
|---|---|---|
| 仅有 `outdated` | **`ok`** | 「有更新」是正常且可操作的状态，不是错误；用警示图标会让用户误以为检查失败 |
| 有 `missing` / `unknown` | `warn` | 本地有历史残留 / 结论不完整，确实需要留意 |
| CLI 非零 | `err` | 真正的失败（另一条分支） |

措辞同步：`missing` 在界面上写「**已卸载但登记残留**」，不写「登记失效」——后者用户
读不出含义（实测被问「为什么会有检查失败的情况」）。有更新时追加一句可操作的下一步
（去哪点一键升级），让弹框是「结论 + 动作」而不是一串计数。

**计数口径纪律（v0.31.1）**：任何「有多少个可升级」的呈现（工具栏 toast、
市场页汇总行、一键升级弹框标题与表格）必须同源——一律取 `summary.outdated`，
且 `missing` 单独报数、不混入前者。前端另有一道防线：一键升级只处理
`SNAP.skills.skills` 里真实存在的技能，被剔除的条目要 toast 说明原因，
不得静默少升。

**检查结果第五态 `repo_outdated`（仓库待同步，v0.31.3）**：`missing` 之外的
另一类「此前查不到」的技能。本机实测 192 个技能里只有 39 个在
`~/.agents/.skill-lock.json` 有来源登记，其余 153 个此前一律落进 `unknown`
——那个巨大的「无法检测」桶不是结论，是**缺口**：它们不属于任何「单技能来源」，
而是**整仓库形态**——统一库目录本身就是一个 git 工作区（`origin` 指向
`my-agent-skills`，分支 `master`）。这类技能的「上游」是该仓库的远端分支，
判定单位因此不是技能包 version，而是「本地 `HEAD` 与 `origin/<branch>` 之间，
该技能目录有没有差异」。

判定实现 `core/skill_repo_source.py`（只读模块）：

| 项 | 口径 |
|---|---|
| 适用条件 | `paths.skills_dir()` 是 git 工作区，且该技能**不在** lock 登记里（有登记的技能仍走单技能来源，精确到各自上游仓库） |
| 比对基准 | `origin/<当前分支>`；**判定前先 `git fetch`**（`refresh=True`，默认），只更新远程跟踪引用、不动工作区 |
| 有更新判据 | `git diff --name-only HEAD origin/<branch>` 的路径收敛到技能目录后命中该技能 |
| 已有最新 | 同一 diff 未命中该技能目录 |
| 本地有未提交修改 | `unknown`（同步必冲突，不能笼统报「可同步」） |
| 判不成的任何一种 | `unknown` + 原因（git 缺失 / 非工作区 / detached HEAD / 缺上游 ref / 子命令非 0），**绝不静默算 `current`** |

三条纪律：**只读**（只跑 `rev-parse` / `diff` / `status` / `log` / `fetch`，
绝不 pull、merge、checkout —— `fetch` 只改 `refs/remotes/origin/<branch>` 一个
引用，工作区一个字节都不动，因此与本地未提交修改不冲突）；
**fetch 失败绝不静默算 current**（见下「基准新鲜度」）；

**路径收敛只认已知技能目录**（仓库根的 `README.md`、`LICENSE`、`_core`、
`_trash` 不是技能，若不收口会凭空多出「待同步」条目——与 v0.31.1「列表 2 个、
弹框 4 个」同一类矛盾）。

**基准新鲜度（2026-11-05 用户反馈修正）**：上一版规定「不发网络请求」，理由是
快、无副作用。那条判断在实测中被证明是错的：

- 本机 `origin/master` 引用停在 2026-11-02，而检查逻辑只比对这个**本地缓存**；
- 结果是 153 个仓库形态技能**即使远端真有新提交也一律显示「与远端一致」**；
- 一个永远说「一致」的检查等于没检查，而且比 `unknown` 更有害 —— `unknown`
  至少承认「不知道」。

用户看到的正是这个后果：某技能本地显示 07/21、远端显示 11/02，问「差这么大为什么
不算可更新」。实查那次远端确实没变（fetch 验证过），但**判定方法不足以支撑那个
结论**。

现行做法：

| 参数 | 行为 | 适用 |
|---|---|---|
| `refresh=True`（`--market check` 默认） | 先 `git fetch`，再对比**真实远端** | 用户主动点「检查更新」 |
| `refresh=False` | 只比对本地缓存的 ref，不联网 | 高频调用路径（托盘巡检等） |
| fetch 失败 | 结论标记 `stale=True` + `stale_reason`，`note` 追加「注意：本轮未拉到真实远端，基准可能过期」 | 无网 / 认证失败 |

`stale` 会一直透传到 GUI 的远端列 title —— 界面不得把「基于过期基准的一致」
当成确定事实展示。

**两列的时间不是同一个量（2026-11-05 用户反馈）**：「本地」列是该技能**目录**
的最后更新时间，「远端」列（仓库形态）是**整仓库上游基准**的提交时间。两者并排
显示成同样的 MM/DD，会让「07/21 vs 11/02」看起来像「本地旧、远端新」。
因此远端列的 `title` 必须写明基准是什么（仓库形态写「整仓库上游基准」，
单技能来源写「上游最新提交」），`stale` 时追加过期提示。

**为什么必须是独立状态而不是并进 `outdated`**：两者的升级通道完全不同。
`outdated` 走市场升级（`npx` 重装单技能），`repo_outdated` 只能同步整个仓库；
若并成一个状态，「一键升级」会拿 npx 去重装一个仓库形态的技能并得到一条假
失败，而且「可升级 N」与技能列表又会开始对不上。因此：`repo_outdated` 单独
计数（`summary.repo_outdated`），**不进** `summary.outdated`、不进「可升级」
筛选段，市场页与技能表都**不提供**「升级」按钮（技能表远端列显示 `tag warn`
的「待同步」，不可点击；市场页显示「仓库待同步」）。汇总行与 toast 各自
单独报这个数，措辞用「仓库待同步」，与「登记失效」区分开。

**计数口径纪律（v0.31.1）**：任何「有多少个可升级」的呈现（工具栏 toast、
市场页汇总行、一键升级弹框标题与表格）必须同源——一律取 `summary.outdated`，
且 `missing` 单独报数、不混入前者。前端另有一道防线：一键升级只处理
`SNAP.skills.skills` 里真实存在的技能，被剔除的条目要 toast 说明原因，
不得静默少升。

**更新列的升级入口（v0.31.0 用户定案）**：**不设独立升级按钮**——
「有更新」tag 本身可点击（`.tag-upgradable`：`cursor:pointer` + hover
边框反馈 + focus ring；`role="button"` + `tabindex="0"`），点击弹升级
确认；升级操作另融入行尾 kebab 菜单（outdated 技能显示「升级到最新版」
项）。确认流：confirmModal（说明覆盖语义）→ runTaskModal
（`--market-upgrade <name> --yes`）→ 成功后刷新技能清单并重查更新。
**筛选段**含「可升级」（`data-seg="updatable"`：SKILL_UPDATES 中
outdated 的技能；未检查时该段为空）。

**统一升级模态（v0.31.0，`.upg-modal`，2026-10-23 taste-skill 重设计）**：
单个与批量共用三阶段（确认 → 进度 → 完成），同一弹框内重渲染。

**确认阶段**（数量自适应）：单个走 `.upg-hero` 锚点分支——
`.upg-hero-name` 技能名（display 字体）+ `.upg-hero-sub` 说明
（muted）+ `.upg-ver` **版本对比条**（panel-2 底 r-control 卡片：
`.upg-ver-side` 两侧竖排——`.upg-ver-num.from` 当前版本 muted /
`.upg-ver-num.to` 远端版本 accent（mono fs-md 粗体）+
`.upg-ver-label` 小标签；中间 `.upg-ver-arrow` 箭头）。
批量走 `.upg-count-row` 大数字锚点（`.upg-count-num` display
fs-xl 粗体 tabular-nums + `.upg-count-label` muted 说明）+
`.upg-table` **版本对比表格**（`table-layout: fixed` + `colgroup`
定列宽：技能 `col.c-name` 取剩余宽度 / 版本 `col.c-ver` 各 22% /
箭头 `col.c-arrow` 1.75rem 仅容符号；四列：技能 `.t-name` mono
单行省略 / 当前 `.t-ver` muted 右对齐 / 箭头 `.t-arrow` 居中 /
远端 `.t-ver.to` accent；每页 8 行，>8 时用统一分页器（§2.5d）
复用 pg-btn/pg-info 语言「第 i / N 页 · 共 M 个」，`margin-top`
取 `sp-4`）。

**表格取值纪律（2026-10-23 修订）**：版本列只放「版本号或日期」，
不放判定说明文字（无本地版本显 `-`，无远端 tag 显提交日期）；
「按上游提交时间判定」这类说明一律进行的 `title`（由 `verTip()`
拼装：本地版本 · 远端版本或提交日 · note），因为长说明会撑破固定
列宽，且让「当前」列出现说明文字属语义错位。`.upg-warn` 覆盖警告行（flex 行内布局、`align-items:
flex-start` + `gap-2`、`text-wrap: pretty` 防孤字；ICONS.info
warn 色 13px 图标；`margin-top` sp-4。**不得删掉 flex/color/
font-size 三项**，退化为 block 会让文案硬换行出现单字孤行）。操作按钮 `upg-cancel` /
`upg-confirm`（actions 区上边线分隔 + sp-4/sp-3 间距）。

**进度阶段**：`.upg-progress` 两端对齐计数（左「**i** / N」右「P%」，
tabular-nums）+ `.upg-bar` 3px 进度条（`.upg-bar-fill` accent，
width .3s）+ `.upg-list` 逐技能行（`.upg-row`：状态类驱动样式——
`.running` panel-2 高亮 / `.done` 半透明淡出；`.upg-ic` 状态图标 +
`.upg-name` mono + `.upg-note` 失败原因 + `.upg-state-word` 状态词）。

**完成阶段**：`.upg-stats` 大数字统计（`.upg-stat` 竖排——
`.upg-stat-num` display 字体 fs-lg 语义色 + `.upg-stat-label` 标签；
失败为 0 时只显示成功块）+ 逐技能结果列表 `.upg-done-item`
（**必须包含版本变迁与失败原因**，用户需求 2026-10-23）：
`.upg-done-row` 单行（`.upg-ic` 图标 + `.upg-name` 技能名 mono
截断 + `.upg-done-ver` 版本变迁 mono fs-xs muted（`本地 → 远端`，
取自升级前的检查快照）+ `.upg-state-word` 右对齐状态词）；
失败行追加第二行 `.upg-done-reason`（err 色 fs-xs，缩进 `sp-9`
对齐名称列，最多两段 ` / ` 拼接 + `title` 悬停全文）。

入口：更新列可点击 tag（单个）/ kebab「升级到最新版」（单个）/
工具栏「一键升级」按钮（`skill-upgrade-all`，批量按顺序逐个）。

### 2.3f 技能启用状态（启停矩阵，`N / M` 徽标与三段筛选）

**「启用」不是技能自带的属性**。上游 Agent Skills 规范里 `SKILL.md` 的 frontmatter
只有 `name` / `description`（外加可选 `version` 等），**没有 `enabled` 字段**；
本项目 `~/.skills-manager/config.yaml` 也没有启停开关。共享库里的技能「存在即存在」。
所谓启用 = **某个客户端的 skills 目录里有没有指向共享库该技能的符号链接**。因此它是
**「每客户端 × 每技能」的矩阵**，允许「在 Cursor 启用、在 VS Code 未启用」这种状态。

**三态判定**（`core/skill_state.py`，ADR-17 审计的第 5 层）：

| 态 | 判据 |
|---|---|
| `enabled` | 客户端 skills 目录里有指向本仓库该技能的**有效符号链接**；**root 形态**客户端（整个 skills 目录就是一条指向共享库的链接）则仓库内全部技能都算启用 |
| `disabled` | 技能在仓库里，但该客户端**没有**有效链接（真实目录里缺这条链接，或客户端目录不存在） |
| `not_in_repo` | 技能名不在共享仓库 —— 这类技能**不进入** `skill_states`，界面上既不显示「已启用」也不显示「未启用」 |

**三段筛选（`data-seg`）的口径必须与 `N / M` 徽标同源**：

| 分段 | 判据 | 含义 |
|---|---|---|
| `on` 已启用 | `N === M && M > 0` | 全部客户端都挂了 |
| `partial` 部分启用 | `0 < N < M` | 挂了一部分 |
| `off` 未启用 | `N === 0` | 一端都没挂 |

`N` = 该技能在 `clients_states` 里 `states[skill] === "enabled"` 的客户端数；
`M` = `clients_states` 长度（= 图例要说明的「客户端总数」）。徽标三色：
`N === M` → `.tag.ok`、`0 < N < M` → `.tag.warn`、`N === 0` → `.tag.err`。

**图例文案必须写全两个字母**：`N / M = 已挂载该技能的客户端数 / 客户端总数（共 M 个
IDE 与 Agent）`。只写 `N/M` 会让用户以为 M 是技能总数（曾如此误解），图例就是为此存在。

**为什么本机常年是「已启用 190 / 部分启用 0 / 未启用 0」**（2026-10-24 实测）：
本机客户端多为 **root 形态**（`~/.claude/skills` 本身就是指向共享库的符号链接），
共享库里有什么就自动全开，**根本没有逐个启用的余地**。要让另外两段有内容，必须先把
客户端迁到 per-skill 形态（`--migrate-skill-links`）。这不是界面 bug，是形态决定的。

**写操作与只读查询**：`--enable-skill <skill> [--client X]` / `--disable-skill`，
实际动作是建 / 删那条 per-skill 符号链接（`core/skill_toggle.py`）；root 形态返回
`skip`（「enable whole repo instead of per-skill」），mixed 形态返回 `skip`（须先迁移）。
只读查询用 `--list-skill-states` 打整张矩阵。

**与「登记失效」（`missing`）的区别（务必分清）**：`missing` 是 lock 有登记、磁盘没有
目录（安装残留，见 §2.3e），它连 `not_in_repo` 都不算 —— 根本不进技能列表，也不进启停
矩阵；`disabled` 则是**技能实实在在在仓库里，只是这个客户端没挂**。两者在界面上都表现为
「看不到它生效」，但一个是**数据残缺**，一个是**正常配置状态**，不可混为一谈。

**弹框家族与宽度治理（v0.31.0 收敛）**：宽度一律走 `--modal-w` 变量，
`.modal` 只声明 `width: var(--modal-w, min(560px, 92vw))`，具体弹框在
自身类上赋值变量即可，**禁止再写 `width: ... !important`**。

家族现状（2 类 + 3 修饰）：

| 类 | 角色 | 宽度变量 |
|---|---|---|
| `.cfm-card` | 确认/结果类（居中排版） | `min(400px, 94vw)` |
| `.modal-form` | 表单/详情类（左对齐排版） | 默认值 |
| `.task-card` | 修饰 `.cfm-card`：任务进度 | `min(420px, 94vw)` |
| `.upg-modal` | 修饰 `.cfm-card .task-card`：升级三阶段 | `min(440px, 92vw)` |
| `.ad-modal` | 修饰 `.modal`：宽详情（左对齐） | `min(880px, 94vw)` |

**不要给 `.ad-modal` 叠加 `.cfm-card`**：后者带 `text-align:center` 与
确认框专用 padding，会污染详情排版（实测验证后放弃该归并）。两个家族
的差异是**排版语义**（居中确认 vs 左对齐内容），不是重复定义。

#### 结果正文的结构化排版（v0.34.2，2026-11-08 用户截图反馈）

**规则：弹框正文不得直接呈现原始 JSON。**

用户截图显示「检查 Git 源更新」弹框里是一屏 `--format json` 的原文——
`{"kind":"git-check","summary":{...},"results":[...]}`。这不是排版问题，
是**把程序契约当成了给用户看的话**。JSON 的消费方是程序，用户要的是
「哪个源、什么结果、下一步该做什么」。

三档正文容器，按信息结构递进：

| 类 | 用途 | 排版 |
|---|---|---|
| `.cfm-msg` | 单句结论 | 居中、`--muted`、`white-space: pre-line` |
| `.notice-lead` + `.notice-list` | 结论 + 若干明细行 | 首行当引子，其余转 `<ul>` 缩进列表（`modalNotice` 的 `renderNoticeBody`） |
| `.notice-stats` + `.notice-stat` | 若干计数指标 | `key/value` 网格：`.notice-stat-v` 大号数字（`--mono`）、`.notice-stat-k` 小标签；`grid-template-columns: repeat(auto-fit, minmax(72px, 1fr))` 自适应列数 |
| `.notice-action` | 一句可操作的下一步 | 独立强调块，带 `.notice-action-icon` 前导箭头；底色 `--accent-bg`，与正文区分开 |
| `.git-result`（`.prog-detail` 内） | 逐条结构化结果 | 一行一实体的 `.git-res-row`（`flex`）：`.git-res-dot` 色点 + `.git-res-id` 主体名 + `.git-res-state` 状态；`.git-res-hint` 另起一行弱化；`.git-res-sum` 顶部汇总 |

**`.git-result` 的色点语义（必须按「需要你做什么」着色，不按退出码）**：

| tone | 含义 | 典型状态 |
|---|---|---|
| `.ok`（绿） | 已达成，无需动作 | `current` / `pulled` / `pushed` / `nothing-to-push` |
| `.todo`（黄） | **待办**，有下一步动作 | `behind` / `ahead` / `dry-run` / `no-remote` |
| `.err`（红） | 需要处理 | `dirty` / `conflict` / `diverged` / `*failed` |

> 为什么不能直接用 `r.ok` 着色：`check` 发现落后 3 个提交时**退出码是 0**，
> 但那时什么都没同步——绿点会让用户以为已经好了。这是本项目「配置 ≠ 连通性 ≠
> 已完成」同一条纪律在弹框层的延伸。

**失败正文必须可行动**：标题已经写着「未完成」，正文再重复「操作未完成」等于
什么也没说。正文取「首个失败源的具体原因 + 怎么办」（`gitFailureMessage`），
例如「有 2 个未提交改动，先提交或清理再拉取」。

**结果弹框的三层结构（v0.36.0，2026-11-08 用户截图「没有排版」）**

`modalNotice(kind, title, message, opts)` 的第四个参数把「数据」与「动作」
从纯文本里拆出来。**计数不得串成一行**（`有更新 1 · 最新 149 · 未知 24`
这种写法用户扫不出重点）：

```js
modalNotice("ok", "检查完成", lead, {
  stats: [                                  // → .notice-stats 网格
    { label: "可升级", value: 1, tone: "todo" },
    { label: "已最新", value: 149 },
    { label: "未知",   value: 24, tone: "warn" },
  ],
  action: "点工具栏「一键升级」批量升级",      // → .notice-action 强调块
});
```

- `message`（结论句）只写「需要留意什么」，没有就留空，不写废话；
- `tone` 只允许 `todo` / `warn` 两档，且只标真正需要处理的项
  （「有更新」是正常可操作状态，不着色）；
- `stats` / `action` 都不传时，行为与从前逐字一致（纯文本路径不变）。

排布顺序固定：图标 → 标题 → 结论 → 计数 → 动作 → 出口按钮。

**提交确认弹框（`.git-commit-modal`，v0.37.0）**

提交是唯一不可逆的本地写操作，因此单独一类：`.git-commit-modal` 修饰
`.cfm-card .task-card`，**左对齐**（与居中确认框不同——它要承载清单）。

| 类 | 作用 |
|---|---|
| `.git-commit-modal` | 容器修饰：内容左对齐，仅标题与导语居中 |
| `.git-commit-src` | 每个源一块：`.git-commit-head` 内放源名与 `.git-chg-line` |
| `.git-chg` / `.git-chg-line` | 改动性质点数（`<b>` 数字 + 小字标签），删除与新增分开计 |
| `.git-commit-files` | 文件清单：`<details>` 默认折叠，`max-height: 22vh` 可滚 |

> **为什么清单默认折叠**：单个源可能有几十个文件（实测 78 条），全部铺开会把
> 「确认提交」按钮挤出视口，用户反而更容易点错。性质点数先给出全貌，
> 需要时再展开看具体路径。
>
> **为什么删除要单独计数**：删除比新增更需要被看见。只给「78 处改动」会让
> 一次「删除整个技能目录」看起来和「改了 78 行」一样重。

### 2.3g DSH 插件页（`page-dsh`，v0.31.4 新增第七页）

**为什么要有这一页**：本工具的 Skills / MCP 是它自己的模型（符号链接 + 端点库），
而 DSH（DeepSeek Harness）的插件是另一套：cordis 载入器的 bundle 体系。用户在
DSH 里装了插件、改了补丁层，却没有一个地方能一眼看清「现在到底会加载什么」。
本页补这个空白。**它是第七页**，归入**「管理」组**（位于「MCP」之后、「系统」组之前）。
**分组的判据是「什么在支配什么」**：管理组各项都是「本工具去检查和管理的对象」
（IDE/Agent / Skills / MCP / DSH 插件 各有自己的清单与启用状态），
而系统组的「变更详情」是审计输出、「设置」是本工具的通用配置——它们描述的是
**工具自身**而非被管理对象。DSH 插件虽然来自另一套 bundle 模型，但与 Skills/MCP
同为「装了哪些、哪些在生效」的资源清单，因此属于管理组，不应混进系统域。

**三种状态必须分开显示**（这是本页存在的全部理由）：

| 状态 | 判据 | 标签 | 为什么不能合并 |
|---|---|---|---|
| `enabled` | 在 `package.json` 的 `dsh.profile.bundles` 里 | `tag ok` 已启用 | 只有它才会被真正加载 |
| `installed` | 在 `dependencies` 里但**不在** `bundles` 里 | `tag warn` 未启用 | 「装了」≠「在用」；合并会让用户以为占着上下文 |
| `broken` | `node_modules/<name>` 里没有该包（且非 `builtin`），**或** `link:` 目标目录已不存在 | `tag err` 来源失效 | DSH 载入会失败；合并会让用户以为一切正常 |

**`broken` 的实际判据是两条并存**（此前本段与 CHANGELOG 都误写成「只判 link 目标
存在性、不以 version 缺失兜底」，与 `core/dsh_plugins.py` 实现不符，已勘正）：

1. `classify_plugin()`：`version is None and kind != "builtin"` → `broken`。这是
   **主路径**，覆盖「清单里声明了、但根本没装进 `node_modules`」这种配置不一致
   （实测本机 `dsh-better-sidebar` / `dsh-context` / `dshmarket` 三个就是这类：
   在 `bundles` 里、但不在 `dependencies`、`node_modules` 也没有）。
2. `scan_profile()` 再额外判一次 `target_missing`：`link:` 依赖的目标目录不存在
   时强制置 `broken`。这条是**补充**，因为 pnpm 的 link 在源码目录被删除后
   `node_modules/<name>` 可能还留着（旧副本或指过去的符号链接），version 读得到
   却被放行。

两条加起来才等价于「这个插件载入会失败」。**只判第 2 条会漏掉第 1 类的静默失效**，
所以不要按旧表述去"修正"代码。

**类型三分类**（`kind`）：`builtin`（`@deepseek-ai/*`，随 DSH 本体分发）/
`local`（`link:` 指向本地源码）/ `registry`（npm 第三方包）。三者在页面上用中性
`tag` 呈现——它们是身份，不是结论，不能抢状态标签的语义色。

**安全约束（硬性）**：`cordis.patch.yml` 的 `config` 段里有**明文 apiKey**（本机
实测存在）。因此本页：

- 只显示 patch 层的**结构统计**（条目数 / 禁用数 / 插入数），
  **绝不渲染任何 config 键值**（连 baseURL 这种也不渲染）；
- 顶部固定显示 `patch 值已脱敏` 标签，`title` 说明原因，让用户知道「这里看不到
  配置」是设计而非缺陷；
- 后端输出带 `secrets_redacted: true` 作为显式承诺，并由
  `tests/test_dsh_plugins.py` 用**含伪造 apiKey 的样本**断言两种出口（JSON 与
  文本）里都查不到它。

**布局**：顶部三计数（已启用 / 装了未启用 / 来源失效，各自独立不合并成总数，
沿用 `.upg-stats` 数字锚点）+ 一行来源与口径说明；下方是**一张** `.settings-card`，
卡头是「全部插件 · N 个唯一插件（去重前 M 条）」，次行是各 profile 的摘要
（插件数 / 启用数 / patch 结构），再下是 `.mcp-table`
（列：插件 / 类型 / 状态 / 版本 / profile）。全部 profile 均无插件时给 `.hint`
而不是空表。

**按插件名去重（v0.31.4 之后、尚未发版）**：同一插件常被多个 profile 同时声明——
实测 `@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-web-app` 在 `desktop` 与 `web`
里都出现，去重前 16 条、去重后 14 个唯一插件。逐 profile 分卡片会让同一插件
重复出现、看起来像装了两份，也无法横向比较，因此改为**一行一个插件**，由
`profile` 列标出它在哪些 profile 下被声明（多值用多个 `.tag` 并排）。

**状态列在跨 profile 不一致时的口径**：以**最严重**的状态为准显示
（`broken` > `installed` > `enabled`，安全优先），并追加「各 profile 不一致」
字样，`title` 给出逐 profile 明细。**不得静默取其一** —— 那会让「web 下失效、
desktop 下正常」被误读成全平台正常。当前实测数据里所有共有插件状态一致，该
分支是为将来出现分歧时准备的。

**「来源」列并入「类型」列**：`source_path` 此前恒为空（16 个插件无一有值），
却固定占一列宽度。改为跟在类型标签后面：有值才显示（超长省略号 + `title`
给全路径），无值时不占位。这样常见情况下表格少一列、更紧凑，同时不丢失
`link:` 依赖的溯源信息。

**数据来源**：`--dsh-plugins --format json`（只读出口，排在通用快照路由之前，
否则 `--format json` 会被快照出口截走）。进页时按需拉一次并缓存到 `DSH_DATA`，
「重新读取」按钮强制重拉；已拉过不重复拉，避免每次切页起子进程。

**侧栏计数徽标（`.nav-item .count`）**：管理组四个导航项右侧的计数徽标
**口径必须一致**——显示「该页要管理的对象**总数**」，不是筛选后的可见数、
也不是启用数：

| 导航项 | 取值 | 语义 |
|---|---|---|
| IDE / Agent | `visible.length`（`install_state !== "none"`） | 受管客户端数 |
| Skills | `skills.skill_count` | 统一技能数 |
| MCP | `endpoints.length` | MCP 端点条目数 |
| DSH 插件 | `summary.plugins` | 插件总数（已启用 + 装了未启用 + 来源失效） |

**四项必须在启动时就都有值**（2026-11-05 用户反馈修正）。

DSH 插件的数据不在主快照里（走独立的只读出口 `--dsh-plugins`），但**这不能
成为「只有它显示占位符」的理由**。此前的做法是「进页才拉」，于是徽标停在
HTML 里写死的 `0` 上 —— 其余三项启动即有数字，唯独它显示 `0`。

用户的原话是「默认是没有数字的，只有点进去才会有数字」。这个判断是对的：
`0` 不是「还没加载」的占位符，它明确声称「一个插件都没有」，而实际值是 16。
上一版把这件事写成「可接受的过渡态（特例1）」，**那个判断是错的** —— 同组三项
都在启动时有值，一项显示假 `0` 只会让人以为数据没读到。

现行做法：`loadManagement()` 成功路径里调一次 `loadDshNavCount()`（**不 await**，
它是次要信息，不该拖慢主快照呈现；失败只影响徽标）。该函数只取 `summary`、
**不渲染整页**（没进页时画 DOM 是白费），并用 `DSH_NAV_LOADED` 防重入 ——
每次刷新快照只起一个子进程，进页拉到全量时也把标记置位。

**失败/无 profile 时显示 `-`（普通连字符）而非 `0`**：`0` 在语义上是「确实一个
插件都没有」，而失败是「不知道有几个」。二者必须可区分，否则「DSH 没装」会被
误读成「装了但没插件」。判定集中在 `setDshNavCount()` 一个函数里。
占位符用 U+002D 普通连字符，**不用 em-dash `—`** —— 徽标数字位也是可见文案，
受 §3「禁用 em-dash」约束。

由 `tests/test_dsh_plugins.py::test_nav_count_badge_*` 守住上述口径与失败态。

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
| **一次操作的结果** | 保存设置、修复 Skills/MCP | **弹框**：`runTaskModal` 的 `.task-card`（`.task-result` ok/err + `.task-fold` 折叠详情） |

> 为什么：把 CLI 的整段 stdout 铺成页面级 `.banner` 会变成一大片文本（实测保存设置
> 失败时贴了 1600 字符的技能扫描报告，用户截图反馈）。操作结果本就该是一次性的、
> 需要用户确认的**弹框**；`.banner` 只留给「非阻塞的页面级告知」（如自动发现新客户端）。
>
> 另：错误详情一律先过 `cliFailLines`（挑失败行）或 `cliErrDetail`（去 ANSI、截断），
> 不要把原始 stdout 直接抛给用户。

**行内状态点（`.dot` 三态）**：`.dot.ok`（`--ok` + `--ring-ok` 环）/
`.dot.warn`（`--warn` + `--ring-warn`）/ `.dot.err`（`--err` + `--ring-err`）/
`.dot.faint`（透明底 + `--line-strong` 内描边）。9px 圆点，`--r-pill`。
用途：表格或列表里一行一个语义状态（如端点连通性）。
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

### 2.3d-2 主表列宽与空态形态（v0.39.7 用户评审后整改）

用户对主表评审后定了三条边界：**不合并 APP/CLI/CONFIG、类型保留独立列、安装列保留**。
在此前提下只做视觉与交互改进：

| 项 | 改前 | 改后 |
|---|---|---|
| 名称 / 类型列 | `width: auto`，各分到 347px（内容仅 44 / 52px） | 定宽 220 / 150px，省下 ~370px 变成表格外缘留白 |
| 0 值计数 | 实线圆环，与 1 几乎同款 | `.al-metric.dim`：虚线 + 透明底 |
| 约束列 | `1/1` / `未配置` / `无约定` 三种形态 | 统一 `N/M`；无约定用 `—` |
| MCP 空态 | 「不支持」两字 | 与约束一致的 `—`（`.tag.tag-none`） |
| 进详情 | 只能点右上角「详情」按钮 | **整行可点**（`tr[data-row-open]`，含键盘 Enter/Space）；按钮降级为提示 |

**为什么文本列要定宽**（反转一条旧判据）：原判据是「文本列不设 px 宽、留弹性吸收剩余」，
初衷是防紧列被平分；但实测弹性列的代价更大——两列吃 54% 宽度却只放 96px 内容。
正确的不变量是「文本列有明确上限」（≤ 300px），而不是「不设宽」。

**为什么整行可点后仍保留「详情」按钮**：`.al-detail` 是既有类名，被
`test_all_panel_buttons_reachable` 等门禁引用；且键盘用户需要显式的可聚焦目标。
行本身也带 `tabindex="0"` + `role="button"`，两条路径并存不冲突。

### 2.3c-2c 共享约束（v0.40.0 用户需求）

**一段内容同步进所有 Agent 的约束文件**，并能检查哪些没同步、一键强制写入。

用户原话：「可以配置一个需要在所有 Agent 中增加的约束内容，然后可以通过同步管理
（和 skill 一样），检查每一个 Agent 是否都拥有这个约束内容；如果没有，可以点击
强制更新进去」。

#### 数据模型

内容存 `data/shared_rules.md`（gitignore），写进各文件时用一对标记包住：

```markdown
<!-- shared-rules:begin v1 -->
（用户配置的内容）
<!-- shared-rules:end -->
```

**为什么用标记而不是整体覆盖**：约束文件里还有用户自己的规则，整体覆盖会把它们
全部冲掉。标记让写入变成幂等的「替换这一段 / 追加这一段」，块外内容逐字节不动
（`test_apply_keeps_content_after_block` 守着这条）。

#### 四种状态（`.tag` 语义统一）

| 状态 | 含义 | 是否可修 |
|---|---|---|
| `current` | 块存在且内容一致 | 不需要 |
| `stale` | 块存在但内容与配置不一致 | ✅「写入」 |
| `absent` | 文件存在但没有块 | ✅「写入」 |
| `missing` | 文件不存在 | ✅「新建并写入」 |
| `dir` | 规则目录（Cline / TRAE） | ➖ 跳过，不支持整体写入 |

客户端的整体状态取「最需要处理」的那一个：`missing > absent > stale > dir > current`。

#### 界面：内容编辑保留，「逐 Agent 面板」删除（v0.40.6 修正）

v0.40.5 删过头了：把**配置约束内容的输入框**一起删掉，用户找不到写内容的地方。
用户真正要删的是那张「逐 Agent 开关 + 逐行写入」的面板，不是写内容的位置。

#### 「约束」列的三态颜色（v0.40.5）

用户：「这个完全是不需要的，不需要放在概览里完全删除；只需要在 IDE 和 Agent 的
那个 tab 里，在约束的绿色框中，通过不同的颜色来展示出是否有约束文件，以及约束
文件中是否有设置的内容」。

**最终形态（v0.40.7 定稿）：卡片只剩一个内容输入框，归位设置页 IDE / Agent tab。**

五次方向修正收敛到这里：

| 版本 | 形态 | 用户反馈 |
|---|---|---|
| v0.40.0 | 全套面板（输入 + 开关 + 逐行写入 + 状态表） | 「有点丑」 |
| v0.40.4 | 同上，从设置页搬到概览页 | 「不要放在设置里」→ 搬 |
| v0.40.5 | 整体删除 | 「删过头，输入框也没了」 |
| v0.40.6 | 找回输入框 + 同步行 + 状态一览（概览页） | 「红框保留，其他删，放到设置」 |
| **v0.40.7** | **只有「约束内容」输入框 + 一个「保存并同步」** | 定稿 |

```
┌ 共享约束 ──────────────────────────────────────────────┐
│ 约束内容   [ textarea（等宽 --mono / --fs-xs，max-width 44rem）] │
│           这里只保存内容…                              [保存]     │
└────────────────────────────────────────────────────────┘
```

- **位置**：设置页 → IDE / Agent tab **顶部**（在「IDE / Agent 默认路径」之上）；
- **同步行、状态一览、逐 Agent 开关全部删除**——「这个 Agent 有没有共享内容」由
  同一个 tab 下面 Agent 列表的**「约束」列颜色**回答（见下一节），不需要第二套表达；
- **设置里只保存，不同步**（v0.40.8 用户定案）：「设置里应该只保存，不需要同步」。
  卡片里只有一枚 `.primary`「保存」；写进各 Agent 是一次独立动作，经 CLI
  `--shared-rules-apply [CLIENT...]` 执行（备份 → 原子写 → 回读校验）；
- 清空内容再保存 = 停用该功能。

#### 「约束」列的三态颜色

| 状态 | 颜色 | 含义 |
|---|---|---|
| 没有约束文件 | 中性（`.tag` 无修饰） | 这个 Agent 没配规则文件 |
| 有文件，但没有共享内容 | `warn`（黄） | 文件在，你设置的共享约束还没进去 |
| 有文件，且已含共享内容 | `ok`（绿） | 就绪 |

判定在 `renderHomeListView()` 的 `rulesCell` 里：

```
hit === 0                                   → 中性
sharedRow.state === "current"               → ok
共享内容本身为空（还没配过）                → ok（有文件即算就绪）
其余（有文件但缺共享块 / 内容过期）          → warn
```

卡片视图的 `_agentRulesSummary()` 同步给徽标：`共享已含` / `共享过期` / `无共享`
（共享内容为空时不显示这枚徽标——没有「共享约束」这回事）。

数据来自 `--shared-rules-audit`，由设置页 IDE / Agent tab 打开时触发一次。

#### 内容编辑与批量写入

卡片虽然删了，能力仍在（CLI 保留，写操作安全形状不变）：

| 能力 | 命令 |
|---|---|
| 读 / 写共享内容 | `--shared-rules-get` / `--shared-rules-set TEXT` |
| 检查各 Agent | `--shared-rules-audit` |
| 写入（指定或全部） | `--shared-rules-apply [CLIENT...]` |
| 逐 Agent 开关 | `--shared-rules-toggle CLIENT on|off` |

#### 共享块状态回显到「约束」列（v0.40.3 用户要求）

用户：「在外面正式功能的上方，没法从约束对应的框中展示出，到底有没有增加进我
要求的这部分约束」。此前「约束」列只回答「路径存不存在」，不回答「共享块在不在」。

两个渲染点都补第二枚徽标（与 `N/M` 并列，同一 `.tag` 家族）：

| 共享块状态 | 徽标 | 类别 |
|---|---|---|
| `current` | `共享已含` | `tag ok` |
| `stale` | `共享过期` | `tag warn` |
| `absent` / `missing` | `无共享` | `tag`（中性） |
| 该 Agent 开关关闭 | 不显示 | —— |

- 卡片：`_agentRulesSummary()` 读 `SHARED_AUDIT`，徽标落在 `.ac-path-badges`；
- 主表列表：`renderHomeListView()` 的 `rulesCell` 追加 `sharedSpan`；
- 数据来自 `--shared-rules-audit`，`loadManagement()` 之后自动跑一次，因此**不必
  先打开设置页**也能看到。

**断言纪律（这条踩过坑）**：最初写的断言是「文件里出现过 `共享已含` 这几个字」——
它被自己的注释满足了，把映射表换成空串测试照样绿。后来改为从源码里抽出
`_agentRulesSummary()` / `renderHomeListView()` 两个函数体，断言其中的**渲染分支**
（`current: "共享已含"`、`${sharedSpan}`），反向验证才真正报红。

**上一版为什么丑**（v0.40.0 → 重设计）：label 放在 textarea 下方、写成了两行
说明 + 两个角落按钮，完全没走 `.row` 结构，等于在设置页里嵌了一个异类表单。

#### 安全形状

`--shared-rules-apply` 逐客户端、逐路径执行，写前经 `write_rules` 的
「备份 → 原子写 → 回读校验」；部分失败如实回报每个客户端的失败原因，
不合并成一个总数。

### 2.3d-1 主表状态列一律可点（v0.39.6 用户要求）

主表「安装 / 技能目录 / 约束 / MCP」四列的状态徽标**全部是按钮**，点开各自的明细。

用户原话：「后面红色框的几个按钮也需要和绿色框一样是完全可点击的，可以展示出它们
具体的内容」——此前 APP / CLI / CONFIG 是按钮，而技能目录 / 安装是静态 `span`、
约束 / MCP 是静态标签，同一行一半能点一半不能，用户会以为功能坏了。

| 列 | 元素 | 点击行为 |
|---|---|---|
| 安装 | `button.al-ico` | `.path-pop` 列出安装证据（APP + CLI + CONFIG 并集） |
| 技能目录 | `button.al-ico` | `.path-pop` 列出技能目录 |
| 约束（单路径） | `button.tag.tag-btn` | 直接打开只读预览弹框 |
| 约束（多路径） | `button.tag.tag-btn` | 先列出路径，点一条再进预览 |
| MCP（有端点） | `button.tag.tag-btn` | `.path-pop` 列出端点 key |
| MCP（`0` / `不支持`） | `span.tag` | 不点——中性空态，没有可展示的内容 |

**可点必须有可点的手感**：`button.al-ico` 与 `.tag-btn` 都补了
`hover`（accent 边框 + 3px 光晕）与 `:focus-visible`（焦点环）。静态 span 与按钮
长得一样，没有 hover 反馈用户根本不知道能点。

### 2.5b-1 表单弹框的三段式骨架（v0.39.5 用户要求）

**操作按钮永远可见，滚动区不含按钮。** 用户原话：「保存、取消这些操作按钮永远是
显示的，滚动部分不应该包括操作按钮」——此前 `.modal` 整体 `overflow-y: auto`，
按钮会跟着内容一起滚出视口。

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
  平铺写 `form-title` / 字段 / `form-actions`，挂载时自动包成三段。这样新增弹框
  不需要记得手写 `.form-body`，也不会漏。
- 只作用于 `.modal-form`；`.ad-modal`（详情）与 `.cfm-card`（确认）有各自的骨架。
- `.form-body` 必须 `min-height: 0`，否则 flex 子项的默认 `min-height: auto`
  会让它撑破容器、滚动失效。

### 2.5b-2 信息展示与询问一律用弹框（硬规则，2026-11-05 用户要求）

**所有面向用户的信息展示与询问都必须走弹框（modal），不得用 toast 吐司。**

为什么（用户原话：「目前的 UI 规范里面，对于信息的展示没有要求必须是弹框吗？」）：
本项目此前没有任何关于「信息用什么容器」的规定，于是 86 处反馈全靠
`showToast()` 这类**自动消失**的浮层。后果是：

- 检查结果、错误原因这类**需要读完再判断**的信息，几秒后就没了；
- 用户刚切回窗口、或正在看别处，就彻底错过；
- 无法复制、无法回看，关键错误只能靠回忆复述。

规范此前只定义了「弹框长什么样」(`§2.5b`)，没定义「什么时候该弹框」。

**规则**：

| 场景 | 容器 | 说明 |
|---|---|---|
| 操作结果（成功 / 失败 / 警告 / 汇总） | **弹框** | 用 §2.5b 的 `.cfm-card` 形态；可含标题 + 详情 + 单个「好」出口 |
| 需要用户确认的询问 | **弹框** | 已有的 `confirmModal` |
| 长任务的过程反馈 | **行内进度** | 页面/按钮就地显示「执行中」，**不发 toast** |
| 页面级致命错误（CLI 未装、连接失败） | **横幅**（`showBanner`） | 属于持续状态，不是一次性消息，维持现状 |

**一次操作 = 一个弹框，过程在框内累积**（用户原话：「可以在弹框中进行进度的展示，
每个操作都作为进度的一部分，只有完整结束之后再关闭弹框」）。

```
┌ 纳入 3 个客户端 ────────────────┐
│ ◎ 打开                            │
│ ● WorkBuddy · 已纳入    （绿点）   │
│ ● Codex · 已纳入        （绿点）   │
│ ● Zed · 失败            （红点）   │
│ 已完成 3 / 3                      │
└──────────────────────────────────┘
            ↓ 全部跑完，原地转成结果
┌ 纳入完成（有失败） ──────────────┐
│ 3 个成功，1 个失败                 │
│ ▸ 查看过程（3 步，失败 1）         │
│            [关掉]                 │
└──────────────────────────────────┘
```

三条 API：`progressBegin(标题)` 打开 → `progressStep(文字, ok)` 追加一条（可标
成功/失败）→ `progressFinish(标题, ok, 明细)` **原地**换成结果。`progressFinish`
**不得**先 `closeModal()` 再 `mountModal()`：那会闪两下，也让过程框提前消失。
全流程只在用户点「关掉」时关闭。

**为什么过程反馈用这个框、而不是行内 spinner**：批量操作（纳入多个客户端、
升级多个技能）天然有 N 步，用户需要看到**走到哪一步、哪一步失败**。行内 spinner
只能表达「在忙」，失败时还得再弹一次结果——那才是「每个操作弹一次」。一个框
贯穿全程，既不闪，也不丢信息。

**同一件事不说两遍**：已经展示了完整结果的面板（如一键升级的逐条结果），
**不得**再弹一个只写「成功 N」的结果框。

**绝对禁止**：在循环里逐条弹结果框（用户要一个个关掉）。

**实现约定**：统一入口 `modalNotice(kind, title, message)`（`kind` 取
`ok` / `err` / `warn` / `info`），内部走 `mountModal` 以进入 top layer，避免被
同为 top layer 的结果面板盖住。禁止在新增代码里直接调用 `showToast`。

进度弹框与信息弹框共用 `.cfm-card` 容器，各自的语义类：

| 类 | 用途 |
|---|---|
| `.progress-card` | 进度弹框容器（过程中）；带 `.prog-spinner` / `.prog-list` / `.prog-count` |
| `.prog-list` | 步骤列表：每步 `.prog-step` + 一个 `.prog-dot` 状态点（灰=进行中 / 绿=成功 / 红=失败） |
| `.prog-fold` | 结束后折叠展示「查看过程」，默认在失败时展开 |

结果态直接复用 `.notice-card`，因此结束时的 DOM 只是把内容换掉 —— 这正是
「原地转态」的落点（代码里用 `data-progress-replace` 标记，**不引入样式类**：
它只是流程标记，给它编样式属于为测试造类）。

信息弹框（`.notice-card`）另加两个语义类：

| 类 | 作用 |
|---|---|
| `.notice-card` | 信息弹框容器；`.notice-ok` / `.notice-warn` / `.notice-err` 按 kind 换图标色（`--ok` / `--warn` / `--err`），无 kind 时用 `--muted` |
| `.notice-icon` | 左侧状态图标；**内联 SVG**，不用 emoji / 符号字（规范 3b） |

`.notice-msg` 承载正文：`user-select: text` 可选中复制，`max-height: 40vh` +
`overflow: auto` 防止长汇总撑破弹框。

判定由 `tests/test_dashboard_no_toast.py` 守住（见该文件头的判据说明）。

### 2.5c 开关（`.switch`）

用于布尔设置项（如自动发现开关）。

- 轨道：宽 34px 高 20px，`--r-pill`，关闭态 `--line-strong` 底
- 旋钮：16px 圆点，`--on-solid` 底，`transition: transform`
- 开启态轨道变 `--accent-strong`，旋钮右移

### 2.5d 分页（`.pagination`，2026-11-06 统一）

**全站只有一套分页**，由 `paginationBar(page, pages, { total })` 渲染（`page` 为
0 基）。改造前并存 3 种实现，其中两套只有上一页/下一页、没有页码可点，用户只能一页页
翻（原话：「统一一下分页组件，要求有具体的页码可以切换」）。

结构（管理台语境：页码是主跳转方式，翻页按钮是补充）：

```
┌ .pagination ─────────────────────────────────────────────────┐
│  ‹ 上一页   1  2  …  5  [6]  7  …  13   下一页 ›   共 248 个 │
└──────────────────────────────────────────────────────────────┘
                        [6] = 当前页（实心强调色）
```

| 元素 | 类 | 规则 |
|---|---|---|
| 页码 | `.pg-num` | 等宽 `min-width: 32px`（换位不抖动），`tabular-nums` |
| 当前页 | `.pg-num.current` | 实心 `--accent` + `--on-accent` 文字；**不只靠颜色区分**，另带 `aria-current="page"` |
| 省略号 | `.pg-ellipsis` | `--faint`，不可点、`user-select: none` |
| 翻页 | `.pg-prev` / `.pg-next` | 首/末页 `disabled`，不隐藏（位置稳定） |
| 结果范围 | `.pg-range` | `第 41-60 条 / 共 248 条`，`--mono` + `tabular-nums` |
| 每页条数 | `.pg-size` / `.pg-size-sel` | 下拉，选项来自 `PAGE_SIZE_OPTIONS` |

**页码窗口**：当前页前后各 2 页 + 首尾两页，其余折叠为省略号 —— 13 页不会铺满一行。

**结果范围与每页条数（2026-11-06 用户要求）**：只有「共 N 个」不够 —— 用户看不出
当前这页覆盖了哪几条，也无法改变每页条数。现在分页条右侧固定给出两项：

```
                                  … 13   下一页 ›   第 41-60 条 / 共 248 条   每页 [20 条/页 ▾]
```

- **范围文案**：`第 X-Y 条 / 共 N 条`，X/Y 由 `page × perPage` 推得并夹到 `total`；
  单页时降级为 `共 N 条`（没有区间可言）；
- **每页条数**：`PAGE_SIZE_OPTIONS = [10, 20, 50, 100]`，**不提供「全部」** ——
  技能表可能数百行，全量渲染会卡住首屏；要看全部请用搜索/筛选；
- **持久化**：按列表标识分别记忆（`page-size-skills` / `page-size-merge`），
  改技能表不会连带改掉其它列表；
- **切换后回到第 1 页**：否则可能停在越界页（原第 13 页、改成 100 条后只剩 3 页）；
- **单页时页码按钮不渲染，但范围与选择器必须出现** —— 只有 1 页时用户更需要
  知道总数、更需要能调大每页条数。这是第一版实现漏掉的一点（返回空串导致整条消失）。

**形状一致性**：与 `.btn-soft` 同圆角（`--r-control`）与描边（`--line`）；
当前页是唯一使用实心强调色的分页元素，不与页面其它强调色元素争抢注意力。

**单页不渲染**：`pages <= 1` 时返回空串，调用方隐藏容器 —— 不要显示一个
只剩禁用按钮的空分页条。

**交互协议**：按钮带 `data-sp="<0 基页码>"`，调用方在自己的容器内绑定
`[data-sp]` 的 click。不再有 `data-pg` / `data-upg-pg` / `data-mp-pg` 这类
各自为政的私有协议。

### 2.5e 路径字段行（`.path-field-row`）

编辑客户端时的多路径输入控件。

- 每行一个 `<input>` + 一个 `×` 删除按钮
- 删除按钮：`padding: 4px 8px`，`--fs-2xs`，`ghost` 风格
- 底部一个「+ 添加路径」按钮

### 2.5f 洞察弹窗（`.insight-dialog`）

技能使用统计的弹窗容器。

- 最大宽 `min(1040px, 100%)`，内部两级滚动（工具条钉顶 + 结果区滚动）
- 不复用 `.modal` 的居中浮层样式，是独立的结构

### 2.5g 端点凭据（`.auth-mode-row` / `.cred-source-row` / `.cred-status` / `.auth-badge`，v0.31.4 之后）

**为什么有这套组件**：MCP 端点的 token 此前只有一种去向 —— 明文存进端点库，再抄进
每个客户端的 `Authorization` 头。用户把 token 存进 macOS 钥匙串之后，工具里**没有
任何地方能表达「凭据在钥匙串里」**，只能把明文再抄一遍，钥匙串等于白存。本组组件
就是「凭据从哪来」的选择器与状态反馈。

**四种认证方式**（`auth_mode`，取值必须与引擎 `core/auth_secret.py` 的 `AUTH_MODES`
一一对应 —— `tests/test_dashboard_auth_ui.py` 守住这条跨端一致性）：

| 值 | 界面标签 | 配置里写的东西 | 明文在哪 |
|---|---|---|---|
| `token` | 明文 Token | `Authorization: Bearer <token>` | 客户端配置文件里 |
| `env` | 环境变量 | `Bearer ${env:VAR}` / Codex `bearer_token_env_var` | 客户端进程环境 |
| `keychain` | 系统钥匙串 | 钥匙串**服务名** | macOS 登录钥匙串 / Linux Secret Service |
| `file` | 凭据文件 | 文件**路径** | 本机 0600 文件 |

**结构**（`.auth-mode-opt` 与 `.transport-opt` 同构：整行可点、`<input type=radio>` 在左）：

```
┌ 认证方式 ────────────────────────────────────────────┐
│ (•) 明文 Token   ( ) 环境变量   ( ) 系统钥匙串  ( ) 凭据文件 │
│  提示句随所选项切换（.note）                              │
└──────────────────────────────────────────────────────┘
（引用型额外展开 ↓）
┌ 来源 ────────────────────────────────────────────────┐
│ [ 服务名 / 变量名 / 路径                ] [检测来源]        │
│ (●) 可用   export hermes-unified-mcp=$(security ... -w)   │
└──────────────────────────────────────────────────────┘
```

- 选择器：`.auth-mode-row` + `.auth-mode-opt`，`role="radiogroup"` +
  `aria-labelledby` 指向字段标签。圆角/描边/选中态取值与 `.transport-opt` **逐值相同**
  （`var(--r-control)` / `var(--accent)` / `var(--accent-bg)`），因此不在 §2.9 另立数字
  —— 这里没有新的不可协商取值，§2.9 只登记「脱离组件默认档」的数字。
- 来源行：`.cred-source-row`（单行 `input` + 右侧动作），复用 `.token-row` 的拼合圆角约定。
- 结果胶囊：`.cred-status`，四态——默认（未检测）/ `.ok` 可用 / `.warn` 未配置 / `.err` 取不到。
  取值全为语义 token（`--ok-bg` / `--warn-bg` / `--err-bg` + 对应 `-border` / 前景色）。
- 表格徽标：`.auth-badge`，引用型加 `.is-ref` 用 `--accent` 强调「配置里没有明文」。

**编排规则**：

1. 选 `token` 时只显示 `.token-row` 明文输入（`autocomplete="off"`，带显示/隐藏切换）；
   选引用型时明文输入**隐藏**，来源行展开并清空上一模式残留值 —— 避免把变量名当服务名存进去。
2. 「检测来源」调 `--test-endpoint` 的凭据探测分支；「存入」调 `--set-auth-secret`
   （只对 `keychain` / `file` 出现，`env` 由用户自己的 shell 管理）。
3. **任何人、任何路径都不得把凭据值写进 DOM**：端点库快照已由后端脱敏，
   编辑按钮只带 `data-key`，凭据值只从 `password` 输入框读到后当次传给 CLI。
4. **客户端能否自己求值，必须如实告诉用户**。三条「能求值」的路径
   （`mcp_fixer_render.reference_is_evaluated`）：

   | 路径 | 说明 |
   |---|---|
   | `token` | 写的就是明文，天然可用 |
   | Codex（TOML） | 引用 `bearer_token_env_var`，客户端自己解析 |
   | 客户端声明 `mcp_root_env_style` | 我们把真值写进配置根的 env 块，客户端启动时注入自身环境 |

   `mcp_root_env_style` 取值为**真实键名**（`env`：Claude Code / Cursor /
   WorkBuddy / VS Code / OpenCode；`process_envs`：Goose），不做二次映射。
   未声明该字段的客户端（如 DSH cordis、Reasonix）写的是占位符，修复结果不复用
   「updated and verified」，而是明确写出「需注入环境变量 X」；界面同样不得用
   「已连接」表达一个只写了占位符的端点。
5. **变量名必须合法且稳定**：`${env.X}` 里的 X 只能是 `[A-Za-z_][A-Za-z0-9_]*`。
   钥匙串服务名常含连字符、文件路径必含斜杠，二者都不能直接当变量名。因此引用型
   统一使用**由端点名派生**的名字（`hermes-home` → `HERMES_MCP_TOKEN`），保证同一
   端点在所有客户端里同名 —— 用户注入一次即可。
4. 设置页的状态表**默认不读凭据内容**（读钥匙串会弹系统授权，GUI 子进程里没人点
   「允许」→ 实测 10 秒超时后误报失败）。「检测」按钮是用户主动动作，才加
   `--check-credential` 真读一次。

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

#### 2.6b 页面级刷新入口（`.page-head` / `.page-actions`）

**每个数据页都必须在页头提供一个「重新拉取」按钮**（`.page-actions` 内，
`btn-soft` 变体）。界面数据来自打开 App 时拉取的快照，不刷新就会一直显示
缓存 —— 实测事故：端点 key 改名后 MCP 页仍显示旧条目名，看起来像「配置重复」，
实际是页面没重新拉数据。用户会先怀疑「工具是不是写重复了」，排查成本很高。

| 页面 | 按钮 | 动作 |
|---|---|---|
| 概览 | 刷新审计 | `refresh` |
| IDE / Agent | 刷新审计 | `refresh-audit` |
| **MCP** | **刷新 MCP** | **`refresh-mcp`** |
| 变更详情 | 运行快照对比 | `run-snapshot` |
| DSH 插件 | 重新读取 | `refresh-dsh` |

统一走 `refreshWithBtn(btn)`：禁用按钮 → 显示「刷新中…」→ 重新拉取快照 →
toast 反馈成功/失败。

**唯一例外是「设置」页**：它的控件本身就是即时生效的写操作（保存即落盘），
没有需要重新拉取的整体视图。这个例外写进 `tests/test_gui_dashboard_structure.py`
的白名单里显式排除，**不是放宽到「任意页都可以不提供」** —— 新增数据页时
若忘记加刷新入口，该测试会点名报错。

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
- **四格统计与产品能力同源**（v0.39.8）：`IDE/Agent · MCP · Skill · DSH 插件`。
  第四格原本是 **Hook**，但 Hook 功能已于 v0.33.0 整体下线（CLI / GUI / 配置 / 代码
  全删），那一格永远读到 0、恒显灰色，用户会以为「Hook 还在，只是没配」。
  改为 DSH 插件数——与本工具实际提供的「DSH 插件」页同源。
  数据来自 `_snapshot_totals()` 的 `dsh` 字段（`--snapshot` 的 `totals`）；
  扫描入口必须传 `None` 让 `dsh_plugins.scan()` 自己解析默认根目录，
  传 `"~/.dsh"` 字面量会以未展开路径找 profiles，结果恒为 0（实测踩过）。

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
| `.pagination .pg-num` | `min-width` | `32px` |
| `.path-field-row button` | `padding` | `var(--sp-1) var(--sp-3)` |
| `.chg-btn` | `min-height` | `32px` |
| `.insight-dialog` | `width` | `min(1040px, 100%)` |
| `.ad-modal` | `--modal-w` | `min(880px, 94vw)` |
| `.agent-card .ac-path-row` / `.agent-card .ac-meta-row` | `grid-template-columns` | `58px minmax(0, 1fr)` |

**触达目标（弹层内动作按钮）**：`.cfm-card .actions button`、`.modal-form .form-actions button`、
`.sheet-actions .btn-soft` 与 `.chg-btn` 必须显式声明 `min-height: 32px`
（分页按钮按 2.5d 刻意更紧凑，不在此列）。

### 2.10 设置页（`.settings-tab` / `.settings-card`）

设置页用左侧分段 tab（`.settings-tab`）+ 右侧卡片分组（`.settings-card`）。
**四个 tab 与各自的卡片归属**（新增设置项必须落到下表的某一 tab，不要新开 tab）：

| tab | 卡片 |
|---|---|
| 通用 `appearance` | 外观（主题 / 缩放）、**后台巡检（定时检查）**、Skills 统一目录、**配置导入 / 导出**（v0.30.0）、关于 |
| Skill `general` | 技能使用统计（自动统计间隔）、**市场源**（默认 skills.sh 可删改 + 自定义远端源，v0.31.0：`#market-sources-card`，源行 + 添加表单 + **登记残留清理**（v0.37.1，`data-action="prune-skill-lock"`），读写经 CLI）、**GitHub API Token**（v0.31.0：`#github-token-card`，状态行脱敏 + password 输入 + 保存/清除，读写经 CLI）、**技能备份**（v0.37.6：`#skill-backups-card`，只读统计 + 清理按钮，读写经 CLI） |
| 通用 `general`（WebDAV，v0.31.1） | **远程同步**（`#webdav-sync-card`，规划中）：远端 URL + 凭据状态行（脱敏）、推/拉按钮（写操作需确认）、同步范围说明。同步范围固定为个人配置层（`local_overrides` / `market_sources` / `discovered_tools` / `skill_versions`），**凭据与技能包本体永不同步** |
| IDE / Agent `agents` | IDE / Agent 默认路径；**卡片/列表上的能力摘要**（Skills / MCP 两行，无需点开详情） |
| MCP `mcp` | **活动端点**（下拉切换）、**自动发现**（开关 + 扫描路径只读）、MCP 端点库、**MCP 端点凭据**（v0.31.4 之后：`#endpoint-cred-card`，模式 / 来源 / 状态表 + 检测 / 存入，读写经 CLI） |

**后台巡检（定时检查）**：开关 + 间隔（5 / 15 / 30 / 60 / 120 分钟）。
取值**不在 localStorage**，而是写进 `config.yaml` 的 `settings` 段
（`patrol_enabled` / `patrol_interval_minutes`）—— 因为 Rust 托盘的「后台巡检」
勾选项读同一份值，两处必须同源，否则托盘显示"已开"而实际没跑。
读写一律经 CLI `--get-setting` / `--set-setting`（后者带备份 → 原子写 → 校验 → 回滚），
GUI 不直接改配置文件。间隔由 CLI 钳到 ≥5 分钟，界面需回读落盘值而不是假定已生效。

**MCP tab（`mcp`）**：三张卡片（2026-10-15 补齐 PRD §10 #1）。

1. **活动端点**：`<select>` 下拉，列出 `settings.endpoints` 全部 key。
   切换后弹确认框（影响所有客户端），确认后经 CLI `--set-active-profile <key>` 写 overlay。
   空值 = 清除活动端点。
2. **自动发现**：开关（`.seg-btn`）+ 扫描路径只读展示（`<code class="mono">` 每行一条）。
   切换后经 CLI `--set-auto-discover enabled=<true|false>` 写 overlay。
   扫描路径与排除清单在 `config.yaml` 的 `auto_discover` 段，不经 GUI 编辑。
3. **MCP 端点库**：端点 CRUD（增删改）。表格列为
   「端点 key / name / 地址·命令 / transport / **认证** / 操作」。
   「认证」列只显示**来源元信息**（`token` / `env:VAR` / `keychain:服务名` / `file:路径`，
   未配置时追加 `· 未配置`），**不回显任何凭据值**；编辑按钮只携带 `data-key`。
4. **MCP 端点凭据**（`#endpoint-cred-card`，v0.31.4 之后）：见 §2.5g。

> 为什么活动端点排在端点库之前："选哪个端点活动"是比"管理端点库"更上层的操作。
> 两条新 CLI 命令走 overlay 路径（与 `--set-setting` 同模式），早返回不跑审计，
> 均在 Rust `run_cli` 白名单内（不是重定向命令，不进 `DENIED_FLAG_PREFIXES`）。

**配置导入 / 导出卡片**（v0.30.0 #3，`#cfg-port-card`，通用 tab，排在后台巡检与
关于之间）：换机 / 分享的配置迁移入口。结构：

```
┌ settings-card#cfg-port-card ────────────────────────────────┐
│ H4: 配置导入 / 导出                                          │
│ row: 导出配置 | [input#cfg-export-path] [ghost sm 导出]      │
│ row: 导入配置 | [input#cfg-import-path] [ghost sm 导入]      │
│ note: 单 JSON · 密钥脱敏 · 合并语义 · icloud 别名说明         │
└─────────────────────────────────────────────────────────────┘
```

- **读写一律经 CLI**（`--export-config` / `--import-config`，Rust 白名单内），
  GUI 不直接碰配置文件——与后台巡检 / 活动端点同一纪律。
- 行内控件容器用 inline `display:flex; gap:var(--gap-2); flex-wrap:wrap`
  （**不写 `width:100%`**，v0.29.1 裁剪教训）；输入框取全局
  `input[type="text"]` 样式（`flex:1; min-width:160px`）。
- 交互：路径为空 → 就地 `toast`（不弹任务模态）；导出走 `runTaskModal`
  （无刷新）；导入先 `confirmModal` 说明合并语义（导入值优先、不删除本地
  已有项、脱敏密钥保留本地值、自动备份），确认后 `runTaskModal` +
  `refreshBlocks(["settings","agents"])`。
- 为什么放通用 tab：导入/导出的是**整份配置**（跨 Skill / MCP 两域），
  属通用配置级操作，与「关于」同为全局卡片；不放 MCP tab（那只是端点域）。

> 设置项的取值来源必须与「谁是唯一事实来源」一致：偏好类（主题/缩放/统计间隔）用
> localStorage，跨进程共享类（巡检开关）用 config.yaml 并经 CLI。

**市场源卡片**（`#market-sources-card`，v0.31.0 起；v0.37.3 重排）：

```
┌ settings-card#market-sources-card ────────────────────────────┐
│ H4: 市场源                                                     │
│ #market-sources-body                                           │
│   └ .rows：已配置源（每源一行）                                  │
│       k: 源名（skills.sh 社区技能库）                            │
│       v: [tag 类型] 启用/停用 [停用][删除]                       │
│          └ .market-source-url（仓库地址，单独一行、超长省略）     │
│   note: 当前为默认源（未自定义配置）                              │
│   └ .settings-group「添加源」                                    │
│       源 ID / 名称 / 类型 / 仓库 URL（控件撑满值列）              │
│       form-actions: [添加源]                                     │
│ note: 默认源可删可改、支持 GitHub 仓库源、配置存 data/…           │
│ └ .settings-group「登记表维护」                                  │
│     note: 残留成因 + 只删磁盘无目录 + 改前备份                    │
│     form-actions: [清理登记残留]                                 │
└───────────────────────────────────────────────────────────────┘
```

**三条结构规则**（v0.37.3，用户截图「排版和视觉有问题」后重排）：

1. **源行必须包在 `.rows` 里**。`.settings-card .rows .row` 才给出行内边距与
   hairline 分隔线；直接把 `.row` 拼进 body 会让整块看起来像散落的表单，
   列表与新增表单之间没有视觉边界。
2. **新增表单独立成组**（`.settings-group` + 自己的 `h4`）。此前源行与添加字段
   连排，用户看不出「下面是新增入口」；分组标题用与 `.agent-settings-section`
   同一套语言（上边线 + mono 大写小标题），不另造视觉。
3. **同一卡片内动作按钮统一 `.btn-soft`**。此前源行与「添加源」用 `.ghost.sm`
   （透明无边框、26px 高），与卡片里的「清理登记残留」不同族，读起来像文字
   链接而不是可点操作；`ghost` 只保留给真正的纯文字动作（如表格行内 kebab）。

**表单字段宽度**：`.settings-card .row .v > input[type="text"]` 与
`> select` 一律 `width: 100%`，由值列决定宽度，不再给每个字段内联写
`min-width`（此前 8rem / 16rem 两种宽度并存，四行参差）。仓库地址用
`.market-source-url` 单独占一行（`flex: 1 0 100%`），避免长 URL 把操作按钮挤走。

**登记残留清理**（v0.37.1，`#market-sources-card` 内的 `data-action="prune-skill-lock"`）：
技能目录被手工删除后，`~/.agents/.skill-lock.json` 里的来源登记不会自己消失。
这些「登记残留」没有内容可升级，却会让「检查更新」的结果条数比技能列表可见行数
多出若干条，也让人误以为库里还装着它们。

此前弹框写「可在技能行删除」是错的：`--delete-skill` 走 `soft_delete_skill()`，
第一句就要求目录存在；而技能表按磁盘目录渲染，残留行根本不出现。所以必须由
登记表自己提供出口，本控件就是唯一入口。

```
┌ settings-card#market-sources-card ────────────────────────────┐
│ H4: 市场源                                                     │
│ #market-sources-body（源行，异步加载）                          │
│ note: 默认源 skills.sh 可删可改；支持 GitHub 仓库源              │
│ form-actions: [btn-soft 清理登记残留]                           │
│ note: 残留成因 + 只删磁盘无目录的条目 + 改前备份                  │
└───────────────────────────────────────────────────────────────┘
```

- **交互**：点击先跑 `--prune-skill-lock --dry-run --format json`，取 `removed` /
  `kept` / `names`；无残留就地 `modalNotice` 告知（不弹一个空的确认框）；有残留则
  `confirmModal` 列出条数与前 8 个示例，确认后 `runTaskModal` 执行并展示备份路径。
- **为什么先 dry-run 再确认**：删除条数必须在动手前可见——「点完才知道删了 116 条」
  不可接受；dry-run 顺带给出「保留多少条有效登记」，让用户能判断比例是否正常。
- **安全边界**（由 `core/skill_market.prune_missing_registrations()` 保证，
  `tests/test_skill_lock_prune.py` 逐条守住）：只删「登记有、磁盘无目录」的条目；
  `dismissed` / `lastSelectedAgents` 等非 `skills` 字段原样保留；改前把整份 lock
  备份为 `<原名>.bak-<时间戳>`，备份失败即中止；dry-run 不落盘、也不生成备份。
- **为什么放在市场源卡片**：残留登记是「市场安装」的副产物（`sourceType=github`），
  与「源」同一域；单独开一张卡会让人以为它和源无关。

**Git 源自动接管**（v0.37.2，`#git-sources-card` 的加载路径，无新增按钮）：

2026-11-09 用户截图反馈：「既然已经发现了，为什么不可以自动扫描或者自动获取？
我的目录和统一默认的目录是一致的，而且页面上的 skill 也扫描到了 170 多个。」
问题成立：统一目录早就在 `config.yaml` 里配好、磁盘上也确实是 git 工作区
（有远端、有分支），但 `data/git_sources.yaml` 是空的——于是同一张卡片里
「统一技能目录」显示已设置、「Git 技能源」却说「尚未登记」，四个同步按钮全在
空转。用户无法判断到底配没配好，只能把同一个路径手输一遍。

**规则：登记表为空且统一目录本身是 git 工作区时，加载即自动接管为主源。**

```
┌ settings-card#git-sources-card ──────────────────────────────┐
│ H4: 统一技能目录与 Git 源                                     │
│ row: 统一技能目录 | <code>~/.skills-manager/skills</code>      │
│ note: 已自动接管统一技能目录为 Git 源：<path>（分支 master）    │
│       … 检查更新 / 拉取 / 提交 / 推送现在可用；不需要点「移除」 │
│ #git-sources-body：源行（主源标签 / 状态 / 设为主源 / 移除）    │
│ form-actions: [登记本地目录][检查更新][拉取][提交改动][推送]     │
└──────────────────────────────────────────────────────────────┘
```

- **触发条件**：`items.length === 0 && !adoptTried`。已有任何登记就永不覆盖，
  每个会话只尝试一次（`GIT_SOURCES.adoptTried` 防重入）。
- **后端判据**（`core/git_sources.adopt_unified_dir()`）：登记表非空 →
  `already-configured`；目录不存在或缺 `.git` → `not-git-repo`（附原因）；
  成功则写入 `primary: true` 的单条登记（原子写 + 备份）。
- **失败不静默**：`not-git-repo` 的原因写进空态文案（「未登记 Git 技能源：
  统一目录不是 Git 工作区…」），而不是退化成笼统的「尚未登记」——后者会让人
  以为功能没做。
- **为什么可以自动写**：这不是替用户做决定，而是把一个**已经成立的事实**
  （目录已配置、技能已在用、目录就是 git 工作区）记进登记表；它不改变任何
  客户端指向、不动仓库内容，且可随时「移除」撤销。要求用户手输同一个路径，
  等于让他证明一个已知事实。
- **为什么不需要再点「设为主源」**：接管的目标就是统一目录本身，直接写
  `primary: true`；`unified_dir_from_sources()` 随即能派生同一路径，主源语义闭环。
- **可观测**：接管成功后卡片顶部显示一行 `note`（路径 + 分支），并说明可移除；
  刷新页面后该提示消失，但源行带「主源 · 统一目录」标签，状态仍然自解释。

**技能备份卡片**（`#skill-backups-card`，v0.37.6，Skill tab，排在市场源之后）：

```
┌ settings-card#skill-backups-card ─────────────────────────────┐
│ H4: 技能备份                                                   │
│ row: 备份总量 | N 个技能 · M 份备份 · X MB · [tag warn 可清理 K 份] │
│ form-actions: [btn-soft 清理备份]                              │
│ note: 升级前自动备份 · 内容相同不重复 · 每技能上限 10 份          │
└───────────────────────────────────────────────────────────────┘
```

- **数据来源**：`--skill-backup-stats`（只读，返回 `skills` / `snapshots` /
  `duplicates` / `bytes` / `keep`）。`duplicates` 就是「清理能删掉多少」。
- **交互**：点击先跑 `--prune-skill-backups --dry-run --format json`；无重复就地
  `modalNotice` 告知（不弹空确认框）；有则 `confirmModal` 列出条数、保留数与释放
  空间，确认后 `runTaskModal` 执行并刷新统计。
- **清理规则**（`core/skill_market_ops.prune_skill_backups()`）：内容指纹去重
  （同一内容只留时间戳最新的一份）+ 每技能保留最近 10 份**不同内容**。实测
  `find-skills` 攒了 327 份、其中 326 份字节完全一致——升级每次都无条件备份，
  纯占盘。备份前也比对内容，相同直接 `skipped`，从源头不再产生重复。
- **为什么放在设置页而不是 Skills 页**：这是**磁盘维护操作**，不是日常技能操作；
  Skills 页工具栏已有 6 个动作，再加会拥挤，且清理频率远低于升级。

---

### 2.11a 概览页统计卡口径（`.stat-card`，2026-11-04 定案）

概览页顶部六张 `.stat-card`。**每张卡的语义色只能表达「需要处理的问题」**，
不能用来表达「本机没有这个东西」——后者是正常状态。

| 卡 | 取值 | 语义色 | 含义 |
|---|---|---|---|
| 受管客户端 | `agents.length` | 中性（`accent` 强调） | 注册表收录总数，**含未安装** |
| 已安装 | `installed` | 中性 + `accent` | 有可执行 / App / 配置证据 |
| 仅发现配置 | `config_only` | `warn` | 只有配置文件、无程序（多为残留） |
| 未安装 | `none` | **中性** | 只在注册表中，不进 Skills / MCP 运行时列表 |
| 统一技能 | `skill_count` | 中性 | 统一技能目录下的技能数 |
| 主流已纳入 | `registered / total` | 中性 | 内置主流工具已进注册表的比例 |

**为什么「未安装」不用 `err` 红**（用户反馈：「概览说未安装 12，MCP 页却说 5 个
客户端，是不是矛盾？」）：两个数在数据上完全一致（17 = 5 安装 + 12 未安装，
MCP 页只渲染 `install_state !== "none"`）。问题在于红色在别处表示「要修的问题」，
与「本机没装」共用一个红，读者就会去找根本不存在的错误。

**规则**：会一起被读的相邻卡（受管客户端 / 未安装）**必须带 `tip` 说明口径**，
且 tip 要能自解释（出现「注册表」「未安装」这类词）。口径本身（受管 = 已装 +
仅配置 + 未安装）不得因文案调整而改变，`tests/test_dashboard_overview_stats.py`
同时守住颜色、tip 与数值口径三条。

### 2.11 概览页「全量检查」区（3 维度 + 端点，v0.30.0）

概览页的「全量检查」按钮（`data-action="endpoint-check"`）跑**与托盘后台
巡检同一条** `--snapshot` 命令（3 维度变更对比：IDE/Agent · MCP · Skill）
+ 端点库整体探活（`--endpoint-status` 无 `--profile`，合并视图过滤
null 软删除，**不绑定活动端点**）。两处同源：概览页显示「检测到变更」⇔
托盘红点（同一 `has_changes` 判据）。2026-10-22 用户反馈：「首页的检查应该
显示后台全量检查的内容，和状态栏的功能统一」+「不应该具体到某个具体的端点」。

结构（复用 `.tag` 语义色 + `.kv` 表，不新造视觉）：

```
┌ 全量检查（.panel 卡片）──────────────────────────────┐
│ .hd.fc-head：h3+hint（左）｜[重新全量检查 btn-soft]（右）│
│ [tag ok|warn] 全部稳定|检测到变更 [tag ok|err] 端点verdict│
│ .fc-grid（两列分组网格，窄屏 auto-fit 单列）：           │
│   ┌ 变更对比 · 3 维度 ┐  ┌ 端点连通性 ┐                 │
│   │ ● IDE/Agent  稳定 │  │ ● K8s-uat 连通 897ms │       │
│   │ ● MCP        稳定 │  │ ● hermes  连通 726ms  │       │
│   │ ● Skill      稳定 │  └──────────────┘               │
│   │ （有变更时行内展开 name: detail）                    │
│   └────────────┘                                        │
└─────────────────────────────────────────────────────────┘
```

**`#endpoint-status` 全量检查主体（v0.30.2 重设计登记）**：信息稀疏（每行
仅名称+一词状态）时表格形式感大于信息量，重构为**两列分组网格 + 状态点行**：

- `.fc-grid`：`repeat(auto-fit, minmax(240px, 1fr))` + `--gap-5`——3 维度
  （变更对比）与端点（连通性）各一列，窄屏自动单列回退。
- `.fc-row`：状态点行——`.dot.ok/.warn/.err`（语义色点，§2.5 状态覆盖语言）
  + `.fc-name`（名称，`--text` 500）+ `.fc-state`（状态词右对齐 `--muted`，
  `margin-left:auto`）；行底 `--line` 分隔（末行无）；行竖向 `--sp-3`。
  有变更/错误时 `.note` 明细 `flex-basis:100%` 行内展开。
- `.fc-group-title`：分组小标题，复用 kv-group 的 mono 大写语言
  （`--fs-2xs` + `--faint` + `.1em` 字距）。
- `.hd.fc-head`：卡片头两端对齐（标题+说明左、动作按钮右，page-head 同构）
  ——动作按钮收进卡片头，不再占底部一整行。
- 状态点行语义色：稳定/连通 `ok`（绿）、有变更 `warn`（黄）、不通/错误
  `err`（红）——与 `.tag` 语义色同源，但更轻（点 vs 徽标）。

**统一 UI 纪律（2026-10-22 用户反馈）**：变更明细**行内展开**在该维度行内
（`.note` 小字，每条 `name: detail`），**不设「变更详情」跳转链接**——
「直接在原有的内容中显示即可，不需要单独展示详情」。3 维度与端点合并
**同一张 kv 表**（同一 tbody），不拆两张表。

- verdict 三态：全部连通（ok 绿）/ 部分不通（err 红）/ 全部不通（err 红）；
  每端点行用 `.tag.ok` / `.tag.err`（有 CSS 定义，勿用幽灵类 endpoint-verdict）。
- 单端点错误以 `.note` 缩在该端点行内（不弹页面级 banner——banner 只留给
  **执行失败**，且新一轮检查开始时清除旧 banner）。
- 状态覆盖：执行失败（error JSON 无 state）→ 红色「检查执行失败」+ 详情；
  未检查 → 中性灰「尚未检查」。

原生身份治理面板：`.native-identity-card` 复用 card，区块底距 `--sp-5`；
`.native-fields` 使用响应式 grid（最小列宽 240px），列间距 `--gap-5`，标签间距 `--gap-3`。
指令 textarea 最小高度 150px；`.native-result` 最大高度 320px 并可滚动。
宿主、端点改变后清空旧计划与验收选择；应用修复须先预览，再确认；
认证与对话保持独立状态，只读配置检查不会自动显示通过。支持恢复历史验收。

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
| 尊重减少动效 | **所有** `animation` / `transition` 在 `@media (prefers-reduced-motion: reduce)` 里关闭；实现用通配兜底 `*, *::before, *::after { animation-duration:.01ms!important; transition-duration:.01ms!important }` + 具体选择器补偿 | 前庭敏感用户会因动效不适 |
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

### 2.3c-2b 路径覆盖（v0.39.0）

内置注册表里的 APP / CLI / CONFIG / SKILLS / MCP / RULES 全是**厂商默认值**。
本机装到别处、或厂商改了落盘位置时，此前没有任何修正入口（用户：「这个功能是否
缺失了？」——确实是缺失）。

**覆盖层**：`data/local_overrides.yaml` 的 `tool_paths` 段（该目录 gitignore，
机器本地路径不进版本库）：

```yaml
tool_paths:
  TRAE:
    config_paths: ["~/custom/mcp.json"]
    skills_path: "~/custom/skills"
```

| 可覆盖字段 | 注册表里的键 |
|---|---|
| `app_bundles` | `install.app_bundles` |
| `commands` | `install.commands` |
| `config_paths` | `install.config_paths` |
| `skills_path` | `skills_paths` |
| `mcp_config_path` | `config_path` |
| `rules_paths` | `rules_paths` |

**只覆盖路径类字段**：工具名、类型、别名一律不动——否则覆盖层会变成第二个
注册表，两处数据迟早打架。

**路径字段一律带「浏览」按钮**（v0.39.2）：调用 Tauri dialog 插件的
`window.__TAURI__.dialog.open({ directory })`——文件字段传 `false`、目录字段
（Skills 目录 / 扫描目录）传 `true`。用户明确要求「可以通过 GUI 去选择电脑上的
文件，而不是只能通过输入路径的方式」。浏览器预览态没有 `__TAURI__`，`pickPath`
返回 null、输入框保持原值，不报错。

**编辑弹框的字段组织**（v0.39.3）：每个路径组 = 标题（`.agent-settings-section h4`）
+ 一句说明（`.agent-settings-hint`，讲清「这个字段填什么」——比塞进 placeholder 稳，
placeholder 一输入就消失）+ 输入行（输入框 + 浏览 + 移除）+ 轻量「+ 添加路径」
（`.path-field-add`，文字按钮，不与右侧浏览/删除抢视觉）。**空数组也渲染一行空输入**：
此前只剩一个「+ 添加路径」，整块看起来像漏了字段。

**三个入口**：

1. 详情弹框的「编辑路径」按钮（六个字段各一个 textarea，每行一个值，清空 = 恢复默认）；
2. `--set-tool-path TOOL FIELD VALUE` / `--reset-tool-path TOOL [FIELD]`；
3. `--list-tool-paths`（查看当前覆盖）。

**合并点**：`register_mainstream_tools()` 内部 `apply_overrides(copy.deepcopy(...))`。
深拷贝是硬要求——调用方（快照构建、详情弹框）会就地读字段，共享引用迟早被改脏。
