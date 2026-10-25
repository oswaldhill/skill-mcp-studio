import test from 'node:test';
import assert from 'node:assert/strict';

import {
  auditSnapshot,
  DEFAULT_CONTEXT_WINDOW,
  DEFAULT_MAX_TOKENS,
} from '../lib/audit.mjs';

/* ------------------------------------------------------------------ *
 * Fixtures
 * ------------------------------------------------------------------ */

/** A snapshot where nothing needs to change. */
function compliantSnapshot(overrides = {}) {
  return {
    route: 'pudding-home-api',
    models: [
      { id: 'multi', name: 'Multi', input: ['text', 'image'], contextWindow: DEFAULT_CONTEXT_WINDOW },
      { id: 'plain', name: 'Plain', input: ['text', 'image'], contextWindow: DEFAULT_CONTEXT_WINDOW },
    ],
    capabilities: { multi: 'image', plain: 'text' },
    discovered: {},
    defaultContextWindow: DEFAULT_CONTEXT_WINDOW,
    describerModel: 'multi',
    vision: { present: false },
    ...overrides,
  };
}

function codes(result) {
  return result.issues.map((issue) => issue.code);
}

function findIssue(result, code) {
  return result.issues.find((issue) => issue.code === code);
}

function deepFreeze(value) {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value)) deepFreeze(value[key]);
  }
  return value;
}

/* ------------------------------------------------------------------ *
 * 1. Fully compliant snapshot
 * ------------------------------------------------------------------ */

test('全部合规时 issues 为空且 compliant 为 true', () => {
  const result = auditSnapshot(compliantSnapshot());

  assert.deepEqual(result.issues, []);
  assert.equal(result.summary.compliant, true);
  assert.deepEqual(result.llmChanges.models, {});
  assert.equal('defaultContextWindow' in result.llmChanges, false);
  assert.deepEqual(result.describer, { model: 'multi' });
});

test('llmChanges 无任何条目且 changes 对象不被意外填充', () => {
  const result = auditSnapshot(compliantSnapshot());

  assert.deepEqual(Object.keys(result.llmChanges.models), []);
  assert.equal(result.llmChanges.defaultContextWindow, undefined);
  assert.deepEqual(result.llmChanges, { models: {} });
});

test('导出的常量符合契约', () => {
  assert.equal(DEFAULT_CONTEXT_WINDOW, 262144);
  assert.equal(DEFAULT_MAX_TOKENS, 32768);
});

/* ------------------------------------------------------------------ *
 * 2. IMAGE_TAG_OFF (contract case 2)
 * ------------------------------------------------------------------ */

test('input 只有 text 时报告 IMAGE_TAG_OFF，并把期望值写入 changes', () => {
  const snapshot = compliantSnapshot();
  snapshot.models[0].input = ['text'];

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'IMAGE_TAG_OFF');

  assert.ok(issue, '应报告 IMAGE_TAG_OFF');
  assert.equal(issue.severity, 'error');
  assert.equal(issue.fixable, true);
  assert.equal(issue.model, 'multi');
  assert.match(issue.message, /图片|input/);
  assert.deepEqual(result.llmChanges.models.multi.input, ['text', 'image']);
  assert.equal(result.summary.compliant, false);
});

test('input 缺失时同样报告 IMAGE_TAG_OFF', () => {
  const snapshot = compliantSnapshot();
  delete snapshot.models[0].input;

  const result = auditSnapshot(snapshot);

  assert.ok(findIssue(result, 'IMAGE_TAG_OFF'));
  assert.deepEqual(result.llmChanges.models.multi.input, ['text', 'image']);
});

test('input 已含 image 时不产生 IMAGE_TAG_OFF 也不写 changes', () => {
  const snapshot = compliantSnapshot();
  snapshot.models[0].input = ['image', 'text', 'audio'];

  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'IMAGE_TAG_OFF'), undefined);
  assert.equal(result.llmChanges.models.multi, undefined);
});

/* ------------------------------------------------------------------ *
 * 3. CONTEXT_NOT_MAX (contract case 3)
 * ------------------------------------------------------------------ */

