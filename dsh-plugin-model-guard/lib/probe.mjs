/**
 * lib/probe.mjs — HTTP-only capability probing / model discovery.
 *
 * Knows nothing about DSH. Every exported function takes an injectable
 * `fetchImpl` (default `globalThis.fetch`) so tests never touch the network.
 * Nothing in this module throws for HTTP, network, timeout or parsing
 * failures: failures are reported through the documented return objects.
 *
 * Zero dependencies: Node built-ins only (none are needed here).
 */

/** Default request timeout in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 8000;

/**
 * 16x16 solid-red PNG (8-bit truecolour RGB), generated with zlib and
 * verified by decoding it back: PNG signature, IHDR 16x16, filter byte 0 per
 * scanline, every pixel exactly rgb(255, 0, 0).
 */
export const PROBE_IMAGE_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR42mP4z8BAEmIY1TCqYfhqAACQ+f8B8u7oVwAAAABJRU5ErkJggg==';

/**
 * Solid-colour probes the model has to NAME. A single fixed colour can be
 * guessed; drawing one of six colours at random makes a lucky answer rare, and
 * lets the answer inside a reasoning trace count as evidence.
 */
/**
 * Probe images that carry a random four-digit number. A colour can be guessed
 * one time in six; a number cannot, so naming the digits is real evidence that
 * the pixels arrived. The digits also survive a reasoning-only reply, because
 * they show up in the trace too.
 */
export const PROBE_TARGETS = Object.freeze([
  {
    digits: '5533',
    base64: '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',
  },
  {
    digits: '4147',
    base64: 'iVBORw0KGgoAAAANSUhEUgAAAPAAAABgCAIAAACsUWiGAAAFXklEQVR42u3dT0iTfxzA8eeZZlgD/3QyC2MquyTaoYs4T4ZQUtAhpwOTWM2DmqGC6EERD+FFVKoRFpToIAkWVAeDhKhDUdQO/gG1QemhiLZ0DB5yrsMPfsjzaM7fnnr2fX7v1/EbPftsvnv69uzZkuPxuASYhYWXAAQNEDRA0ABBg6ABggYIGiBogKBB0ABBAwQNEDRA0CBogKABggYIGiBoEDRA0ABBAwQNEDQIGiBogKBFcePGDVkjEonwyhD0n7W2tmaz2VTlHTlyJJljbmxsDA0NpdrkjY2Nsn6cTidBp6KmpqZgMKjvMQcHB5eXl0WcnDO02O7du+fz+fQ95rt37/r7+0WcnKDFtri42NzcrO8xg8HgmTNnFEURbnKCFtvPnz/r6+v1/VdaIBBwOBxfvnwRbnKCFl53d/fbt291PODU1JTD4VhdXRVu8v+duOlMT0/Lsvybp5yfn5/40cLh8KVLlxJ5JdfX1w2c/OLFi3olcfDgwVevXgn60zfbGfrr168NDQ26/Mcxm5ub9+/ft9vtd+/eFWvyZGRkZPj9/vLycs7Qxtvc3Dx9+vSuT3nXM3Q4HL5165bdbt/TK5nMGVqvyfekq6tL+xBer1foBkwVdILvd+yaxdWrV//DqSGZoPWaPHGPHz/Wbm/cbrfoDZgn6Pfv3+/fv/9PB52VlVVaWqpv0DpOnqBgMJiTk6M6uN1uj0ajomdgkj10NBqtq6tTXSGWZbmsrEzHRzl06NDz58+PHz8u3ORbxWIxp9MZCoW2Lqanp4+Pj2dmZopeQro5gm5tbV1YWFAttrW1WSyWDx8+6PIQNpvt0aNH+tb8dyZXGR4efv36tWqxs7Pz5MmTXLZLCQ8ePNA+rxMnTiiK0t7ersuW49y5c6FQ6J9fdblcem05dJ98Vx8/fjxw4IDqsMeOHTPBZsMkW45Pnz5duXJFeyXV5/NlZGToss3wer1+vz87O1usybfl8Xii0ahqcXR01ASbDTNsOWKxmMvlCofDqvWRkZG9XnTT2rdvn9vtHhgYyM3NFWvynfj9/mfPnqkWT506VVNTY5o3IsQOur+//+XLl6rFCxcuJPje3k5yc3O7urpaWloOHz4s1uS//yPU09OjWpRl+fr16xJvfaeCFy9epKWlqZ5OQUHBv5vdeDz+J3aiye+hDZn8zp072gPW1taa7MYHUffQoVDI5XLFYrGti2lpaZOTk7pvdk0wuaIofX192nXtOVvibjtDXL58+fPnz6rF3t7e1L8JwZDJJycntQ9aXV1dUlJC0Ma7ffv2w4cPVYuVlZXd3d1MLu1w7Vm72NHRIUncD220+fn5a9euqRZzcnImJia0G1MmlyRpZmYmEAioFouLi6uqqgjaYIqi1NXVaa+kjo2NJflZbhNPvu3pubGxUZL4xIrROjs7tScbj8dz/vx5Jt/Wt2/fnjx5ov6pWywNDQ0Sn1gxnNVq1f0VKCws/AuX7Yya/ObNm9rfWFlZGTcpi3B//MQ9cRjyuNt+HcLZs2cliQ/JQjQrKyva9yMJGqJ6+vSp9m+GoqKi4uJigoZ4ZmZmtt1AS3wvB0wTtMPhIGiIZ25ubtvveaqoqCDoVBGJRPZ0ESeRe9aWlpZMOfmbN2+0i1artbCwkKAh5Blau1hSUvL7L2ciaKSo2dlZ7aLuH/IlaBh5hi4oKCBoSIK+q6JdPHr0KEFDPD9+/NjY2NCu5+XlETTE8/37d2mHr8olaJgnaO23zJiMLO79awBnaBA0QNAAQQMEDRA0CBogaICgAYIGCBoEDRA0QNAAQYOgAYIGCBogaICgQdAAQQMEDRA0QNAgaICggRTxC4CKTFH9Mar9AAAAAElFTkSuQmCC',
  },
  {
    digits: '9932',
    base64: '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',
  },
  {
    digits: '9804',
    base64: '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',
  },
  {
    digits: '1723',
    base64: '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',
  },
  {
    digits: '9625',
    base64: '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',
  },
]);

