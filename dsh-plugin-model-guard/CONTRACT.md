# dsh-plugin-model-guard — 内部接口契约

> 本文件是分块开发的接口契约。实现必须严格遵守下面的导出名、入参、返回值形状；
> 任何实现细节可以自行决定，但**不要**修改这些签名（Lead 负责集成）。

包目录：`/Users/oswaldhill/personal/skill-mcp-studio/dsh-plugin-model-guard/`

运行环境：Node.js >= 20，纯 ESM（`.mjs`），**禁止 import 任何 `@deepseek-ai/*` 包**
（保持零依赖，避免 profile 安装时的解析风险）。除 Node 内置模块外不得有第三方依赖。

## 目标（来自用户需求）

每次启动 DSH 时检查 `llm-pi-ai` 插件里配置的所有自定义模型：

1. 所有模型都要开启 `image` 输入标签（`input` 包含 `"image"`），使界面允许提交图片；
2. 识图逻辑：当前模型真正支持多模态就直接用；否则先用列表中真正支持多模态的模型识别，
   再把识别结果交给当前模型（运行时由 `lib/describe.mjs` + `index.js` 的 `agent/pre-step` 实现）；
3. 所有模型默认上下文使用「官方指定的或获取到的最大上下文空间」；
4. 每次启动检查，发现问题要能告知用户并让用户决定是否修复。

本契约覆盖：`lib/probe.mjs`（能力探测/模型发现）、`lib/audit.mjs`（纯函数体检与修复计划）。
运行时识图与配置落盘由 Lead 在 `index.js` / `lib/describe.mjs` 实现，不在本契约内。

---

## 1. `lib/probe.mjs`

只做 HTTP，不认识 DSH。所有函数必须接受可注入的 `fetchImpl`（默认 `globalThis.fetch`），
便于测试；必须处理超时与网络错误，**不得抛异常**（返回错误字段）。

```js
export const PROBE_IMAGE_PNG_BASE64 = '...'; // 16x16 纯红色 PNG 的 base64（不含 data: 前缀）
/** 随机多目标：读取图中的 4 位数字（猜中概率 1/10000），比认颜色可靠得多。 */
export const PROBE_TARGETS = [{ digits: '9214', base64: '...' }, /* ... */];

/**
 * 探测某个模型是否真的能看图。
 * @param {object} input
 * @param {string} input.baseURL      端点根，如 https://api.pd-h.top/v1
 * @param {string} input.api          线格式：'openai-completions' | 'openai-responses' | 'anthropic-messages' | 其他
 * @param {string} [input.apiKey]     Bearer/x-api-key；空则不带鉴权头
 * @param {string} input.model        模型 id
 * @param {string} [input.probe]      固定使用某个探测目标（测试用），缺省随机
 * @param {number} [input.timeoutMs]  默认 8000
 * @param {Function} [input.fetchImpl]
 * @returns {Promise<{
 *   verdict: 'image'|'text'|'unknown',
 *   status?: number,
 *   detail?: string,     // 简短原因，给日志/报告用（不含密钥）
 * }>}
 */
export async function probeImageSupport(input)

/**
 * 读取端点声明的模型清单（GET {baseURL}/models 或 anthropic 的 /v1/models）。
 * @param {object} input  { baseURL, api, apiKey, timeoutMs?, fetchImpl? }
 * @returns {Promise<{
 *   models: Array<{
 *     id: string,
 *     contextWindow?: number,
 *     maxTokens?: number,
 *     inputModalities?: string[],
 *   }>,
 *   error?: string,
 * }>}
 */
export async function discoverModels(input)

/** 端点路径归一化（去掉尾部斜杠），导出让 audit/index 复用。 */
export function normalizeEndpoint(baseURL)
```

### probe 判定规则（重要）

请求：`POST {normalizeEndpoint(baseURL)}/chat/completions`
（`api === 'anthropic-messages'` 时改为 `POST {..}/messages`，用 `x-api-key` +
`anthropic-version: 2023-06-01`，body 用 base64 `source` 块；`openai-responses` 其它情况
一律走 `/chat/completions`）

OpenAI 线格式 body：

```json
{
  "model": "<model>",
  "max_tokens": 24,
  "stream": false,
  "messages": [{
    "role": "user",
    "content": [
      { "type": "text", "text": "What color is this image? Answer with one word." },
      { "type": "image_url", "image_url": { "url": "data:image/png;base64,<PROBE_IMAGE_PNG_BASE64>" } }
    ]
  }]
}
```