test('未声明 contextWindow 时报告 CONTEXT_NOT_MAX 且 target 取 discovery', () => {
  const snapshot = compliantSnapshot();
  delete snapshot.models[0].contextWindow;
  snapshot.discovered = { multi: { contextWindow: 100000 } };

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'CONTEXT_NOT_MAX');

  assert.ok(issue, '应报告 CONTEXT_NOT_MAX');
  assert.equal(issue.severity, 'warn');
  assert.equal(issue.fixable, true);
  assert.equal(issue.model, 'multi');
  assert.match(issue.message, /未声明/);
  assert.match(issue.message, /100000/);
  assert.equal(result.llmChanges.models.multi.contextWindow, 100000);
});

test('未声明 contextWindow 且无 discovery 时回退到默认值，无需改动', () => {
  const snapshot = compliantSnapshot();
  delete snapshot.models[0].contextWindow;

  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'CONTEXT_NOT_MAX'), undefined);
  assert.equal(result.llmChanges.models.multi, undefined);
  assert.equal(result.summary.compliant, true);
});

/* ------------------------------------------------------------------ *
 * 4. CONTEXT_BELOW_MAX / CONTEXT_OVER_MAX (contract case 4)
 * ------------------------------------------------------------------ */

test('discovery 大于已声明值时报告 CONTEXT_BELOW_MAX 并上调', () => {
  const snapshot = compliantSnapshot();
  snapshot.models[0].contextWindow = 100000;
  snapshot.discovered = { multi: { contextWindow: 200000 } };

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'CONTEXT_BELOW_MAX');

  assert.ok(issue, '应报告 CONTEXT_BELOW_MAX');
  assert.equal(issue.severity, 'warn');
  assert.equal(issue.fixable, true);
  assert.equal(issue.model, 'multi');
  assert.match(issue.message, /100000/);
  assert.match(issue.message, /200000/);
  assert.equal(result.llmChanges.models.multi.contextWindow, 200000);
});

test('discovery 小于已声明值时报告 CONTEXT_OVER_MAX 并下调', () => {
  const snapshot = compliantSnapshot();
  snapshot.models[0].contextWindow = 300000;
  snapshot.discovered = { multi: { contextWindow: 200000 } };

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'CONTEXT_OVER_MAX');

  assert.ok(issue, '应报告 CONTEXT_OVER_MAX');
  assert.equal(issue.severity, 'warn');
  assert.equal(issue.fixable, true);
  assert.equal(issue.model, 'multi');
  assert.match(issue.message, /300000/);
  assert.match(issue.message, /200000/);
  assert.equal(result.llmChanges.models.multi.contextWindow, 200000);
});

test('CONTEXT_OVER_MAX 仅在 discovery 明确给出更小值时触发', () => {
  const snapshot = compliantSnapshot();
  snapshot.models[0].contextWindow = 300000;
  snapshot.defaultContextWindow = DEFAULT_CONTEXT_WINDOW;
  // no discovery entry for `multi`
  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'CONTEXT_OVER_MAX'), undefined);
  assert.equal(result.llmChanges.models.multi, undefined);
  assert.equal(result.summary.compliant, true);
});

test('当前值与目标值相同则不产生上下文问题', () => {
  const snapshot = compliantSnapshot();
  snapshot.discovered = { multi: { contextWindow: DEFAULT_CONTEXT_WINDOW } };

  const result = auditSnapshot(snapshot);

  assert.deepEqual(codes(result), []);
  assert.equal(result.llmChanges.models.multi, undefined);
});

/* ------------------------------------------------------------------ *
 * 5. NO_IMAGE_MODEL / pins precedence (contract case 5)
 * ------------------------------------------------------------------ */

test('没有任何 image 能力模型时报告 NO_IMAGE_MODEL 且不可修复', () => {
  const snapshot = compliantSnapshot();
  snapshot.capabilities = { multi: 'text', plain: 'text' };
  snapshot.describerModel = undefined;

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'NO_IMAGE_MODEL');

  assert.ok(issue, '应报告 NO_IMAGE_MODEL');
  assert.equal(issue.severity, 'error');
  assert.equal(issue.fixable, false);
  assert.match(issue.message, /多模态|imageModels/);
  assert.equal(result.describer, null);
  assert.equal(result.summary.compliant, false);
  assert.equal(result.summary.imageCapable, 0);
});