/**
 * Reasoning models may spend the whole budget thinking and never emit a final
 * answer, so this must be generous; a truncated trace is still evidence.
 */
const PROBE_MAX_TOKENS = 512;

const PROBE_PROMPT = 'Read the digits in this image. Reply with the digits only.';
const ANTHROPIC_API_VERSION = '2023-06-01';
const ANTHROPIC_API = 'anthropic-messages';

/** Explicit "I cannot see the image" style refusals. */
const REFUSAL_PATTERN =
  /(?:can(?:no|')?t|don'?t|do not|didn'?t|unable to) see|can ?not view|no image|not able to (?:see|view)|看不到|无法查看|没有图片|未收到图片/i;

/** Server-side wording that means "this model does not take images". */
const MODALITY_HINT_PATTERN = /image|vision|multimodal|modality|图片|图像|不支持/i;

/** How many characters of a response body we keep in `detail`. */
const DETAIL_CLIP = 200;

/** How many characters of a network error message we keep. */
const ERROR_CLIP = 200;

/**
 * Normalise an endpoint root by trimming whitespace and dropping trailing
 * slashes. Non-string / empty input yields an empty string (callers treat that
 * as "no endpoint").
 *
 * @param {string} baseURL
 * @returns {string}
 */
export function normalizeEndpoint(baseURL) {
  if (typeof baseURL !== 'string') return '';
  return baseURL.trim().replace(/\/+$/, '');
}

/**
 * Remove an API key from arbitrary text so `detail` / `error` never leaks
 * credentials (some proxies echo the Authorization header back).
 *
 * @param {string} text
 * @param {string} [apiKey]
 * @returns {string}
 */
function redactSecret(text, apiKey) {
  const value = typeof text === 'string' ? text : '';
  if (typeof apiKey !== 'string' || apiKey.length < 4) return value;
  return value.split(apiKey).join('[redacted]');
}

/**
 * Collapse whitespace and clip to at most `max` characters.
 *
 * @param {unknown} value
 * @param {number} [max]
 * @returns {string}
 */
function collapse(value, max = DETAIL_CLIP) {
  if (value === undefined || value === null) return '';
  const text = String(value).replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/**
 * Read a fetch Response body as text without ever throwing.
 *
 * @param {any} response
 * @returns {Promise<string>}
 */
async function readBody(response) {
  if (!response || typeof response.text !== 'function') return '';
  try {
    const raw = await response.text();
    return typeof raw === 'string' ? raw : '';
  } catch {
    return '';
  }
}

/** @param {string} text */
function tryParseJson(text) {
  if (!text) return { ok: false, parsed: undefined };
  try {
    return { ok: true, parsed: JSON.parse(text) };
  } catch {
    return { ok: false, parsed: undefined };
  }
}

/**
 * Pull the assistant reply out of an OpenAI-style response.
 *
 * @param {any} payload
 * @returns {string}
 */
function extractOpenAIReply(payload) {
  const choice = payload?.choices?.[0];
  const content = choice?.message?.content ?? choice?.text;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    const parts = [];
    for (const part of content) {
      if (typeof part === 'string') parts.push(part);
      else if (part && typeof part.text === 'string') parts.push(part.text);
    }
    return parts.join('\n');
  }
  return '';
}

/**
 * Pull the assistant reply out of an Anthropic-style response.
 *
 * @param {any} payload
 * @returns {string}
 */
function extractAnthropicReply(payload) {
  const content = payload?.content;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    const parts = [];
    for (const block of content) {
      if (typeof block === 'string') parts.push(block);
      else if (block && typeof block.text === 'string') parts.push(block.text);
    }
    return parts.join('\n');
  }
  return '';
}

/**
 * Pull a reasoning trace out of a response, when the provider returns one.
 * OpenAI-compatible gateways expose it as `reasoning_content` (or `reasoning`);
 * Anthropic returns `thinking` blocks.
 *
 * @param {string} api
 * @param {any} payload
 * @returns {string}
 */
function extractReasoningText(api, payload) {
  if (api === ANTHROPIC_API) {
    const content = payload?.content;
    if (!Array.isArray(content)) return '';
    return content
      .filter((block) => block && (block.type === 'thinking' || block.type === 'redacted_thinking'))
      .map((block) => (typeof block.thinking === 'string' ? block.thinking : ''))
      .join('\n');
  }
  const message = payload?.choices?.[0]?.message ?? {};
  const trace = message.reasoning_content ?? message.reasoning ?? message.reasoning_text;
  return typeof trace === 'string' ? trace : '';
}

/**
 * @param {string} api
 * @param {any} payload
 * @returns {string}
 */
function extractReplyText(api, payload) {
  return api === ANTHROPIC_API ? extractAnthropicReply(payload) : extractOpenAIReply(payload);
}

/**
 * @param {string} api
 * @param {string} [apiKey]
 * @returns {Record<string, string>}
 */
function probeHeaders(api, apiKey) {
  const headers = { 'content-type': 'application/json' };
  const hasKey = typeof apiKey === 'string' && apiKey.length > 0;
  if (api === ANTHROPIC_API) {
    headers['anthropic-version'] = ANTHROPIC_API_VERSION;
    if (hasKey) headers['x-api-key'] = apiKey;
  } else if (hasKey) {
    headers.authorization = `Bearer ${apiKey}`;
  }
  return headers;
}

/**
 * @param {string} api
 * @param {string} [apiKey]
 * @returns {Record<string, string>}
 */
function discoveryHeaders(api, apiKey) {
  const headers = { accept: 'application/json' };
  const hasKey = typeof apiKey === 'string' && apiKey.length > 0;
  if (api === ANTHROPIC_API) {
    headers['anthropic-version'] = ANTHROPIC_API_VERSION;
    if (hasKey) headers['x-api-key'] = apiKey;
  } else if (hasKey) {
    headers.authorization = `Bearer ${apiKey}`;
  }
  return headers;
}

/**
 * @param {string} model
 * @returns {object}
 */
function openAIBody(model, target) {
  return {
    model,
    max_tokens: PROBE_MAX_TOKENS,
    stream: false,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'text', text: PROBE_PROMPT },
          {
            type: 'image_url',
            image_url: { url: `data:image/png;base64,${target.base64}` },
          },
        ],
      },
    ],
  };
}

