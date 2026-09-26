// 崩溃点定位：在桩 DOM 下**完整执行** dashboard 脚本，捕获它真正跑不到
// 第 4935 行（点击委托绑定）的原因是哪一个、发生在哪一行。
// 动机：node --check 只查语法，不查引用。FEAT-10 的 MARKET_DATA 就是语法全过、
// 运行期抛错，导致委托之后的所有按钮集体失效。
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const out = [];
function log(s) { out.push(s); }

const a = html.indexOf("<script>") + "<script>".length;
const b = html.indexOf("</script>", a);
const js = html.slice(a, b);
// 行号换算：js 的第 1 行对应 html 的第 jsFirstLine 行
const jsFirstLine = html.slice(0, a).split("\n").length;
log(`脚本块：${js.length} 字节，起始于 dashboard.html 第 ${jsFirstLine} 行`);

const listeners = {};
function mkEl(id) {
  const store = {};
  const el = {
    id: id || "", style: {}, dataset: {}, children: [], disabled: false,
    classList: {
      add() {}, remove() {}, contains() { return false; },
      toggle() { return false; },
    },
    appendChild(n) { this.children.push(n); return n; },
    removeChild() {}, remove() {},
    setAttribute(k, v) { store[k] = v; }, getAttribute(k) { return store[k] ?? null; },
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
    removeEventListener() {},
    querySelector() { return mkEl("sub"); },
    querySelectorAll() { return []; },
    focus() {}, blur() {}, click() {}, scrollIntoView() {},
    insertAdjacentHTML() {},
    closest() { return null; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 20 }; },
  };
  el.textContent = "";
  Object.defineProperty(el, "innerHTML", { get() { return ""; }, set() {} });
  Object.defineProperty(el, "value", { get() { return ""; }, set() {} });
  Object.defineProperty(el, "checked", { get() { return false; }, set() {} });
  return el;
}

global.window = {
  __TAURI__: { core: { invoke: (_c, payload) => Promise.resolve(JSON.stringify(
    { code: 0, stdout: stubStdout((payload && payload.args) || []), stderr: "" })) } },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  addEventListener() {}, setTimeout, clearTimeout, setInterval, clearInterval,
  location: { href: "tauri://localhost" }, alert() {}, confirm: () => true,
};
// 关键增强：真实 DOM 的 getElementById 对**不存在**的 id 返回 null。
// 桩里一律返回对象会掩盖"`$(不存在的id).classList` 在委托绑定前崩掉"这类真崩。
// 故先从 HTML 收集全部真实 id，不在名单里的返回 null。
const realIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
log(`HTML 中的 id 数: ${realIds.size}`);
const missingIds = new Set();

global.document = {
  addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
  createElement: () => mkEl("new"), createDocumentFragment: () => mkEl("frag"),
  getElementById: (id) => {
    if (realIds.has(id)) return mkEl(id);
    missingIds.add(id);                       // 记录脚本要找而不存在的 id
    return null;
  },
  querySelector: (sel) => mkEl("q"),
  querySelectorAll: () => [], body: mkEl("body"), head: mkEl("head"),
  documentElement: mkEl("html"), title: "", visibilityState: "visible",
};
global.localStorage = global.window.localStorage;
global.navigator = { clipboard: { writeText: () => Promise.resolve() }, platform: "Mac" };
global.fetch = () => Promise.reject(new Error("no-network-in-harness"));
global.__listeners = listeners;

const MGMT = { agents: [], skills: { entries: [] }, mcp: { clients: [], servers: [] },
  overview: {}, summary: {} };
const USAGE = { kind: "skill-usage", skills: [], total_sessions: 0, window_days: 30 };
const ADVICE = { summary: { scanned: 3, actionable_groups: 0, upstream_only_groups: 0,
  rejected_entries: 0 }, actionable: [], upstream_only: [], rejected: [] };
const MKT = { sources: [], installed: [], updates: [] };
function stubStdout(args) {
  const j = (o) => JSON.stringify(o);
  if (args.includes("--merge-advice")) return j(ADVICE);
  if (args.includes("--skill-usage")) return j(USAGE);
  if (args.includes("--market")) return j(MKT);
  return j(MGMT);
}
/* invoke stub 见上方加载期定义 */

try {
  vm.runInThisContext(js, { filename: "dash_script.js" });
  log("✅ 顶层执行未抛错（脚本能跑到末尾）");
} catch (e) {
  const stack = String(e.stack || "");
  // 把栈里的 dash_script.js 行号换算回 dashboard.html 的真实行号
  const hits = [...stack.matchAll(/dash_script\.js:(\d+):(\d+)/g)];
  log("❌ 顶层抛错：" + e.message);
  if (hits.length) {
    const first = hits[0];
    log(`   崩溃位置：dash_script.js 第 ${first[1]} 列 ${first[2]}`);
    log(`   换算到源文件：dashboard.html 约第 ${jsFirstLine + Number(first[1]) - 1} 行`);
    const lines = js.split("\n");
    const k = Number(first[1]) - 1;
    for (let i = Math.max(0, k - 4); i < Math.min(lines.length, k + 3); i++) {
      log(`   ${i === k ? ">>" : "  "} ${jsFirstLine + i}: ${lines[i].slice(0, 110)}`);
    }
  }
  log("   --- 栈顶 ---");
  stack.split("\n").slice(0, 6).forEach((l) => log("   " + l.trim()));
}