test('钉住 imageModels 可让未知能力的模型成为识图模型', () => {
  const snapshot = compliantSnapshot();
  snapshot.describerModel = undefined;
  snapshot.capabilities = { multi: 'unknown', plain: 'unknown' };
  snapshot.imageModels = ['plain'];

  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'NO_IMAGE_MODEL'), undefined);
  assert.deepEqual(result.describer, { model: 'plain' });
  assert.equal(result.summary.imageCapable, 1);
});

test('textModels 钉住优先于探测到的 image 能力', () => {
  const snapshot = compliantSnapshot();
  snapshot.capabilities = { multi: 'image', plain: 'text' };
  snapshot.textModels = ['multi'];

  const result = auditSnapshot(snapshot);

  assert.ok(findIssue(result, 'NO_IMAGE_MODEL'));
  assert.equal(result.summary.imageCapable, 0);
  assert.equal(result.summary.textOnly, 2);
  assert.equal(result.describer, null);
});

/* ------------------------------------------------------------------ *
 * 6. Describer selection order (contract case 6)
 * ------------------------------------------------------------------ */

test('钉住的 describerModel 优先于第一个 image 模型', () => {
  const snapshot = compliantSnapshot();
  snapshot.describerModel = 'plain';
  snapshot.capabilities = { multi: 'image', plain: 'image' };

  const result = auditSnapshot(snapshot);

  assert.deepEqual(result.describer, { model: 'plain' });
  assert.equal(result.summary.describerModel, 'plain');
});

test('未钉住时 describer 取第一个 image 模型', () => {
  const snapshot = compliantSnapshot();
  snapshot.describerModel = undefined;
  snapshot.capabilities = { multi: 'text', plain: 'image' };

  const result = auditSnapshot(snapshot);

  assert.deepEqual(result.describer, { model: 'plain' });
  assert.equal(result.summary.describerModel, 'plain');
});

test('钉住的模型被判定为 text 时报告 DESCRIBER_NOT_MULTIMODAL 并回退', () => {
  const snapshot = compliantSnapshot();
  snapshot.describerModel = 'plain';
  snapshot.capabilities = { multi: 'image', plain: 'text' };

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'DESCRIBER_NOT_MULTIMODAL');

  assert.ok(issue, '应报告 DESCRIBER_NOT_MULTIMODAL');
  assert.equal(issue.severity, 'error');
  assert.equal(issue.fixable, false);
  assert.equal(issue.model, 'plain');
  assert.deepEqual(result.describer, { model: 'multi' });
});

test('所有模型能力未知时报告 CAPABILITY_UNKNOWN（info，不影响 compliant）', () => {
  const snapshot = compliantSnapshot();
  snapshot.capabilities = {};
  snapshot.describerModel = undefined;
  snapshot.imageModels = [];
  snapshot.textModels = [];

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'CAPABILITY_UNKNOWN');

  assert.ok(issue, '应报告 CAPABILITY_UNKNOWN');
  assert.equal(issue.severity, 'info');
  assert.equal(issue.fixable, false);
  assert.equal(result.summary.unknown, 2);
});

/* ------------------------------------------------------------------ *
 * 7. Vision plugin mismatch (contract case 7)
 * ------------------------------------------------------------------ */

test('vision.present 且模型不一致时报告 VISION_PLUGIN_MISMATCH', () => {
  const snapshot = compliantSnapshot();
  snapshot.vision = { present: true, model: 'other-model', autoDescribe: true };

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'VISION_PLUGIN_MISMATCH');

  assert.ok(issue, '应报告 VISION_PLUGIN_MISMATCH');
  assert.equal(issue.severity, 'info');
  assert.equal(issue.fixable, false);
  assert.match(issue.message, /vision/);
  // info 级别不影响 compliant，也不产生 changes
  assert.equal(result.summary.compliant, true);
  assert.deepEqual(result.llmChanges.models, {});
});

test('vision 模型一致但未开启 autoDescribe 时报告 VISION_PLUGIN_MISMATCH', () => {
  const snapshot = compliantSnapshot();
  snapshot.vision = { present: true, model: 'multi', autoDescribe: false };

  const result = auditSnapshot(snapshot);

  assert.ok(findIssue(result, 'VISION_PLUGIN_MISMATCH'));
});

test('vision 模型一致且 autoDescribe 为 true 时不报告', () => {
  const snapshot = compliantSnapshot();
  snapshot.vision = { present: true, model: 'multi', autoDescribe: true };

  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'VISION_PLUGIN_MISMATCH'), undefined);
  assert.deepEqual(result.issues, []);
});

