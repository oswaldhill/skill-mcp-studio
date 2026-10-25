/**
 * model-guard: keep every hand-configured custom model usable.
 *
 * At every process start this host plugin audits the `@deepseek-ai/dsh-llm-pi-ai`
 * providers configuration and checks the three things the deployment asked for:
 *
 * 1. every custom model declares the `image` input modality, so the Harness UI
 *    admits a pasted image for it at all;
 * 2. the model that actually looks at an image is chosen by measured
 *    capability, never by that declaration: a truly multimodal model receives
 *    the image, while a text-only model first receives a description produced
 *    by a multimodal model from the same custom list (`agent/pre-step` rewrite
 *    in `lib/describe.mjs`);
 * 3. every model's effective context window is the largest value known for it —
 *    the provider's own `/models` listing when advertised, otherwise the
 *    Harness default of 262144 that an undeclared window already falls back to.
 *
 * Findings are never repaired silently. They are published to the agent through
 * a system-prompt section (which tells it to ask the user), to the user through
 * the `/model-guard` command, and to the model through the `model_guard` tool.
 * Repairs go through `ctx.configEditor`, so the Harness validates, persists, and
 * reloads them itself; this plugin never rewrites profile files by hand.
 *
 * Deliberately dependency-free: no `@deepseek-ai/*` import, so the bundle
 * activates no matter which peer packages this Harness build exposes.
 */

import { auditSnapshot, DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_TOKENS } from './lib/audit.mjs'
import { discoverModels, probeImageSupport } from './lib/probe.mjs'
import { collectImages, createVisionBridge, rewriteMessage } from './lib/describe.mjs'

export const name = 'model-guard'

/** Services this plugin cannot run without. */
export const inject = ['llm', 'configEditor', 'credentials', 'tools', 'commands', 'systemPrompt']

const LLM_PI_AI = '@deepseek-ai/dsh-llm-pi-ai'
const VISION_PLUGIN = 'dsh-plugin-vision'
const CAPABILITY_IMAGE = 'image'
const CAPABILITY_TEXT = 'text'
const CAPABILITY_UNKNOWN = 'unknown'
const DISCOVERY_TTL_MS = 10 * 60 * 1000
const AUDIT_TTL_MS = 60 * 1000
const PROBE_CONCURRENCY = 3

/** Bumped with package.json; also printed so a running build is identifiable. */
const VERSION = '0.2.2'

/** The row that names the model a new session starts on. */
const AGENT_DEFAULT_MODEL = '@deepseek-ai/dsh-agent-default-model'

/** Keys this section uses, kept in one place for the README and the tests. */
const CONFIG_DEFAULTS = Object.freeze({
	enabled: true,
	auditOnStartup: true,
	announce: true,
	probeImages: 'auto',
	probeTimeoutMs: 20_000,
	discoveryTimeoutMs: 8_000,
	describeTimeoutMs: 120_000,
	describeMaxTokens: 2_048,
	describerModel: '',
	imageModels: [],
	textModels: [],
	describePrompt: '',
	manageVisionPlugin: false,
})