/**
 * @param {string} model
 * @returns {object}
 */
function anthropicBody(model, target) {
  return {
    model,
    max_tokens: PROBE_MAX_TOKENS,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'text', text: PROBE_PROMPT },
          {
            type: 'image',
            source: {
              type: 'base64',
              media_type: 'image/png',
              data: target.base64,
            },
          },
        ],
      },
    ],
  };
}

/**
 * @param {unknown} error
 * @param {number} timeoutMs
 * @param {string} [apiKey]
 * @returns {string}
 */
function describeTransportFailure(error, timeoutMs, apiKey) {
  const name = error && typeof error === 'object' ? String(error.name ?? '') : '';
  if (name === 'AbortError' || name === 'TimeoutError') {
    return `request timed out after ${timeoutMs}ms`;
  }
  if (name === 'SyntaxError') {
    return 'could not read the response body';
  }
  const message =
    error && typeof error === 'object' && typeof error.message === 'string'
      ? error.message
      : typeof error === 'string'
        ? error
        : '';
  const safe = collapse(redactSecret(message, apiKey), ERROR_CLIP);
  return `network error: ${safe || name || 'unknown failure'}`;
}

/**
 * Classify an already-received probe response.
 *
 * @param {any} response
 * @param {{api: string, apiKey?: string}} context
 * @returns {Promise<{verdict: 'image'|'text'|'unknown', status?: number, detail?: string}>}
 */
