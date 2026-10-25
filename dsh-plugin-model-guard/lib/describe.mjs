/**
 * Vision fallback: turn pasted images into text through a model that can
 * actually see them.
 *
 * The plugin mode exists because the host admits an image only when the
 * selected model declares the `image` input modality, while the model list a
 * user configures is mostly text-only. Requirement 2(b) of the plugin is
 * therefore implemented here: the Harness rewrites the message a step is about
 * to send, so an image a text-only model cannot consume becomes a description
 * produced by a multimodal model on the same provider route.
 *
 * No `@deepseek-ai/*` import: the `llm` service is passed in as a call
 * argument so this module stays dependency-free and unit-testable.
 */

/** Default instruction sent with every image; the user can override it. */
/** The one line the description must start with; also the preamble cut mark. */
export const DESCRIBE_ANCHOR = '图片类型：';

export const DEFAULT_DESCRIBE_PROMPT = [
	'用中文描述这张图片，读者是一个看不到图片、只能依赖你这段文字的模型。',
	'输出格式（严格遵守）：',
	`第一行必须以「${DESCRIBE_ANCHOR}」开头，写明图片类型（截图/照片/图表/表格/代码/文档扫描等）与一句话概括；`,
	'之后逐项给出正文：',
	'1) 逐字转录所有可见文字，保留原有顺序与行结构（这是最重要的部分）；',
	'2) 说明关键对象、数量、颜色与它们的相对位置；',
	'3) 若是图表、表格或界面截图，给出数值、坐标轴、行列标题与结构；',
	'4) 无法确认的地方写「不确定」，不要臆测或补全不存在的内容。',
	'禁止：任何开场白、寒暄、自我介绍、复述或解释这段要求、输出你的思考过程、「我们需要…」「用户要求…」这类自言自语；',
	'禁止：把这段要求当成问题来回答，或回答图片以外的内容。',
	'第一个字符就是「图」，不要有任何前缀。',
].join('\n');

/**
 * Drop a leaked chain-of-thought preamble.
 *
 * Why this is not a simple `indexOf(ANCHOR)`: on this provider, streaming
 * responses inline the reasoning trace into the content deltas, wrapped as
 *
 *     备注
 *     哦，我需要提取图中的文字内容。……我准备按这个要求组织
 *     ```
 *     图片类型：软件界面截图，……
 *
 * The trace *quotes the prompt*, so the anchor itself appears inside the trace
 * (「图片类型：」开头), and some runs omit the anchor line entirely and answer
 * with the bare summary. The rules below are ordered by how strong each piece
 * of evidence is:
 *
 * 1. the last line that starts with the anchor — the contract position of the
 *    real description; a trace can draft the anchor earlier, never later;
 * 2. the last ``` fence line — the wrapper this endpoint puts around inlined
 *    thinking; the description follows it;
 * 3. an anchor that is not immediately a quoted fragment (「图片类型：」), taking
 *    the last candidate, for runs that answer on the same line as a prefix;
 * 4. otherwise drop leading planning paragraphs and transition prefixes
 *    (「输出。」), which is what an anchor-less trace leaves behind.
 *
 * @param {string} text
 * @returns {string}
 */