/** @param {unknown} ctx - host plugin context. @param {object} rawConfig - loader config row. */
export function apply(ctx, rawConfig) {
	const config = resolveConfig(rawConfig)
	const logger = ctx.logger
	const llm = ctx.llm
	const configEditor = ctx.configEditor
	const bridge = createVisionBridge({
		getLlm: () => ctx.get('llm'),
		getLogger: () => logger,
		getConfig: () => config,
	})

	const state = {
		/** @type {null | {at: number, routes: Array<{route: object, plan: object}>, describer: object|undefined, error?: string, probed: number}} */
		audit: null,
		/** `${provider}\u0000${model}` -> 'image' | 'text' (measured only). */
		capabilities: new Map(),
		/** provider -> {at, models: Map<string, object>, error?} */
		discovery: new Map(),
		/** Config rows read for the current audit. */
		routes: [],
		running: null,
		lastApplied: null,
	}

	// ---------------------------------------------------------------- reporting

	/** Human-readable one-line label for a model's declared state. */
	function describeModel(route, model) {
		const parts = [`${route.name}/${model.id}`]
		if (Array.isArray(model.input) && model.input.includes(CAPABILITY_IMAGE)) parts.push('已声明 image')
		return parts.join(' · ')
	}

	/** Multi-line Chinese report used by the tool, the command, and the logs. */
	/** Render `['text','image']` the way the audit messages do. */
	function renderModalities(modalities) {
		return `[${modalities.join(', ')}]`
	}

	function renderReport(audit) {
		if (audit === null) return '尚未完成检查。'
		if (audit.error !== undefined) return `检查未完成：${audit.error}`
		const lines = []
		let counts = { error: 0, warn: 0, info: 0 }
		for (const { route, plan } of audit.routes) {
			const s = plan.summary
			lines.push(
				`路由 ${route.name}：${s.totalModels} 个自定义模型，`
				+ `${s.imageTagged} 个已声明 image 标签，`
				+ `${s.imageCapable} 个实测支持图片，`
				+ `${s.textOnly} 个纯文本，`
				+ `${s.unknown} 个能力未知；最大上下文 ${s.maxContextWindow}。`,
			)
			for (const issue of plan.issues) {
				counts[issue.severity] = (counts[issue.severity] ?? 0) + 1
				lines.push(`  - [${issue.severity}] ${issue.code}${issue.model === undefined ? '' : ` (${issue.model})`}：${issue.message}`)
			}
		}
		const runtime = audit.runtime
		if (runtime !== undefined) {
			const parts = []
			if (runtime.contextWindow !== undefined) parts.push(`上下文 ${runtime.contextWindow}`)
			if (runtime.inputModalities !== undefined) parts.push(`输入 ${renderModalities(runtime.inputModalities)}`)
			if (runtime.error !== undefined) parts.push(`解析失败：${runtime.error}`)
			if (parts.length > 0) lines.push(`运行时视图：${runtime.provider}/${runtime.model} → ${parts.join('，')}。`)
			if (Array.isArray(runtime.mismatches)) {
				for (const mismatch of runtime.mismatches) lines.push(`  - [warn] RUNTIME_MISMATCH：${mismatch}。`)
			}
		}
		const describer = audit.describer
		lines.push(describer === undefined
			? '识图回退：未找到可用的多模态模型，纯文本模型无法看图。'
			: `识图回退：纯文本模型将使用 ${describer.provider}/${describer.model} 识别图片后再作答。`)
		lines.push(`汇总：error ${counts.error ?? 0} 项，warn ${counts.warn ?? 0} 项，info ${counts.info ?? 0} 项。`)
		const fixable = audit.routes.some(({ plan }) => plan.issues.some((issue) => issue.fixable))
		lines.push(fixable ? '可修复项：运行 /model-guard fix（或调用 model_guard 工具 apply）即可写入配置。' : '没有可自动修复的项。')
		lines.push(`（model-guard v${VERSION}）`)
		return lines.join('\n')
	}

	// ------------------------------------------------------------ config access

	/** Read the effective `llm-pi-ai` and `vision` rows without mutating anything. */
	function readRows() {
		const rows = configEditor.configuration()
		// A row may be addressed by package name or only by its patch id: the
		// profile's `vision` row, for instance, carries no package name.
		const match = (row, names, ids) => {
			const options = row?.entry?.options ?? {}
			return names.includes(options.name) || ids.includes(options.id)
		}
		const llmRow = rows.find((row) => match(row, [LLM_PI_AI], ['llm-pi-ai'])) ?? null
		const visionRow = rows.find((row) => match(row, [VISION_PLUGIN], ['vision'])) ?? null
		const defaultModelRow = rows.find((row) => match(row, [AGENT_DEFAULT_MODEL], ['agent-default-model'])) ?? null
		return { rows, llmRow, visionRow, defaultModelRow }
	}

	/** Effective provider routes that declare at least one model. */
	function readRoutes() {
		const { llmRow, visionRow } = readRows()
		if (llmRow === null) {
			return { routes: [], vision: undefined, present: false, error: `未找到 ${LLM_PI_AI} 配置行` }
		}
		const current = isRecord(llmRow.entry?.options?.config) ? llmRow.entry.options.config : {}
		const effective = deepMerge(cloneJson(llmRow.inherited ?? {}), cloneJson(current))
		const providers = isRecord(effective.providers) ? effective.providers : {}
		const routes = []
		for (const [routeName, profile] of Object.entries(providers)) {
			if (!isRecord(profile)) continue
			const models = normalizeModels(profile.models)
			if (models.length === 0) continue
			routes.push({
				name: routeName,
				api: typeof profile.api === 'string' ? profile.api : undefined,
				baseURL: typeof profile.baseURL === 'string' ? profile.baseURL : undefined,
				apiKeyEnv: typeof profile.apiKeyEnv === 'string' ? profile.apiKeyEnv : undefined,
				defaultContextWindow: numberOr(profile.defaultContextWindow),
				defaultMaxTokens: numberOr(profile.defaultMaxTokens),
				models,
			})
		}
		const vision = visionRow === null ? undefined : (() => {
			const rowCurrent = isRecord(visionRow.entry?.options?.config) ? visionRow.entry.options.config : {}
			const eff = deepMerge(cloneJson(visionRow.inherited ?? {}), cloneJson(rowCurrent))
			return {
				present: true,
				provider: typeof eff.provider === 'string' ? eff.provider : undefined,
				model: typeof eff.model === 'string' ? eff.model : undefined,
				baseURL: typeof eff.baseURL === 'string' ? eff.baseURL : undefined,
				autoDescribe: eff.autoDescribe === true,
			}
		})()
		return { routes, vision, present: true }
	}

	/** Resolve one route's API key: the credentials service first, then the process environment. */
	async function apiKeyOf(route) {
		if (route.apiKeyEnv === undefined) return undefined
		const credentials = ctx.get('credentials')
		if (credentials !== undefined) {
			try {
				const hit = await credentials.resolve(route.apiKeyEnv)
				if (hit?.value) return hit.value
			} catch (error) {
				logger.warn?.(`model-guard: 读取凭据 ${route.apiKeyEnv} 失败：${String(error)}`)
			}
		}
		const ambient = process.env[route.apiKeyEnv]
		return ambient !== undefined && ambient.length > 0 ? ambient : undefined
	}

	// -------------------------------------------------------- capability probes

	function capabilityKey(routeName, modelId) {
		return `${routeName}\u0000${modelId}`
	}

	/** Declared pin from the plugin config, if any. */
	function pinnedCapability(routeName, modelId) {
		if (config.textModels.includes(modelId)) return CAPABILITY_TEXT
		if (config.imageModels.includes(modelId)) return CAPABILITY_IMAGE
		return undefined
	}

	/** Query the provider's model listing once per TTL; failures are remembered, not thrown. */
	async function discoveryOf(route, { signal, refresh } = {}) {
		const cached = state.discovery.get(route.name)
		if (cached !== undefined && refresh !== true && Date.now() - cached.at < DISCOVERY_TTL_MS) return cached
		const entry = { at: Date.now(), models: new Map(), error: undefined }
		if (route.baseURL !== undefined && route.baseURL.length > 0) {
			const apiKey = await apiKeyOf(route)
			const result = await discoverModels({
				baseURL: route.baseURL,
				api: route.api,
				apiKey,
				timeoutMs: config.discoveryTimeoutMs,
			})
			for (const model of result.models) entry.models.set(model.id, model)
			if (result.error !== undefined) entry.error = result.error
		} else {
			entry.error = '未配置 baseURL'
		}
		state.discovery.set(route.name, entry)
		return entry
	}

	/** Probe one exact model once per process and cache a definite verdict. */
	async function probeCapability(route, modelId, { signal } = {}) {
		const key = capabilityKey(route.name, modelId)
		const cached = state.capabilities.get(key)
		if (cached !== undefined) return cached
		if (config.probeImages !== 'auto') return CAPABILITY_UNKNOWN
		if (route.baseURL === undefined || route.baseURL.length === 0) return CAPABILITY_UNKNOWN
		const apiKey = await apiKeyOf(route)
		const result = await probeImageSupport({
			baseURL: route.baseURL,
			api: route.api,
			apiKey,
			model: modelId,
			timeoutMs: config.probeTimeoutMs,
		})
		logger.debug?.(`model-guard: 探测 ${route.name}/${modelId} → ${result.verdict}${result.detail === undefined ? '' : `（${result.detail}）`}`)
		if (result.verdict !== CAPABILITY_UNKNOWN) {
			state.capabilities.set(key, result.verdict)
			return result.verdict
		}
		return CAPABILITY_UNKNOWN
	}

	/**
	 * Measured capability of one model: pins, then discovery metadata, then a
	 * live probe. The declared `input` modality is never consulted — it is the
	 * admission flag this plugin sets, not evidence about the model.
	 */
	async function capabilityOf(routeName, modelId, { signal, allowProbe = true } = {}) {
		const pinned = pinnedCapability(routeName, modelId)
		if (pinned !== undefined) return pinned
		const cached = state.capabilities.get(capabilityKey(routeName, modelId))
		if (cached !== undefined) return cached
		const discovered = state.discovery.get(routeName)?.models?.get(modelId)?.inputModalities
		if (Array.isArray(discovered) && discovered.length > 0) {
			const verdict = discovered.includes(CAPABILITY_IMAGE) ? CAPABILITY_IMAGE : CAPABILITY_TEXT
			state.capabilities.set(capabilityKey(routeName, modelId), verdict)
			return verdict
		}
		if (!allowProbe) return CAPABILITY_UNKNOWN
		const route = state.routes.find((candidate) => candidate.name === routeName)
		if (route === undefined) return CAPABILITY_UNKNOWN
		return probeCapability(route, modelId, { signal })
	}

	// -------------------------------------------------------------------- audit

	/** Run one full audit, reusing an in-flight run unless `force` is set. */
	function runAudit({ force = false } = {}) {
		if (state.running !== null && force !== true) return state.running
		const run = (async () => {
			const read = readRoutes()
			state.routes = read.routes
			if (read.present !== true) {
				state.audit = { at: Date.now(), routes: [], describer: undefined, error: read.error }
				logger.warn?.(`model-guard: ${read.error}`)
				return state.audit
			}
			const routePlans = []
			let probed = 0
			for (const route of read.routes) {
				const discovery = await discoveryOf(route)
				const capabilities = {}
				for (const model of route.models) {
					const verdict = await capabilityOf(route.name, model.id, { allowProbe: false })
					if (verdict !== CAPABILITY_UNKNOWN) {
						capabilities[model.id] = verdict
						continue
					}
					if (config.probeImages === 'auto' && route.baseURL !== undefined) {
						const live = await probeCapability(route, model.id)
						probed += 1
						if (live !== CAPABILITY_UNKNOWN) capabilities[model.id] = live
					}
				}
				const discovered = {}
				for (const [id, entry] of discovery.models) {
					discovered[id] = {
						...(entry.contextWindow === undefined ? {} : { contextWindow: entry.contextWindow }),
						...(entry.maxTokens === undefined ? {} : { maxTokens: entry.maxTokens }),
						...(entry.inputModalities === undefined ? {} : { inputModalities: entry.inputModalities }),
					}
				}
				const plan = auditSnapshot({
					route: route.name,
					models: route.models,
					capabilities,
					discovered,
					...(route.defaultContextWindow === undefined ? {} : { defaultContextWindow: route.defaultContextWindow }),
					...(route.defaultMaxTokens === undefined ? {} : { defaultMaxTokens: route.defaultMaxTokens }),
					...(config.describerModel.length > 0 ? { describerModel: config.describerModel } : {}),
					imageModels: config.imageModels,
					textModels: config.textModels,
					...(read.vision === undefined ? {} : { vision: read.vision }),
				})
				routePlans.push({ route, plan })
			}
			const { defaultModelRow } = readRows()
			const defaultConfig = isRecord(defaultModelRow?.entry?.options?.config) ? defaultModelRow.entry.options.config : {}
			const defaultProvider = typeof defaultConfig.provider === 'string' ? defaultConfig.provider : ''
			const defaultModel = typeof defaultConfig.model === 'string' ? defaultConfig.model : ''
			const runtime = defaultProvider.length > 0 && defaultModel.length > 0
				? await runtimeReport(defaultProvider, defaultModel, routePlans)
				: undefined
			const describer = selectDescriber(routePlans)
			state.audit = { at: Date.now(), routes: routePlans, describer, probed, runtime }
			logAudit(state.audit)
			return state.audit
		})().catch((error) => {
			state.audit = { at: Date.now(), routes: [], describer: undefined, error: String(error?.message ?? error) }
			logger.warn?.(`model-guard: 启动检查失败：${String(error)}`)
			return state.audit
		}).finally(() => {
			state.running = null
		})
		state.running = run
		return run
	}

	/**
	 * Ask the llm adapter what it really uses for one route, rather than trusting
	 * the written config. A stale adapter or a catalog override shows up here.
	 */
	async function runtimeView(routeName, modelId) {
		const llm = ctx.get('llm') ?? ctx.llm
		if (llm === undefined || typeof llm.resolveModelInfo !== 'function') return undefined
		try {
			const info = await llm.resolveModelInfo(routeName, modelId)
			return {
				contextWindow: typeof info?.context?.contextWindow === 'number' ? info.context.contextWindow : undefined,
				inputModalities: Array.isArray(info?.inputModalities) ? [...info.inputModalities] : undefined,
			}
		} catch (error) {
			return { error: String(error?.message ?? error) }
		}
	}

	/**
	 * Compare what the adapter resolved with what the profile declares, for the
	 * default model and for every model of the same route. A stale adapter or a
	 * catalog override changes these numbers, and the audit alone cannot see it.
	 */
	async function runtimeReport(provider, model, routePlans) {
		const view = await runtimeView(provider, model)
		if (view === undefined) return undefined
		const report = { provider, model, ...view }
		const routePlan = routePlans.find(({ route }) => route.name === provider)
		if (routePlan === undefined) return report
		const mismatches = []
		for (const entry of routePlan.route.models) {
			const one = await runtimeView(provider, entry.id)
			if (one === undefined || one.error !== undefined) continue
			const declaredInput = Array.isArray(entry.input) ? entry.input : []
			if (one.inputModalities !== undefined && declaredInput.length > 0) {
				const same = declaredInput.length === one.inputModalities.length
					&& declaredInput.every((value) => one.inputModalities.includes(value))
				if (!same) mismatches.push(`${entry.id} 输入声明 ${renderModalities(declaredInput)} 而运行时 ${renderModalities(one.inputModalities)}`)
			}
			const declaredContext = typeof entry.contextWindow === 'number' ? entry.contextWindow : undefined
			if (declaredContext !== undefined && one.contextWindow !== undefined && declaredContext !== one.contextWindow) {
				mismatches.push(`${entry.id} 上下文声明 ${declaredContext} 而运行时 ${one.contextWindow}`)
			}
		}
		if (mismatches.length > 0) report.mismatches = mismatches
		return report
	}

	/** Pick the model that describes images for text-only models. */
	function selectDescriber(routePlans) {
		for (const { route, plan } of routePlans) {
			if (plan.describer !== null && plan.describer !== undefined) {
				return { provider: route.name, model: plan.describer.model }
			}
		}
		return undefined
	}

	function logAudit(audit) {
		if (audit === null || audit.error !== undefined) return
		const issues = audit.routes.flatMap(({ route, plan }) => plan.issues.map((issue) => ({ route: route.name, issue })))
		if (issues.length === 0) {
			logger.info?.('model-guard: 自定义模型配置检查通过。')
			return
		}
		logger.warn?.(`model-guard: 自定义模型配置检查发现 ${issues.length} 项问题（可运行 /model-guard 查看，fix 修复）。`)
		for (const { route: routeName, issue } of issues) {
			const prefix = `model-guard: [${routeName}] ${issue.code}`
			if (issue.severity === 'error') logger.warn?.(`${prefix}：${issue.message}`)
			else logger.info?.(`${prefix}：${issue.message}`)
		}
	}

	/** Audit on demand with a freshness bound. */
	async function ensureAudit({ refresh = false } = {}) {
		if (refresh) return runAudit({ force: true })
		if (state.audit !== null && state.running === null && Date.now() - state.audit.at < AUDIT_TTL_MS) return state.audit
		return runAudit()
	}

	// ------------------------------------------------------------------ repair

	/** Apply every fixable change of the last audit through the config editor. */
	async function applyFixes() {
		const audit = await ensureAudit({ refresh: true })
		if (audit.error !== undefined) return { ok: false, changed: [], text: `检查未完成，未写入任何配置：${audit.error}` }
		const pending = audit.routes.filter(({ plan }) => plan.issues.some((issue) => issue.fixable))
		if (pending.length === 0) return { ok: true, changed: [], text: '没有需要修复的配置项，未修改任何内容。' }

		const { llmRow, visionRow } = readRows()
		if (llmRow === null) return { ok: false, changed: [], text: `未找到 ${LLM_PI_AI} 配置行，无法修复。` }

		/** @type {string[]} */
		const changed = []
		await configEditor.edit(llmRow.entry, (current, inherited) => {
			const next = deepMerge(cloneJson(inherited ?? {}), cloneJson(isRecord(current) ? current : {}))
			const providers = isRecord(next.providers) ? next.providers : {}
			for (const { route, plan } of pending) {
				const profile = providers[route.name]
				if (!isRecord(profile)) continue
				if (plan.llmChanges.defaultContextWindow !== undefined) {
					profile.defaultContextWindow = plan.llmChanges.defaultContextWindow
					changed.push(`${route.name}: defaultContextWindow → ${plan.llmChanges.defaultContextWindow}`)
				}
				const models = Array.isArray(profile.models) ? profile.models : []
				for (const [modelId, change] of Object.entries(plan.llmChanges.models ?? {})) {
					const index = models.findIndex((entry) => (typeof entry === 'string' ? entry : entry?.id) === modelId)
					if (index < 0) continue
					const raw = models[index]
					const entry = typeof raw === 'string' ? { id: raw } : { ...raw }
					if (change.input !== undefined) {
						entry.input = [...change.input]
						changed.push(`${route.name}/${modelId}: input → [${change.input.join(', ')}]`)
					}
					if (change.contextWindow !== undefined) {
						entry.contextWindow = change.contextWindow
						changed.push(`${route.name}/${modelId}: contextWindow → ${change.contextWindow}`)
					}
					models[index] = entry
				}
				profile.models = models
			}
			next.providers = providers
			return next
		})

		state.lastApplied = { at: Date.now(), changed: [...changed] }
		logger.info?.(`model-guard: 已写入 ${changed.length} 项配置修复。`)
		const after = await ensureAudit({ refresh: true })
		const remaining = after.error === undefined
			? after.routes.reduce((total, { plan }) => total + plan.issues.filter((issue) => issue.fixable).length, 0)
			: undefined
		return {
			ok: true,
			changed,
			text: [
				`已修复 ${changed.length} 项配置：`,
				...changed.map((line) => `  - ${line}`),
				remaining === undefined ? '重新检查失败，请手动运行 /model-guard 确认。' : `重新检查后仍可自动修复的项：${remaining} 项。`,
				'配置已即时生效，无需重启。',
			].join('\n'),
		}
	}

	// ----------------------------------------------------------- announcements

	let sectionCache = { at: -1, text: '' }

	/** Prompt section text: empty unless the last audit found something to ask about. */
	function renderSection() {
		const audit = state.audit
		if (config.announce !== true || audit === null) return ''
		if (sectionCache.at === audit.at) return sectionCache.text
		const findings = []
		for (const { route, plan } of audit.routes) {
			for (const issue of plan.issues) {
				if (issue.severity === 'info') continue
				findings.push({ route: route.name, issue })
			}
		}
		let text = ''
		if (findings.length > 0) {
			const lines = findings.map(({ route: routeName, issue }, index) => {
				const target = issue.model === undefined ? '' : `\`${issue.model}\` `
				return `${index + 1}. [${issue.severity}] ${target}${issue.message}（${routeName}）`
			})
			text = [
				'## 自定义模型配置体检（每次启动自动检查）',
				`本次启动发现 ${findings.length} 项与用户要求不一致的自定义模型配置：`,
				...lines,
				'处理规则：在本次会话的第一次回复里，用中文简明列出上面这些问题，然后询问用户「是否现在修复？」。',
				'只有用户明确同意后，才调用 `model_guard` 工具（`action: "apply"`）执行修复；未获同意前不得修改任何配置。',
				'用户也可以自己运行 `/model-guard` 查看，或 `/model-guard fix` 直接修复。修复即时生效，无需重启。',
			].join('\n')
		}
		sectionCache = { at: audit.at, text }
		return text
	}

	// ------------------------------------------------------------- runtime hook

	/** The agent that initiated the current driver chain, when resolvable. */
	function currentAgent() {
		const agents = ctx.get('agents')
		if (agents === undefined) return undefined
		try {
			const initiator = agents.currentInitiator?.()
			if (initiator !== undefined) return initiator
		} catch {
			// No initiator boundary: fall through to the single-agent heuristic.
		}
		try {
			const live = agents.list?.() ?? []
			if (live.length === 1) return live[0]
		} catch {
			// Listing is advisory only.
		}
		return undefined
	}

	/** The model the next request will use, from the freshest public signal. */
	function stepModel(agent) {
		const session = agent?.session
		if (session !== undefined && session !== null) {
			const projections = ctx.get('sessionProjections')
			if (projections !== undefined) {
				try {
					const projected = projections.stateOf(session, 'modelSelection')
					const pending = projected?.pending
					if (typeof pending?.provider === 'string' && typeof pending?.model === 'string') {
						return { provider: pending.provider, model: pending.model }
					}
				} catch {
					// The projection is optional; the logged header is the next signal.
				}
			}
			try {
				const header = session.requestHeader?.()
				const config0 = header?.config
				if (typeof config0?.provider === 'string' && typeof config0?.model === 'string') {
					return { provider: config0.provider, model: config0.model }
				}
			} catch {
				// A session without a logged request has no header yet.
			}
		}
		try {
			const selection = ctx.get('agentDefaultModel')?.currentSelection?.()
			if (typeof selection?.provider === 'string' && typeof selection?.model === 'string') {
				return { provider: selection.provider, model: selection.model }
			}
		} catch {
			// Selection storage is optional.
		}
		return undefined
	}

	/** Resolve (and probe, if needed) the describer right before it is used. */
	async function ensureDescriber({ signal } = {}) {
		const audit = await ensureAudit()
		if (audit.describer !== undefined) return audit.describer
		if (config.describerModel.length > 0) {
			const route = state.routes.find((candidate) => candidate.models.some((model) => model.id === config.describerModel))
			if (route !== undefined) {
				const verdict = await capabilityOf(route.name, config.describerModel, { signal })
				if (verdict === CAPABILITY_IMAGE) return { provider: route.name, model: config.describerModel }
			}
		}
		for (const route of state.routes) {
			for (const model of route.models) {
				const verdict = await capabilityOf(route.name, model.id, { signal })
				if (verdict === CAPABILITY_IMAGE) return { provider: route.name, model: model.id }
			}
		}
		return undefined
	}

	/**
	 * Requirement 2: a truly multimodal model gets the pixels; a text-only model
	 * gets a description produced by one that does. The rewrite happens before
	 * the step's messages are appended to the session log, so the substitute
	 * text is what the durable history and the provider both see.
	 */
	ctx.on('agent/pre-step', async (payload, next) => {
		const decision = await next()
		try {
			if (config.enabled !== true) return decision
			if (decision?.kind !== 'enter' || !Array.isArray(decision.messages)) return decision
			const images = collectImages(decision.messages)
			if (images.length === 0) return decision
			const target = stepModel(currentAgent())
			if (target === undefined) return decision
			const capability = await capabilityOf(target.provider, target.model, { signal: payload?.signal, allowProbe: true })
			if (capability === CAPABILITY_IMAGE) return decision
			const describer = await ensureDescriber({ signal: payload?.signal })
			if (describer === undefined) {
				logger.warn?.(`model-guard: ${target.provider}/${target.model} 需要识图回退，但没有可用的多模态模型，保持原样发送。`)
				return decision
			}
			const refs = dedupeRefs(images.map((image) => image.ref))
			const outcomes = await bridge.describeAll({
				provider: describer.provider,
				model: describer.model,
				refs,
				signal: payload?.signal,
			})
			const byAttachment = new Map(outcomes.map((outcome) => [outcome.attachmentId, outcome]))
			const messages = decision.messages.map((message) => rewriteMessage(message, byAttachment, describer.model))
			const described = outcomes.filter((outcome) => outcome.text !== undefined).length
			logger.info?.(`model-guard: ${target.provider}/${target.model} 不支持图片输入，已用 ${describer.model} 转述 ${described}/${refs.length} 张图片。`)
			return { ...decision, messages }
		} catch (error) {
			logger.warn?.(`model-guard: 识图回退失败，保持原样发送：${String(error)}`)
			return decision
		}
	})

	// ----------------------------------------------------------------- surfaces

	ctx.systemPrompt.section({
		name: 'model-guard:status',
		order: 3_050,
		text: () => renderSection(),
	})

	ctx.tools.register({
		name: 'model_guard',
		description: [
			'检查或修复自定义模型（llm-pi-ai 路由下手工配置的模型）的配置。',
			'`action: "status"` 只读检查：image 输入标签、最大上下文、识图回退模型是否就绪，并列出问题；',
			'`action: "apply"` 把可修复项写入配置（用户同意后才可调用）。',
			'每次启动会自动检查一次；本工具用于向用户复述结果或在获得同意后执行修复。',
		].join(''),
		parameters: {
			type: 'object',
			properties: {
				action: {
					type: 'string',
					enum: ['status', 'apply'],
					description: 'status 只读检查；apply 写入可修复项（需要用户同意）。',
				},
				refresh: {
					type: 'boolean',
					description: '为 true 时重新探测与读取端点模型清单，忽略缓存。',
				},
			},
			required: ['action'],
			additionalProperties: false,
		},
		output: {
			schema: {
				type: 'object',
				properties: {
					ok: { type: 'boolean' },
					action: { type: 'string' },
					text: { type: 'string' },
					version: { type: 'string' },
					runtime: {
						type: 'object',
						properties: {
							provider: { type: 'string' },
							model: { type: 'string' },
							contextWindow: { type: 'number' },
							inputModalities: { type: 'array', items: { type: 'string' } },
							error: { type: 'string' },
							mismatches: { type: 'array', items: { type: 'string' } },
						},
						required: ['provider', 'model'],
						additionalProperties: false,
					},
					compliant: { type: 'boolean' },
					describer: { type: 'string' },
					issues: {
						type: 'array',
						items: {
							type: 'object',
							properties: {
								code: { type: 'string' },
								severity: { type: 'string' },
								route: { type: 'string' },
								model: { type: 'string' },
								message: { type: 'string' },
								fixable: { type: 'boolean' },
							},
							required: ['code', 'severity', 'route', 'message', 'fixable'],
							additionalProperties: false,
						},
					},
					changed: { type: 'array', items: { type: 'string' } },
				},
				required: ['ok', 'action', 'text', 'version', 'compliant', 'issues', 'changed'],
				additionalProperties: false,
			},
			render: (_args, value) => [{ type: 'text', text: value?.text ?? JSON.stringify(value) }],
		},
		timeoutMs: 120_000,
		async execute(args) {
			const action = args?.action === 'apply' ? 'apply' : 'status'
			if (action === 'apply') {
				const result = await applyFixes()
				const audit = await ensureAudit()
				return {
					ok: result.ok,
					action,
					version: VERSION,
					text: result.text,
					compliant: isCompliant(audit),
					...(audit.describer === undefined ? {} : { describer: `${audit.describer.provider}/${audit.describer.model}` }),
					issues: collectIssueRows(audit),
					changed: result.changed,
				}
			}
			const audit = await ensureAudit({ refresh: args?.refresh === true })
			return {
				ok: audit.error === undefined,
				action,
				version: VERSION,
				text: renderReport(audit),
				...(audit.runtime === undefined ? {} : { runtime: audit.runtime }),
				compliant: isCompliant(audit),
				...(audit.describer === undefined ? {} : { describer: `${audit.describer.provider}/${audit.describer.model}` }),
				issues: collectIssueRows(audit),
				changed: [],
			}
		},
	})

	ctx.commands.register({
		name: 'model-guard',
		description: '检查自定义模型的 image 标签、最大上下文与识图回退；`/model-guard fix` 写入修复',
		input: { hint: '[status|fix]' },
		async handler(invocation) {
			const raw = typeof invocation?.rawInput === 'string' ? invocation.rawInput.trim().toLowerCase() : ''
			const wantsFix = raw === 'fix' || raw === 'apply' || raw === 'repair'
			if (wantsFix) {
				const result = await applyFixes()
				return { kind: 'success', text: result.text }
			}
			const audit = await ensureAudit({ refresh: raw === 'refresh' })
			return { kind: 'success', text: renderReport(audit) }
		},
	})

	// ------------------------------------------------------------------ startup

	const kickoff = () => {
		runAudit().catch((error) => logger.warn?.(`model-guard: 启动检查异常：${String(error)}`))
	}
	// Adapter registration and config reload both change what there is to audit.
	ctx.on('llm/adapters-updated', () => kickoff())
	ctx.on('app-boot/config-reload', () => kickoff())
	if (config.auditOnStartup === true) {
		const timer = setTimeout(kickoff, 0)
		if (typeof timer.unref === 'function') timer.unref()
	}

	logger.debug?.(`model-guard: 已加载（probeImages=${config.probeImages}，describerModel=${config.describerModel || '(auto)'}）。`)
}