// 关键：点击委托到底绑上了没有
const clickCount = (listeners.click || []).length;
log(`\n已绑定的 click 监听器数量: ${clickCount}` +
    (clickCount ? "（委托存在）" : " ← 委托从未绑定，这就是所有按钮无反应的直接原因"));
if (missingIds.size) {
  log(`\n脚本索取但 HTML 中不存在的 id（真实浏览器里 $() 返回 null，极易崩）:`);
  [...missingIds].sort().forEach((i) => log("   · " + i));
}

// —— 端到端：真的派发一次点击，走通「委托 → toggleAdvicePanel → runCli → showBusy」——
// 静态检查证明"能加载"，这一步才证明"点了有反应"。
// 前提：mkEl 的 classList 必须**有状态**（否则 contains("hidden") 恒 false，
// 面板逻辑会测出假阴性）——用事件日志记录每次 hidden 增删。
function statefulEl(id, initialHidden) {
  const el = mkEl(id);
  const st = { hidden: !!initialHidden, log: [] };
  el.classList = {
    contains: (c) => (c === "hidden" ? st.hidden : false),
    add: (c) => { if (c === "hidden") { st.hidden = true; st.log.push("+" + c); } },
    remove: (c) => { if (c === "hidden") { st.hidden = false; st.log.push("-" + c); } },
    toggle: (c, force) => {
      if (c === "hidden") {
        st.hidden = force === undefined ? !st.hidden : !!force;
        st.log.push("toggle" + (force === undefined ? "" : force ? ":0" : ":1"));
      }
      return st.hidden;
    },
    _st: st,
  };
  return el;
}
const elCache = {};
const HIDDEN_INIT = new Set(["busy-root", "insight-panel", "market-panel"]);
const origById = global.document.getElementById;
global.document.getElementById = function (id) {
  if (!realIds.has(id)) { missingIds.add(id); return null; }
  if (!elCache[id]) elCache[id] = origById.call(this, id);
  if (!elCache[id].__stateful && HIDDEN_INIT.has(id)) {
    elCache[id] = statefulEl(id, true);
    elCache[id].__stateful = true;
  }
  return elCache[id];
};
const clickHandler = (listeners.click || []).find((fn) => /\[data-action\]/.test(String(fn)));
  // open-insight 的 busy 期望值为 false：统计与整理建议已合并成一次后台扫描，
  // 打开面板只呈现缓存结果，不再弹「正在计算」全屏框（用户明确要求）。
  // 只有面板内的「强制重新统计」才会弹可取消的进度框。
const CASES = [
  { action: "open-insight", panel: "insight-panel", busy: false },
  { action: "open-market", panel: "market-panel", busy: false },
];
function dispatch(action) {
  const btn = mkEl("btn-" + action);
  btn.dataset = { action };
  const ev = { target: { closest: (sel) => (sel === "[data-action]" ? btn : null) },
               preventDefault() {}, stopPropagation() {} };
  const r = clickHandler(ev);
  if (r && r.catch) r.catch((e) => log(`   [async ${action}] ${e && e.message}`));
}
function reportCase(c, elCache) {
  const panel = elCache[c.panel];
  const busy = elCache["busy-root"];
  const okPanel = !!(panel && panel.classList && panel.classList._st && !panel.classList._st.hidden);
  const bLog = (busy && busy.classList && busy.classList._st) ? busy.classList._st.log : [];
  const okBusy = !c.busy || (bLog.includes("-hidden") && bLog.includes("+hidden"));
  const okBusyClosed = !busy || !busy.classList._st || busy.classList._st.hidden;
  const verdict = okPanel && okBusy && okBusyClosed ? "✅" : "❌";
  log(`   ${verdict} ${c.action}: 面板打开=${!!okPanel}` +
      (c.busy ? `｜进度框出现+收掉=${okBusy}` : "") +
      `\n      panel=${JSON.stringify(panel ? panel.classList._st.log : "缺失")}` +
      ` busy=${JSON.stringify(bLog)}`);
  return okPanel && okBusy && okBusyClosed;
}
if (clickHandler) {
  log(`\n端到端逐按钮点击（真实走「委托→toggle→runCli→showBusy」）:`);
  (async () => {
    let allOk = true;
    for (const c of CASES) {
      for (const k of Object.keys(elCache)) {       // 上一轮遗留态清零（本轮开始前）
        const e = elCache[k];
        if (e.__stateful) { e.classList._st.hidden = true; e.classList._st.log.length = 0; }
      }
      dispatch(c.action);
      await new Promise((r) => setTimeout(r, 250));   // 让 stub invoke 的微任务跑完
      allOk = reportCase(c, elCache) && allOk;         // 先报告，后清场
    }
    log(allOk ? "\n✅ 全部按钮点击链路端到端通过" : "\n❌ 存在断链按钮（多为作用域/未定义函数）");
    fs.writeFileSync(process.argv[3], out.join("\n") + "\n", "utf8");
    process.exit(allOk ? 0 : 1);   // 同上：清掉页面注册的定时器，跑完即退
  })();
} else {
  fs.writeFileSync(process.argv[3], out.join("\n") + "\n", "utf8");
  // 仪表盘脚本会在顶层注册自动统计的 setInterval。真实定时器持有事件循环，
  // 不显式退出的话进程会一直挂着（测试表现为超时）。哨兵跑完就该收工。
  process.exit(0);
}