export function stripPreamble(text) {
	const value = typeof text === 'string' ? text : '';
	const trimmed = value.replace(/^[^\S\n]+/, '');
	if (trimmed.startsWith(DESCRIBE_ANCHOR)) return trimmed;

	// 1. Contract position: the last line that starts with the anchor.
	const lineStarts = [...trimmed.matchAll(/(^|\n)[^\S\n]*图片类型：/g)];
	if (lineStarts.length > 0) {
		const last = lineStarts[lineStarts.length - 1];
		const at = last.index + (last[1] === '\n' ? 1 : 0);
		return trimmed.slice(at).replace(/^[^\S\n]+/, '');
	}

	// 2. The fence that closes inlined thinking on this endpoint.
	const fenceEnd = lastFenceEnd(trimmed);
	if (fenceEnd > 0) return trimmed.slice(fenceEnd).replace(/^[^\S\n]+/, '');

	// 3. An anchor that is not a quoted fragment of the instructions.
	let chosen = -1;
	let cursor = trimmed.indexOf(DESCRIBE_ANCHOR);
	while (cursor !== -1) {
		const next = trimmed[cursor + DESCRIBE_ANCHOR.length];
		if (next === undefined || !/^[」"'』）)]/.test(next)) chosen = cursor;
		cursor = trimmed.indexOf(DESCRIBE_ANCHOR, cursor + 1);
	}
	if (chosen > 0) return trimmed.slice(chosen);

	// 4. No anchor anywhere: drop the trace's planning paragraphs.
	return dropPlanning(trimmed);
}

/** End offset of the last line that is a bare markdown fence. */
function lastFenceEnd(text) {
	let end = -1;
	const lines = text.split('\n');
	let offset = 0;
	for (const line of lines) {
		if (/^\s*```/.test(line)) end = offset + line.length;
		offset += line.length + 1;
	}
	return end;
}

/** A leading sentence that only announces the answer. */
const TRANSITION_PREFIX = /^(输出|如下|以下是|好的|明白了?|哦，?)[。：:，、]\s*/;

/** Language a reasoning trace uses while planning the reply. */
const PLANNING_LANGUAGE =
	/(我需要|我准备|我会|我将|用户要求|要求逐字|格式要求|禁止|需要按|按这个|组织输出|首先|接下来|备注|思考)/;

/** Strip announcing prefixes such as 「输出。」 repeatedly. */
function dropLeadingTransitions(text) {
	let value = text;
	while (TRANSITION_PREFIX.test(value)) value = value.replace(TRANSITION_PREFIX, '');
	return value;
}

/** Drop leading paragraphs that read like planning, keeping the answer. */
function dropPlanning(text) {
	const paragraphs = text.split(/\n{2,}/);
	let dropped = 0;
	for (const paragraph of paragraphs.slice(0, 4)) {
		const candidate = dropLeadingTransitions(paragraph.trim());
		if (candidate.length === 0 || !PLANNING_LANGUAGE.test(candidate)) break;
		dropped += 1;
	}
	const rest = dropped === 0 ? text : paragraphs.slice(dropped).join('\n\n');
	return dropLeadingTransitions(rest.replace(/^[^\S\n]+/, ''));
}

/**
 * Build the vision-bridge closure used by the host wiring.
 * @param {object} options
 * @param {() => any} options.getLlm - returns the `llm` service (or undefined).
 * @param {() => any} options.getLogger - returns the logger (or undefined).
 * @param {() => object} options.getConfig - returns resolved plugin config.
 * @returns {{
 *   describeOne: (input: object) => Promise<{text?: string, error?: string}>,
 *   describeAll: (input: object) => Promise<Array<{attachmentId: string, text?: string, error?: string}>>,
 * }}
 */
export function createVisionBridge({ getLlm, getLogger, getConfig }) {
	/** Describe one image reference; never throws. */
	async function describeOne({ provider, model, ref, signal }) {
		const llm = getLlm();
		if (llm === undefined || typeof llm.stream !== 'function') {
			return { error: 'llm service is unavailable' };
		}
		const config = getConfig();
		const prompt = typeof config.describePrompt === 'string' && config.describePrompt.trim().length > 0
			? config.describePrompt
			: DEFAULT_DESCRIBE_PROMPT;
		const timeoutMs = positiveNumber(config.describeTimeoutMs, 120_000);
		const maxTokens = positiveNumber(config.describeMaxTokens, 2_048);

		const local = new AbortController();
		const onOuterAbort = () => local.abort(outerReason(signal));
		if (signal !== undefined) {
			if (signal.aborted) return { error: 'aborted' };
			signal.addEventListener('abort', onOuterAbort, { once: true });
		}
		let timedOut = false;
		const timer = setTimeout(() => {
			timedOut = true;
			local.abort(new Error('describe timeout'));
		}, timeoutMs);
		if (typeof timer.unref === 'function') timer.unref();

		let text = '';
		let failure;
		let truncated = false;
		try {
			const stream = llm.stream({
				provider,
				model,
				maxTokens,
				messages: [{
					role: 'user',
					content: [
						{ type: 'text', text: prompt },
						{ type: 'image', attachment: ref },
					],
				}],
				signal: local.signal,
			});
			for await (const chunk of stream) {
				if (chunk?.type === 'text-delta' && typeof chunk.text === 'string') {
					text += chunk.text;
					continue;
				}
				if (chunk?.type === 'block-end' && chunk.block?.type === 'text' && text.length === 0) {
					text = chunk.block.text ?? '';
					continue;
				}
				if (chunk?.type === 'finish') {
					const reason = chunk.reason;
					if (reason?.kind === 'error') failure = reason.failure?.message ?? 'model call failed';
					else if (reason?.kind === 'aborted') failure = reason.failure?.message ?? 'model call aborted';
					else if (reason?.kind !== undefined && /length|max/i.test(String(reason.kind))) truncated = true;
					break;
				}
			}
		} catch (error) {
			let message;
			try {
				message = error instanceof Error ? error.message : String(error);
			} catch {
				message = 'unknown error';
			}
			failure = message;
		} finally {
			clearTimeout(timer);
			if (signal !== undefined) signal.removeEventListener('abort', onOuterAbort);
		}

		if (failure !== undefined) {
			const hint = timedOut ? `超时（${timeoutMs}ms）` : failure;
			getLogger()?.warn?.(`model-guard: 识图失败（${provider}/${model}）：${hint}`);
			return { error: hint };
		}
		const trimmed = stripPreamble(text.trim());
		if (trimmed.length === 0) {
			getLogger()?.warn?.(`model-guard: 识图返回空内容（${provider}/${model}）`);
			return { error: 'empty description' };
		}
		// An output cut at the token ceiling would otherwise read as complete.
		return truncated ? { text: `${trimmed}\n（注：描述达到输出长度上限，末尾可能被截断）` } : { text: trimmed };
	}

	/**
	 * Describe images sequentially so one slow call cannot fan out into N
	 * concurrent provider requests, and so the first failure does not hide the
	 * successes that already arrived.
	 */
	async function describeAll({ provider, model, refs, signal }) {
		const results = [];
		for (const ref of refs) {
			if (signal?.aborted) {
				results.push({ attachmentId: ref.attachmentId, error: 'aborted' });
				continue;
			}
			const outcome = await describeOne({ provider, model, ref, signal });
			results.push({ attachmentId: ref.attachmentId, ...outcome });
		}
		return results;
	}

	return { describeOne, describeAll };
}

/** Re-throw the outer cancellation reason inside the local controller. */
function outerReason(signal) {
	try {
		return signal?.reason ?? new Error('aborted');
	} catch {
		return new Error('aborted');
	}
}

function positiveNumber(value, fallback) {
	return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback;
}

/**
 * Collect the image blocks a step would send to a model.
 * @param {readonly object[]} messages - the messages of one `agent/pre-step` decision.
 * @returns {Array<{ref: object, messageIndex: number, blockIndex: number}>}
 */
export function collectImages(messages) {
	const found = [];
	if (!Array.isArray(messages)) return found;
	for (const [messageIndex, message] of messages.entries()) {
		if (message?.role !== 'user' || !Array.isArray(message.content)) continue;
		for (const [blockIndex, block] of message.content.entries()) {
			if (block?.type !== 'image' || block.offloaded === true) continue;
			if (block.attachment === undefined || block.attachment === null) continue;
			found.push({ ref: block.attachment, messageIndex, blockIndex });
		}
	}
	return found;
}

/**
 * Replace every non-offloaded image block in a user message with the text that
 * stands in for it, keeping all other blocks and the message identity intact.
 * @param {object} message - the user message to rewrite.
 * @param {Map<string, {text?: string, error?: string}>} byAttachment - outcomes by attachment id.
 * @param {string} label - the model that produced the descriptions.
 * @returns {object} the same message object when nothing changed.
 */
export function rewriteMessage(message, byAttachment, label) {
	const parts = [];
	let changed = false;
	for (const block of message.content) {
		if (block?.type === 'image' && block.offloaded !== true && block.attachment !== undefined) {
			const outcome = byAttachment.get(block.attachment.attachmentId);
			changed = true;
			parts.push({ type: 'text', text: renderImageText(block.attachment, outcome, label) });
			continue;
		}
		parts.push(block);
	}
	if (!changed) return message;
	return { ...message, content: parts };
}

/** One image's model-visible text: the description, or an explicit failure note. */
function renderImageText(attachment, outcome, label) {
	const name = attachment?.name === undefined ? '图片' : `图片「${attachment.name}」`;
	if (outcome?.text !== undefined) {
		return `【${name}·转述】以下内容由 ${label} 识别后转述，原图本身未直接发送给当前模型：\n${outcome.text}`;
	}
	const reason = outcome?.error === undefined ? '未知原因' : outcome.error;
	return `【${name}·无法识别】当前模型不支持图片输入，且识图模型调用失败（${reason}）。请告知用户这张图片未能被读取，必要时请其重新发送或改用支持多模态的模型。`;
}
