/**
 * Wiring tests for `index.js`: a hand-made Cordis context drives the real
 * plugin so the audit, the repair, the surfaces, and the `agent/pre-step`
 * rewrite are exercised without a Harness process.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { CONFIG_DEFAULTS, apply, inject, name } from '../index.js'

const ROUTE = 'test-route'
const LLM_ROW_NAME = '@deepseek-ai/dsh-llm-pi-ai'

/** Minimal stand-in for the services `apply` touches. */
function makeHarness({ models, config = {}, vision, respond, defaultModel, resolveModelInfo } = {}) {
	const rows = [
		{
			entry: {
				options: {
					id: 'llm-pi-ai',
					name: LLM_ROW_NAME,
					config: { providers: { [ROUTE]: { api: 'openai-completions', baseURL: 'https://api.example.test/v1', apiKeyEnv: 'TEST_KEY', models } } },
				},
			},
			inherited: {},
			override: {},
		},
	]
	if (defaultModel !== undefined) {
		rows.push({
			entry: { options: { id: 'agent-default-model', name: '@deepseek-ai/dsh-agent-default-model', config: defaultModel } },
			inherited: {},
			override: {},
		})
	}
	if (vision !== undefined) {
		// Mirrors the real profile: a `vision` row addressed by patch id only.
		rows.push({
			entry: { options: { id: 'vision', config: vision } },
			inherited: {},
			override: {},
		})
	}
	const handlers = new Map()
	const sections = []
	const tools = new Map()
	const commands = new Map()
	const streamCalls = []
	const edits = []
	const optional = new Map()

	const ctx = {
		logger: { debug() {}, info() {}, warn() {}, error() {} },
		llm: {
			stream(options) {
				streamCalls.push(options)
				return respond({ options, streamCalls })
			},
			...(resolveModelInfo === undefined ? {} : { resolveModelInfo }),
		},
		configEditor: {
			configuration: () => rows,
			async edit(entry, change) {
				const current = structuredClone(entry.options.config ?? {})
				const inherited = {}
				const next = change(current, inherited)
				entry.options.config = structuredClone(next)
				edits.push(next)
			},
		},
		credentials: { resolve: async () => ({ value: 'test-key' }) },
		tools: { register: (definition) => { tools.set(definition.name, definition); return () => {} } },
		commands: { register: (definition) => { commands.set(definition.name, definition); return () => {} } },
		systemPrompt: { section: (section) => { sections.push(section); return () => {} } },
		on: (event, handler) => { handlers.set(event, handler); return () => {} },
		get: (key) => optional.get(key) ?? ctx[key],
	}
	return { ctx, rows, handlers, sections, tools, commands, streamCalls, edits, optional }
}

/** Async generator that answers one describe call with text, or a failure. */
function describeStream(text) {
	return async function* () {
		yield { type: 'text-delta', text }
		yield { type: 'finish', reason: { kind: 'stop' } }
	}()
}

function failingStream(message) {
	return async function* () {
		yield { type: 'finish', reason: { kind: 'error', failure: { message, code: 'PROVIDER_ERROR' } } }
	}()
}

function imageMessage() {
	return {
		role: 'user',
		content: [
			{ type: 'text', text: '这张图里是什么？' },
			{ type: 'image', attachment: { attachmentId: 'img-1', mediaType: 'image/png', bytes: 12, width: 1, height: 1 } },
		],
		source: { kind: 'user' },
	}
}

function enterDecision(messages) {
	return { kind: 'enter', messages }
}

/** Wait for the audit chain (a few await hops plus one timer) to settle. */
async function settle() {
	for (let index = 0; index < 6; index += 1) await new Promise((resolve) => setTimeout(resolve, 5))
}

/** Force a fresh audit through the status tool, which awaits it. */
async function statusOf(tools) {
	return tools.get('model_guard').execute({ action: 'status' })
}

test('exports a plugin shape the loader can mount', () => {
	assert.equal(name, 'model-guard')
	assert.ok(Array.isArray(inject))
	for (const service of ['llm', 'configEditor', 'credentials', 'tools', 'commands', 'systemPrompt']) {
		assert.ok(inject.includes(service), `inject must include ${service}`)
	}
})