async function classifyProbeResponse(response, context) {
  const status = typeof response?.status === 'number' ? response.status : 0;
  const raw = redactSecret(await readBody(response), context.apiKey);
  const target = context.target ?? PROBE_TARGETS[0];

  // 1. Success: the reply tells us whether the model actually saw the image.
  if (status >= 200 && status < 300) {
    const { ok, parsed } = tryParseJson(raw);
    const reply = collapse(ok ? extractReplyText(context.api, parsed) : raw);
    // A reasoning model can burn the whole budget thinking and never answer, so a
    // colour named only inside the trace still proves the pixels arrived.
    const reasoning = collapse(ok ? extractReasoningText(context.api, parsed) : '');
    // A bare digit string parses as JSON (number 5533), which carries no message
    // shape at all; fall back to the raw body so such a reply is still read.
    const evidence = [reply, reasoning].filter((part) => part.length > 0).join('\n') || raw;
    if (evidence.includes(target.digits)) {
      return { verdict: 'image', status, detail: `the model read the probe digits (${target.digits})` };
    }
    if (REFUSAL_PATTERN.test(evidence)) {
      return { verdict: 'text', status, detail: 'the model said it could not see the image' };
    }
    if (!reply) {
      return { verdict: 'unknown', status, detail: `HTTP ${status} but the response carried no readable text` };
    }
    return {
      verdict: 'unknown',
      status,
      detail: `HTTP ${status} but the reply did not name the probe colour: ${reply}`,
    };
  }

  // 2. Client-side rejection: something about the payload was refused.
  //    401/403/429 say nothing about image support, so they stay 'unknown'.
  if (status >= 400 && status < 500 && status !== 401 && status !== 403 && status !== 429) {
    if (MODALITY_HINT_PATTERN.test(raw)) {
      return {
        verdict: 'text',
        status,
        detail: `HTTP ${status}: the endpoint rejected image input (${collapse(raw) || 'no body'})`,
      };
    }
    return {
      verdict: 'text',
      status,
      detail: `HTTP ${status}: ${collapse(raw) || 'request rejected'}`,
    };
  }

  // 3. Auth / rate limit / server / transport problems prove nothing.
  if (status === 401) {
    return { verdict: 'unknown', status, detail: 'HTTP 401: missing or rejected credentials' };
  }
  if (status === 403) {
    return { verdict: 'unknown', status, detail: 'HTTP 403: access forbidden' };
  }
  if (status === 429) {
    return { verdict: 'unknown', status, detail: 'HTTP 429: rate limited, try again later' };
  }
  if (status >= 500) {
    return { verdict: 'unknown', status, detail: `HTTP ${status}: endpoint server error` };
  }
  if (!status) {
    return { verdict: 'unknown', detail: 'the response had no HTTP status' };
  }
  return { verdict: 'unknown', status, detail: `HTTP ${status}: unexpected status` };
}

/**
 * Probe whether `model` on the given endpoint can actually read images.
 *
 * Sends one tiny red PNG and asks for its colour. Never throws.
 *
 * @param {object} input
 * @param {string} input.baseURL      endpoint root, e.g. https://api.example.com/v1
 * @param {string} input.api          'openai-completions' | 'openai-responses' | 'anthropic-messages' | other
 * @param {string} [input.apiKey]     Bearer / x-api-key; omitted when empty
 * @param {string} input.model        model id
 * @param {number} [input.timeoutMs]  default 8000
 * @param {Function} [input.fetchImpl]
 * @returns {Promise<{verdict: 'image'|'text'|'unknown', status?: number, detail?: string}>}
 */