test('vision.present 不为 true 时不报告 vision 问题', () => {
  const snapshot = compliantSnapshot();
  snapshot.vision = { present: false, model: 'other-model', autoDescribe: false };

  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'VISION_PLUGIN_MISMATCH'), undefined);
});

/* ------------------------------------------------------------------ *
 * 8. summary / compliant semantics (contract case 8)
 * ------------------------------------------------------------------ */

test('summary 统计 imageTagged / imageCapable / textOnly / unknown 与 maxContextWindow', () => {
  const snapshot = {
    route: 'pudding-home-api',
    models: [
      { id: 'a', input: ['text', 'image'], contextWindow: 100000 },
      { id: 'b', input: ['text'], contextWindow: 200000 },
      { id: 'c', input: ['text', 'image'], contextWindow: 150000 },
    ],
    capabilities: { a: 'image', b: 'text', c: 'unknown' },
    discovered: { a: { contextWindow: 120000 }, c: { contextWindow: 180000 } },
    defaultContextWindow: DEFAULT_CONTEXT_WINDOW,
    describerModel: 'a',
    vision: { present: false },
  };

  const result = auditSnapshot(snapshot);

  assert.equal(result.summary.totalModels, 3);
  assert.equal(result.summary.imageTagged, 2);
  assert.equal(result.summary.imageCapable, 1);
  assert.equal(result.summary.textOnly, 1);
  assert.equal(result.summary.unknown, 1);
  assert.equal(result.summary.maxContextWindow, DEFAULT_CONTEXT_WINDOW);
  assert.equal(result.summary.describerModel, 'a');
  assert.equal(result.summary.compliant, false);
  // b 缺 image 标签 + 三个模型的上下文调整
  assert.deepEqual(result.llmChanges.models.a, { contextWindow: 120000 });
  assert.equal(result.llmChanges.models.b.input.length, 2);
  assert.equal(result.llmChanges.models.b.contextWindow, DEFAULT_CONTEXT_WINDOW);
  assert.equal(result.llmChanges.models.c.contextWindow, 180000);
});

test('compliant 为 true 当且仅当没有 error、没有 changes', () => {
  const onlyWarningsButChanges = compliantSnapshot();
  delete onlyWarningsButChanges.models[0].contextWindow;
  onlyWarningsButChanges.discovered = { multi: { contextWindow: 100000 } };
  const warned = auditSnapshot(onlyWarningsButChanges);
  assert.equal(findIssue(warned, 'CONTEXT_NOT_MAX').severity, 'warn');
  assert.equal(warned.summary.compliant, false);

  const infoOnly = compliantSnapshot();
  infoOnly.vision = { present: true, model: 'other', autoDescribe: true };
  const info = auditSnapshot(infoOnly);
  assert.deepEqual(codes(info), ['VISION_PLUGIN_MISMATCH']);
  assert.equal(info.summary.compliant, true);

  const clean = auditSnapshot(compliantSnapshot());
  assert.equal(clean.summary.compliant, true);
});

test('空快照不抛异常且统计为零', () => {
  for (const snapshot of [undefined, null, {}, { models: null }, { models: [null, {}, 42] }]) {
    const result = auditSnapshot(snapshot);
    assert.ok(Array.isArray(result.issues), 'issues 必须是数组');
    assert.equal(result.summary.totalModels, 0);
    assert.equal(result.summary.maxContextWindow, 0);
    assert.deepEqual(result.describer, null);
    assert.equal(result.summary.compliant, true);
  }
});

test('缺少 route / vision / capabilities 等字段时不抛异常', () => {
  const result = auditSnapshot({ models: [{ id: 'm' }] });

  assert.ok(findIssue(result, 'IMAGE_TAG_OFF'));
  // 单模型：缺 image 标签、没有任何 image 能力模型、能力全未知；
  // 上下文回退默认值所以没有上下文问题。
  assert.deepEqual(codes(result), ['IMAGE_TAG_OFF', 'NO_IMAGE_MODEL', 'CAPABILITY_UNKNOWN']);
  assert.deepEqual(result.llmChanges.models, { m: { input: ['text', 'image'] } });
});

/* ------------------------------------------------------------------ *
 * 9. ROUTE_CONTEXT_LOW
 * ------------------------------------------------------------------ */