// -----------------------------------------------------------------------------
// helpers
// -----------------------------------------------------------------------------

function isCompliant(audit) {
	if (audit === null || audit.error !== undefined) return false
	return audit.routes.every(({ plan }) => plan.summary.compliant === true)
}

function collectIssueRows(audit) {
	if (audit === null || audit.error !== undefined) return []
	const rows = []
	for (const { route, plan } of audit.routes) {
		for (const issue of plan.issues) {
			rows.push({
				code: issue.code,
				severity: issue.severity,
				route: route.name,
				...(issue.model === undefined ? {} : { model: issue.model }),
				message: issue.message,
				fixable: issue.fixable,
			})
		}
	}
	return rows
}

function dedupeRefs(refs) {
	const seen = new Set()
	const unique = []
	for (const ref of refs) {
		const id = String(ref?.attachmentId ?? '')
		if (id.length === 0 || seen.has(id)) continue
		seen.add(id)
		unique.push(ref)
	}
	return unique
}

function resolveConfig(raw) {
	const source = isRecord(raw) ? raw : {}
	const resolved = { ...CONFIG_DEFAULTS }
	for (const [key, value] of Object.entries(source)) {
		if (!(key in CONFIG_DEFAULTS)) continue
		resolved[key] = value
	}
	resolved.enabled = resolved.enabled !== false
	resolved.auditOnStartup = resolved.auditOnStartup !== false
	resolved.announce = resolved.announce !== false
	resolved.manageVisionPlugin = resolved.manageVisionPlugin === true
	resolved.probeImages = resolved.probeImages === 'never' ? 'never' : 'auto'
	resolved.describerModel = typeof resolved.describerModel === 'string' ? resolved.describerModel.trim() : ''
	resolved.describePrompt = typeof resolved.describePrompt === 'string' ? resolved.describePrompt : ''
	resolved.imageModels = stringArray(resolved.imageModels)
	resolved.textModels = stringArray(resolved.textModels)
	for (const key of ['probeTimeoutMs', 'discoveryTimeoutMs', 'describeTimeoutMs', 'describeMaxTokens']) {
		resolved[key] = positiveNumber(resolved[key], CONFIG_DEFAULTS[key])
	}
	return resolved
}

