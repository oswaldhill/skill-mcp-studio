# tools/

开发期验证工具。都不参与运行时，也不需要构建。

## `shot_dialog.swift`

离屏渲染 `gui/dashboard.html` 并回答**"这个元素在屏幕上真正可见吗"**。

```bash
swift tools/shot_dialog.swift <input.html> <output.png> [选项]

  --wait <秒>        加载完成后等待多久再测量/截图（默认 3）
  --target <id>      要测量的元素 id，可重复；不给则自动测页面里所有 <dialog>
  --timeout <秒>     总超时（默认 60）
  --size <宽>x<高>   视口尺寸（默认 1280x860）
```

兼容环境变量 `SHOT_WAIT` / `SHOT_TARGET`；命令行给了同名选项就整体接管，不叠加。
未识别的参数直接报错退出（`EX_USAGE`=64），不静默忽略。

**为什么要它**：DOM 里存在 ≠ 屏幕上可见。本项目两个真实缺陷都属于这类——
确认框被 top-layer 面板盖住（"点了没反应、只闪一下"），以及挂在
`<section class="hidden">` 内的 `<dialog>` 即便 `showModal()` 成功
（`open=true`、`:modal` 匹配）也拿不到尺寸（`rect=0x0`）。
只看 `innerHTML` 或 `open` 属性都会误判，所以输出里同时给
`visible`（尺寸是否非零）与 `topIsSelf`（中心点上是不是它自己）。

**两个使用要点**：
1. **先切到目标所在的页面**。挂在隐藏 `<section>` 里的 dialog，祖先
   `display:none` 会让它即使进了 top layer 也塌成 `0x0`；探针里应先
   `document.querySelector('.nav-item[data-page="skills"]').click()`。
2. **等待时间要覆盖 App 启动流程**。启动流会重置视图并覆盖 `document.title`，
   早于它执行的探针会被冲掉。

`MEASURE:` 行是测量结果，`SNAP ok` 表示截图已写出。

## `dash_crash_harness.js`

在桩 DOM 下完整执行 dashboard 的脚本块，定位运行时抛错的位置。

```bash
node tools/dash_crash_harness.js gui/dashboard.html /tmp/out.txt
```

动机：`node --check` 只查语法不查引用。曾出现语法全过、运行期抛错，
导致点击委托之后的按钮集体失效的情况。退出码 0 表示链路完整走通。