test('显式声明的路由默认值偏小时报告 ROUTE_CONTEXT_LOW 并写入统一默认值', () => {
  const snapshot = compliantSnapshot();
  snapshot.models.forEach((model) => { model.contextWindow = DEFAULT_CONTEXT_WINDOW; });
  snapshot.defaultContextWindow = 32768;

  const result = auditSnapshot(snapshot);
  const issue = findIssue(result, 'ROUTE_CONTEXT_LOW');

  assert.ok(issue, '应报告 ROUTE_CONTEXT_LOW');
  assert.equal(issue.severity, 'warn');
  assert.equal(issue.fixable, true);
  assert.match(issue.message, /32768/);
  assert.equal(result.llmChanges.defaultContextWindow, DEFAULT_CONTEXT_WINDOW);
  assert.equal(result.summary.compliant, false);
});

test('路由默认值未声明时不报告 ROUTE_CONTEXT_LOW 也不写 defaultContextWindow', () => {
  const snapshot = compliantSnapshot();
  delete snapshot.defaultContextWindow;

  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'ROUTE_CONTEXT_LOW'), undefined);
  assert.equal('defaultContextWindow' in result.llmChanges, false);
});

/* ------------------------------------------------------------------ *
 * 10. Issue ordering
 * ------------------------------------------------------------------ */

test('issues 先按 severity（error > warn > info）再按 code 排序', () => {
  const snapshot = {
    route: 'r',
    models: [
      { id: 'a', input: ['text'], contextWindow: 300000 },
      { id: 'b', input: ['text', 'image'], contextWindow: 100000 },
    ],
    capabilities: { a: 'image', b: 'text' },
    discovered: { a: { contextWindow: 200000 }, b: { contextWindow: 200000 } },
    defaultContextWindow: 32768,
    describerModel: undefined,
    vision: { present: true, model: 'other', autoDescribe: true },
  };

  const result = auditSnapshot(snapshot);
  const ordered = result.issues.map((issue) => `${issue.severity}:${issue.code}`);

  assert.deepEqual(ordered, [
    'error:IMAGE_TAG_OFF',
    'warn:CONTEXT_BELOW_MAX',
    'warn:CONTEXT_OVER_MAX',
    'warn:ROUTE_CONTEXT_LOW',
    'info:VISION_PLUGIN_MISMATCH',
  ]);
});

/* ------------------------------------------------------------------ *
 * 11. Purity / immutability
 * ------------------------------------------------------------------ */

test('不修改输入的 models / 数组 / capabilities / discovered', () => {
  const snapshot = {
    route: 'r',
    models: [
      { id: 'a', name: 'A', input: ['text'], contextWindow: 100000 },
      { id: 'b', name: 'B', input: ['text', 'image'] },
    ],
    capabilities: { a: 'image', b: 'text' },
    discovered: { a: { contextWindow: 200000 } },
    defaultContextWindow: 32768,
    describerModel: 'a',
    vision: { present: true, model: 'x', autoDescribe: false },
    imageModels: [],
    textModels: [],
  };
  const pristine = structuredClone(snapshot);

  auditSnapshot(snapshot);

  assert.deepEqual(snapshot, pristine);
});

test('深度冻结的快照也不会抛错（说明实现没有写入输入）', () => {
  const snapshot = deepFreeze(compliantSnapshot());

  assert.doesNotThrow(() => auditSnapshot(snapshot));
  const result = auditSnapshot(snapshot);
  assert.deepEqual(result.describer, { model: 'multi' });
});

test('返回的 changes 数组与输入数组不共享引用', () => {
  const snapshot = compliantSnapshot();
  snapshot.models[0].input = ['text'];

  const result = auditSnapshot(snapshot);
  result.llmChanges.models.multi.input.push('audio');

  assert.deepEqual(snapshot.models[0].input, ['text']);
  const again = auditSnapshot(snapshot);
  assert.deepEqual(again.llmChanges.models.multi.input, ['text', 'image']);
});