export async function probeImageSupport(input) {
  const opts = input && typeof input === 'object' ? input : {};
  const api = typeof opts.api === 'string' && opts.api ? opts.api : 'openai-completions';
  const apiKey = typeof opts.apiKey === 'string' ? opts.apiKey : '';
  const timeoutMs =
    typeof opts.timeoutMs === 'number' && Number.isFinite(opts.timeoutMs) && opts.timeoutMs > 0
      ? opts.timeoutMs
      : DEFAULT_TIMEOUT_MS;
  const fetchImpl = typeof opts.fetchImpl === 'function' ? opts.fetchImpl : globalThis.fetch;
  const base = normalizeEndpoint(opts.baseURL);
  const model = typeof opts.model === 'string' ? opts.model.trim() : '';

  if (typeof fetchImpl !== 'function') {
    return { verdict: 'unknown', detail: 'no fetch implementation available' };
  }
  if (!base) {
    return { verdict: 'unknown', detail: 'missing or invalid baseURL' };
  }
  if (!model) {
    return { verdict: 'unknown', detail: 'missing model id' };
  }

  const url = api === ANTHROPIC_API ? `${base}/messages` : `${base}/chat/completions`;
  const wanted = typeof opts.probe === 'string' ? opts.probe.trim() : '';
  const target =
    PROBE_TARGETS.find((entry) => entry.digits === wanted) ??
    PROBE_TARGETS[Math.floor(Math.random() * PROBE_TARGETS.length)] ??
    PROBE_TARGETS[0];
  const body = api === ANTHROPIC_API ? anthropicBody(model, target) : openAIBody(model, target);

  try {
    const response = await fetchImpl(url, {
      method: 'POST',
      headers: probeHeaders(api, apiKey),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
    return await classifyProbeResponse(response, { api, apiKey, target });
  } catch (error) {
    return { verdict: 'unknown', detail: describeTransportFailure(error, timeoutMs, apiKey) };
  }
}

/** Candidate field paths for `contextWindow`, in contract order. */
const CONTEXT_WINDOW_PATHS = [
  ['contextWindow'],
  ['context_window'],
  ['context_length'],
  ['max_input_tokens'],
  ['limit', 'context'],
];

/** Candidate field paths for `maxTokens`, in contract order. */
const MAX_TOKENS_PATHS = [
  ['maxOutputTokens'],
  ['max_output_tokens'],
  ['maxTokens'],
  ['max_tokens'],
  ['limit', 'output'],
];

/** Candidate field paths for `inputModalities`, in contract order. */
const INPUT_MODALITIES_PATHS = [
  ['architecture', 'input_modalities'],
  ['input_modalities'],
  ['modalities', 'input'],
];

/**
 * @param {any} source
 * @param {string[]} path
 * @returns {unknown}
 */
function readPath(source, path) {
  let current = source;
  for (const key of path) {
    if (!current || typeof current !== 'object') return undefined;
    current = current[key];
  }
  return current;
}

/**
 * @param {any} source
 * @param {string[][]} paths
 * @returns {number|undefined}
 */
function pickNumber(source, paths) {
  for (const path of paths) {
    const value = readPath(source, path);
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return undefined;
}

/**
 * @param {any} source
 * @param {string[][]} paths
 * @returns {string[]|undefined}
 */
function pickStringArray(source, paths) {
  for (const path of paths) {
    const value = readPath(source, path);
    if (Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'string')) {
      return value.slice();
    }
  }
  return undefined;
}

/**
 * @param {any} entry
 * @param {string} [fallbackId]
 * @returns {{id: string, contextWindow?: number, maxTokens?: number, inputModalities?: string[]}|undefined}
 */
function normalizeModelEntry(entry, fallbackId) {
  const source = entry && typeof entry === 'object' ? entry : undefined;
  const rawId = source && typeof source.id === 'string' ? source.id : '';
  const id = rawId.trim() || (typeof fallbackId === 'string' ? fallbackId.trim() : '');
  if (!id) return undefined;

  /** @type {{id: string, contextWindow?: number, maxTokens?: number, inputModalities?: string[]}} */
  const model = { id };
  if (source) {
    const contextWindow = pickNumber(source, CONTEXT_WINDOW_PATHS);
    if (contextWindow !== undefined) model.contextWindow = contextWindow;
    const maxTokens = pickNumber(source, MAX_TOKENS_PATHS);
    if (maxTokens !== undefined) model.maxTokens = maxTokens;
    const inputModalities = pickStringArray(source, INPUT_MODALITIES_PATHS);
    if (inputModalities !== undefined) model.inputModalities = inputModalities;
  }
  return model;
}

/**
 * Normalise the many shapes a `/models` payload can take.
 *
 * Tolerates `{data: [...]}`, `{models: {...}}`, `{models: [...]}` and a bare
 * array. Entries may be plain strings or objects.
 *
 * @param {any} payload
 * @returns {Array<{id: string, contextWindow?: number, maxTokens?: number, inputModalities?: string[]}>}
 */
function normalizeModelList(payload) {
  /** @type {any[]} */
  const entries = [];

  if (Array.isArray(payload)) {
    entries.push(...payload);
  } else if (payload && typeof payload === 'object') {
    if (Array.isArray(payload.data)) {
      entries.push(...payload.data);
    } else if (Array.isArray(payload.models)) {
      entries.push(...payload.models);
    } else if (payload.models && typeof payload.models === 'object') {
      for (const [key, value] of Object.entries(payload.models)) {
        if (value && typeof value === 'object') {
          // The map key is the model id unless the value carries its own.
          entries.push({ ...value, id: typeof value.id === 'string' && value.id ? value.id : key });
        } else if (typeof value === 'string' && value) {
          entries.push({ id: key });
        }
      }
    }
  }

  const models = [];
  for (const entry of entries) {
    if (typeof entry === 'string') {
      const normalized = normalizeModelEntry(undefined, entry);
      if (normalized) models.push(normalized);
      continue;
    }
    if (!entry || typeof entry !== 'object') continue;
    const normalized = normalizeModelEntry(entry);
    if (normalized) models.push(normalized);
  }
  return models;
}

/**
 * `GET {base}/models` for OpenAI-ish APIs; Anthropic's listing lives under
 * `/v1/models`, so add `/v1` when the base does not already carry it (probe
 * requests use `{base}/messages`, i.e. the base usually includes `/v1`).
 *
 * @param {string} base
 * @param {string} api
 * @returns {string}
 */
function modelsUrl(base, api) {
  if (api === ANTHROPIC_API && !/\/v1$/i.test(base)) return `${base}/v1/models`;
  return `${base}/models`;
}

/**
 * Discover the models an endpoint declares. Never throws.
 *
 * @param {object} input
 * @param {string} input.baseURL
 * @param {string} [input.api]
 * @param {string} [input.apiKey]
 * @param {number} [input.timeoutMs]
 * @param {Function} [input.fetchImpl]
 * @returns {Promise<{
 *   models: Array<{id: string, contextWindow?: number, maxTokens?: number, inputModalities?: string[]}>,
 *   error?: string,
 * }>}
 */
export async function discoverModels(input) {
  const opts = input && typeof input === 'object' ? input : {};
  const api = typeof opts.api === 'string' && opts.api ? opts.api : 'openai-completions';
  const apiKey = typeof opts.apiKey === 'string' ? opts.apiKey : '';
  const timeoutMs =
    typeof opts.timeoutMs === 'number' && Number.isFinite(opts.timeoutMs) && opts.timeoutMs > 0
      ? opts.timeoutMs
      : DEFAULT_TIMEOUT_MS;
  const fetchImpl = typeof opts.fetchImpl === 'function' ? opts.fetchImpl : globalThis.fetch;
  const base = normalizeEndpoint(opts.baseURL);

  if (typeof fetchImpl !== 'function') {
    return { models: [], error: 'no fetch implementation available' };
  }
  if (!base) {
    return { models: [], error: 'missing or invalid baseURL' };
  }

  const url = modelsUrl(base, api);

  try {
    const response = await fetchImpl(url, {
      method: 'GET',
      headers: discoveryHeaders(api, apiKey),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const status = typeof response?.status === 'number' ? response.status : 0;
    const raw = redactSecret(await readBody(response), apiKey);

    if (status !== 200) {
      return { models: [], error: `HTTP ${status}` };
    }

    const { ok, parsed } = tryParseJson(raw);
    if (!ok) {
      return { models: [], error: 'invalid JSON response' };
    }

    return { models: normalizeModelList(parsed) };
  } catch (error) {
    return { models: [], error: describeTransportFailure(error, timeoutMs, apiKey) };
  }
}