test('audit reports a missing image tag and a missing multimodal model', async () => {
	const harness = makeHarness({
		models: [{ id: 'text-model', name: 'Text Model', input: ['text'] }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })

	const status = await statusOf(harness.tools)
	assert.equal(status.ok, true)
	assert.equal(status.compliant, false)
	const codes = status.issues.map((issue) => issue.code)
	assert.ok(codes.includes('IMAGE_TAG_OFF'))
	// With probing disabled and nothing pinned, no model proves it can see.
	assert.ok(codes.includes('NO_IMAGE_MODEL'))

	const imageIssue = status.issues.find((issue) => issue.code === 'IMAGE_TAG_OFF')
	assert.equal(imageIssue.model, 'text-model')
	assert.equal(imageIssue.fixable, true)
	const noImage = status.issues.find((issue) => issue.code === 'NO_IMAGE_MODEL')
	assert.equal(noImage.fixable, false)
})

test('apply writes the image tag and the maximum context window through the editor', async () => {
	const harness = makeHarness({
		models: [
			{ id: 'text-model', name: 'Text Model', input: ['text'] },
			{ id: 'vision-model', name: 'Vision', input: ['text', 'image'] },
		],
	})
	// The endpoint advertises a larger window than the Harness fallback.
	const restore = stubFetch((url) => {
		assert.match(String(url), /\/models$/)
		return jsonResponse({ data: [
			{ id: 'text-model', context_length: 1_048_576 },
			{ id: 'vision-model', context_length: 1_048_576, architecture: { input_modalities: ['text', 'image'] } },
		] })
	})
	try {
		apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })

		const applied = await harness.tools.get('model_guard').execute({ action: 'apply' })
		assert.equal(applied.ok, true)
		assert.equal(harness.edits.length, 1)

		const provider = harness.edits[0].providers[ROUTE]
		const model = provider.models.find((entry) => entry.id === 'text-model')
		assert.deepEqual(model.input, ['text', 'image'])
		assert.equal(model.contextWindow, 1_048_576)

		// The persisted config is what the next audit reads, so nothing fixable remains.
		const after = await statusOf(harness.tools)
		assert.equal(after.issues.filter((issue) => issue.fixable).length, 0)
	} finally {
		restore()
	}
})