test('对同一快照连续两次调用结果深度相等', () => {
  const snapshot = {
    route: 'r',
    models: [
      { id: 'a', input: ['text'], contextWindow: 300000 },
      { id: 'b', input: ['text', 'image'] },
      { id: 'c', input: ['text', 'image'], contextWindow: 1000 },
    ],
    capabilities: { a: 'image', c: 'unknown' },
    discovered: { a: { contextWindow: 250000 }, c: { contextWindow: 262144 } },
    defaultContextWindow: 65536,
    describerModel: 'a',
    vision: { present: true, model: 'other', autoDescribe: false },
  };

  const first = auditSnapshot(snapshot);
  const second = auditSnapshot(snapshot);

  assert.deepEqual(first, second);
});

test('重复模型 id 会被去重，不受顺序影响产生重复问题', () => {
  const snapshot = compliantSnapshot();
  snapshot.models.push({ id: 'multi', input: ['text'] });

  const result = auditSnapshot(snapshot);

  assert.equal(result.summary.totalModels, 2);
  assert.equal(result.issues.filter((issue) => issue.code === 'IMAGE_TAG_OFF').length, 0);
  assert.deepEqual(result.llmChanges.models, {});
});

/* ------------------------------------------------------------------ *
 * 12. Message & code contract
 * ------------------------------------------------------------------ */

test('所有 issue 均有稳定 code、合法 severity、中文 message 与布尔 fixable', () => {
  const snapshot = {
    route: 'r',
    models: [{ id: 'a', input: ['text'] }],
    capabilities: { a: 'text' },
    defaultContextWindow: 1024,
    describerModel: 'a',
    vision: { present: true, model: 'z' },
  };

  const result = auditSnapshot(snapshot);

  for (const issue of result.issues) {
    assert.equal(typeof issue.code, 'string');
    assert.ok(issue.code.length > 0);
    assert.ok(['error', 'warn', 'info'].includes(issue.severity));
    assert.equal(typeof issue.message, 'string');
    assert.match(issue.message, /[\u4e00-\u9fa5]/, `${issue.code} 的 message 应为中文`);
    assert.equal(typeof issue.fixable, 'boolean');
  }

  const allowed = new Set([
    'IMAGE_TAG_OFF', 'CONTEXT_NOT_MAX', 'CONTEXT_BELOW_MAX', 'CONTEXT_OVER_MAX',
    'ROUTE_CONTEXT_LOW', 'NO_IMAGE_MODEL', 'DESCRIBER_NOT_MULTIMODAL',
    'CAPABILITY_UNKNOWN', 'VISION_PLUGIN_MISMATCH',
  ]);
  for (const code of codes(result)) {
    assert.ok(allowed.has(code), `未在契约中声明的 code: ${code}`);
  }
});

test('不合法的数值字段（NaN/负数/字符串）按未声明处理', () => {
  const snapshot = compliantSnapshot();
  snapshot.models[0].contextWindow = 'not-a-number';
  snapshot.models[1].contextWindow = -5;
  snapshot.discovered = { multi: { contextWindow: NaN } };

  const result = auditSnapshot(snapshot);

  assert.equal(findIssue(result, 'CONTEXT_NOT_MAX'), undefined);
  assert.deepEqual(result.llmChanges.models, {});
  assert.equal(result.summary.compliant, true);
});

// ---------------------------------------------------------------------------
// A provider may declare a context window above the harness fallback
// ---------------------------------------------------------------------------

test('a provider defaultContextWindow above 262144 becomes the target, not an issue', () => {
  const result = auditSnapshot({
    route: 'custom',
    defaultContextWindow: 1000000,
    models: [{ id: 'a', input: ['text', 'image'] }],
    imageModels: ['a'],
  });
  assert.equal(result.summary.maxContextWindow, 1000000);
  assert.equal(result.issues.length, 0, JSON.stringify(result.issues));
});

test('a provider below the harness fallback is still reported', () => {
  const result = auditSnapshot({
    route: 'custom',
    defaultContextWindow: 8192,
    models: [{ id: 'a', input: ['text', 'image'] }],
    imageModels: ['a'],
  });
  const codes = result.issues.map((issue) => issue.code);
  assert.ok(codes.includes('ROUTE_CONTEXT_LOW'), JSON.stringify(codes));
});

test('an explicit model contextWindow larger than the provider default is left alone', () => {
  const result = auditSnapshot({
    route: 'custom',
    defaultContextWindow: 262144,
    models: [{ id: 'a', input: ['text', 'image'], contextWindow: 1000000 }],
    imageModels: ['a'],
  });
  assert.equal(result.issues.length, 0, JSON.stringify(result.issues));
});
