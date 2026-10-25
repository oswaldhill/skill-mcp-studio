/**
 * lib/audit.mjs — pure audit / repair-plan logic for dsh-plugin-model-guard.
 *
 * Design constraints (see CONTRACT.md §2):
 *   - Pure functions only: no I/O, no timers, no network, no environment access.
 *   - Pure ESM, zero third-party imports (Node builtins are not needed either).
 *   - The caller's snapshot is never mutated: we take a defensive deep copy
 *     before reading anything, and the returned plan only ever contains new
 *     objects/arrays.
 *   - Every user-facing message is Simplified Chinese; `code` values are the
 *     stable machine-readable identifiers.
 *
 * Rule precedence implemented here:
 *   capabilities: textModels pin > imageModels pin > capabilities[id] > 'unknown'
 *   context:      discovered[id].contextWindow > defaultContextWindow > DEFAULT_CONTEXT_WINDOW
 *   issues:       IMAGE_TAG_OFF + context issues per model, then route/describer/vision
 *                 issues; sorted by severity (error > warn > info) then by code.
 */

/** Fallback "maximum" context window when neither discovery nor config says otherwise. */
/**
 * The harness fallback when a provider declares no `defaultContextWindow`.
 * A provider (or a model) may legitimately exceed it: the configured endpoint
 * in this profile accepts 1,000,000 input tokens, so this is a floor for
 * comparison, not a ceiling to enforce.
 */
export const DEFAULT_CONTEXT_WINDOW = 262144;
/** Fallback output-token budget (part of the public API contract; not needed by the audit rules). */
export const DEFAULT_MAX_TOKENS = 32768;

/** Severity ordering: error > warn > info. Anything unrecognised sorts last. */
const SEVERITY_ORDER = Object.freeze({ error: 0, warn: 1, info: 2 });
const UNKNOWN_SEVERITY_ORDER = 3;

/** Every model must advertise both tags; `image` is the one this plugin repairs. */
const TARGET_INPUT = Object.freeze(['text', 'image']);

const KNOWN_CAPABILITIES = new Set(['image', 'text', 'unknown']);

/* ------------------------------------------------------------------ *
 * Small defensive helpers
 * ------------------------------------------------------------------ */

function isObjectLike(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Deep copy the snapshot so this module can never mutate caller state, even by
 * accident. `structuredClone` is the preferred path; the JSON fallback keeps us
 * alive for exotic inputs (functions, proxies, ...) and the final fallback lets
 * the audit run on garbage without throwing.
 */
function safeClone(value) {
  if (value === undefined) return undefined;
  try {
    return structuredClone(value);
  } catch {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch {
      return undefined;
    }
  }
}

/** Accept only finite positive numbers; anything else counts as "not declared". */
function positiveNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined;
}

/** Normalise a "list of ids" field: strings only, de-duplicated, order preserved. */
function normalizeStringList(value) {
  if (!Array.isArray(value)) return [];
  const result = [];
  for (const item of value) {
    if (typeof item === 'string' && item.length > 0 && !result.includes(item)) {
      result.push(item);
    }
  }
  return result;
}

/** Own-property lookup that tolerates non-objects and null-prototype records. */
function ownEntry(record, key) {
  if (!isObjectLike(record)) return undefined;
  if (!Object.prototype.hasOwnProperty.call(record, key)) return undefined;
  return record[key];
}

