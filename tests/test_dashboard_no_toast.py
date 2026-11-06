"""界面反馈一律用弹框，不得用 toast（2026-11-05 用户要求的硬规则）。

## 为什么需要这条规则

规范此前只定义了「弹框长什么样」（DESIGN.md §2.5b），没定义「什么时候该弹框」。
于是 86 处反馈全部走 ``showToast()`` —— 自动消失的浮层。用户的原话是
「对于信息的展示，有没有要求必须是弹框？如果不是，请增加要求」。

自动消失对**需要读完再判断**的信息是有害的：检查汇总、错误原因几秒后就没，
用户切回窗口时已错过，也无法复制回看。

## 判据（为什么这样切）

- **操作结果**（成功 / 失败 / 警告 / 汇总）必须弹框 —— 这是本次要改的主体；
- **过程反馈**（「正在执行…」）允许行内状态 —— 用户明确要求保留，否则每个操作
  都会先弹一个框、完成后再弹一个，交互反而更差；
- **页面级横幅**（CLI 未装这类持续状态）不属于一次性消息，不在此列。

所以在源码层面，``showToast`` 只允许出现在两类位置：过程反馈，以及
``showToast`` 自身的定义/兼容层。其余任何新增调用都会被本测试点名。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests._gui_source import page_source  # noqa: E402


def _src() -> str:
    return page_source()


def _html() -> str:
    from tests._gui_source import page_html

    return page_html()


def _call_sites(src: str):
    """返回 [(行号, 行文本)] 形式的 showToast 调用点。"""
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        if "showToast(" in line and "function showToast" not in line:
            out.append((i, line.strip()))
    return out


def _strip_js_comments(code: str) -> str:
    """剥掉 JS 的行注释与块注释（保留字符串内的内容不动，够用即可）。

    为什么要剥：断言「不得出现 setInterval」时要排除解释历史的注释，
    否则把历史原因写清楚反而会让测试失败。
    """
    code = re.sub(r"/\*[\s\S]*?\*/", "", code)
    return re.sub(r"(?m)//.*$", "", code)



class NoToastForMessagesTest(unittest.TestCase):
    def test_no_showtoast_calls_remain(self):
        offenders = [
            f"line {i}: {line[:110]}"
            for i, line in _call_sites(_src())
        ]
        self.assertEqual(
            offenders[:10],
            [],
            "仍有 toast 调用。信息展示/询问必须走弹框（modalNotice）。\n"
            "若确实是「正在执行…」的过程反馈，请改用行内状态而不是 toast：\n"
            + "\n".join(offenders[:10]),
        )

    def test_modal_notice_entry_exists(self):
        src = _src()
        m = re.search(r"function modalNotice\(([^)]*)\)", src)
        self.assertIsNotNone(m, "缺少统一的弹框入口 modalNotice(kind, title, message)")
        self.assertIn("mountModal", src, "弹框必须走 mountModal 才能进入 top layer")

    def test_modal_notice_is_not_a_toast_in_disguise(self):
        """modalNotice 必须真的弹框，不能内部又转调 toast。"""
        src = _src()
        i = src.find("function modalNotice(")
        self.assertGreater(i, 0)
        body = src[i:i + 1200]
        self.assertNotIn(
            "showToast", body,
            "modalNotice 内部仍调用 toast —— 那就是把吐司改了个名字",
        )
        self.assertIn("mountModal", body)


class LoadingStateTest(unittest.TestCase):
    """「正在执行…」必须是行内状态，且必须能被清掉。

    只检查「没用 toast」不够：把加载提示删掉、或者只显示不关闭，都会让用户
    以为操作卡住。因此要求每个启动加载的地方都能观察到结束。
    """

    def test_loading_uses_inline_state_not_toast(self):
        src = _src()
        self.assertNotRegex(
            src,
            r'showToast\(\s*"info"',
            "仍有用 toast 显示「正在…」的过程提示",
        )


class SpecDocumentTest(unittest.TestCase):
    def test_spec_requires_modal_for_messages(self):
        spec = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("一律用弹框", spec)
        self.assertIn("modalNotice", spec)


if __name__ == "__main__":
    unittest.main()


class ProgressModalTest(unittest.TestCase):
    """一次操作 = 一个弹框：过程在框内累积，结束后原地变结果（2026-11-05 用户要求）。

    用户原话：「可以在弹框中进行进度的展示，每个操作都作为进度的一部分，
    只有完整结束之后再关闭弹框」。

    上一版把每次操作都做成了独立弹框（67 处 modalNotice），于是：
    - 批量操作会连弹 N 个框，必须逐个关掉；
    - 弹框本身就是「结果」，过程仍然看不见。

    判据：
    1. 存在进度弹框入口（progressModal*），能「开始 / 追加一条 / 结束」；
    2. 结束时**复用同一个弹框**转成结果态，不 close 再新开（否则又是一次闪烁）；
    3. 批量循环里不得逐条弹结果框 —— 循环内只追加进度项。
    """

    def test_progress_modal_api_exists(self):
        src = _src()
        for fn in ("function progressBegin", "function progressStep", "function progressFinish"):
            self.assertIn(fn, src, f"缺少进度弹框接口：{fn}")

    def test_finish_reuses_the_same_modal(self):
        """结束必须原地转态，不能先关掉再重开一个新框。

        注意 closeModal 本身是允许的 —— 它是「关掉」按钮的点击处理（用户主动关闭，
        正是「完整结束之后再关闭」那条要求）。要禁的是**执行路径里**先关后开：
        那会闪两下，也会让过程框提前消失。
        """
        src = _src()
        i = src.find("function progressFinish")
        self.assertGreater(i, 0)
        body = src[i:src.find("\nfunction ", i + 10)]
        self.assertEqual(
            body.count("closeModal"), 1,
            "progressFinish 出现多处 closeModal —— 流程里先关再开会闪两下",
        )
        self.assertIn("btn.onclick = closeModal", body,
                      "唯一的 closeModal 必须是「关掉」按钮的点击处理")
        self.assertIn("data-progress-replace", body,
                      "结束时没有原地替换内容（应复用同一弹框）")


    def test_batch_loops_append_steps_not_modals(self):
        """批量循环内只追加进度项，不逐条弹结果框。"""
        src = _src()
        # 找批量开关客户端的那段循环
        i = src.find("async function batchToggleMts")
        self.assertGreater(i, 0, "找不到 batchToggleMts")
        body = src[i:i + 2200]
        self.assertIn("progressStep", body, "批量操作没有把每条计入进度")
        self.assertEqual(
            body.count('modalNotice("ok"'), 0,
            "批量循环内仍在逐条弹成功框，用户要一个个关掉",
        )


class RealProgressStepsTest(unittest.TestCase):
    """进度必须是**真实逐条**的，不能是「按时间点亮」的假阶段（2026-11-06 用户要求）。

    用户原话：「我希望逐条都改成真实逐条进度」。

    此前 runTaskModal 的 stages 数组是一串写死的文案，setInterval 每 800ms 点亮
    一条，与实际执行毫无关系：命令早就跑完了，进度条还在慢慢爬；命令失败时，
    它却已经把「校验回写」点亮成绿色。那不是进度，是动画。

    判据：
    1. runTaskModal 不再用定时器假装推进；
    2. 它把「报告一步」的回调交给调用方，由调用方在**真实动作完成处**调用；
    3. 批量场景（一键修复所有）把每个客户端作为独立一步。
    """

    def test_task_modal_has_no_fake_stage_timer(self):
        # 只看**代码**（剥掉注释）：注释里会提到 setInterval 解释历史，那不算违规。
        src = _src()
        i = src.find("async function runTaskModal")
        self.assertGreater(i, 0)
        body = _strip_js_comments(src[i:src.find("\nfunction ", i + 10)])
        self.assertNotIn(
            "setInterval", body,
            "runTaskModal 仍在用定时器「假装」推进进度 —— 它与真实执行无关",
        )

    def test_task_modal_accepts_a_step_reporter(self):
        src = _src()
        i = src.find("async function runTaskModal")
        body = _strip_js_comments(src[i:src.find("\nfunction ", i + 10)])
        # 形如 `await run(progressStep)`：把报告入口交给调用方
        self.assertRegex(
            body, r"run\(\s*progressStep\s*\)",
            "runTaskModal 没有把「报告一步」的入口交给调用方",
        )

    def test_fix_all_reports_each_client_as_a_step(self):
        """一键修复所有：每个客户端 = 一行真实进度。"""
        src = _src()
        i = src.find("async function fixAllSkillsMcp")
        self.assertGreater(i, 0)
        body = src[i:src.find("\nasync function ", i + 10)]
        # 它通过 runTaskModal 拿到的 `step` 回调逐条上报；每个「客户端 × 维度」一行
        steps = body.count("step(`${name}")
        self.assertGreaterEqual(
            steps, 2,
            f"一键修复应至少为 Skills / MCP 两个维度各报步（实际 {steps} 处）",
        )


class UpdateCheckPersistenceTest(unittest.TestCase):
    """更新检查结果必须持久化，且未检查时明确说「未检查」（2026-11-06 用户反馈）。

    现象：技能表「远端」整列显示 `-`，用户问「为什么又没有信息了」。
    实查后端数据完整（249 条里 0 条缺 remote_time），问题在前端：
    `SKILL_UPDATES` 只存在内存里（`let SKILL_UPDATES = null`），App 一重启就
    回到 null，整列变 `-`。而 `-` 既不说明「没查过」也不说明「查了没结果」，
    用户只能靠记忆回想。

    判据：
    1. 检查结果写入本地存储，启动时回填；
    2. 未检查时显示「未检查」而不是中性的 `-`；
    3. 回填要带时间戳，让用户知道这份结果是哪一轮的。
    """

    def test_results_are_persisted_and_restored(self):
        src = _src()
        self.assertIn("SKILL_UPDATES_STORE", src,
                      "检查结果没有持久化 key，重启后会全部丢失")
        # 写入
        self.assertRegex(src, r"saveStore\(\s*SKILL_UPDATES_STORE",
                         "检查完成后没有写入本地存储")
        # 读取（启动/渲染时回填）。assertRegex 在任何位置都能命中函数体里的那一次，
        # 抓不住「启动时没调用」——所以额外要求启动段真的调用了回填函数。
        self.assertRegex(src, r"loadStore\(\s*SKILL_UPDATES_STORE",
                         "没有读取本地存储的检查结果")
        startup = src[src.find("// startup"):]
        self.assertIn(
            "restoreSkillUpdates()", startup,
            "启动流程里没有调用 restoreSkillUpdates —— 重启后仍是「未检查」",
        )

    def test_unchecked_state_is_explicit(self):
        """未检查时不得显示中性的 `-`。"""
        src = _src()
        i = src.find('data-action="skill-check-updates"')
        self.assertGreater(i, 0)
        # 表头或空状态要说明「未检查」；只查关键词存在，措辞可调
        self.assertIn("未检查", src, "界面没有「未检查」这个状态词")

    def test_restore_records_the_check_time(self):
        """回填必须带上「这份结果是什么时候查的」。"""
        src = _src()
        i = src.find("SKILL_UPDATES_STORE")
        self.assertGreater(i, 0)
        self.assertIn("checkedAt", src,
                      "持久化的结果没有记录检查时间，用户无法判断新旧")


class SyncStatusColumnTest(unittest.TestCase):
    """「本地 / 远端」两个日期不得并排（2026-11-06 用户反馈）。

    现象：本地列显示 `07/17`、远端列显示 `11/02`，用户问「两者完全没有关系，
    这个是不正确的」。

    实查两列本就是**两个不同的量**：
    - 本地 = 该技能 SKILL.md 的 mtime（文件最后修改时间）；
    - 远端 = 上游仓库基准的提交时间（仓库形态技能全部是同一个值）。
    并排显示成同样的 MM/DD，读者自然会把它当成「本地旧、远端新」。

    用户的决定：**合并成一列状态**，不并排两个日期。

    判据：
    1. 表头不再同时出现「本地」「远端」两列；
    2. 存在一个同步状态列，能表达 一致 / 本地较新 / 远端较新；
    3. 精确日期降级到 title（悬停可查），不占主视觉。
    """

    def test_no_side_by_side_local_remote_headers(self):
        src = _html()
        head = src[src.find('<table class="skill-table">'):]
        head = head[:head.find("</thead>")]
        self.assertNotIn(">本地<", head, "仍有「本地」列与远端并排")
        self.assertNotIn(">远端<", head, "仍有「远端」列与本地并排")

    def test_sync_status_column_exists(self):
        src = _html()
        self.assertIn("st-sync", src, "缺少合并后的同步状态列")

    def test_status_expresses_local_ahead(self):
        """必须能表达「本地改过、上游没变」，否则用户无法判断谁新。"""
        src = _src()
        for word in ("本地较新", "远端较新", "一致"):
            self.assertIn(word, src, f"同步状态缺少「{word}」这一态")


class CheckResultIconSemanticsTest(unittest.TestCase):
    """「有更新」不是警告，不得用警示图标（2026-11-06 用户反馈）。

    用户看到「检查完成」弹框带橙色感叹号三角，问「为什么会有检查失败的情况」。
    实际结果完全成功（有更新 2 · 最新 243 · 未知 3 · 登记失效 1）—— 他把**警示
    图标**读成了「失败了」。

    「有更新」是**正常且值得高兴**的状态：有东西可以升级。真正需要提醒的只有：
    - 登记失效（装过又被删，登记残留）；
    - 未知（查不到上游，结论不完整）。

    判据：
    1. 只有 outdated 时用 ok（不是 warn）；
    2. 有 missing / unknown 时才用 warn；
    3. 「登记失效」的措辞要能自解释（不能只写四个字让人猜）。
    """

    def _check_block(self) -> str:
        src = _src()
        i = src.find("async function runSkillCheckUpdates")
        self.assertGreater(i, 0)
        return src[i:src.find("\n  async function ", i + 20)]

    def test_outdated_alone_is_ok_not_warn(self):
        body = self._check_block()
        # 判定表达式里不得把 outdated 当作警告条件
        import re
        # 目标是「检查完成」那一条，不是 catch 里的 err 分支
        m = re.search(r"modalNotice\(\s*\n?\s*([^,]*?),\s*\n?\s*`检查完成", body, re.S)
        self.assertIsNotNone(m, "找不到「检查完成」的 modalNotice 调用")
        cond = m.group(1)
        self.assertNotIn("s.outdated", cond,
                         "「有更新」被当成警告条件 —— 它是正常状态，不是错误")
        # kind 可能走中间变量（形如 `needsAttention ? "warn" : "ok"`），
        # 此时要追到它的定义去校验 —— 否则只改一处定义就能绕过整条断言。
        var = re.match(r"\s*([A-Za-z_$][\w$]*)\s*\?", cond)
        scope = body
        if var:
            m2 = re.search(rf"const\s+{var.group(1)}\s*=\s*([^;]+);", body)
            self.assertIsNotNone(m2, f"找不到 {var.group(1)} 的定义")
            scope = m2.group(1)
            self.assertNotIn("s.outdated", scope,
                             "「有更新」进了警告条件（经中间变量）")
        self.assertIn("s.missing", scope, "登记失效应进警告条件")
        self.assertIn("s.unknown", scope, "未知应进警告条件")

    def test_missing_label_is_self_explanatory(self):
        body = self._check_block()
        # 旧的「登记失效」四个字读不出含义；新措辞要说明是「装过又删了」
        self.assertNotIn("登记失效 ${s.missing}", body,
                         "仍用「登记失效」这种需要猜的措辞")
        self.assertTrue(
            ("已卸载" in body) or ("目录不存在" in body) or ("残留" in body),
            "缺少能自解释的措辞（应说明是「装过、目录已不存在」）",
        )


class InlineBusyLifecycleTest(unittest.TestCase):
    """`setInlineBusy` 开的进度框必须被关掉（2026-11-06 用户实测缺陷）。

    ## 现象

    点「刷新」后，操作已经完成、弹框也已确认，但**「正在刷新…」的全屏进度框
    一直不走**，把界面锁死。

    ## 根因

    上一版把 8 处「正在执行…」从 toast 改成 `setInlineBusy()`，它内部调
    `showBusy()` 开全屏 dialg；而关掉它的 `hideBusy()` **只在 `runCli` 收到
    progress 参数时才调用**。`setInlineBusy` 是独立打开的，于是**没有任何路径负责关闭**。

    那不是「偶尔没关」，是必然泄漏：每个调用点都漏。

    ## 判据

    1. `setInlineBusy` 必须返回可关闭的句柄，或存在成对语义；
    2. 每个调用 `setInlineBusy` 的函数，必须在 `finally`（或等价路径）里
       调用 `hideBusy()` —— 异常路径也必须关闭，否则一次失败就永久锁屏。
    """

    def _functions_with(self, needle: str) -> list:
        """找出**函数体内直接调用** needle 的函数。

        只认「直接调用」：父函数常经子函数间接使用 busy，把那些也算进来会
        误报（实测第一版就把 render / skillDisplayName 这类纯渲染函数列成违规）。
        """
        src = _src()
        starts = [m for m in re.finditer(r"\n(?:async\s+)?function\s+(\w+)\s*\(", src)]
        out = []
        for idx, m in enumerate(starts):
            start = m.start()
            end = starts[idx + 1].start() if idx + 1 < len(starts) else len(src)
            body = src[start:end]
            if needle in body:
                out.append((m.group(1), body))
        return out

    def test_every_busy_open_is_closed(self):
        offenders = []
        for name, body in self._functions_with("setInlineBusy("):
            if name == "setInlineBusy":
                continue  # 定义本身
            if "hideBusy()" not in body:
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            "这些函数开了进度框却从不关闭（界面会永久锁死）：%r" % (offenders,),
        )

    def test_close_happens_in_finally(self):
        """关闭必须放 finally：异常路径不关 = 一次失败就永久锁屏。"""
        bad = []
        for name, body in self._functions_with("setInlineBusy("):
            if name == "setInlineBusy" or "hideBusy()" not in body:
                continue
            fin = body.find("finally")
            if fin < 0 or "hideBusy()" not in body[fin:]:
                bad.append(name)
        self.assertEqual(bad, [], "这些函数的 hideBusy() 不在 finally 里：%r" % (bad,))
