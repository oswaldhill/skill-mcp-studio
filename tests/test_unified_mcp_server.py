import asyncio
import importlib.util
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "scripts" / "unified_mcp_server.py"


class FakeFastMCP:
    def __init__(self, name, **kwargs):
        self.name = name
        self.options = kwargs
        self.tools = {}
        self.run_args = None

    def tool(self, name=None, **_kwargs):
        def register(function):
            self.tools[name or function.__name__] = function
            return function

        return register

    def run(self, **kwargs):
        self.run_args = kwargs


def load_server_module(use_mcp_server=False):
    fake_fastmcp = type(sys)("fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    fake_mcp = type(sys)("mcp")
    fake_mcp_server = type(sys)("mcp.server")
    fake_mcp_server.MCPServer = FakeFastMCP
    spec = importlib.util.spec_from_file_location("unified_mcp_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    replacements = {"fastmcp": None, "mcp": fake_mcp, "mcp.server": fake_mcp_server} if use_mcp_server else {
        "fastmcp": fake_fastmcp
    }
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module


class UnifiedMcpServerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_server_module()

    def test_settings_have_local_defaults_and_bounded_timeout(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = self.module.Settings.from_env()

        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8765)
        self.assertEqual(settings.path, "/mcp")
        self.assertEqual(settings.hermes_url, "http://127.0.0.1:8642")
        self.assertEqual(settings.ai_memory_url, "http://127.0.0.1:49374/mcp")
        self.assertEqual(settings.tdai_url, "http://127.0.0.1:8420")
        self.assertEqual(settings.memory_url, "http://127.0.0.1:8424/v3")
        self.assertEqual(settings.tdai_service_id, "default")
        self.assertEqual(settings.tdai_team_id, "")
        self.assertEqual(settings.tdai_user_id, "")
        self.assertEqual(settings.tdai_agent_id, "")
        self.assertIn("memory_handoff_begin", settings.ai_memory_allowed_tools)
        self.assertNotIn("memory_write_page", settings.ai_memory_allowed_tools)
        self.assertNotIn("local", settings.secrets)
        self.assertFalse(hasattr(settings, "memory_token"))

        with patch.dict(os.environ, {"HERMES_UNIFIED_TIMEOUT": "999"}, clear=True):
            self.assertEqual(self.module.Settings.from_env().timeout, 30.0)

    def test_settings_allow_environment_overrides(self):
        environment = {
            "HERMES_UNIFIED_HOST": "0.0.0.0",
            "HERMES_UNIFIED_PORT": "9000",
            "HERMES_UNIFIED_PATH": "tools",
            "HERMES_GATEWAY_URL": "http://hermes:1",
            "AI_MEMORY_URL": "http://ai:2/mcp",
            "TDAI_URL": "http://tdai:3",
            "TENCENTDB_MEMORY_URL": "http://memory:4/v3",
            "AI_MEMORY_ALLOWED_TOOLS": "memory_query,memory_handoff_begin,custom_safe_tool",
            "TDAI_SERVICE_ID": "service-test",
            "TDAI_TEAM_ID": "team-test",
            "TDAI_USER_ID": "user-test",
            "TDAI_AGENT_ID": "agent-test",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = self.module.Settings.from_env()

        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 9000)
        self.assertEqual(settings.path, "/tools")
        self.assertEqual(settings.ai_memory_allowed_tools[-1], "custom_safe_tool")
        self.assertEqual(settings.tdai_service_id, "service-test")

    def test_server_registers_the_required_named_tools(self):
        gateway = self.module.UnifiedGateway(self.module.Settings.from_env(), request=lambda **_: {})
        server = self.module.create_server(gateway)

        self.assertEqual(
            set(server.tools),
            {
                "memory_health", "memory_search", "memory_add", "memory_list", "memory_delete",
                "ai_memory_query", "ai_memory_handoff_begin", "ai_memory_call",
                "tdai_memory_search", "tdai_conversation_search", "tdai_recall",
                "tdai_capture", "tdai_session", "tdai_knowledge",
                "hermes_health", "hermes_chat",
            },
        )

    async def test_named_tool_calls_are_forwarded_with_bounded_timeout(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        with patch.dict(os.environ, {"AI_MEMORY_TOKEN": "test-token"}, clear=True):
            settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        result = await server.tools["tdai_memory_search"]("needle", limit=7)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0]["url"], "http://127.0.0.1:8420/search/memories")
        self.assertEqual(calls[0]["json_body"], {"query": "needle", "limit": 7})
        self.assertLessEqual(calls[0]["timeout"], 30.0)
        self.assertEqual(calls[0]["headers"]["Content-Type"], "application/json")

    def test_redaction_ignores_non_secret_sentinels_but_masks_real_tokens(self):
        with patch.dict(os.environ, {}, clear=True):
            defaults = self.module.Settings.from_env()
        self.assertEqual(
            self.module._redact("localhost local default", defaults.secrets),
            "localhost local default",
        )

        with patch.dict(os.environ, {"TDAI_TOKEN": "actual-secret-token"}, clear=True):
            secured = self.module.Settings.from_env()
        self.assertEqual(
            self.module._redact("Bearer actual-secret-token", secured.secrets),
            "Bearer [REDACTED]",
        )

    async def test_sse_parser_selects_matching_jsonrpc_event(self):
        body = (
            ": heartbeat\n\n"
            "event: progress\n"
            'data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
            "event: message\n"
            'data: {"jsonrpc":"2.0",\n'
            'data: "id":42,"result":{"matched":true}}\n\n'
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":99,"result":{"wrong":true}}\n\n'
        )

        parsed = self.module._parse_json_or_sse(body, expected_id=42)
        self.assertEqual(parsed["result"], {"matched": True})

    async def test_blocking_requests_obey_configured_concurrency_limit(self):
        active = 0
        peak = 0
        guard = threading.Lock()

        def request(**_kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with guard:
                active -= 1
            return {"ok": True}

        settings = self.module.Settings.from_env()
        settings.max_concurrency = 2
        gateway = self.module.UnifiedGateway(settings, request=request)
        await asyncio.gather(*(gateway.rest("GET", "http://upstream/{}".format(index)) for index in range(6)))
        self.assertEqual(peak, 2)

    async def test_requests_timed_out_waiting_for_semaphore_never_execute(self):
        active = 0
        completed = 0
        peak = 0
        guard = threading.Lock()

        def request(**_kwargs):
            nonlocal active, completed, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.12)
            with guard:
                active -= 1
                completed += 1
            return {"ok": True}

        settings = self.module.Settings.from_env()
        settings.timeout = 0.02
        settings.max_concurrency = 1
        gateway = self.module.UnifiedGateway(settings, request=request)

        for index in range(3):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                await gateway.rest("GET", "http://upstream/{}".format(index))
        await asyncio.sleep(0.4)

        self.assertEqual(completed, 1)
        self.assertEqual(peak, 1)

    async def test_timed_out_worker_releases_semaphore_after_thread_finishes(self):
        completed = 0

        def request(**_kwargs):
            nonlocal completed
            time.sleep(0.06)
            completed += 1
            return {"ok": True}

        settings = self.module.Settings.from_env()
        settings.timeout = 0.01
        settings.max_concurrency = 1
        gateway = self.module.UnifiedGateway(settings, request=request)

        with self.assertRaisesRegex(RuntimeError, "deadline"):
            await gateway.rest("GET", "http://upstream/slow")
        await asyncio.sleep(0.08)

        self.assertEqual(completed, 1)
        self.assertFalse(gateway.semaphore.locked())

    async def test_memory_tools_use_tdai_v3_contract_headers_and_routing(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            return {"data": {"items": [], "total_count": 2, "deleted_count": 1}}

        with patch.dict(os.environ, {"TDAI_TOKEN": "local-test", "TDAI_HOME_LAB_TEAM_ID": "team-ops"}, clear=True):
            settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        await server.tools["memory_health"]()
        await server.tools["memory_search"]("query", 4)
        added = await server.tools["memory_add"]("Docker NAS backup")
        await server.tools["memory_list"](8, "global")
        await server.tools["memory_delete"]("m-1")

        self.assertEqual(
            [(call["method"], call["url"]) for call in calls],
            [
                ("GET", "http://127.0.0.1:8420/health"),
                ("POST", "http://127.0.0.1:8420/v3/atomic/search"),
                ("POST", "http://127.0.0.1:8420/v3/conversation/add"),
                ("POST", "http://127.0.0.1:8420/v3/atomic/query"),
                ("POST", "http://127.0.0.1:8420/v3/atomic/delete"),
            ],
        )
        for call in calls:
            self.assertEqual(call["headers"]["Authorization"], "Bearer local-test")
            self.assertEqual(call["headers"]["x-tdai-service-id"], "default")
            self.assertIn("x-tdai-team-id", call["headers"])
            self.assertIn("x-tdai-user-id", call["headers"])
            self.assertIn("x-tdai-agent-id", call["headers"])
        add_call = calls[2]
        self.assertEqual([item["role"] for item in add_call["json_body"]["messages"]], ["user", "assistant"])
        self.assertEqual(add_call["headers"]["x-tdai-team-id"], "team-ops")
        self.assertEqual(added["routed_to"], "home-lab")

    async def test_memory_scope_controls_tenant_and_total_count_wins(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            if kwargs["url"].endswith("/v3/atomic/query"):
                return {"data": {"total_count": 11, "total": 3, "items": []}}
            return {"data": {"items": [], "total_count": 1}}

        with patch.dict(os.environ, {"TDAI_HOME_LAB_TEAM_ID": "team-ops", "TDAI_TEAM_ID": "team-default"}, clear=True):
            settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        await server.tools["memory_search"]("query", 4, "home-lab")
        listed = await server.tools["memory_list"](8, "home-lab")
        explicit = await server.tools["memory_add"]("Docker NAS backup", "default")
        automatic = await server.tools["memory_add"]("Docker NAS backup")

        self.assertEqual(calls[0]["headers"]["x-tdai-team-id"], "team-ops")
        self.assertEqual(calls[1]["headers"]["x-tdai-team-id"], "team-ops")
        self.assertEqual(explicit["routed_to"], "default")
        self.assertEqual(automatic["routed_to"], "home-lab")
        self.assertEqual(listed["total"], 11)
        self.assertRegex(automatic["session_id"], r"^mcp-manual-[0-9a-f]{8}-[0-9a-f-]{27}$")

        for invalid_scope in ("work", "../../other"):
            with self.assertRaisesRegex(ValueError, "scope"):
                await server.tools["memory_search"]("query", 1, invalid_scope)

    async def test_tdai_tools_use_v1_paths_and_complete_schemas(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        await server.tools["tdai_memory_search"]("needle", 5)
        await server.tools["tdai_conversation_search"]("needle", 6)
        await server.tools["tdai_recall"]("needle", "session-key", "user-1")
        await server.tools["tdai_capture"](
            "question", "answer", "session-key", "session-id", "user-1", [{"role": "user", "content": "question"}]
        )
        await server.tools["tdai_session"]("session-key", "session-id", "user-1")

        self.assertEqual(
            [call["url"] for call in calls],
            [
                "http://127.0.0.1:8420/search/memories",
                "http://127.0.0.1:8420/search/conversations",
                "http://127.0.0.1:8420/recall",
                "http://127.0.0.1:8420/capture",
                "http://127.0.0.1:8420/session/end",
            ],
        )
        self.assertEqual(set(calls[2]["json_body"]), {"query", "session_key", "user_id"})
        self.assertEqual(
            set(calls[3]["json_body"]),
            {"user_content", "assistant_content", "session_key", "session_id", "user_id", "messages"},
        )

    async def test_knowledge_has_strict_28_operation_allowlist_on_8424(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        self.assertEqual(len(self.module.KNOWLEDGE_OPERATIONS), 28)
        await server.tools["tdai_knowledge"]("wiki_raw_read", {"wiki_id": "wiki-1", "filenames": ["README.md"]})
        await server.tools["tdai_knowledge"]("code_graph_callers", {"code_graph_id": "cg-1", "symbol": "main"})
        self.assertEqual(calls[0]["url"], "http://127.0.0.1:8424/v3/wiki/raw/read")
        self.assertEqual(calls[1]["url"], "http://127.0.0.1:8424/v3/code-graph/callers")
        self.assertEqual(calls[0]["headers"]["x-tdai-service-id"], "default")

        with self.assertRaisesRegex(ValueError, "not allowed"):
            await server.tools["tdai_knowledge"]("../../admin", {})
        self.assertEqual(len(calls), 2)

    async def test_generic_ai_memory_call_rejects_tools_outside_allowlist(self):
        gateway = self.module.UnifiedGateway(
            self.module.Settings.from_env(),
            request=lambda **_: self.fail("disallowed tool reached network boundary"),
        )
        server = self.module.create_server(gateway)

        with self.assertRaisesRegex(ValueError, "not allowed"):
            await server.tools["ai_memory_call"]("delete_everything", {})

    async def test_credentials_are_redacted_from_results_and_errors(self):
        secret = "top-secret-token"
        environment = {"AI_MEMORY_TOKEN": secret}

        def response(**kwargs):
            method = kwargs["json_body"]["method"]
            if method == "initialize":
                return self.module.HttpResponse(
                    200,
                    {"Mcp-Session-Id": "secret-test-session"},
                    json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
                )
            if method == "notifications/initialized":
                return self.module.HttpResponse(202, {}, "")
            return self.module.HttpResponse(
                200,
                {},
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"message": f"upstream echoed {secret}"}}),
            )

        with patch.dict(os.environ, environment, clear=True):
            settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=response))
        result = await server.tools["ai_memory_query"]("topic", 3)
        self.assertNotIn(secret, repr(result))

        def failure(**_kwargs):
            raise RuntimeError(f"Authorization: Bearer {secret}")

        server = self.module.create_server(self.module.UnifiedGateway(settings, request=failure))
        with self.assertRaisesRegex(RuntimeError, "REDACTED") as caught:
            await server.tools["ai_memory_query"]("topic", 3)
        self.assertNotIn(secret, str(caught.exception))

    async def test_ai_memory_preserves_session_id_and_parses_sse_then_json(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            if kwargs["method"] == "DELETE":
                return self.module.HttpResponse(202, {}, "")
            method = kwargs["json_body"]["method"]
            if method == "initialize":
                return self.module.HttpResponse(
                    200,
                    {"Mcp-Session-Id": "session-7"},
                    'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
                )
            if method == "notifications/initialized":
                return self.module.HttpResponse(202, {}, "")
            return self.module.HttpResponse(
                200,
                {"content-type": "application/json"},
                '{"jsonrpc":"2.0","id":2,"result":{"items":["match"]}}',
            )

        with patch.dict(os.environ, {"AI_MEMORY_TOKEN": "test-token"}, clear=True):
            settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        result = await server.tools["ai_memory_query"]("topic", 3)

        self.assertEqual(result, {"items": ["match"]})
        self.assertEqual(calls[0]["json_body"]["params"]["protocolVersion"], "2024-11-05")
        tool_call = next(call for call in calls if call["json_body"] and call["json_body"].get("method") == "tools/call")
        self.assertEqual(tool_call["json_body"]["params"]["name"], "memory_query")
        self.assertEqual(tool_call["headers"]["Mcp-Session-Id"], "session-7")
        self.assertEqual(tool_call["headers"]["Authorization"], "Bearer test-token")
        cleanup = calls[-1]
        self.assertEqual(cleanup["method"], "DELETE")
        self.assertEqual(cleanup["headers"]["Mcp-Session-Id"], "session-7")

    async def test_handoff_uses_real_tool_name_and_complete_schema(self):
        calls = []

        def request(**kwargs):
            calls.append(kwargs)
            if kwargs["method"] == "DELETE":
                return self.module.HttpResponse(202, {}, "")
            method = kwargs["json_body"]["method"]
            if method == "initialize":
                return self.module.HttpResponse(
                    200,
                    {"Mcp-Session-Id": "handoff-session"},
                    json.dumps({"jsonrpc": "2.0", "id": kwargs["json_body"]["id"], "result": {}}),
                )
            if method == "notifications/initialized":
                return self.module.HttpResponse(202, {}, "")
            return self.module.HttpResponse(
                200,
                {},
                json.dumps({"jsonrpc": "2.0", "id": kwargs["json_body"]["id"], "result": {"ok": True}}),
            )

        with patch.dict(os.environ, {"AI_MEMORY_TOKEN": "test-token"}, clear=True):
            settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        await server.tools["ai_memory_handoff_begin"](
            "summary", ["question"], ["step"], ["file.py"], "/workspace", True
        )

        tool_call = next(call for call in calls if call["json_body"] and call["json_body"].get("method") == "tools/call")
        params = tool_call["json_body"]["params"]
        self.assertEqual(params["name"], "memory_handoff_begin")
        self.assertEqual(
            set(params["arguments"]),
            {"summary", "open_questions", "next_steps", "files_touched", "cwd", "shared"},
        )

    async def test_ai_memory_session_is_per_call_and_rebuilds_invalid_session(self):
        calls = []
        tool_attempts = 0

        def request(**kwargs):
            nonlocal tool_attempts
            calls.append(kwargs)
            if kwargs["method"] == "DELETE":
                return self.module.HttpResponse(202, {}, "")
            method = kwargs["json_body"]["method"]
            if method == "initialize":
                session_number = sum(
                    bool(call["json_body"]) and call["json_body"].get("method") == "initialize" for call in calls
                )
                return self.module.HttpResponse(
                    200,
                    {"Mcp-Session-Id": "session-{}".format(session_number)},
                    json.dumps({"jsonrpc": "2.0", "id": kwargs["json_body"]["id"], "result": {}}),
                )
            if method == "notifications/initialized":
                return self.module.HttpResponse(202, {}, "")
            tool_attempts += 1
            if tool_attempts == 1:
                return self.module.HttpResponse(404, {}, "invalid session")
            return self.module.HttpResponse(
                200,
                {},
                json.dumps({"jsonrpc": "2.0", "id": kwargs["json_body"]["id"], "result": {"ok": True}}),
            )

        with patch.dict(os.environ, {"AI_MEMORY_TOKEN": "test-token"}, clear=True):
            settings = self.module.Settings.from_env()
        server = self.module.create_server(self.module.UnifiedGateway(settings, request=request))
        await server.tools["ai_memory_query"]("first", 1)
        await server.tools["ai_memory_query"]("second", 1)

        initialize_count = sum(
            bool(call["json_body"]) and call["json_body"].get("method") == "initialize" for call in calls
        )
        self.assertEqual(initialize_count, 3)
        self.assertEqual(sum(call["method"] == "DELETE" for call in calls), 3)

    async def test_rest_deadline_returns_before_blocking_thread_finishes(self):
        def slow_request(**_kwargs):
            time.sleep(0.2)
            return {"too": "late"}

        settings = self.module.Settings.from_env()
        settings.timeout = 0.02
        gateway = self.module.UnifiedGateway(settings, request=slow_request)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            await gateway.rest("GET", "http://upstream/slow")
        self.assertLess(time.monotonic() - started, 0.1)

    def test_main_runs_streamable_http_with_configured_listener(self):
        with patch.dict(
            os.environ,
            {
                "HERMES_UNIFIED_HOST": "0.0.0.0", "HERMES_UNIFIED_PORT": "9876",
                "HERMES_UNIFIED_PATH": "/gateway", "AI_MEMORY_TOKEN": "test-token",
            },
            clear=True,
        ):
            server = self.module.main()

        self.assertEqual(
            server.run_args,
            {"transport": "streamable-http", "host": "0.0.0.0", "port": 9876, "path": "/gateway"},
        )

    def test_mcp_server_fallback_uses_sdk_2_run_arguments(self):
        module = load_server_module(use_mcp_server=True)
        with patch.dict(os.environ, {"AI_MEMORY_TOKEN": "test-token"}, clear=True):
            server = module.main()

        self.assertEqual(
            server.run_args,
            {
                "transport": "streamable-http",
                "host": "127.0.0.1",
                "port": 8765,
                "streamable_http_path": "/mcp",
                "json_response": True,
                "stateless_http": True,
            },
        )

    def test_main_fails_fast_without_ai_memory_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "AI_MEMORY_TOKEN"):
                self.module.main()

    def test_smoke_mode_creates_server_and_lists_all_tools(self):
        with patch.dict(os.environ, {"AI_MEMORY_TOKEN": "smoke-token"}, clear=True):
            names = self.module.smoke()
        self.assertEqual(set(names), set(self.module.EXPOSED_TOOL_NAMES))


if __name__ == "__main__":
    unittest.main()