test('a second apply is a no-op once everything is fixed', async () => {
	const harness = makeHarness({
		models: [{ id: 'text-model', name: 'Text Model', input: ['text'] }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })
	await harness.tools.get('model_guard').execute({ action: 'apply' })
	const editsAfterFirst = harness.edits.length
	const second = await harness.tools.get('model_guard').execute({ action: 'apply' })
	assert.equal(second.ok, true)
	assert.equal(harness.edits.length, editsAfterFirst)
})

test('the system prompt section asks the agent to obtain consent', async () => {
	const harness = makeHarness({
		models: [{ id: 'text-model', name: 'Text Model', input: ['text'] }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })
	await statusOf(harness.tools)
	const section = harness.sections.find((entry) => entry.name === 'model-guard:status')
	assert.ok(section, 'a status section must be registered')
	const text = section.text()
	assert.match(text, /是否现在修复/)
	assert.match(text, /model_guard/)
})

test('the section is empty when the configuration is compliant', async () => {
	const harness = makeHarness({
		models: [{ id: 'vision-model', name: 'Vision', input: ['text', 'image'], contextWindow: 262144 }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never', imageModels: ['vision-model'] })
	await statusOf(harness.tools)
	const section = harness.sections.find((entry) => entry.name === 'model-guard:status')
	assert.equal(section.text(), '')
})

test('the command reports status and honours fix', async () => {
	const harness = makeHarness({
		models: [{ id: 'text-model', name: 'Text Model', input: ['text'] }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })
	const command = harness.commands.get('model-guard')
	const status = await command.handler({ rawInput: '' })
	assert.equal(status.kind, 'success')
	assert.match(status.text, /路由 test-route/)

	const fixed = await command.handler({ rawInput: 'fix' })
	assert.equal(fixed.kind, 'success')
	assert.equal(harness.edits.length, 1)
})

test('pre-step replaces an image with a description for a text-only model', async () => {
	const harness = makeHarness({
		models: [
			{ id: 'text-model', name: 'Text Model', input: ['text', 'image'] },
			{ id: 'vision-model', name: 'Vision', input: ['text', 'image'] },
		],
		respond: () => describeStream('图里是一块红色的正方形。'),
	})
	apply(harness.ctx, {
		auditOnStartup: false,
		probeImages: 'never',
		imageModels: ['vision-model'],
		textModels: ['text-model'],
	})
	harness.optional.set('agents', {
		currentInitiator: () => ({ id: 's-1', session: { requestHeader: () => ({ config: { provider: ROUTE, model: 'text-model' } }) } }),
	})

	const handler = harness.handlers.get('agent/pre-step')
	const result = await handler({ signal: undefined }, async () => enterDecision([imageMessage()]))

	const content = result.messages[0].content
	assert.equal(content[0].type, 'text')
	assert.equal(content[1].type, 'text')
	assert.match(content[1].text, /红色/)
	assert.match(content[1].text, /vision-model/)
	assert.equal(harness.streamCalls.length, 1)
	assert.equal(harness.streamCalls[0].provider, ROUTE)
	assert.equal(harness.streamCalls[0].model, 'vision-model')
	const imageBlock = harness.streamCalls[0].messages[0].content.find((block) => block.type === 'image')
	assert.equal(imageBlock.attachment.attachmentId, 'img-1')
})

test('pre-step leaves the image untouched for a multimodal model', async () => {
	const harness = makeHarness({
		models: [{ id: 'vision-model', name: 'Vision', input: ['text', 'image'] }],
		respond: () => describeStream('should not be called'),
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never', imageModels: ['vision-model'] })
	harness.optional.set('agents', {
		currentInitiator: () => ({ id: 's-1', session: { requestHeader: () => ({ config: { provider: ROUTE, model: 'vision-model' } }) } }),
	})

	const handler = harness.handlers.get('agent/pre-step')
	const decision = enterDecision([imageMessage()])
	const result = await handler({ signal: undefined }, async () => decision)
	assert.equal(result, decision)
	assert.equal(harness.streamCalls.length, 0)
})

test('pre-step records an honest failure note when the describer call fails', async () => {
	const harness = makeHarness({
		models: [
			{ id: 'text-model', name: 'Text Model', input: ['text', 'image'] },
			{ id: 'vision-model', name: 'Vision', input: ['text', 'image'] },
		],
		respond: () => failingStream('upstream 500'),
	})
	apply(harness.ctx, {
		auditOnStartup: false,
		probeImages: 'never',
		imageModels: ['vision-model'],
		textModels: ['text-model'],
	})
	harness.optional.set('agents', {
		currentInitiator: () => ({ id: 's-1', session: { requestHeader: () => ({ config: { provider: ROUTE, model: 'text-model' } }) } }),
	})

	const handler = harness.handlers.get('agent/pre-step')
	const result = await handler({ signal: undefined }, async () => enterDecision([imageMessage()]))
	const content = result.messages[0].content
	assert.equal(content[1].type, 'text')
	assert.match(content[1].text, /无法识别/)
	assert.match(content[1].text, /upstream 500/)
})

test('pre-step ignores messages without images and rejected decisions', async () => {
	const harness = makeHarness({
		models: [{ id: 'text-model', name: 'Text Model', input: ['text', 'image'] }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })
	const handler = harness.handlers.get('agent/pre-step')

	const plain = enterDecision([{ role: 'user', content: [{ type: 'text', text: '你好' }] }])
	assert.equal(await handler({ signal: undefined }, async () => plain), plain)

	const rejected = { kind: 'reject' }
	assert.equal(await handler({ signal: undefined }, async () => rejected), rejected)
	assert.equal(harness.streamCalls.length, 0)
})

test('pre-step tolerates an unresolvable model by leaving the decision alone', async () => {
	const harness = makeHarness({
		models: [{ id: 'text-model', name: 'Text Model', input: ['text', 'image'] }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })
	const handler = harness.handlers.get('agent/pre-step')
	const decision = enterDecision([imageMessage()])
	assert.equal(await handler({ signal: undefined }, async () => decision), decision)
	assert.equal(harness.streamCalls.length, 0)
})

test('a config reload triggers a new audit', async () => {
	const harness = makeHarness({
		models: [{ id: 'text-model', name: 'Text Model', input: ['text'] }],
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never', imageModels: ['text-model'] })
	await statusOf(harness.tools)

	// Fix the model behind the plugin's back, then announce the reload.
	harness.rows[0].entry.options.config.providers[ROUTE].models = [
		{ id: 'text-model', name: 'Text Model', input: ['text', 'image'], contextWindow: 262144 },
	]
	harness.handlers.get('llm/adapters-updated')()
	await settle()

	const status = await statusOf(harness.tools)
	assert.equal(status.compliant, true)
	assert.equal(status.issues.length, 0)
})

test('a vision row addressed only by patch id is still audited, never rewritten', async () => {
	const harness = makeHarness({
		models: [{ id: 'vision-model', name: 'Vision', input: ['text', 'image'], contextWindow: 262144 }],
		vision: { provider: 'custom', model: 'other-model', autoDescribe: false },
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never', imageModels: ['vision-model'] })
	const status = await statusOf(harness.tools)
	const mismatch = status.issues.find((issue) => issue.code === 'VISION_PLUGIN_MISMATCH')
	assert.ok(mismatch, 'a vision mismatch is reported')
	assert.equal(mismatch.fixable, false)
	assert.equal(harness.edits.length, 0)
})

test('a missing llm-pi-ai row yields a report instead of a crash', async () => {
	const harness = makeHarness({ models: [] })
	harness.ctx.configEditor.configuration = () => []
	apply(harness.ctx, { auditOnStartup: false })
	const status = await statusOf(harness.tools)
	assert.equal(status.ok, false)
	assert.match(status.text, /未找到 @deepseek-ai\/dsh-llm-pi-ai 配置行/)
})
// -----------------------------------------------------------------------------
// fetch stub helpers for the discovery path
// -----------------------------------------------------------------------------

/** Replace global fetch for the duration of one test. */
function stubFetch(handler) {
	const original = globalThis.fetch
	globalThis.fetch = async (url, init) => handler(url, init)
	return () => { globalThis.fetch = original }
}

/** Minimal Response-like object shaped the way `discoverModels` reads it. */
function jsonResponse(body, status = 200) {
	const text = JSON.stringify(body)
	return {
		ok: status >= 200 && status < 300,
		status,
		async text() { return text },
	}
}

test('the reported version matches package.json', async () => {
	const { readFileSync } = await import('node:fs')
	const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
	const harness = makeHarness({ models: [{ id: 'text-model', name: 'T', input: ['text'] }] })
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })
	const status = await harness.tools.get('model_guard').execute({ action: 'status' })
	assert.equal(status.version, pkg.version)
	assert.match(status.text, new RegExp(`model-guard v${pkg.version.replace(/\./g, '\\.')}`))
})

test('timeouts default to values measured against the real endpoint', async () => {
	const harness = makeHarness({ models: [{ id: 'a', name: 'A', input: ['text', 'image'] }] })
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never' })
	// A screenshot description was measured at ~35s, and a reasoning probe at ~12s.
	assert.ok(CONFIG_DEFAULTS.describeTimeoutMs >= 90_000, 'describeTimeoutMs must clear a slow screenshot')
	assert.ok(CONFIG_DEFAULTS.probeTimeoutMs >= 15_000, 'probeTimeoutMs must clear a reasoning model')
})

test('the report shows what the runtime resolved, when the adapter answers', async () => {
	const harness = makeHarness({
		models: [{ id: 'm1', name: 'M1', input: ['text', 'image'] }],
		defaultModel: { provider: ROUTE, model: 'm1' },
		resolveModelInfo: async () => ({ context: { contextWindow: 1000000 }, inputModalities: ['text', 'image'] }),
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never', imageModels: ['m1'] })
	const status = await harness.tools.get('model_guard').execute({ action: 'status', refresh: true })
	assert.match(status.text, new RegExp(`运行时视图：${ROUTE}/m1 → 上下文 1000000`))
	assert.equal(status.runtime?.contextWindow, 1000000)
})

test('a failing adapter surfaces as a parse failure, not a crash', async () => {
	const harness = makeHarness({
		models: [{ id: 'm1', name: 'M1', input: ['text', 'image'] }],
		defaultModel: { provider: ROUTE, model: 'm1' },
		resolveModelInfo: async () => { throw new Error('adapter offline') },
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never', imageModels: ['m1'] })
	const status = await harness.tools.get('model_guard').execute({ action: 'status', refresh: true })
	assert.match(status.text, /解析失败：adapter offline/)
})

test('a runtime modality that disagrees with the written tag is reported', async () => {
	const harness = makeHarness({
		models: [
			{ id: 'm1', name: 'M1', input: ['text', 'image'] },
			{ id: 'm2', name: 'M2', input: ['text', 'image'] },
		],
		defaultModel: { provider: ROUTE, model: 'm1' },
		resolveModelInfo: async (_provider, model) => (model === 'm2'
			? { context: { contextWindow: 1000000 }, inputModalities: ['text'] }
			: { context: { contextWindow: 1000000 }, inputModalities: ['text', 'image'] }),
	})
	apply(harness.ctx, { auditOnStartup: false, probeImages: 'never', imageModels: ['m1', 'm2'] })
	const status = await harness.tools.get('model_guard').execute({ action: 'status', refresh: true })
	assert.match(status.text, /RUNTIME_MISMATCH/)
	assert.match(status.text, /m2 输入声明 \[text, image\] 而运行时 \[text\]/)
})