判定（按顺序）：

1. HTTP 200：
   - 响应文本能提取出 `choices[0].message.content`（anthropic 为 `content[0].text`）：
     - 文本匹配 `/red|红色|红/i` → `verdict: 'image'`（可信：模型确实看到了红色图）。
     - 文本匹配 `/can(?:no|')?t see|unable to see|can ?not view|no image|not able to (?:see|view)|看不到|无法查看|没有图片/i` → `verdict: 'text'`。
     - 其它（例如回 "OK" 或空）→ `verdict: 'unknown'`，`detail` 说明"端点为 200 但没有报告颜色"。
2. HTTP 4xx（除 401/403/429）：
   - 响应体匹配 `/image|vision|multimodal|modality|图片|图像|不支持/i` → `verdict: 'text'`。
   - 否则 → `verdict: 'text'`，`detail` 记录状态与响应体前 200 字符。
3. HTTP 401/403/429/5xx、AbortError、网络错误 → `verdict: 'unknown'`，`detail` 说明原因。
4. 任何解析异常都不得抛出，返回 `unknown`。

`discoverModels` 解析兼容 OpenAI 风格 `{data:[...]}` 与 `{models:{...}}` 两种形状；
每个模型的 `contextWindow` 依次尝试 `contextWindow` / `context_window` / `context_length` /
`max_input_tokens` / `limit.context`；`maxTokens` 尝试 `maxOutputTokens` / `max_output_tokens` /
`maxTokens` / `max_tokens` / `limit.output`；`inputModalities` 尝试
`architecture.input_modalities` / `input_modalities` / `modalities.input`（只接受 string[]）。
非 200 时返回 `{models: [], error: 'HTTP <status>'}`；解析失败返回 `{models: [], error: '...'}`。

---

## 2. `lib/audit.mjs`

纯函数，无 I/O。**所有面向用户的文案用中文**；对外的稳定标识是 `code`。

```js
export const DEFAULT_CONTEXT_WINDOW = 262144;
export const DEFAULT_MAX_TOKENS = 32768;

/**
 * @typedef {object} ModelEntry
 * @property {string} id
 * @property {string} [name]
 * @property {string[]} [input]          // 配置里已声明的输入模态，如 ['text']
 * @property {number} [contextWindow]
 * @property {number} [maxTokens]
 *
 * @typedef {object} Snapshot
 * @property {string} route                       // provider 路由名，如 'pudding-home-api'
 * @property {ModelEntry[]} models                // 路由下配置的全部自定义模型
 * @property {Object<string,'image'|'text'|'unknown'>} [capabilities]  // 探测/钉住得到的真实能力
 * @property {Object<string,{contextWindow?:number,maxTokens?:number,inputModalities?:string[]}>} [discovered]
 * @property {number} [defaultContextWindow]
 * @property {number} [defaultMaxTokens]
 * @property {string} [describerModel]            // 用户钉住的识图模型
 * @property {{present:boolean, model?:string, baseURL?:string, autoDescribe?:boolean, provider?:string}} [vision]
 * @property {string[]} [imageModels]             // 手工钉住为「能看图」
 * @property {string[]} [textModels]              // 手工钉住为「纯文本」
 *
 * @typedef {object} Issue
 * @property {string} code        // 稳定标识，见下表
 * @property {'error'|'warn'|'info'} severity
 * @property {string} message     // 中文，一句话说清问题与期望值
 * @property {string} [model]
 * @property {boolean} fixable    // true 表示可在用户同意后由插件自动改配置
 *
 * @typedef {object} Plan
 * @property {Issue[]} issues
 * @property {{
 *   models: Object<string,{input?:string[], contextWindow?:number}>,
 *   defaultContextWindow?: number,
 * }} llmChanges                     // 需要写入 llm-pi-ai 配置的完整目标值（空对象表示无需改）
 * @property {{model:string}|null} describer   // 运行时识图应当使用的模型（null = 无法确定）
 * @property {{
 *   totalModels:number, imageTagged:number, imageCapable:number,
 *   textOnly:number, unknown:number,
 *   maxContextWindow:number, describerModel?:string, compliant:boolean,
 * }} summary
 */

/** @returns {Plan} */
export function auditSnapshot(snapshot)
```

### 规则

**能力判定**（每个模型）：
`effective = textModels 含该 id ? 'text' : imageModels 含该 id ? 'image' : capabilities[id] ?? 'unknown'`

