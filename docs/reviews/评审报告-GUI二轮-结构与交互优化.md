# GUI 二轮评审：结构与交互优化

> 触发：用户反馈——"只是结构参照，不是所有的颜色都参照；交互方式需要参照；目前还不够，因为具体项目不完全一样，请对具体内容重新评审和优化设计"。
>
> 依据：`ui-ux-pro-max`（UX 规范）、`design-taste-frontend` 评审方法论（仅取评审纪律与反模板准则，其 §13 明确排除 dashboard 场景）、参照项目 `xingkongliang/skills-manager` 的**结构与交互模式**（非配色）。

## 一、评审结论

| 维度 | 上一轮问题 | 本轮裁定 |
|------|-----------|----------|
| 配色 | 将参照项目的 emerald + zinc 配色整体照搬 | **纠正**：保留 zinc 灰阶作为纯结构骨架（中性、跨产品通用），但强调色回归本产品 Brand Blue 自有身份；语义色（绿/黄/红）属审计通用语义，保留 |
| 交互 | 仅有主题切换、少数弹窗，离参照项目的交互密度差距明显 | **补齐**：命令面板 / 右侧详情抽屉 / 开关 / 溢出菜单 / toast / 分段筛选 / 视图切换 / 折叠分组 / 披露 / 空态 CTA |

结论：结构可参照，颜色必须自持；交互要"对位参照但不照抄业务对象"——参照项目是技能市场（`ToggleSwitch`/`DetailSheet`/`CommandPalette`/`CardActionMenu`/`InstallToast`），我方的业务对象是**受管客户端 / 端点 / 技能挂载状态**，因此只借鉴其组件形态，绑定到我方 CLI 的真实指令（例如开关直接落到 `--enable-skill/--disable-skill`）。

## 二、落地清单（全部完成）

### 颜色（品牌自觉）
- 浅色强调色 `#2563EB`（hover `#1D4ED8`），深色强调色 `#60A5FA`（hover `#3B82F6`，primary 按钮深底文字 `#0A1220` 保证对比）。
- 语义状态三色（绿 `ok`/黄 `warn`/红 `err`）不变，仅用于审计结论，不参与品牌识别。

### 交互组件（结构参照 skills-manager，行为接入我方 CLI）
1. **⌘K 命令面板**：分组（页面/操作/技能/主题）+ 过滤 + ↑↓/Enter 导航 + `requestAnimationFrame` 等价滚动定位；Esc 关闭。
2. **技能详情改为右侧 Sheet**（原为居中弹窗）：标题 + 描述 + 源路径 + 每客户端启用状态；右上角关闭 X。
3. **ToggleSwitch（34×20，`role=switch`）**：逐客户端启停，绑定 `--enable-skill <skill> --client <name>` / `--disable-skill ...`（此前 GUI 未暴露该 CLI 能力），loading 态旋钮转 spinner。
4. **Agent 卡片 kebab 溢出菜单**：查看详情 / 重新扫描 / 移出管理（danger，二次确认后 `--remove-client`）。
5. **底部 Toast 栈**：进度 spinner → 成功/失败，接入重扫、合并预览、启停技能、移出客户端等异步流。
6. **技能页分段筛选**：全部/已启用/部分启用/未启用；**网格/列表视图切换**（localStorage 记忆）。
7. **侧栏分组可折叠**：chevron + 折叠态记忆（localStorage）。
8. **添加面板披露**：主流工具默认展示前 12 项 +「更多(N)」展开。
9. **空态 CTA**：技能为空时提供「一键合并技能」入口。
10. **全局 Esc 逐级关闭**：面板 → 溢出菜单 → 抽屉/弹窗；⌘K 开关。

### 可见性/可访问性（ui-ux-pro-max 核心项）
- 图标一律内联 SVG，无 emoji 图标；可点击卡片 `cursor:pointer`；focus ring 用 accent；`prefers-reduced-motion` 覆盖所有新动画。

## 三、验证

- `node --check`：JS 语法通过。
- 真机浏览器截图核对：浅/深双主题、技能工具栏（分段+视图）、列表视图、右侧 Sheet（开关 ON/OFF/禁用三态）、⌘K 命令面板、Agent kebab 菜单，均渲染正确。
- 合成 `metaKey+'k'` keydown 触发 `PALETTE.open === true`，证明 ⌘K 键路正确（浏览器自动化工具的组合键派发不可靠，非代码缺陷）。
- `python3 -m pytest tests/ -q`：320 passed, 2 subtests。
- `./scripts/verify_gui_consistency.sh`：GUI/CLI 审计结论一致（2 profiles）。

## 四、边界说明

- 未触达我方 CLI 暂未开放的领域（如 `--set-skill-state` 占位、自动发现路径编辑、端点 transport 选择），未强行造交互。
- `--enable-skill/--disable-skill` 对 `root` 链接形态客户端可能降级（无 `--strict-skill-state`），失败以 toast 反馈，不回写错误状态。
- 视觉层改动与 `verify_gui_consistency.sh`（Python 侧快照语义）正交，不触碰数据契约（`--management --format json` 字段、`data-action`/`data-goto` 委托）。