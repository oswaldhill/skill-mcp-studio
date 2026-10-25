/**
 * Tests for the vision fallback: the description call, the preamble cut, and
 * the truncation marker. A fake `llm` service keeps this free of the host.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
	DEFAULT_DESCRIBE_PROMPT,
	DESCRIBE_ANCHOR,
	createVisionBridge,
	stripPreamble,
} from '../lib/describe.mjs'

const REF = { attachmentId: 'img-1', mediaType: 'image/png' }

/** Fake `llm.stream` that replays fixed chunks and records the options. */
function fakeLlm(chunks) {
	const calls = []
	return {
		calls,
		stream(options) {
			calls.push(options)
			return (async function* () {
				for (const chunk of chunks) yield chunk
			})()
		},
	}
}

function bridgeFor(llm, config = {}) {
	return createVisionBridge({
		getLlm: () => llm,
		getLogger: () => undefined,
		getConfig: () => ({ provider: 'route', model: 'vision-model', ...config }),
	})
}

const deltas = (...texts) => texts.map((text) => ({ type: 'text-delta', text }))
const finish = (kind) => ({ type: 'finish', reason: { kind } })

test('the prompt forbids preamble and pins the first token', () => {
	assert.match(DEFAULT_DESCRIBE_PROMPT, /图片类型：/)
	assert.match(DEFAULT_DESCRIBE_PROMPT, /禁止/)
	assert.match(DEFAULT_DESCRIBE_PROMPT, /思考过程/)
	// The anchor must be the literal prefix the cut relies on.
	assert.equal(DESCRIBE_ANCHOR, '图片类型：')
})

test('stripPreamble cuts a leaked chain of thought', () => {
	const leaked = '我们需要回答用户。用户要求用中文描述图片。需要直接输出正文。\n图片类型：截图\n正文…'
	assert.equal(stripPreamble(leaked), '图片类型：截图\n正文…')
})

test('stripPreamble leaves clean text and anchor-less text alone', () => {
	assert.equal(stripPreamble('图片类型：照片，一只猫。'), '图片类型：照片，一只猫。')
	assert.equal(stripPreamble('一只猫。'), '一只猫。')
	assert.equal(stripPreamble('图片类型：'), '图片类型：')
})

test('describeOne sends the prompt plus the image block and returns the text', async () => {
	const llm = fakeLlm([...deltas('图片类型：截图\n', '正文'), finish('stop')])
	const bridge = bridgeFor(llm)
	const result = await bridge.describeOne({ provider: 'route', model: 'vision-model', ref: REF, signal: undefined })

	assert.deepEqual(result, { text: '图片类型：截图\n正文' })
	assert.equal(llm.calls.length, 1)
	const options = llm.calls[0]
	assert.equal(options.provider, 'route')
	assert.equal(options.model, 'vision-model')
	assert.equal(options.maxTokens, 2048)
	const [textBlock, imageBlock] = options.messages[0].content
	assert.equal(textBlock.type, 'text')
	assert.equal(textBlock.text, DEFAULT_DESCRIBE_PROMPT)
	assert.equal(imageBlock.type, 'image')
	assert.equal(imageBlock.attachment, REF)
})

test('describeOne cuts a leaked preamble out of the stored description', async () => {
	const llm = fakeLlm([
		...deltas('我需要先看清图片。用户要求逐字转录。\n', '图片类型：截图，深色背景的文字。'),
		finish('stop'),
	])
	const result = await bridgeFor(llm).describeOne({ ref: REF, signal: undefined })
	assert.equal(result.text, '图片类型：截图，深色背景的文字。')
})

test('describeOne marks a length-limited description instead of passing it off as complete', async () => {
	const llm = fakeLlm([...deltas('图片类型：截图\n正文写到一半'), finish('length')])
	const result = await bridgeFor(llm).describeOne({ ref: REF, signal: undefined })
	assert.match(result.text, /正文写到一半/)
	assert.match(result.text, /可能被截断/)
})

test('describeOne reports a model error instead of returning partial text', async () => {
	const llm = fakeLlm([
		...deltas('图片类型：截图\n'),
		{ type: 'finish', reason: { kind: 'error', failure: { message: 'upstream 500' } } },
	])
	const result = await bridgeFor(llm).describeOne({ ref: REF, signal: undefined })
	assert.deepEqual(result, { error: 'upstream 500' })
})

test('describeOne reports an abort reason', async () => {
	const llm = fakeLlm([{ type: 'finish', reason: { kind: 'aborted' } }])
	const result = await bridgeFor(llm).describeOne({ ref: REF, signal: undefined })
	assert.equal(result.error, 'model call aborted')
})

test('describeOne reports empty content as an error', async () => {
	const llm = fakeLlm([finish('stop')])
	const result = await bridgeFor(llm).describeOne({ ref: REF, signal: undefined })
	assert.deepEqual(result, { error: 'empty description' })
})

test('describeOne degrades to an error when the llm service is missing', async () => {
	const bridge = createVisionBridge({
		getLlm: () => undefined,
		getLogger: () => undefined,
		getConfig: () => ({ provider: 'route', model: 'vision-model' }),
	})
	const result = await bridge.describeOne({ provider: 'route', model: 'vision-model', ref: REF, signal: undefined })
	assert.ok(result.error)
})

test('describeOne honours a caller override of the prompt and budget', async () => {
	const llm = fakeLlm([...deltas('图片类型：图表'), finish('stop')])
	const bridge = bridgeFor(llm, { describePrompt: '只描述数字', describeMaxTokens: 99 })
	await bridge.describeOne({ provider: 'route', model: 'vision-model', ref: REF, signal: undefined })
	assert.equal(llm.calls[0].maxTokens, 99)
	assert.equal(llm.calls[0].messages[0].content[0].text, '只描述数字')
})