function stringArray(value) {
	if (Array.isArray(value)) return value.filter((entry) => typeof entry === 'string' && entry.length > 0)
	if (typeof value === 'string' && value.trim().length > 0) return value.split(',').map((entry) => entry.trim()).filter(Boolean)
	return []
}

function normalizeModels(models) {
	if (!Array.isArray(models)) return []
	const normalized = []
	for (const entry of models) {
		if (typeof entry === 'string' && entry.length > 0) {
			normalized.push({ id: entry, name: entry })
			continue
		}
		if (!isRecord(entry) || typeof entry.id !== 'string' || entry.id.length === 0) continue
		normalized.push({
			id: entry.id,
			name: typeof entry.name === 'string' ? entry.name : entry.id,
			...(Array.isArray(entry.input) ? { input: entry.input.filter((value) => typeof value === 'string') } : {}),
			...(numberOr(entry.contextWindow) === undefined ? {} : { contextWindow: numberOr(entry.contextWindow) }),
			...(numberOr(entry.maxTokens) === undefined ? {} : { maxTokens: numberOr(entry.maxTokens) }),
		})
	}
	return normalized
}

/** Recursive merge where plain objects merge and every other value is replaced. */
function deepMerge(base, patch) {
	if (!isRecord(base)) return patch
	if (!isRecord(patch)) return patch
	const merged = { ...base }
	for (const [key, value] of Object.entries(patch)) {
		const existing = merged[key]
		merged[key] = isRecord(existing) && isRecord(value) ? deepMerge(existing, value) : value
	}
	return merged
}

function cloneJson(value) {
	if (Array.isArray(value)) return value.map(cloneJson)
	if (isRecord(value)) {
		const copy = {}
		for (const [key, entry] of Object.entries(value)) copy[key] = cloneJson(entry)
		return copy
	}
	return value
}

function isRecord(value) {
	return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function numberOr(value) {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function positiveNumber(value, fallback) {
	return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
}

export { CONFIG_DEFAULTS, DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_TOKENS }
