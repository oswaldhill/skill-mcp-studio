"""Probe transport abstraction (phase 2; hardened 2026-09-05 review CLI-5/Windows).

The HTTP probe lives in ``mcp_probe`` and is unchanged.  This module adds the
stdio transport for local MCP servers: spawn ``command`` (argv list, no shell),
perform the same three read-only JSON-RPC steps (initialize →
notifications/initialized → tools/list), then terminate the child.

Design §5.2 shape (评审 CLI-5b 落地):

- ``ProbeSpec`` — unified probe input (URL for HTTP, command for stdio);
- ``Transport`` protocol — ``probe(spec, timeout) -> ProbeResult``;
- ``TRANSPORTS`` registry + ``get_transport``/``dispatch_probe`` — the single
  extension point for future transports;
- ``probe_mcp`` dispatches its stdio branch through this registry.

Hardening (评审 CLI-5a / 阶段二 §5.2.3 / Windows 兼容):

- ``timeout`` is a single **deadline budget** covering spawn + both handshakes
  (previously each handshake got its own timeout → up to 2× the budget);
- line reading uses a background reader thread + queue instead of
  ``select.select`` — Windows ``select`` only supports sockets, not pipes;
- termination uses portable ``proc.terminate()``/``proc.kill()`` instead of
  POSIX-only ``SIGTERM``/``SIGKILL``;
- on Windows the child is spawned with ``CREATE_NO_WINDOW`` so console apps do
  not flash a console window.

Security (设计 §8):

- ``command``/``args`` must be an argv list; ``shell=True`` is never used;
- ``env`` values support ``${NAME}`` expansion against the parent environment so
  tokens never touch config or reports;
- the child is terminated after the probe.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable


class StdioProbeError(RuntimeError):
    """Raised when a stdio endpoint cannot be started or a handshake fails."""


# ---------------------------------------------------------------------------
# §5.2 抽象：ProbeSpec / ProbeResult / Transport / registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbeSpec:
    """统一探测输入（设计 §5.2）：HTTP 用 ``url``，stdio 用 ``command``+``args``。"""

    transport: str = "streamable-http"
    url: str = ""
    command: str = ""
    args: Tuple[str, ...] = ()
    env: Dict[str, Any] = field(default_factory=dict)
    token: Optional[str] = None
    token_env: Optional[str] = None
    url_policy: str = "strict"


#: 统一探测输出（沿用现有结构）：
#: ``{"initialize_ok", "tools_list_ok", "tool_names", "error"}``
ProbeResult = Dict[str, Any]


@runtime_checkable
class Transport(Protocol):
    """探测传输抽象（设计 §5.2）：新增 transport 只需实现本接口并注册。"""

    name: str

    def probe(self, spec: ProbeSpec, timeout: float) -> ProbeResult: ...


class StdioTransport:
    """stdio 传输：本地 MCP 服务器（argv 启动，无 shell）。"""

    name = "stdio"

    def probe(self, spec: ProbeSpec, timeout: float = 8.0) -> ProbeResult:
        if not spec.command:
            raise StdioProbeError("stdio transport requires a non-empty command")
        return probe_stdio(spec.command, args=list(spec.args), env=dict(spec.env) or None, timeout=timeout)


class HttpTransport:
    """streamable-http 传输：包装既有 ``mcp_probe.probe_mcp``（纯委托，零重写）。"""

    name = "streamable-http"

    def probe(self, spec: ProbeSpec, timeout: float = 8.0) -> ProbeResult:
        from mcp_probe import probe_mcp  # lazy：避免 mcp_probe ↔ transport 循环导入

        return probe_mcp(
            spec.url,
            transport="streamable-http",
            timeout=timeout,
            token=spec.token,
            token_env=spec.token_env,
            url_policy=spec.url_policy,
        )


TRANSPORTS: Dict[str, Transport] = {
    "streamable-http": HttpTransport(),
    "stdio": StdioTransport(),
}


def get_transport(name: str) -> Transport:
    """按白名单解析传输；未知值 fail fast（与 profile_loader 加载期校验一致）。"""
    transport = TRANSPORTS.get(name)
    if transport is None:
        raise StdioProbeError(
            f"unsupported transport {name!r}; expected one of {sorted(TRANSPORTS)}"
        )
    return transport


def dispatch_probe(spec: ProbeSpec, timeout: float = 8.0) -> ProbeResult:
    """统一探测分派入口：``ProbeSpec`` → 注册的 ``Transport`` → ``ProbeResult``。"""
    return get_transport(spec.transport).probe(spec, timeout)


# ---------------------------------------------------------------------------
# env 展开（不变）
# ---------------------------------------------------------------------------

def expand_env(value: str, environ: Optional[Dict[str, str]] = None) -> str:
    """Expand ``${NAME}`` references against ``environ`` (defaults to os.environ).

    A missing reference raises ``StdioProbeError`` (fail fast, never silently
    empty a token).
    """
    environ = os.environ if environ is None else environ
    out = []
    i = 0
    value = str(value)
    while i < len(value):
        j = value.find("${", i)
        if j == -1:
            out.append(value[i:])
            break
        out.append(value[i:j])
        end = value.find("}", j)
        if end == -1:
            raise StdioProbeError(f"unterminated env reference in {value!r}")
        name = value[j + 2:end]
        if name not in environ:
            raise StdioProbeError(f"env variable {name!r} not set (required for stdio probe)")
        out.append(environ[name])
        i = end + 1
    return "".join(out)


def _build_env(profile_env: Optional[Dict[str, Any]], environ: Dict[str, str]) -> Dict[str, str]:
    merged = dict(environ)
    for key, value in (profile_env or {}).items():
        merged[str(key)] = expand_env(str(value), environ)
    return merged


# ---------------------------------------------------------------------------
# stdio 读取：后台线程 + 队列（跨平台，替代 select——Windows 的 select 仅支持
# socket，不能用于管道；评审 Windows 兼容项）
# ---------------------------------------------------------------------------

_EOF = object()


class _LineReader(threading.Thread):
    """Daemon thread pumping stdout lines into a bounded-free queue."""

    def __init__(self, stream):
        super().__init__(daemon=True)
        self._stream = stream
        self.lines: "queue.Queue[Any]" = queue.Queue()
        self.start()

    def run(self) -> None:  # pragma: no cover - exercised via probe_stdio tests
        # 显式 readline()：TextIOWrapper 的迭代器带预读缓冲，在管道上会阻塞到
        # 凑满缓冲才返回；readline() 按换行即时返回（本机实测确认）。
        try:
            while True:
                line = self._stream.readline()
                if not line:
                    break
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self.lines.put(_EOF)


#: stderr 尾部保留上限（字符）——只留末尾，诊断信息通常在最后。
_STDERR_TAIL_LIMIT = 2000


class _StderrDrain(threading.Thread):
    """Daemon thread that keeps the child's stderr pipe empty (评审 P0-5).

    为什么必须排空：``stderr`` 以 ``subprocess.PIPE`` 打开时，子进程写入的量
    一旦超过管道缓冲（POSIX 通常 64 KiB）就会阻塞在 ``write`` 上，再也不读
    stdin、不回握手 —— 外部只看到「stdio handshake timed out」。这与
    ``test_stdio_probe`` 那次未定位的偶发失败特征吻合（是否触发取决于子进程
    在握手期间往 stderr 写了多少）。

    为什么按块读而不是 ``readline()``：两者**都能**把管道排空 —— ``readline()``
    会持续把数据读进自己的内部缓冲，所以它并不会死锁（实测如此，别照抄
    「必须按块读否则死锁」的说法）。真正的差别是：``readline()`` 要读满一整行
    才返回，遇到不含换行的 stderr（进度条、未换行的 traceback）就是**无界内存
    增长**，而且 ``tail()`` 在它返回前一直取不到东西 —— 偏偏这种输入正是最需要
    取证的时候。``read(4096)`` 读一块丢一块（只留尾部），内存恒定。
    （stdout 是行协议的 JSON-RPC，那里用 ``readline()`` 是正确的。）
    """

    def __init__(self, stream):
        super().__init__(daemon=True)
        self._stream = stream
        self._lock = threading.Lock()
        self._tail = ""
        self.start()

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(4096)
                if not chunk:
                    break
                with self._lock:
                    self._tail = (self._tail + chunk)[-_STDERR_TAIL_LIMIT:]
        except (OSError, ValueError):
            # 与 _LineReader 一致：流被主线程收尾关闭时静默退出。
            pass

    def tail(self) -> str:
        with self._lock:
            return self._tail


def _read_json_message(reader: _LineReader, deadline: float) -> Optional[Dict[str, Any]]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise StdioProbeError("stdio handshake timed out")
    try:
        line = reader.lines.get(timeout=remaining)
    except queue.Empty:
        raise StdioProbeError("stdio handshake timed out")
    if line is _EOF:
        return None  # EOF：继续等到 deadline（与原语义一致）
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _wait_for_id(reader: _LineReader, request_id: int, deadline: float) -> Dict[str, Any]:
    # 单一 deadline 预算（评审 CLI-5a）：启动 + 两次握手共享同一个超时。
    while time.monotonic() < deadline:
        message = _read_json_message(reader, deadline)
        if message is None:
            continue
        if message.get("id") == request_id:
            return message
    raise StdioProbeError("stdio handshake timed out waiting for response")


def _rpc(proc: subprocess.Popen, payload: Dict[str, Any]) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _terminate(proc: subprocess.Popen) -> None:
    # 跨平台：terminate()/kill() 在 POSIX=SIGTERM/SIGKILL、Windows=TerminateProcess，
    # 避免直接引用 Windows 上不存在的 signal.SIGKILL。
    if proc.poll() is not None:
        return
    for kill in (proc.terminate, proc.kill):
        try:
            kill()
        except (OSError, ProcessLookupError):
            return
        try:
            proc.wait(timeout=2.0)
            return
        except subprocess.TimeoutExpired:
            continue


def probe_stdio(
    command: str,
    *,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, Any]] = None,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Probe a local MCP server over stdio (the fourth-question live check).

    ``timeout`` is a single deadline budget covering spawn + initialize +
    tools/list（阶段二 §5.2.3「启动 + initialize 握手计入 timeout」，评审 CLI-5a
    落地为覆盖全部握手）。
    """
    result: Dict[str, Any] = {
        "initialize_ok": False,
        "tools_list_ok": False,
        "tool_names": [],
        "error": "",
    }
    argv = [command] + list(args or [])
    try:
        environ = _build_env(env, os.environ)
    except StdioProbeError as exc:
        result["error"] = str(exc)
        return result

    popen_kwargs: Dict[str, Any] = {}
    if os.name == "nt":  # Windows：控制台程序不弹窗口
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environ,
            text=True,
            # 解码失败绝不能把排空线程打退（它会因 UnicodeDecodeError 提前结束，
            # 管道重新被填满 → 死锁回归）。errors="replace" 让非 UTF-8 的 stderr
            # 退化成替换字符，而不是中断排空。
            errors="replace",
            bufsize=1,
            **popen_kwargs,
        )
    except (OSError, FileNotFoundError) as exc:
        result["error"] = f"failed to start stdio server: {exc}"
        return result

    deadline = time.monotonic() + timeout  # 单一预算（评审 CLI-5a）
    reader = _LineReader(proc.stdout)  # __init__ 内已 start()
    # 必须与 stdout 同时开始排空 stderr：握手期间子进程往 stderr 写多少，
    # 都不该把它卡死（评审 P0-5）。
    stderr_drain = _StderrDrain(proc.stderr)
    try:
        _rpc(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "skill-mcp-studio", "version": "1.0"},
            },
        })
        init = _wait_for_id(reader, 1, deadline)
        if init.get("error") or not init.get("result"):
            result["error"] = str(init.get("error") or "initialize returned no result")
            return result
        result["initialize_ok"] = True

        _rpc(proc, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        _rpc(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        listed = _wait_for_id(reader, 2, deadline)
        tools = (listed.get("result") or {}).get("tools", [])
        result["tool_names"] = sorted(
            tool.get("name", "")
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        )
        result["tools_list_ok"] = bool(tools)
        if not tools:
            result["error"] = str(listed.get("error") or "tools/list returned no tools")
    except (StdioProbeError, OSError, ValueError) as exc:
        result["error"] = str(exc)
    finally:
        _terminate(proc)
        # 进程已终止 → 子进程 stderr 写端关闭，排空线程读到 EOF 后自然结束；
        # join 给它一点时间把管道里剩余内容收干净。
        stderr_drain.join(timeout=1.0)
        detail = stderr_drain.tail().strip()
        if result["error"] and detail:
            # P0-5 要的可诊断性：超时不再只是一句「stdio handshake timed out」，
            # 而是带上子进程自己说的话 —— 足以区分「没启动」「卡在 stderr」
            # 「真的没回应」。
            result["error"] = f"{result['error']}\n--- server stderr (tail) ---\n{detail}"
        # 收尾关管道，避免 ResourceWarning（读线程对已关闭流的读错误已被其捕获）。
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except OSError:
                pass
    return result