test('describeAll keeps going after one image fails', async () => {
	let call = 0
	const llm = {
		calls: [],
		stream(options) {
			call += 1
			this.calls.push(options)
			const chunks = call === 1
				? [{ type: 'finish', reason: { kind: 'error', failure: { message: 'boom' } } }]
				: [...deltas('图片类型：照片\n一只猫。'), finish('stop')]
			return (async function* () {
				for (const chunk of chunks) yield chunk
			})()
		},
	}
	const results = await bridgeFor(llm).describeAll({
		provider: 'route',
		model: 'vision-model',
		refs: [REF, { attachmentId: 'img-2' }],
	})
	assert.equal(results.length, 2)
	assert.equal(results[0].error, 'boom')
	assert.equal(results[1].attachmentId, 'img-2')
	assert.match(results[1].text, /一只猫/)
})

test('describeAll stops issuing calls once the step is aborted', async () => {
	const llm = fakeLlm([...deltas('图片类型：照片'), finish('stop')])
	const controller = new AbortController()
	const bridge = bridgeFor(llm)
	controller.abort()
	const results = await bridge.describeAll({
		provider: 'route',
		model: 'vision-model',
		refs: [REF, { attachmentId: 'img-2' }],
		signal: controller.signal,
	})
	assert.equal(llm.calls.length, 0)
	assert.deepEqual(results.map((entry) => entry.error), ['aborted', 'aborted'])
})
test('stripPreamble removes a trace that quotes the anchor inside instructions', () => {
	// Streaming endpoints inline the reasoning trace into content deltas. The
	// trace quotes the format contract — anchor included — before the real
	// description begins on its own line.
	const leaked = [
		'哦，我需要提取图中的文字内容。',
		'用户要求第一行必须以「图片类型：」开头，之后逐项给出正文，禁止任何开场白或解释。我准备按这个要求组织',
		'',
		'输出。',
		'',
		'图片类型：界面截图，展示上下文用量面板。',
		'',
		'1) 逐字转录：上下文已用 64%',
	].join('\n');
	assert.equal(stripPreamble(leaked), '图片类型：界面截图，展示上下文用量面板。\n\n1) 逐字转录：上下文已用 64%');
});

test('stripPreamble rejects a quoted anchor but keeps a later real one', () => {
	const leaked = '好的。第一行以「图片类型：」开头。图片类型：照片，一只猫。';
	assert.equal(stripPreamble(leaked), '图片类型：照片，一只猫。');
});

test('stripPreamble prefers the last candidate when a trace quotes twice', () => {
	const leaked = '要求「图片类型：」开头。「图片类型：」？最终：图片类型：图表。';
	assert.equal(stripPreamble(leaked), '图片类型：图表。');
});

test('stripPreamble leaves an anchor-less trace untouched (no wrong cut)', () => {
	const leaked = '我先想想。这是一张深色界面截图。';
	assert.equal(stripPreamble(leaked), leaked);
});

test('stripPreamble removes the 备注 wrapper and inlined trace before the fence', () => {
	// The exact streaming shape this endpoint produces: a wrapper marker, the
	// reasoning trace, a closing fence, then the real description.
	const leaked = [
		'备注',
		'哦，我需要提取图中的文字内容。',
		'这张图是深色界面截图……我需要按这个要求组织输出：第一行先写图片类型和概括。',
		'```',
		'图片类型：软件界面截图，展示一个深色主题的上下文用量统计浮层。',
		'',
		'1) 逐字转录所有可见文字：',
		'上下文已用 64%',
	].join('\n');
	assert.equal(
		stripPreamble(leaked),
		'图片类型：软件界面截图，展示一个深色主题的上下文用量统计浮层。\n\n1) 逐字转录所有可见文字：\n上下文已用 64%',
	);
});

test('stripPreamble prefers the last line-start anchor over an earlier draft', () => {
	const leaked = [
		'备注',
		'我准备这样写：',
		'图片类型：草稿版本，可能不对。',
		'```',
		'图片类型：正式描述。',
		'',
		'1) 内容',
	].join('\n');
	assert.equal(stripPreamble(leaked), '图片类型：正式描述。\n\n1) 内容');
});

test('stripPreamble handles the anchor-less trace the real session produced', () => {
	// glm-5.3 run: no fence, no anchor line; the trace quotes the instructions
	// (anchor included, mid-line) and the answer begins after 「输出。」.
	const leaked = [
		'哦，我需要提取图中的文字内容。',
		'用户要求第一行必须以「图片类型：」开头，之后逐项给出正文，禁止任何开场白或解释。我准备按这个要求组织',
		'',
		'输出。截图，一张聊天/AI 助手界面片段截图，包含操作说明文字和底部文件编辑状态卡片。',
		'',
		'1) 逐字转录所有可见文字：',
		'图片标签 9/9',
	].join('\n');
	assert.equal(
		stripPreamble(leaked),
		'截图，一张聊天/AI 助手界面片段截图，包含操作说明文字和底部文件编辑状态卡片。\n\n1) 逐字转录所有可见文字：\n图片标签 9/9',
	);
});

test('stripPreamble keeps fenced code inside a real description', () => {
	// A screenshot OF code produces a description that legitimately contains a
	// fence in its transcription; the line-start anchor rule must win first.
	const clean = [
		'图片类型：代码截图。',
		'',
		'1) 逐字转录：',
		'```js',
		'const x = 1',
		'```',
	].join('\n');
	assert.equal(stripPreamble(clean), clean);
});
