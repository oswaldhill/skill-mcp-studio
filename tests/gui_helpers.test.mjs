// T-3（JS 侧）：对 dashboard.html 内联脚本里的纯函数做真实行为测试。
//
// 这些函数在单文件里内联，无法直接 import；本测试从 HTML 提取其真实源码，
// 用 node:vm 编译后按源头做行为断言——一旦有人改坏 escapeHtml/stripAnsi/
// dotFor/cliFailLines 的输出语义，这里立即失败（耦合真实实现，非复制品）。
//
// 运行：node --test tests/gui_helpers.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync(new URL("../gui/dashboard.html", import.meta.url), "utf8");
const script = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => m[1])
  .join("\n");

// 从 script 里找一个 top-level 声明（function / const 箭头）并按其真实源码抽取。
function matchBrace(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    const c = src[i];
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) return i;
    }
  }
  throw new Error("未闭合的大括号");
}

function extractDecl(src, name) {
  const fn = new RegExp(`function\\s+${name}\\b`);
  const arrow = new RegExp(`const\\s+${name}\\s*=\\s*\\([^)]*\\)\\s*=>`);
  let m = src.match(fn);
  if (m) {
    const open = src.indexOf("{", m.index);
    const close = matchBrace(src, open);
    return src.slice(m.index, close + 1);
  }
  m = src.match(arrow);
  if (!m) throw new Error(`找不到声明: ${name}`);
  const afterArrow = src.indexOf("=>", m.index) + 2;
  // 箭头体可能是 { ... } 块，也可能是表达式直到行尾 ';'。
  const rest = src.slice(afterArrow);
  const firstNonWs = rest.search(/\S/);
  if (firstNonWs >= 0 && rest[firstNonWs] === "{") {
    const close = matchBrace(src, afterArrow + firstNonWs);
    return src.slice(m.index, close + 1);
  }
  // 表达式箭头体的语句结束是「行尾 ;」——不能直接用 indexOf(";")，因为字符串字面量
  // 里可能含分号（如 HTML 实体 &amp; / &#39; 的尾分号）。匹配「; + 行尾空白 + 换行」。
  const semiMatch = rest.match(/;[ \t]*\r?\n/);
  if (!semiMatch) throw new Error(`找不到 ${name} 的语句结束`);
  const semi = afterArrow + semiMatch.index;
  return src.slice(m.index, semi + 1);
}

// 用极简 DOM 桩编译这些纯函数（它们运行时不触碰 DOM）。
const decls = ["escapeHtml", "stripAnsi", "cliErrDetail", "cliFailLines", "dotFor"]
  .map((n) => extractDecl(script, n))
  .join("\n");

const sandbox = { document: { getElementById: () => null } };
vm.createContext(sandbox);
// 顶层 const 在 vm 里是词法绑定、不会挂到 sandbox 对象上，故在同一段脚本里用
// globalThis 显式导出后再取出。
vm.runInContext(
  decls +
    "\nglobalThis.__gui = { escapeHtml, stripAnsi, cliErrDetail, cliFailLines, dotFor };\n",
  sandbox,
);

const { escapeHtml, stripAnsi, cliErrDetail, cliFailLines, dotFor } = sandbox.__gui;

test("escapeHtml 转义五个 HTML 元字符且 null/undefined 归一为空串", () => {
  assert.equal(escapeHtml(`<a href="x">&'</a>`),
    "&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;");
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
  assert.equal(escapeHtml(0), "0");
});

test("stripAnsi 去除 ANSI 颜色与私有控制序列", () => {
  assert.equal(stripAnsi("\x1b[31mred\x1b[0m ok"), "red ok");
  assert.equal(stripAnsi(null), "");
  assert.equal(stripAnsi("plain"), "plain");
});

test("cliErrDetail 优先取 stderr，回退 stdout，再无则退出码", () => {
  assert.equal(cliErrDetail({ code: 2, stdout: "", stderr: "\x1b[31mboom\x1b[0m" }), "boom");
  assert.equal(cliErrDetail({ code: 0, stdout: "ok", stderr: "" }), "ok");
  assert.equal(cliErrDetail({ code: 2, stdout: "", stderr: "" }), "退出码 2");
  assert.equal(cliErrDetail(null), "run_cli 无返回");
});

test("cliFailLines 从 stdout 挑失败行并去 emoji，空则回退 stderr", () => {
  const res = { code: 1, stdout: "line ok\n❌ refuSed thing\n失败 一项\n", stderr: "" };
  const out = cliFailLines(res);
  assert.match(out, /refuSed thing/);
  assert.match(out, /失败 一项/);
  assert.doesNotMatch(out, /line ok/);
  // stderr 回退路径不做 emoji 剥离（仅 stdout 行做去噪），保留原始错误标记。
  assert.equal(cliFailLines({ code: 1, stdout: "", stderr: "✗ denied" }), "✗ denied");
});

test("dotFor 三态点色", () => {
  assert.equal(dotFor(true, "installed"), "ok");
  assert.equal(dotFor(false, "config_only"), "warn");
  assert.equal(dotFor(false, "none"), "faint");
});