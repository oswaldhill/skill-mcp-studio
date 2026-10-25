/**
 * test/probe.test.js — unit tests for lib/probe.mjs.
 *
 * Every fetch is injected: no test touches the network.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import zlib from 'node:zlib';

import {
  PROBE_IMAGE_PNG_BASE64,
  PROBE_TARGETS,
  discoverModels,
  normalizeEndpoint,
  probeImageSupport,
} from '../lib/probe.mjs';

const BASE = 'https://api.example.test/v1';
const API_KEY = 'sk-test-secret-key-0123456789';
const PROMPT = 'Read the digits in this image. Reply with the digits only.';
const DIGITS = PROBE_TARGETS[0].digits;

/**
 * Build a fake fetch that records (url, init) and replies via `handler`.
 * @param {(url: string, init: object, n: number) => any} handler
 */
function capturedFetch(handler) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return handler(url, init, calls.length);
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

/** Fake Response with a text body. */
function textResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
  };
}

/** Fake Response carrying a JSON body. */
function jsonResponse(status, payload) {
  return textResponse(status, JSON.stringify(payload));
}

/** Fake Response whose body access blows up (parsing edge). */
function brokenBodyResponse(status) {
  return {
    ok: status === 200,
    status,
    text: async () => {
      throw new Error('body stream failed');
    },
  };
}

/** OpenAI-shaped chat completion reply. */
function openAIReply(content) {
  return jsonResponse(200, { choices: [{ message: { role: 'assistant', content } }] });
}

/** Anthropic-shaped messages reply. */
function anthropicReply(text) {
  return jsonResponse(200, { content: [{ type: 'text', text }] });
}

function abortError() {
  const error = new Error('The operation was aborted.');
  error.name = 'AbortError';
  return error;
}

// ---------------------------------------------------------------------------
// 1. Verdicts for HTTP 200
// ---------------------------------------------------------------------------

test('probeImageSupport: HTTP 200 naming red => verdict image', async () => {
  const fetchImpl = capturedFetch(() => openAIReply(DIGITS));
  const result = await probeImageSupport({ baseURL: BASE, apiKey: API_KEY, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(result.verdict, 'image');
  assert.equal(result.status, 200);
  assert.equal(typeof result.detail, 'string');
});

test('probeImageSupport: HTTP 200 naming 红色 => verdict image (CJK colour word)', async () => {
  const fetchImpl = capturedFetch(() => openAIReply(DIGITS));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(result.verdict, 'image');
});

test('probeImageSupport: HTTP 200 with explicit refusal => verdict text', async () => {
  const fetchImpl = capturedFetch(() => openAIReply("Sorry, I can't see the image."));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'text');
  assert.equal(result.status, 200);
});

test('probeImageSupport: HTTP 200 refusal in Chinese => verdict text', async () => {
  const fetchImpl = capturedFetch(() => openAIReply('抱歉，我无法查看图片。'));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'text');
});

test('probeImageSupport: HTTP 200 with unrelated text => verdict unknown', async () => {
  const fetchImpl = capturedFetch(() => openAIReply('OK'));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.equal(result.status, 200);
  assert.match(result.detail, /did not name/i);
});

test('probeImageSupport: HTTP 200 with empty content => verdict unknown', async () => {
  const fetchImpl = capturedFetch(() => openAIReply(''));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.equal(result.status, 200);
});

test('probeImageSupport: HTTP 200 plain-text body naming red => verdict image', async () => {
  // Not JSON: the raw body is the reply.
  const fetchImpl = capturedFetch(() => textResponse(200, DIGITS));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(result.verdict, 'image');
});

test('probeImageSupport: HTTP 200 array-style OpenAI content => verdict image', async () => {
  const fetchImpl = capturedFetch(() =>
    jsonResponse(200, {
      choices: [{ message: { content: [{ type: 'text', text: DIGITS }] } }],
    }),
  );
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(result.verdict, 'image');
});