function trimToId(value) {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function formatInputList(input) {
  return JSON.stringify(Array.isArray(input) ? input : []);
}

/* ------------------------------------------------------------------ *
 * Issue construction & ordering
 * ------------------------------------------------------------------ */

function makeIssue(code, severity, message, { model, fixable = false } = {}) {
  const issue = { code, severity, message };
  if (model !== undefined) issue.model = model;
  issue.fixable = fixable === true;
  return issue;
}

function severityOrder(severity) {
  const rank = SEVERITY_ORDER[severity];
  return typeof rank === 'number' ? rank : UNKNOWN_SEVERITY_ORDER;
}

function compareCodes(left, right) {
  const a = String(left ?? '');
  const b = String(right ?? '');
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

/**
 * error > warn > info, then by `code`. Ties keep their generation order so the
 * output is deterministic for any (even unknown) severity value.
 */
function sortIssues(issues) {
  return issues
    .map((issue, index) => ({ issue, index }))
    .sort((left, right) => (
      severityOrder(left.issue.severity) - severityOrder(right.issue.severity)
      || compareCodes(left.issue.code, right.issue.code)
      || left.index - right.index
    ))
    .map((entry) => entry.issue);
}

/* ------------------------------------------------------------------ *
 * Main entry point
 * ------------------------------------------------------------------ */

/**
 * Audit a configuration snapshot and produce the repair plan.
 *
 * @param {object} [snapshot] see CONTRACT.md §2 typedef `Snapshot`
 * @returns {object} `Plan` — { issues, llmChanges, describer, summary }
 */
export function auditSnapshot(snapshot) {
  const cloned = safeClone(snapshot);
  const snap = isObjectLike(cloned) ? cloned : {};

  const models = collectModels(snap);
  const textPins = new Set(normalizeStringList(snap.textModels));
  const imagePins = new Set(normalizeStringList(snap.imageModels));
  const capabilities = snap.capabilities;
  const discovered = snap.discovered;

  const routeDefault = positiveNumber(snap.defaultContextWindow);
  const fallbackContextWindow = routeDefault ?? DEFAULT_CONTEXT_WINDOW;
  const routeLabel = trimToId(snap.route) ?? '当前路由';

  /** Effective capability: explicit text pin > explicit image pin > probe result > unknown. */
  const effectiveOf = (id) => {
    if (textPins.has(id)) return 'text';
    if (imagePins.has(id)) return 'image';
    const probed = ownEntry(capabilities, id);
    return KNOWN_CAPABILITIES.has(probed) ? probed : 'unknown';
  };

  /** @type {Array<object>} */
  const issues = [];
  /** @type {Map<string, {input?: string[], contextWindow?: number}>} */
  const modelChanges = new Map();
  /** @type {Map<string, number>} */
  const targets = new Map();

  const ensureChange = (id) => {
    let patch = modelChanges.get(id);
    if (!patch) {
      patch = {};
      modelChanges.set(id, patch);
    }
    return patch;
  };

  for (const model of models) {
    const { id, entry } = model;
    const input = model.input;
    const hasImageTag = input.includes('image');

    // --- Requirement 1: input tags -------------------------------------
    if (!hasImageTag) {
      issues.push(makeIssue(
        'IMAGE_TAG_OFF',
        'error',
        `模型「${id}」未开启图片输入标签：当前 input 为 ${formatInputList(input)}，期望为 ${formatInputList(TARGET_INPUT)}。`,
        { model: id, fixable: true },
      ));
      ensureChange(id).input = [...TARGET_INPUT];
    }

    // --- Requirement 3: maximum context window -------------------------
    const declaredContext = positiveNumber(entry.contextWindow);
    const currentContext = declaredContext ?? fallbackContextWindow;
    const discoveredEntry = ownEntry(discovered, id);
    const discoveredContext = positiveNumber(ownEntry(discoveredEntry, 'contextWindow'));
    const targetContext = discoveredContext ?? fallbackContextWindow;
    targets.set(id, targetContext);

    if (targetContext !== currentContext) {
      if (declaredContext === undefined) {
        issues.push(makeIssue(
          'CONTEXT_NOT_MAX',
          'warn',
          `模型「${id}」未声明上下文窗口（当前回退 ${currentContext}），该模型最大上下文为 ${targetContext}。`,
          { model: id, fixable: true },
        ));
        ensureChange(id).contextWindow = targetContext;
      } else if (declaredContext < targetContext) {
        issues.push(makeIssue(
          'CONTEXT_BELOW_MAX',
          'warn',
          `模型「${id}」声明的上下文窗口 ${declaredContext} 小于最大可用值 ${targetContext}。`,
          { model: id, fixable: true },
        ));
        ensureChange(id).contextWindow = targetContext;
      } else if (discoveredContext !== undefined) {
        // declaredContext > targetContext. Only an explicit discovery result may
        // lower a user-declared window; otherwise we would silently downgrade.
        issues.push(makeIssue(
          'CONTEXT_OVER_MAX',
          'warn',
          `模型「${id}」声明的上下文窗口 ${declaredContext} 超过模型实际最大可用值 ${targetContext}，将按 ${targetContext} 写入。`,
          { model: id, fixable: true },
        ));
        ensureChange(id).contextWindow = targetContext;
      }
    }
  }

  // --- Route-level default context window ------------------------------
  const routeContextTooLow = routeDefault !== undefined && routeDefault < DEFAULT_CONTEXT_WINDOW;
  if (routeContextTooLow) {
    issues.push(makeIssue(
      'ROUTE_CONTEXT_LOW',
      'warn',
      `路由「${routeLabel}」的默认上下文窗口 ${routeDefault} 小于最大上下文 ${DEFAULT_CONTEXT_WINDOW}。`,
      { fixable: true },
    ));
  }

  // --- Requirement 2: describer selection / vision fallback ------------
  const describerPinned = trimToId(snap.describerModel);
  const anyImageModel = models.some((model) => effectiveOf(model.id) === 'image');

  let describerId = null;
  if (describerPinned && effectiveOf(describerPinned) !== 'text') {
    describerId = describerPinned;
  } else {
    const firstImage = models.find((model) => effectiveOf(model.id) === 'image');
    describerId = firstImage ? firstImage.id : null;
  }

  const allUnknown = models.length > 0 && models.every((model) => effectiveOf(model.id) === 'unknown');
  // An empty model list is not this rule's business (there is nothing to describe
  // and nothing to repair); report NO_IMAGE_MODEL only when models are configured.
  if (models.length > 0 && !anyImageModel) {
    issues.push(makeIssue(
      'NO_IMAGE_MODEL',
      'error',
      '没有检测到任何真正支持多模态（可看图）的模型：请至少配置一个多模态模型，或在 imageModels 中把某个模型钉为可看图。',
      { fixable: false },
    ));
  }
  if (describerPinned && effectiveOf(describerPinned) === 'text') {
    issues.push(makeIssue(
      'DESCRIBER_NOT_MULTIMODAL',
      'error',
      `钉住的识图模型「${describerPinned}」被判定为纯文本，无法用于识图；请改用一个真正支持多模态的模型。`,
      { model: describerPinned, fixable: false },
    ));
  }
  if (allUnknown) {
    issues.push(makeIssue(
      'CAPABILITY_UNKNOWN',
      'info',
      '所有模型的多模态能力都未能确定（探测未完成或失败），因此无法自动选择识图模型。',
      { fixable: false },
    ));
  }

  const vision = isObjectLike(snap.vision) ? snap.vision : null;
  if (vision && vision.present === true) {
    const visionModel = trimToId(vision.model) ?? null;
    const mismatch = visionModel !== describerId || vision.autoDescribe !== true;
    if (mismatch) {
      issues.push(makeIssue(
        'VISION_PLUGIN_MISMATCH',
        'info',
        `第三方 vision 插件的识图模型「${visionModel ?? '未设置'}」与本次选定的识图模型「${describerId ?? '无'}」不一致，或未开启 autoDescribe；这不影响本插件自带的运行时回退。`,
        { fixable: false },
      ));
    }
  }

  // --- Assemble plan ---------------------------------------------------
  const changedModels = Object.fromEntries(modelChanges.entries());
  /** @type {{models: object, defaultContextWindow?: number}} */
  const llmChanges = { models: changedModels };
  if (routeContextTooLow) {
    llmChanges.defaultContextWindow = DEFAULT_CONTEXT_WINDOW;
  }

  const sortedIssues = sortIssues(issues);
  const compliant = sortedIssues.every((issue) => issue.severity !== 'error')
    && Object.keys(changedModels).length === 0
    && llmChanges.defaultContextWindow === undefined;

  const summary = {
    totalModels: models.length,
    imageTagged: models.reduce((count, model) => count + (model.input.includes('image') ? 1 : 0), 0),
    imageCapable: models.reduce((count, model) => count + (effectiveOf(model.id) === 'image' ? 1 : 0), 0),
    textOnly: models.reduce((count, model) => count + (effectiveOf(model.id) === 'text' ? 1 : 0), 0),
    unknown: models.reduce((count, model) => count + (effectiveOf(model.id) === 'unknown' ? 1 : 0), 0),
    maxContextWindow: models.length === 0 ? 0 : Math.max(...targets.values()),
  };
  if (describerId !== null) summary.describerModel = describerId;
  summary.compliant = compliant;

  return {
    issues: sortedIssues,
    llmChanges,
    describer: describerId === null ? null : { model: describerId },
    summary,
  };
}

/* ------------------------------------------------------------------ *
 * Snapshot normalisation
 * ------------------------------------------------------------------ */

/**
 * Keep only usable model entries (object with a non-empty string id), de-duplicated
 * by id with the first occurrence winning. Defensive against `models: null`,
 * `models: [null, {}]`, duplicated ids, etc.
 */
function collectModels(snapshot) {
  const rawModels = Array.isArray(snapshot.models) ? snapshot.models : [];
  const seen = new Set();
  const models = [];

  for (const entry of rawModels) {
    if (!isObjectLike(entry)) continue;
    const id = trimToId(entry.id);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    models.push({
      id,
      entry,
      input: normalizeStringList(entry.input),
    });
  }

  return models;
}
