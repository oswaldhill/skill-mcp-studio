#!/usr/bin/env python3
"""Unified Streamable HTTP MCP facade for Hermes memory services."""

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

try:
    from fastmcp import FastMCP
    SERVER_STYLE = "fastmcp"
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP
        SERVER_STYLE = "fastmcp"
    except ImportError:  # mcp 2.x in the pinned Hermes image.
        from mcp.server import MCPServer as FastMCP
        SERVER_STYLE = "mcpserver"


MIN_TIMEOUT = 1.0
MAX_TIMEOUT = 30.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_BACKGROUND_WORKERS = set()

DEFAULT_AI_MEMORY_ALLOWED_TOOLS = (
    "memory_query",
    "memory_recent",
    "memory_status",
    "memory_briefing",
    "memory_explore",
    "memory_read_page",
    "memory_read_session_observations",
    "memory_feedback",
    "memory_lint",
    "memory_consolidate",
    "memory_auto_improve",
    "memory_forget_sweep",
    "memory_handoff_accept",
    "memory_handoff_begin",
    "memory_handoff_cancel",
)

KNOWLEDGE_OPERATIONS = {
    "wiki_create": "wiki/create",
    "wiki_get": "wiki/get",
    "wiki_list": "wiki/list",
    "wiki_ingest": "wiki/ingest",
    "wiki_delete": "wiki/delete",
    "wiki_raw_ls": "wiki/raw/ls",
    "wiki_raw_read": "wiki/raw/read",
    "wiki_raw_write": "wiki/raw/write",
    "wiki_raw_rm": "wiki/raw/rm",
    "wiki_page_ls": "wiki/page/ls",
    "wiki_page_read": "wiki/page/read",
    "wiki_page_write": "wiki/page/write",
    "wiki_page_rm": "wiki/page/rm",
    "wiki_graph": "wiki/graph",
    "wiki_search": "wiki/search",
    "code_graph_create": "code-graph/create",
    "code_graph_list": "code-graph/list",
    "code_graph_get": "code-graph/get",
    "code_graph_sync": "code-graph/sync",
    "code_graph_delete": "code-graph/delete",
    "code_graph_search": "code-graph/search",
    "code_graph_explore": "code-graph/explore",
    "code_graph_callers": "code-graph/callers",
    "code_graph_callees": "code-graph/callees",
    "code_graph_impact": "code-graph/impact",
    "code_graph_node": "code-graph/node",
    "code_graph_status": "code-graph/status",
    "code_graph_files": "code-graph/files",
}