**输入标签（需求 1）**：目标 `input` 恒为 `['text','image']`。
- 若模型当前 `input` 不含 `'image'` → issue `IMAGE_TAG_OFF`（severity `error`，fixable true），
  并在 `llmChanges.models[id].input = ['text','image']` 中列出。

**上下文（需求 3）**：目标值
`target = discovered[id].contextWindow ?? defaultContextWindow ?? DEFAULT_CONTEXT_WINDOW`
- 若 `target` 与当前有效 `contextWindow`（`models[i].contextWindow ?? defaultContextWindow ??
  DEFAULT_CONTEXT_WINDOW`）不同 → issue：
  - 当前未声明且 target 存在 → `CONTEXT_NOT_MAX`（severity `warn`，fixable true），message 写明
    “当前未声明（回退 X），最大为 Y”。
  - 当前声明但小于 target → `CONTEXT_BELOW_MAX`（`warn`，fixable true）。
  - 当前声明大于 target（只在 discovery 明确给出时发生）→ `CONTEXT_OVER_MAX`（`warn`，
    fixable true，写入 target；说明模型实际只能到 target）。
  - 两种都应写 `llmChanges.models[id].contextWindow = target`。
- 只有当某个值确实需要改变时才写 changes；不需要改时不出现在 `llmChanges.models`。
- 路由级：若 `defaultContextWindow` 显式给出且 `< DEFAULT_CONTEXT_WINDOW` → issue
  `ROUTE_CONTEXT_LOW`（`warn`，fixable true），`llmChanges.defaultContextWindow =
  DEFAULT_CONTEXT_WINDOW`；否则不要写 `defaultContextWindow`。

**识图回退（需求 2）**：
- 选 describer：`describerModel`（仅当它的 effective 能力不是 `'text'`）→ 否则第一个
  effective === `'image'` 的模型 → 否则 null。
- 若没有任何模型 `effective === 'image'` → issue `NO_IMAGE_MODEL`（severity `error`，
  fixable **false**，message 说明需要至少一个真正支持多模态的模型，或把某个模型钉为
  imageModels）。
- 若 `describerModel` 钉住但被钉为/探测为 text → issue `DESCRIBER_NOT_MULTIMODAL`
  （`error`，fixable false）。
- 若所有模型都是 `unknown`（探测未完成/失败）→ issue `CAPABILITY_UNKNOWN`（`info`，
  fixable false），不影响 compliant。
- `vision.present === true` 且（`vision.model` 与 describer 不一致 或
  `vision.autoDescribe !== true`）→ issue `VISION_PLUGIN_MISMATCH`（`info`，fixable false，
  说明第三方 vision 插件的识图模型与本次选定的不一致，其实不影响本插件的运行时回退）。
- `vision.present !== true` → 不报 issue（本插件自带回退）。

**summary**：统计数量；`compliant = issues.every(i => i.severity !== 'error')` 且
`llmChanges.models` 为空对象且 `llmChanges.defaultContextWindow === undefined`。
`maxContextWindow` = 所有模型 target 的最大值。

**排序**：`issues` 先按 severity（error > warn > info）再按 `code`。

### 测试要求（`test/audit.test.js`）

用 `node:test` + `node:assert/strict`，至少覆盖：
1. 全部合规时 `issues` 为空、`compliant === true`；
2. `input: ['text']` → `IMAGE_TAG_OFF` 且 changes 里有 `['text','image']`；
3. 未声明 contextWindow → `CONTEXT_NOT_MAX`，target 取 discovery 值；
4. discovery 值大于已声明值 → `CONTEXT_BELOW_MAX`；小于已声明值 → `CONTEXT_OVER_MAX`；
5. 无 image 能力模型 → `NO_IMAGE_MODEL`（不可修）；
6. describer 选择顺序：钉住 > 第一个 image；钉住但 text → `DESCRIBER_NOT_MULTIMODAL`；
7. `vision.present` 且 model 不一致 → `VISION_PLUGIN_MISMATCH`；
8. summary 统计与 `compliant` 判定。

---

## 3. 约定

- 文件名固定：`lib/probe.mjs`、`lib/audit.mjs`、`test/probe.test.js`、`test/audit.test.js`。
- 注释用英文或中文均可，但**用户可见文案必须中文**。
- 不要修改 `index.js`、`lib/describe.mjs`、`package.json`、`cordis.patch.yml`、`locale/*`、
  `README.md`（由 Lead / 其他成员负责）。
- 完成后运行 `node --check` 与 `node --test test/<yours>.test.js` 自测通过。