// ---------------------------------------------------------------------------
// 2. HTTP failures and transport failures
// ---------------------------------------------------------------------------

test('probeImageSupport: HTTP 400 "does not support image input" => verdict text', async () => {
  const fetchImpl = capturedFetch(() =>
    jsonResponse(400, { error: { message: 'This model does not support image input' } }),
  );
  const result = await probeImageSupport({ baseURL: BASE, apiKey: API_KEY, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'text');
  assert.equal(result.status, 400);
});

test('probeImageSupport: HTTP 400 with unrelated body => verdict text', async () => {
  const fetchImpl = capturedFetch(() => textResponse(400, 'Bad Request: malformed JSON body'));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'text');
  assert.equal(result.status, 400);
  assert.match(result.detail, /400/);
  assert.match(result.detail, /malformed JSON body/);
});

test('probeImageSupport: HTTP 422 mention of vision => verdict text', async () => {
  const fetchImpl = capturedFetch(() => jsonResponse(422, { detail: 'vision is not enabled for this model' }));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'text');
});

test('probeImageSupport: HTTP 401 => verdict unknown', async () => {
  const fetchImpl = capturedFetch(() => jsonResponse(401, { error: 'unauthorized' }));
  const result = await probeImageSupport({ baseURL: BASE, apiKey: API_KEY, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.equal(result.status, 401);
});

test('probeImageSupport: HTTP 403 => verdict unknown', async () => {
  const fetchImpl = capturedFetch(() => jsonResponse(403, { error: 'forbidden' }));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.equal(result.status, 403);
});

test('probeImageSupport: HTTP 429 => verdict unknown', async () => {
  const fetchImpl = capturedFetch(() => jsonResponse(429, { error: 'rate limited' }));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.equal(result.status, 429);
  assert.match(result.detail, /rate limited/i);
});

test('probeImageSupport: HTTP 500 => verdict unknown', async () => {
  const fetchImpl = capturedFetch(() => jsonResponse(500, { error: 'internal' }));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.equal(result.status, 500);
});

test('probeImageSupport: HTTP 503 => verdict unknown', async () => {
  const fetchImpl = capturedFetch(() => textResponse(503, 'unavailable'));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
});

test('probeImageSupport: thrown AbortError => verdict unknown, no throw', async () => {
  const fetchImpl = capturedFetch(() => {
    throw abortError();
  });
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', timeoutMs: 25, fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.match(result.detail, /timed out/i);
});

test('probeImageSupport: thrown network error => verdict unknown, no throw', async () => {
  const fetchImpl = capturedFetch(() => {
    throw new TypeError('fetch failed');
  });
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.match(result.detail, /network error/i);
});

test('probeImageSupport: unreadable response body => verdict unknown, no throw', async () => {
  const fetchImpl = capturedFetch(() => brokenBodyResponse(200));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
});

test('probeImageSupport: invalid input returns unknown without calling fetch', async () => {
  let called = 0;
  const fetchImpl = async () => {
    called += 1;
    return openAIReply(DIGITS);
  };
  assert.equal((await probeImageSupport({ baseURL: '', model: 'm1', fetchImpl })).verdict, 'unknown');
  assert.equal((await probeImageSupport({ baseURL: BASE, model: '', fetchImpl })).verdict, 'unknown');
  assert.equal((await probeImageSupport({ baseURL: BASE, model: 'm1', fetchImpl: undefined })).verdict, 'unknown');
  assert.equal(called, 0);
});

// ---------------------------------------------------------------------------
// 3. Request path / headers / body
// ---------------------------------------------------------------------------

test('probeImageSupport: OpenAI request path, headers and body', async () => {
  const fetchImpl = capturedFetch(() => openAIReply(DIGITS));
  await probeImageSupport({
    baseURL: `${BASE}/`,
    api: 'openai-completions',
    apiKey: API_KEY,
    model: 'gpt-test',
    timeoutMs: 1234,
    probe: DIGITS,
    fetchImpl,
  });

  assert.equal(fetchImpl.calls.length, 1);
  const { url, init } = fetchImpl.calls[0];
  assert.equal(url, `${BASE}/chat/completions`);
  assert.equal(init.method, 'POST');
  assert.equal(init.headers['content-type'], 'application/json');
  assert.equal(init.headers.authorization, `Bearer ${API_KEY}`);
  assert.ok(init.signal instanceof AbortSignal);

  const body = JSON.parse(init.body);
  assert.equal(body.model, 'gpt-test');
  assert.equal(body.max_tokens, 512);
  assert.equal(body.stream, false);
  assert.equal(body.messages.length, 1);
  assert.equal(body.messages[0].role, 'user');
  const [textPart, imagePart] = body.messages[0].content;
  assert.deepEqual(textPart, { type: 'text', text: PROMPT });
  assert.equal(imagePart.type, 'image_url');
  assert.equal(imagePart.image_url.url, `data:image/png;base64,${PROBE_TARGETS[0].base64}`);
});

test('probeImageSupport: openai-responses also posts to /chat/completions', async () => {
  const fetchImpl = capturedFetch(() => openAIReply(DIGITS));
  await probeImageSupport({ baseURL: BASE, api: 'openai-responses', model: 'm1', fetchImpl });
  assert.equal(fetchImpl.calls[0].url, `${BASE}/chat/completions`);
  const body = JSON.parse(fetchImpl.calls[0].init.body);
  assert.equal(body.messages[0].content[1].type, 'image_url');
});

test('probeImageSupport: anthropic-messages request path, headers and body', async () => {
  const fetchImpl = capturedFetch(() => anthropicReply(DIGITS));
  const result = await probeImageSupport({
    baseURL: `${BASE}/`,
    api: 'anthropic-messages',
    apiKey: API_KEY,
    model: 'claude-test',
    probe: DIGITS,
    fetchImpl,
  });

  assert.equal(result.verdict, 'image');
  assert.equal(result.status, 200);

  const { url, init } = fetchImpl.calls[0];
  assert.equal(url, `${BASE}/messages`);
  assert.equal(init.method, 'POST');
  assert.equal(init.headers['x-api-key'], API_KEY);
  assert.equal(init.headers['anthropic-version'], '2023-06-01');
  assert.equal(init.headers.authorization, undefined);

  const body = JSON.parse(init.body);
  assert.equal(body.model, 'claude-test');
  assert.equal(body.max_tokens, 512);
  const [textPart, imagePart] = body.messages[0].content;
  assert.deepEqual(textPart, { type: 'text', text: PROMPT });
  assert.deepEqual(imagePart, {
    type: 'image',
    source: { type: 'base64', media_type: 'image/png', data: PROBE_TARGETS[0].base64 },
  });
});

test('probeImageSupport: no apiKey means no auth header', async () => {
  const openai = capturedFetch(() => openAIReply(DIGITS));
  await probeImageSupport({ baseURL: BASE, api: 'openai-completions', model: 'm1', fetchImpl: openai });
  assert.equal(openai.calls[0].init.headers.authorization, undefined);

  const anthropic = capturedFetch(() => anthropicReply(DIGITS));
  await probeImageSupport({ baseURL: BASE, api: 'anthropic-messages', model: 'm1', fetchImpl: anthropic });
  assert.equal(anthropic.calls[0].init.headers['x-api-key'], undefined);
  assert.equal(anthropic.calls[0].init.headers['anthropic-version'], '2023-06-01');
});

test('probeImageSupport: detail never contains the API key', async () => {
  const fetchImpl = capturedFetch(() =>
    textResponse(400, `bad request for key ${API_KEY} — malformed payload`),
  );
  const result = await probeImageSupport({ baseURL: BASE, apiKey: API_KEY, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'text');
  assert.ok(!result.detail.includes(API_KEY), `detail leaked the key: ${result.detail}`);
  assert.match(result.detail, /redacted/);
});

test('probeImageSupport: network error message never contains the API key', async () => {
  const fetchImpl = capturedFetch(() => {
    throw new TypeError(`socket closed while using ${API_KEY}`);
  });
  const result = await probeImageSupport({ baseURL: BASE, apiKey: API_KEY, model: 'm1', fetchImpl });
  assert.equal(result.verdict, 'unknown');
  assert.ok(!result.detail.includes(API_KEY), `detail leaked the key: ${result.detail}`);
});

// ---------------------------------------------------------------------------
// 4. discoverModels
// ---------------------------------------------------------------------------

test('discoverModels: parses {data:[...]} with contract field names', async () => {
  const fetchImpl = capturedFetch(() =>
    jsonResponse(200, {
      object: 'list',
      data: [
        {
          id: 'model-a',
          context_length: 128000,
          max_output_tokens: 4096,
          architecture: { input_modalities: ['text', 'image'] },
        },
        { id: 'model-b', contextWindow: 200000, maxTokens: 8192, input_modalities: ['text'] },
        { id: 'model-c' },
      ],
    }),
  );

  const result = await discoverModels({ baseURL: BASE, api: 'openai-completions', apiKey: API_KEY, fetchImpl });
  assert.deepEqual(result, {
    models: [
      {
        id: 'model-a',
        contextWindow: 128000,
        maxTokens: 4096,
        inputModalities: ['text', 'image'],
      },
      { id: 'model-b', contextWindow: 200000, maxTokens: 8192, inputModalities: ['text'] },
      { id: 'model-c' },
    ],
  });

  const { url, init } = fetchImpl.calls[0];
  assert.equal(url, `${BASE}/models`);
  assert.equal(init.method, 'GET');
  assert.equal(init.headers.authorization, `Bearer ${API_KEY}`);
});

test('discoverModels: parses {models:{...}} map shape and nested limit fields', async () => {
  const fetchImpl = capturedFetch(() =>
    jsonResponse(200, {
      models: {
        'map-model': {
          limit: { context: 100000, output: 2048 },
          modalities: { input: ['text', 'image'] },
        },
        named: { id: 'explicit-id', context_window: 64000, max_tokens: 1024 },
      },
    }),
  );

  const result = await discoverModels({ baseURL: BASE, fetchImpl });
  assert.deepEqual(result, {
    models: [
      {
        id: 'map-model',
        contextWindow: 100000,
        maxTokens: 2048,
        inputModalities: ['text', 'image'],
      },
      { id: 'explicit-id', contextWindow: 64000, maxTokens: 1024 },
    ],
  });
});

test('discoverModels: tolerates {models:[...]} array and bare arrays', async () => {
  const list = capturedFetch(() => jsonResponse(200, { models: [{ id: 'from-models-array' }] }));
  assert.deepEqual((await discoverModels({ baseURL: BASE, fetchImpl: list })).models, [
    { id: 'from-models-array' },
  ]);

  const bare = capturedFetch(() => jsonResponse(200, [{ id: 'bare-a' }, 'bare-b']));
  assert.deepEqual((await discoverModels({ baseURL: BASE, fetchImpl: bare })).models, [
    { id: 'bare-a' },
    { id: 'bare-b' },
  ]);
});

test('discoverModels: field fallback order (context/maxTokens/modalities)', async () => {
  const fetchImpl = capturedFetch(() =>
    jsonResponse(200, {
      data: [
        {
          id: 'ordered',
          // first match in contract order must win
          contextWindow: 1,
          context_window: 2,
          context_length: 3,
          max_input_tokens: 4,
          maxOutputTokens: 11,
          max_output_tokens: 12,
          maxTokens: 13,
          max_tokens: 14,
          architecture: { input_modalities: ['first'] },
          input_modalities: ['second'],
          modalities: { input: ['third'] },
        },
      ],
    }),
  );
  const result = await discoverModels({ baseURL: BASE, fetchImpl });
  assert.deepEqual(result.models, [
    { id: 'ordered', contextWindow: 1, maxTokens: 11, inputModalities: ['first'] },
  ]);
});

test('discoverModels: falls through to later keys and ignores bad modality values', async () => {
  const fetchImpl = capturedFetch(() =>
    jsonResponse(200, {
      data: [
        {
          id: 'fallthrough',
          // context_length comes before max_input_tokens in the contract order
          context_length: 32000,
          max_input_tokens: 99000,
          max_tokens: 512,
          input_modalities: 'image', // not a string[]
          modalities: { input: [1, 2] }, // not a string[]
        },
        {
          id: 'nested-limit',
          limit: { context: 65536 },
          max_output_tokens: 2048,
        },
      ],
    }),
  );
  const result = await discoverModels({ baseURL: BASE, fetchImpl });
  assert.deepEqual(result.models, [
    { id: 'fallthrough', contextWindow: 32000, maxTokens: 512 },
    { id: 'nested-limit', contextWindow: 65536, maxTokens: 2048 },
  ]);
});

test('discoverModels: non-200 yields empty models plus HTTP status error', async () => {
  const fetchImpl = capturedFetch(() => textResponse(500, 'boom'));
  const result = await discoverModels({ baseURL: BASE, fetchImpl });
  assert.deepEqual(result, { models: [], error: 'HTTP 500' });

  const unauthorized = capturedFetch(() => textResponse(401, 'no'));
  assert.deepEqual(await discoverModels({ baseURL: BASE, fetchImpl: unauthorized }), {
    models: [],
    error: 'HTTP 401',
  });
});

test('discoverModels: malformed JSON yields empty models plus error', async () => {
  const fetchImpl = capturedFetch(() => textResponse(200, '{not json'));
  const result = await discoverModels({ baseURL: BASE, fetchImpl });
  assert.deepEqual(result.models, []);
  assert.equal(typeof result.error, 'string');
  assert.ok(result.error.length > 0);
});

test('discoverModels: transport failure and abort never throw', async () => {
  const failed = capturedFetch(() => {
    throw new TypeError('fetch failed');
  });
  const network = await discoverModels({ baseURL: BASE, apiKey: API_KEY, fetchImpl: failed });
  assert.deepEqual(network.models, []);
  assert.match(network.error, /network error/i);
  assert.ok(!network.error.includes(API_KEY));

  const aborted = capturedFetch(() => {
    throw abortError();
  });
  const timeout = await discoverModels({ baseURL: BASE, model: 'x', timeoutMs: 5, fetchImpl: aborted });
  assert.deepEqual(timeout.models, []);
  assert.match(timeout.error, /timed out/i);
});

test('discoverModels: anthropic auth header and /v1/models path', async () => {
  const withV1 = capturedFetch(() => jsonResponse(200, { data: [{ id: 'claude-1' }] }));
  await discoverModels({
    baseURL: 'https://api.anthropic.test/v1/',
    api: 'anthropic-messages',
    apiKey: API_KEY,
    fetchImpl: withV1,
  });
  assert.equal(withV1.calls[0].url, 'https://api.anthropic.test/v1/models');
  assert.equal(withV1.calls[0].init.headers['x-api-key'], API_KEY);
  assert.equal(withV1.calls[0].init.headers['anthropic-version'], '2023-06-01');
  assert.equal(withV1.calls[0].init.headers.authorization, undefined);

  const hostOnly = capturedFetch(() => jsonResponse(200, { data: [{ id: 'claude-1' }] }));
  await discoverModels({ baseURL: 'https://api.anthropic.test', api: 'anthropic-messages', fetchImpl: hostOnly });
  assert.equal(hostOnly.calls[0].url, 'https://api.anthropic.test/v1/models');
  assert.equal(hostOnly.calls[0].init.headers['x-api-key'], undefined);
});

test('discoverModels: invalid baseURL returns error without calling fetch', async () => {
  let called = 0;
  const fetchImpl = async () => {
    called += 1;
    return jsonResponse(200, { data: [] });
  };
  const result = await discoverModels({ baseURL: '', fetchImpl });
  assert.deepEqual(result.models, []);
  assert.equal(typeof result.error, 'string');
  assert.equal(called, 0);
});

// ---------------------------------------------------------------------------
// 5. Endpoint normalisation
// ---------------------------------------------------------------------------

test('normalizeEndpoint: strips trailing slashes and whitespace', () => {
  assert.equal(normalizeEndpoint('https://api.example.test/v1/'), 'https://api.example.test/v1');
  assert.equal(normalizeEndpoint('https://api.example.test/v1///'), 'https://api.example.test/v1');
  assert.equal(normalizeEndpoint('  https://api.example.test/v1  '), 'https://api.example.test/v1');
  assert.equal(normalizeEndpoint('https://api.example.test/v1'), 'https://api.example.test/v1');
  assert.equal(normalizeEndpoint('https://api.example.test/'), 'https://api.example.test');
  assert.equal(normalizeEndpoint('/', ''), '');
  assert.equal(normalizeEndpoint(''), '');
  assert.equal(normalizeEndpoint(undefined), '');
  assert.equal(normalizeEndpoint(null), '');
  assert.equal(normalizeEndpoint(42), '');
});

test('probeImageSupport: trailing slash in baseURL does not double slashes', async () => {
  const fetchImpl = capturedFetch(() => openAIReply(DIGITS));
  await probeImageSupport({ baseURL: `${BASE}//`, model: 'm1', fetchImpl });
  assert.equal(fetchImpl.calls[0].url, `${BASE}/chat/completions`);
});

// ---------------------------------------------------------------------------
// 6. Embedded probe PNG is a real 16x16 red PNG
// ---------------------------------------------------------------------------

test('PROBE_IMAGE_PNG_BASE64: decodes to a valid 16x16 red PNG', () => {
  assert.equal(typeof PROBE_IMAGE_PNG_BASE64, 'string');
  assert.ok(!PROBE_IMAGE_PNG_BASE64.startsWith('data:'), 'constant must not carry a data: prefix');

  const bytes = Buffer.from(PROBE_IMAGE_PNG_BASE64, 'base64');
  assert.ok(bytes.length > 8);

  // 8-byte PNG signature
  assert.deepEqual(
    [...bytes.subarray(0, 8)],
    [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
  );

  // First chunk must be IHDR with 16x16 dimensions.
  assert.equal(bytes.readUInt32BE(8), 13, 'IHDR length');
  assert.equal(bytes.subarray(12, 16).toString('ascii'), 'IHDR');
  assert.equal(bytes.readUInt32BE(16), 16, 'width must be 16');
  assert.equal(bytes.readUInt32BE(20), 16, 'height must be 16');
  assert.equal(bytes[24], 8, 'bit depth 8');
  assert.equal(bytes[25], 2, 'colour type 2 (truecolour RGB)');

  // Walk the chunks, inflate IDAT, and check every pixel is pure red.
  const idat = [];
  let sawIend = false;
  let offset = 8;
  while (offset + 12 <= bytes.length) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.subarray(offset + 4, offset + 8).toString('ascii');
    const data = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === 'IDAT') idat.push(data);
    offset += 12 + length;
    if (type === 'IEND') {
      sawIend = true;
      break;
    }
  }
  assert.ok(sawIend, 'PNG must end with IEND');
  assert.ok(idat.length > 0, 'PNG must contain IDAT');

  const raw = zlib.inflateSync(Buffer.concat(idat));
  const rowLength = 1 + 16 * 3;
  assert.equal(raw.length, 16 * rowLength, '16 scanlines of 16 RGB pixels');

  for (let y = 0; y < 16; y += 1) {
    const rowOffset = y * rowLength;
    assert.equal(raw[rowOffset], 0, `scanline ${y} must use filter type 0`);
    for (let x = 0; x < 16; x += 1) {
      const p = rowOffset + 1 + x * 3;
      assert.deepEqual([raw[p], raw[p + 1], raw[p + 2]], [255, 0, 0], `pixel ${x},${y} must be red`);
    }
  }
});

// ---------------------------------------------------------------------------
// 7. Reasoning traces count as evidence (the fix that unblocked reasoning models)
// ---------------------------------------------------------------------------

test('probeImageSupport: colour named only inside reasoning_content still proves vision', async () => {
  // A reasoning model can spend the whole budget thinking and never answer.
  const payload = {
    choices: [{
      finish_reason: 'length',
      message: { content: '', reasoning_content: `The user sent an image containing the digits ${DIGITS}. They want them read back.` },
    }],
  };
  const fetchImpl = capturedFetch(() => ({
    ok: true,
    status: 200,
    async text() { return JSON.stringify(payload) },
  }));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(result.verdict, 'image');
  assert.match(result.detail, /digits|reasoning/i);
});

test('probeImageSupport: refusal inside reasoning_content means text-only', async () => {
  const payload = {
    choices: [{
      finish_reason: 'length',
      message: { content: '', reasoning_content: 'The user asks about an image, but I do not see any image attached.' },
    }],
  };
  const fetchImpl = capturedFetch(() => ({
    ok: true,
    status: 200,
    async text() { return JSON.stringify(payload) },
  }));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(result.verdict, 'text');
});

test('probeImageSupport: a truncated answer naming the wrong digits stays unknown', async () => {
  const payload = {
    choices: [{ finish_reason: 'length', message: { content: '', reasoning_content: `It looks like the digits ${PROBE_TARGETS[2].digits}.` } }],
  };
  const fetchImpl = capturedFetch(() => ({
    ok: true,
    status: 200,
    async text() { return JSON.stringify(payload) },
  }));
  const result = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(result.verdict, 'unknown');
});

test('probeImageSupport: a reply is judged against the target actually drawn', async () => {
  // Naming another target's digits proves nothing about this one.
  const other = PROBE_TARGETS[1].digits;
  const payload = { choices: [{ message: { content: other } }] };
  const fetchImpl = capturedFetch(() => ({
    ok: true,
    status: 200,
    async text() { return JSON.stringify(payload) },
  }));
  const matching = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: other, fetchImpl });
  assert.equal(matching.verdict, 'image');
  const wrong = await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  assert.equal(wrong.verdict, 'unknown');
});

test('the probe budget is large enough for a reasoning model to answer', async () => {
  const fetchImpl = capturedFetch(() => openAIReply(DIGITS));
  await probeImageSupport({ baseURL: BASE, model: 'm1', probe: DIGITS, fetchImpl });
  const body = JSON.parse(fetchImpl.calls[0].init.body);
  assert.ok(body.max_tokens >= 256, `max_tokens ${body.max_tokens} is too small for a reasoning model`);
});

test('PROBE_TARGETS are distinct four-digit numbers with their own images', () => {
  const digits = PROBE_TARGETS.map((entry) => entry.digits);
  assert.equal(new Set(digits).size, digits.length, 'targets must be unique');
  assert.ok(PROBE_TARGETS.length >= 4, 'too few targets to stop guessing');
  for (const entry of PROBE_TARGETS) {
    assert.match(entry.digits, /^[1-9]\d{3}$/, 'a leading zero would break exact matching');
    assert.ok(entry.base64.length > 100, `${entry.digits} needs a PNG payload`);
    const bytes = Buffer.from(entry.base64, 'base64');
    assert.deepEqual([...bytes.subarray(0, 4)], [0x89, 0x50, 0x4e, 0x47], 'must be a PNG');
  }
});