def _env_tuple(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    """Parse a comma-separated environment variable into a tuple, else default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


# Tool names exposed by this facade. Override with comma-separated EXPOSED_TOOL_NAMES.
DEFAULT_EXPOSED_TOOL_NAMES = (
    "memory_health", "memory_search", "memory_add", "memory_list", "memory_delete",
    "ai_memory_query", "ai_memory_handoff_begin", "ai_memory_call",
    "tdai_memory_search", "tdai_conversation_search", "tdai_recall", "tdai_capture",
    "tdai_session", "tdai_knowledge", "hermes_health", "hermes_chat",
)
EXPOSED_TOOL_NAMES = _env_tuple("EXPOSED_TOOL_NAMES", DEFAULT_EXPOSED_TOOL_NAMES)

# Neutral ops-routing keywords (no hostnames, IP ranges, or tenant names).
# Override with comma-separated OPS_KEYWORDS.
DEFAULT_OPS_KEYWORDS = (
    "nginx", "proxy_pass", "Certbot", "Let's Encrypt", "SSL", "Docker",
    "docker-compose", "fail2ban", "SOCKS", "反代", "备份", "企业微信",
)
OPS_KEYWORDS = _env_tuple("OPS_KEYWORDS", DEFAULT_OPS_KEYWORDS)


def _bounded_float(value: str, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, parsed))


def _bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normal_path(value: str) -> str:
    value = value.strip() or "/mcp"
    return value if value.startswith("/") else "/" + value


class Settings:
    def __init__(
        self,
        host: str,
        port: int,
        path: str,
        timeout: float,
        hermes_url: str,
        ai_memory_url: str,
        tdai_url: str,
        memory_url: str,
        ai_memory_allowed_tools: Tuple[str, ...],
        ai_memory_token: str = "",
        tdai_token: str = "",
        hermes_api_key: str = "",
        hermes_model: str = "hermes-agent",
        tdai_service_id: str = "default",
        tdai_team_id: str = "",
        tdai_user_id: str = "",
        tdai_agent_id: str = "",
        tdai_routing: str = "auto",
        home_lab_team_id: str = "",
        home_lab_user_id: str = "",
        home_lab_agent_id: str = "",
        max_concurrency: int = 8,
    ):
        self.host = host
        self.port = port
        self.path = path
        self.timeout = timeout
        self.hermes_url = hermes_url.rstrip("/")
        self.ai_memory_url = ai_memory_url.rstrip("/")
        self.tdai_url = tdai_url.rstrip("/")
        self.memory_url = memory_url.rstrip("/")
        self.ai_memory_allowed_tools = ai_memory_allowed_tools
        self.ai_memory_token = ai_memory_token
        self.tdai_token = tdai_token
        self.hermes_api_key = hermes_api_key
        self.hermes_model = hermes_model
        self.tdai_service_id = tdai_service_id
        self.tdai_team_id = tdai_team_id
        self.tdai_user_id = tdai_user_id
        self.tdai_agent_id = tdai_agent_id
        self.tdai_routing = tdai_routing
        self.home_lab_team_id = home_lab_team_id
        self.home_lab_user_id = home_lab_user_id
        self.home_lab_agent_id = home_lab_agent_id
        self.max_concurrency = max_concurrency

    @classmethod
    def from_env(cls) -> "Settings":
        allowed = tuple(
            item.strip()
            for item in os.environ.get("AI_MEMORY_ALLOWED_TOOLS", ",".join(DEFAULT_AI_MEMORY_ALLOWED_TOOLS)).split(",")
            if item.strip()
        )
        return cls(
            host=os.environ.get("HERMES_UNIFIED_HOST", "127.0.0.1"),
            port=_bounded_int(os.environ.get("HERMES_UNIFIED_PORT", "8765"), 8765, 1, 65535),
            path=_normal_path(os.environ.get("HERMES_UNIFIED_PATH", "/mcp")),
            timeout=_bounded_float(os.environ.get("HERMES_UNIFIED_TIMEOUT", "10"), 10.0),
            hermes_url=os.environ.get("HERMES_GATEWAY_URL", "http://127.0.0.1:8642"),
            ai_memory_url=os.environ.get("AI_MEMORY_URL", "http://127.0.0.1:49374/mcp"),
            tdai_url=os.environ.get("TDAI_URL", "http://127.0.0.1:8420"),
            memory_url=os.environ.get("TENCENTDB_MEMORY_URL", "http://127.0.0.1:8424/v3"),
            ai_memory_allowed_tools=allowed,
            ai_memory_token=os.environ.get("AI_MEMORY_TOKEN", ""),
            tdai_token=os.environ.get("TDAI_TOKEN", "") or "local",
            hermes_api_key=os.environ.get("HERMES_API_KEY", ""),
            hermes_model=os.environ.get("HERMES_MODEL", "hermes-agent"),
            tdai_service_id=os.environ.get("TDAI_SERVICE_ID", "default"),
            tdai_team_id=os.environ.get("TDAI_TEAM_ID", ""),
            tdai_user_id=os.environ.get("TDAI_USER_ID", ""),
            tdai_agent_id=os.environ.get("TDAI_AGENT_ID", ""),
            tdai_routing=os.environ.get("TDAI_ROUTING", "auto"),
            home_lab_team_id=os.environ.get("TDAI_HOME_LAB_TEAM_ID", ""),
            home_lab_user_id=os.environ.get("TDAI_HOME_LAB_USER_ID", ""),
            home_lab_agent_id=os.environ.get("TDAI_HOME_LAB_AGENT_ID", ""),
            max_concurrency=_bounded_int(
                os.environ.get("HERMES_UNIFIED_MAX_CONCURRENCY", "8"), 8, 1, 64
            ),
        )

    def require_ai_memory_token(self) -> None:
        if not self.ai_memory_token:
            raise RuntimeError("AI_MEMORY_TOKEN is required")

    @property
    def secrets(self) -> Tuple[str, ...]:
        non_secret_sentinels = {"", "local", "default"}
        return tuple(
            value
            for value in (
                self.ai_memory_token,
                self.tdai_token,
                self.hermes_api_key,
            )
            if value not in non_secret_sentinels
        )


class HttpResponse:
    def __init__(self, status: int, headers: Mapping[str, str], body: str):
        self.status = status
        self.headers = dict(headers)
        self.body = body


class UpstreamHttpError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__("upstream HTTP error {}".format(status))


async def _blocking_with_deadline(
    function: Callable[..., Any],
    deadline: float,
    semaphore: Optional[asyncio.Semaphore] = None,
    **kwargs: Any
) -> Any:
    """Return by the deadline while retaining the permit until the worker thread finishes."""
    loop = asyncio.get_running_loop()
    expires_at = loop.time() + deadline

    if semaphore is not None:
        remaining = expires_at - loop.time()
        if remaining <= 0:
            raise RuntimeError("upstream deadline exceeded after {:.3g}s".format(deadline))
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=remaining)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "upstream deadline exceeded after {:.3g}s".format(deadline)
            ) from None

    async def invoke() -> Any:
        try:
            return await asyncio.to_thread(function, **kwargs)
        finally:
            if semaphore is not None:
                semaphore.release()

    task = asyncio.create_task(invoke())
    _BACKGROUND_WORKERS.add(task)

    def consume_result(completed: asyncio.Task) -> None:
        _BACKGROUND_WORKERS.discard(completed)
        try:
            completed.exception()
        except (asyncio.CancelledError, Exception):
            pass

    task.add_done_callback(consume_result)
    remaining = max(0, expires_at - loop.time())
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
    except asyncio.TimeoutError:
        raise RuntimeError("upstream deadline exceeded after {:.3g}s".format(deadline)) from None


def default_http_request(
    *,
    method: str,
    url: str,
    json_body: Optional[Dict[str, Any]],
    headers: Mapping[str, str],
    timeout: float,
) -> HttpResponse:
    data = None if json_body is None else json.dumps(json_body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=min(timeout, MAX_TIMEOUT)) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise RuntimeError("upstream response exceeds size limit")
            return HttpResponse(response.status, dict(response.headers.items()), body.decode("utf-8"))
    except urllib.error.HTTPError as error:
        error.read(MAX_RESPONSE_BYTES)
        raise UpstreamHttpError(error.code) from None
    except urllib.error.URLError as error:
        raise RuntimeError("upstream connection failed: {}".format(error.reason)) from None


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return None


def _parse_json_or_sse(body: str, expected_id: Any = None) -> Dict[str, Any]:
    body = body.strip()
    if not body:
        return {}
    if body.startswith("{") or body.startswith("["):
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise RuntimeError("upstream response must be a JSON object")
        candidates = [parsed]
    else:
        candidates = []
        normalized = body.replace("\r\n", "\n").replace("\r", "\n")
        for event in normalized.split("\n\n"):
            data_lines = []
            for line in event.splitlines():
                if not line or line.startswith(":"):
                    continue
                field, separator, value = line.partition(":")
                if field == "data" and separator:
                    data_lines.append(value[1:] if value.startswith(" ") else value)
            if not data_lines:
                continue
            parsed = json.loads("\n".join(data_lines))
            if isinstance(parsed, dict):
                candidates.append(parsed)
    if not candidates:
        raise RuntimeError("upstream returned neither JSON nor SSE data")
    if expected_id is not None:
        for candidate in candidates:
            if candidate.get("id") == expected_id:
                return candidate
        raise RuntimeError("upstream response did not contain matching JSON-RPC id")
    return candidates[-1]


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, secrets) for item in value)
    return value


class McpHttpClient:
    def __init__(
        self,
        settings: Settings,
        request: Callable[..., Any],
        semaphore: asyncio.Semaphore,
    ):
        self.url = settings.ai_memory_url
        self.token = settings.ai_memory_token
        self.timeout = settings.timeout
        self.request = request
        self.session_id = None
        self.next_id = 1
        self.secrets = settings.secrets
        self.lock = asyncio.Lock()
        self.semaphore = semaphore

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = await _blocking_with_deadline(
            self.request,
            self.timeout,
            self.semaphore,
            method="POST",
            url=self.url,
            json_body=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if isinstance(response, dict):
            return response
        if not isinstance(response, HttpResponse):
            raise RuntimeError("invalid upstream response type")
        session_id = _header(response.headers, "Mcp-Session-Id")
        if session_id:
            self.session_id = session_id
        if response.status >= 400:
            raise UpstreamHttpError(response.status)
        return _parse_json_or_sse(response.body, expected_id=payload.get("id"))

    async def _cleanup_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        headers = self._headers()
        headers["Mcp-Session-Id"] = session_id
        try:
            await _blocking_with_deadline(
                self.request,
                self.timeout,
                self.semaphore,
                method="DELETE",
                url=self.url,
                json_body=None,
                headers=headers,
                timeout=self.timeout,
            )
        except Exception:
            pass

    async def _initialize(self) -> None:
        request_id = self.next_id
        self.next_id += 1
        response = await self._post({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hermes-unified-mcp", "version": "1.0.0"},
            },
        })
        self._result(response)
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def _result(self, response: Dict[str, Any]) -> Any:
        if "error" in response:
            error = response.get("error") or {}
            message = error.get("message", "upstream MCP error") if isinstance(error, dict) else str(error)
            raise RuntimeError(str(_redact(message, self.secrets)))
        return _redact(response.get("result", response), self.secrets)

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        async with self.lock:
            for attempt in range(2):
                self.session_id = None
                try:
                    await self._initialize()
                    request_id = self.next_id
                    self.next_id += 1
                    response = await self._post({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    })
                    return self._result(response)
                except Exception as error:
                    retryable = isinstance(error, UpstreamHttpError) and error.status == 404
                    retryable = retryable or "invalid session" in str(error).lower()
                    if retryable and attempt == 0:
                        continue
                    message = _redact(str(error), self.secrets)
                    raise RuntimeError(message) from None
                finally:
                    await self._cleanup_session(self.session_id)
                    self.session_id = None
        raise RuntimeError("unreachable")


class UnifiedGateway:
    def __init__(self, settings: Settings, request: Callable[..., Any] = default_http_request):
        self.settings = settings
        self.request = request
        self.semaphore = asyncio.Semaphore(settings.max_concurrency)
        self.ai_memory = McpHttpClient(settings, request, self.semaphore)

    def _auth_headers(self, token: str = "") -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        return headers

    def tdai_headers(
        self,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, str]:
        settings = self.settings
        return {
            "Authorization": "Bearer " + settings.tdai_token,
            "x-tdai-service-id": settings.tdai_service_id,
            "x-tdai-team-id": team_id or settings.tdai_team_id,
            "x-tdai-user-id": user_id or settings.tdai_user_id,
            "x-tdai-agent-id": agent_id or settings.tdai_agent_id,
        }

    async def rest(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
        token: str = "",
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        try:
            request_headers = self._auth_headers(token)
            if json_body is not None:
                request_headers["Content-Type"] = "application/json"
            if headers:
                request_headers.update(headers)
            response = await _blocking_with_deadline(
                self.request,
                self.settings.timeout,
                self.semaphore,
                method=method,
                url=url,
                json_body=json_body,
                headers=request_headers,
                timeout=self.settings.timeout,
            )
            if isinstance(response, dict):
                result = response
            elif isinstance(response, HttpResponse):
                if response.status >= 400:
                    raise UpstreamHttpError(response.status)
                result = _parse_json_or_sse(response.body)
            else:
                raise RuntimeError("invalid upstream response type")
            return _redact(result, self.settings.secrets)
        except Exception as error:
            raise RuntimeError(_redact(str(error), self.settings.secrets)) from None


def _url(base: str, suffix: str) -> str:
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def _memory_route(
    settings: Settings,
    text: str = "",
    scope: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    normalized_scope = scope.strip().lower() if scope else None
    if normalized_scope == "home-lab":
        return (
            settings.home_lab_team_id,
            settings.home_lab_user_id,
            settings.home_lab_agent_id,
            "home-lab",
        )
    if normalized_scope in ("global", "default"):
        return settings.tdai_team_id, settings.tdai_user_id, settings.tdai_agent_id, "default"
    if normalized_scope is not None:
        raise ValueError("unknown memory scope: {}".format(scope))
    if text and settings.tdai_routing == "auto" and any(keyword in text for keyword in OPS_KEYWORDS):
        return (
            settings.home_lab_team_id,
            settings.home_lab_user_id,
            settings.home_lab_agent_id,
            "home-lab",
        )
    return settings.tdai_team_id, settings.tdai_user_id, settings.tdai_agent_id, "default"


def create_server(gateway: UnifiedGateway) -> FastMCP:
    settings = gateway.settings
    if SERVER_STYLE == "mcpserver":
        server = FastMCP("Hermes Unified MCP")
    else:
        server = FastMCP("Hermes Unified MCP", stateless_http=True, json_response=True)

    @server.tool(name="memory_health")
    async def memory_health() -> Any:
        return await gateway.rest("GET", _url(settings.tdai_url, "health"), headers=gateway.tdai_headers())

    @server.tool(name="memory_search")
    async def memory_search(query: str, limit: int = 5, scope: Optional[str] = None) -> Any:
        team_id, user_id, agent_id, _ = _memory_route(settings, scope=scope)
        body = {"query": query, "limit": _bounded_int(str(limit), 5, 1, 100)}
        response = await gateway.rest(
            "POST",
            _url(settings.tdai_url, "v3/atomic/search"),
            body,
            headers=gateway.tdai_headers(team_id, user_id, agent_id),
        )
        items = response.get("data", {}).get("items", []) if isinstance(response, dict) else []
        return {
            "count": len(items),
            "items": [
                {
                    "id": item.get("id"), "type": item.get("type"),
                    "content": item.get("content"), "score": round(item.get("score", 0), 4),
                }
                for item in items
            ],
        }

    @server.tool(name="memory_add")
    async def memory_add(text: str, scope: Optional[str] = None) -> Any:
        team_id, user_id, agent_id, destination = _memory_route(settings, text, scope)
        session_id = "mcp-manual-" + str(uuid.uuid4())
        response = await gateway.rest(
            "POST",
            _url(settings.tdai_url, "v3/conversation/add"),
            {
                "session_id": session_id,
                "messages": [
                    {"role": "user", "content": "[manual memory] " + text},
                    {"role": "assistant", "content": "已记录。"},
                ],
            },
            headers=gateway.tdai_headers(team_id, user_id, agent_id),
        )
        accepted = response.get("data", {}).get("total_count", 0) if isinstance(response, dict) else 0
        return {
            "accepted": accepted,
            "session_id": session_id,
            "routed_to": destination,
            "note": "L1 extraction runs asynchronously - search again shortly after",
        }

    @server.tool(name="memory_list")
    async def memory_list(limit: int = 20, scope: Optional[str] = None) -> Any:
        team_id, user_id, agent_id, _ = _memory_route(settings, scope=scope)
        response = await gateway.rest(
            "POST",
            _url(settings.tdai_url, "v3/atomic/query"),
            {"limit": _bounded_int(str(limit), 20, 1, 100), "offset": 0},
            headers=gateway.tdai_headers(team_id, user_id, agent_id),
        )
        data = response.get("data", {}) if isinstance(response, dict) else {}
        items = data.get("items", [])
        return {
            "total": data.get("total_count", data.get("total", len(items))),
            "items": [
                {"id": item.get("id"), "type": item.get("type"), "content": item.get("content")}
                for item in items
            ],
        }

    @server.tool(name="memory_delete")
    async def memory_delete(memory_id: str) -> Any:
        response = await gateway.rest(
            "POST",
            _url(settings.tdai_url, "v3/atomic/delete"),
            {"ids": [memory_id]},
            headers=gateway.tdai_headers(),
        )
        deleted = response.get("data", {}).get("deleted_count", 0) if isinstance(response, dict) else 0
        return {"deleted": deleted}

    @server.tool(name="ai_memory_query")
    async def ai_memory_query(query: str, limit: int = 5) -> Any:
        return await gateway.ai_memory.call_tool("memory_query", {"query": query, "limit": limit})

    @server.tool(name="ai_memory_handoff_begin")
    async def ai_memory_handoff_begin(
        summary: str,
        open_questions: Optional[list] = None,
        next_steps: Optional[list] = None,
        files_touched: Optional[list] = None,
        cwd: str = "",
        shared: bool = False,
    ) -> Any:
        return await gateway.ai_memory.call_tool("memory_handoff_begin", {
            "summary": summary,
            "open_questions": open_questions or [],
            "next_steps": next_steps or [],
            "files_touched": files_touched or [],
            "cwd": cwd,
            "shared": shared,
        })

    @server.tool(name="ai_memory_call")
    async def ai_memory_call(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if tool_name not in settings.ai_memory_allowed_tools:
            raise ValueError("ai-memory tool is not allowed: {}".format(tool_name))
        return await gateway.ai_memory.call_tool(tool_name, arguments or {})

    @server.tool(name="tdai_memory_search")
    async def tdai_memory_search(query: str, limit: int = 5) -> Any:
        return await gateway.rest(
            "POST",
            _url(settings.tdai_url, "search/memories"),
            {"query": query, "limit": limit},
            headers=gateway.tdai_headers(),
        )

    @server.tool(name="tdai_conversation_search")
    async def tdai_conversation_search(query: str, limit: int = 5) -> Any:
        return await gateway.rest(
            "POST",
            _url(settings.tdai_url, "search/conversations"),
            {"query": query, "limit": limit},
            headers=gateway.tdai_headers(),
        )

    @server.tool(name="tdai_recall")
    async def tdai_recall(query: str, session_key: str, user_id: Optional[str] = None) -> Any:
        return await gateway.rest(
            "POST",
            _url(settings.tdai_url, "recall"),
            {"query": query, "session_key": session_key, "user_id": user_id or settings.tdai_user_id},
            headers=gateway.tdai_headers(user_id=user_id),
        )

    @server.tool(name="tdai_capture")
    async def tdai_capture(
        user_content: str,
        assistant_content: str,
        session_key: str,
        session_id: str,
        user_id: Optional[str] = None,
        messages: Optional[list] = None,
    ) -> Any:
        captured_messages = messages or [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
        return await gateway.rest(
            "POST",
            _url(settings.tdai_url, "capture"),
            {
                "user_content": user_content,
                "assistant_content": assistant_content,
                "session_key": session_key,
                "session_id": session_id,
                "user_id": user_id or settings.tdai_user_id,
                "messages": captured_messages,
            },
            headers=gateway.tdai_headers(user_id=user_id),
        )

    @server.tool(name="tdai_session")
    async def tdai_session(session_key: str, session_id: str, user_id: Optional[str] = None) -> Any:
        return await gateway.rest(
            "POST",
            _url(settings.tdai_url, "session/end"),
            {"session_key": session_key, "session_id": session_id, "user_id": user_id or settings.tdai_user_id},
            headers=gateway.tdai_headers(user_id=user_id),
        )

    @server.tool(name="tdai_knowledge")
    async def tdai_knowledge(operation: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        path = KNOWLEDGE_OPERATIONS.get(operation)
        if path is None:
            raise ValueError("knowledge operation is not allowed: {}".format(operation))
        return await gateway.rest(
            "POST",
            _url(settings.memory_url, path),
            arguments or {},
            headers={"x-tdai-service-id": settings.tdai_service_id},
        )

    @server.tool(name="hermes_health")
    async def hermes_health() -> Any:
        return await gateway.rest("GET", _url(settings.hermes_url, "health"), token=settings.hermes_api_key)

    @server.tool(name="hermes_chat")
    async def hermes_chat(message: str) -> Any:
        response = await gateway.rest(
            "POST",
            _url(settings.hermes_url, "v1/chat/completions"),
            {"model": settings.hermes_model, "messages": [{"role": "user", "content": message}], "stream": False},
            settings.hermes_api_key,
        )
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return response

    return server


def main() -> FastMCP:
    settings = Settings.from_env()
    settings.require_ai_memory_token()
    server = create_server(UnifiedGateway(settings))
    if SERVER_STYLE == "mcpserver":
        server.run(
            transport="streamable-http",
            host=settings.host,
            port=settings.port,
            streamable_http_path=settings.path,
            json_response=True,
            stateless_http=True,
        )
    else:
        server.run(
            transport="streamable-http",
            host=settings.host,
            port=settings.port,
            path=settings.path,
        )
    return server


def smoke() -> Tuple[str, ...]:
    """Import the fixed-image SDK and build the complete tool registry without networking."""
    settings = Settings.from_env()
    settings.require_ai_memory_token()
    create_server(UnifiedGateway(settings))
    return EXPOSED_TOOL_NAMES


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        print(json.dumps({"tools": smoke()}))
    else:
        main()
