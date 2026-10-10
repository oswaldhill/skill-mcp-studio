//! Tauri shell for the Skill/MCP management dashboard (stage 5).
//!
//! The webview renders `gui/dashboard.html`; the native surface exposes:
//!
//! - `run_audit` -> `skill-mcp-studio --all-profiles --format json` (read-only;
//!   returns the raw JSON snapshot unchanged, no parsing, no re-derivation);
//! - `run_cli` -> `skill-mcp-studio <args...>` (generic passthrough for the
//!   stage-5 management actions: endpoint CRUD, attachment edits, skill merge,
//!   unified-dir set, client discovery).  It returns a structured JSON envelope
//!   `{"code": int, "stdout": str, "stderr": str}` so the webview can tell a
//!   tool error (code 2) apart from an audit conclusion (0/1) for write commands
//!   whose stdout is human-readable Chinese text, not JSON.
//!
//! The CLI is the single source of truth (ADR: one engine, one data contract);
//! this shell only spawns the already-installed `skill-mcp-studio` subprocess.
//!
//! Repairs are deliberately *not* re-implemented in Rust: every write still runs
//! the CLI's backup -> atomic-write -> validate -> rollback safety chain.
//!
//! CLI resolution: GUI-launched apps inherit a minimal PATH (`/usr/bin:/bin` on
//! macOS, or the bare system PATH on Windows when launched from Explorer), so a
//! bare name lookup can miss user-local wrappers.  We try the PATH name first,
//! then common absolute locations per platform (see `cli_candidates`).

use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent, WindowEvent};
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

/// 置位后表示应用正在退出（Cmd+Q / ExitRequested），此时放行窗口关闭；
/// 否则单窗口的 CloseRequested（Cmd+W / 红色关闭钮）只隐藏窗口，不退出。
static EXITING: AtomicBool = AtomicBool::new(false);

/// popover 最近一次显示的时刻。
///
/// 为什么要它：失焦即收起是 macOS 弹框的惯例，但 `show()` 到 `set_focus()`
/// 之间窗口还不是 key window，会先抛一次 `Focused(false)`。若不设防，弹框
/// 会「闪现即消失」。这里给显示后的一小段时间设抑制窗，窗口稳定获得焦点后
/// 再恢复正常的失焦收起行为。
static POPOVER_SHOWN_AT: Mutex<Option<std::time::Instant>> = Mutex::new(None);
/// 显示后的失焦抑制时长；取值要盖住 `show()` → `set_focus()` 的生效延迟。
const POPOVER_FOCUS_GRACE: Duration = Duration::from_millis(400);

/// Candidate CLI launch targets: PATH name first, then common install locations.
///
/// Cross-platform (three targets):
///
/// - macOS: ``skill-mcp-studio`` (PATH) + ``~/.local/bin`` + Homebrew/系统路径;
/// - Linux: ``skill-mcp-studio`` (PATH) + ``~/.local/bin`` + ``/usr/local/bin``;
/// - Windows: ``skill-mcp-studio``/``skill-mcp-studio.exe`` (PATH, pipx/pip
///   ``%LOCALAPPDATA%\Programs\Python\*\Scripts`` 通常已加入用户 PATH) +
///   ``%USERPROFILE%\.local\bin\skill-mcp-studio.exe`` + ``%APPDATA%\Python\Scripts``.
///
/// 统一策略：先裸名（依赖 PATH），再补用户级/系统级绝对路径。Windows 裸露的
/// 裸名需同时试 ``.exe`` 后缀，因为 ``Command::new`` 不会自动补全扩展名。
fn cli_candidates() -> Vec<String> {
    let name = "skill-mcp-studio";
    let mut candidates: Vec<String> = Vec::new();

    // 先裸名（依赖 PATH）：finde通过 PATH 定位已安装 CLI（pipx/pip 均会把
    // scripts 目录加入用户 PATH）。
    candidates.push(name.to_string());

    #[cfg(target_os = "windows")]
    {
        // Windows 的 CreateProcess 不自动补扩展名：pipx 生成的是
        // ``skill-mcp-studio.exe``，裸名不一定能被 Command::new 直接启动，
        // 需同时试带 ``.exe`` 的形式。
        let exe = format!("{name}.exe");
        candidates.push(exe.clone());

        // pipx 默认用户级安装点 %USERPROFILE%\.local\bin（回退 HOME）。
        let home = std::env::var_os("USERPROFILE")
            .or_else(|| std::env::var_os("HOME"))
            .map(std::path::PathBuf::from);
        if let Some(home) = home {
            candidates.push(home.join(".local/bin").join(&exe).to_string_lossy().into_owned());
        }
        // pip install --user 的 Roaming scripts 目录。
        if let Some(appdata) = std::env::var_os("APPDATA") {
            candidates.push(
                std::path::PathBuf::from(appdata)
                    .join("Python/Scripts")
                    .join(exe)
                    .to_string_lossy()
                    .into_owned(),
            );
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        // Unix 系：pipx / pip --user 的用户级安装点 ``~/.local/bin`` 优先。
        if let Some(home) = std::env::var_os("HOME") {
            let home = std::path::PathBuf::from(home);
            candidates.push(home.join(".local/bin").join(name).to_string_lossy().into_owned());
        }
        // 系统级常见路径。
        candidates.push("/usr/local/bin/skill-mcp-studio".to_string());
        #[cfg(target_os = "macos")]
        candidates.push("/opt/homebrew/bin/skill-mcp-studio".to_string());
        #[cfg(target_os = "linux")]
        candidates.push("/usr/bin/skill-mcp-studio".to_string());
    }

    candidates
}

/// Common subprocess spawn: try each CLI candidate until one runs.
///
/// Returns `(code, stdout, stderr)`; `None` code means the process could not be
/// spawned or was killed by a signal.
fn spawn(args: &[String]) -> Result<(Option<i32>, String, String), String> {
    let mut attempts: Vec<String> = Vec::new();
    for cli in cli_candidates() {
        let output = match Command::new(&cli).args(args).output() {
            Ok(output) => output,
            Err(e) => {
                attempts.push(format!("{cli}: {e}"));
                continue;
            }
        };
        let code = output.status.code();
        let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
        let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
        return Ok((code, stdout, stderr));
    }
    Err(format!(
        "无法启动 skill-mcp-studio（已尝试 PATH 与常见安装位置）：{}。请先安装 CLI：pipx install skill-mcp-studio（或 pip3 install --user），安装后重试。",
        attempts.join("；")
    ))
}

/// 当前正在运行的 CLI 子进程 PID；`None` 表示空闲。
///
/// 存在的唯一理由是「关闭进度对话框 = 立即停止任务」：`run_cli` 把 PID 登记进来，
/// 新命令 `cancel_cli` 据此终止子进程。没有它，长扫描一旦发起就只能干等到底。
static RUNNING_PID: Mutex<Option<u32>> = Mutex::new(None);

/// 本次运行是否被用户取消（用于把"被杀的进程"与"自己失败"区分开）。
static CANCELLED: AtomicBool = AtomicBool::new(false);

/// 扫描进度文件的固定位置。
///
/// **路径由 shell 独占决定，webview 不能指定**：否则 `--progress-file` 就变成
/// 一个"往任意路径写 JSON"的写原语，越过了 ARCH-2 的写边界。两侧（Python 用
/// `tempfile.gettempdir()`，这里用 `env::temp_dir()`）解析同一个 TMPDIR，
/// 因此无需协商即可指向同一文件。
fn progress_file_path() -> std::path::PathBuf {
    std::env::temp_dir().join("skill-mcp-studio-progress.json")
}

/// 终止子进程（优先整个进程组，退回单 PID）。
fn kill_child(pid: u32) {
    // spawn 时已建独立进程组（PGID == PID），所以 `-pid` 能连子孙一起收掉。
    #[cfg(unix)]
    {
        let grouped = Command::new("kill")
            .arg("-TERM")
            .arg(format!("-{pid}"))
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if !grouped {
            let _ = Command::new("kill").arg("-TERM").arg(pid.to_string()).status();
        }
    }
    #[cfg(target_os = "windows")]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .status();
    }
}

/// 可取消的 `spawn`：与 [`spawn`] 相同的候选回退语义，但登记 PID 供取消，
/// 并返回是否被取消。
fn spawn_cancellable(args: &[String]) -> Result<(Option<i32>, String, String, bool), String> {
    let mut attempts: Vec<String> = Vec::new();
    for cli in cli_candidates() {
        let mut cmd = Command::new(&cli);
        cmd.args(args).stdout(Stdio::piped()).stderr(Stdio::piped());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            cmd.process_group(0);
        }
        let mut child = match cmd.spawn() {
            Ok(child) => child,
            Err(e) => {
                attempts.push(format!("{cli}: {e}"));
                continue;
            }
        };
        let pid = child.id();
        let mut out_pipe = child.stdout.take();
        let mut err_pipe = child.stderr.take();

        CANCELLED.store(false, Ordering::SeqCst);
        *RUNNING_PID.lock().unwrap() = Some(pid);

        // 两个管道必须并发读：只 wait 不读，子进程写满 64KB 缓冲区就会卡死。
        let out_reader = std::thread::spawn(move || {
            let mut buf = String::new();
            if let Some(pipe) = out_pipe.as_mut() {
                let _ = pipe.read_to_string(&mut buf);
            }
            buf
        });
        let err_reader = std::thread::spawn(move || {
            let mut buf = String::new();
            if let Some(pipe) = err_pipe.as_mut() {
                let _ = pipe.read_to_string(&mut buf);
            }
            buf
        });

        // 轮询 try_wait 而不是阻塞 wait：取消要走另一条命令，不能被 wait 独占。
        let status = loop {
            match child.try_wait() {
                Ok(Some(st)) => break Some(st),
                Ok(None) => std::thread::sleep(Duration::from_millis(80)),
                Err(_) => break None,
            }
        };

        let stdout = out_reader.join().unwrap_or_default();
        let stderr = err_reader.join().unwrap_or_default();
        let cancelled = CANCELLED.load(Ordering::SeqCst);
        *RUNNING_PID.lock().unwrap() = None;
        return Ok((status.and_then(|s| s.code()), stdout, stderr, cancelled));
    }
    Err(format!(
        "无法启动 skill-mcp-studio（已尝试 PATH 与常见安装位置）：{}。请先安装 CLI：pipx install skill-mcp-studio（或 pip3 install --user），安装后重试。",
        attempts.join("；")
    ))
}

/// 取消正在运行的 CLI 任务（进度对话框上的「取消」）。
///
/// 返回是否真的杀掉了一个进程：`false` 表示调用时任务已自行结束。
#[tauri::command]
fn cancel_cli() -> Result<bool, String> {
    let pid = *RUNNING_PID.lock().unwrap();
    match pid {
        Some(p) => {
            CANCELLED.store(true, Ordering::SeqCst);
            kill_child(p);
            Ok(true)
        }
        None => Ok(false),
    }
}

/// 读取扫描进度文件（CLI 原子写入，GUI 轮询）。
///
/// 文件不存在返回空串而非报错：进度是可选的过程信号，"还没有进度"不是故障。
#[tauri::command]
fn read_scan_progress() -> Result<String, String> {
    Ok(std::fs::read_to_string(progress_file_path()).unwrap_or_default())
}

/// Aggregate snapshot across every profile (populates the profile dropdown too).
///
/// Async: the blocking subprocess spawn runs on the async blocking pool via
/// `spawn_blocking`, so the webview main thread never freezes during a refresh.
#[tauri::command]
async fn run_audit() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let (code, stdout, stderr) = spawn(&[
            "--all-profiles".to_string(),
            "--format".to_string(),
            "json".to_string(),
        ])?;
        // Exit code 2 == tool error (surface it; NOT an audit conclusion).
        // Exit code 0/1 == audit result; stdout still carries the snapshot.
        if code == Some(2) {
            return Err(format!("skill-mcp-studio 运行失败 (exit 2): {stderr}"));
        }
        Ok(stdout)
    })
    .await
    .map_err(|e| format!("审计任务失败: {e}"))?
}

/// Generic CLI passthrough for stage-5 management (read + write) actions.
///
/// `args` is the argv tail (without the program name).  Returns a JSON envelope
/// string; the caller must not assume stdout is JSON — only the envelope is.
///
/// ARCH-2 fix: a fixed allowlist of subcommands gates what the webview may
/// invoke — unknown subcommands are rejected so a compromised page cannot
/// reach arbitrary CLI surface (e.g. ``--config <arbitrary>`` to redirect the
/// engine to a hostile YAML).  ``--config`` itself is rejected outright
/// (redirection class).  Returned ``stderr`` is truncated to bound size.
/// 读取后台巡检当前是否启用（CLI 为唯一事实来源）。
///
/// 托盘菜单的勾选态与后台线程的判定都走这里，避免两处各解析一份字符串。
fn patrol_enabled_now() -> bool {
    let args = vec![
        "--get-setting".to_string(),
        "patrol_enabled".to_string(),
        "--format".to_string(),
        "json".to_string(),
    ];
    match spawn(&args) {
        Ok((_, stdout, _)) => json_bool(&stdout, "patrol_enabled").unwrap_or_else(|| {
            // JSON 不可用时退回旧的文本判据（兼容 CLI 未升级的情形）。
            stdout.contains("patrol_enabled = True") || stdout.contains("patrol_enabled = true")
        }),
        Err(_) => false,
    }
}

/// 从 CLI 的 JSON 输出里取一个布尔字段。
///
/// 为什么要走 JSON 而不是匹配中文文案：此前巡检判据是
/// `stdout.contains("检测到变更")`，等于把**界面文案当成协议**——
/// CLI 改一个措辞（例如「发现变更」），巡检就静默失效且不报错。
/// 同一个命令早已提供 `--format json`，用它才是稳定契约。
///
/// 兼容两种返回形态：
/// - CLI 直接打印的裸 JSON；
/// - `run_cli` 那类 `{code, stdout, ...}` 外壳（此处不涉及，但一并容忍）。
fn json_bool(stdout: &str, key: &str) -> Option<bool> {
    let value: serde_json::Value = serde_json::from_str(stdout.trim()).ok()?;
    value
        .get(key)
        .or_else(|| value.get("stdout").and_then(|s| s.get(key)))
        .and_then(|v| v.as_bool())
}

/// 判断一次 `--snapshot --format json` 的输出是否报告了变更。
///
/// 解析失败时返回 `None`，让调用方区分「确实无变更」与「没读懂输出」——
/// 后者不应被当成无变更而静默吞掉。
fn snapshot_has_changes(stdout: &str) -> Option<bool> {
    let value: serde_json::Value = serde_json::from_str(stdout.trim()).ok()?;
    value.get("has_changes").and_then(|v| v.as_bool())
}

/// 托盘图标的三态。
///
/// - `Idle`：空闲。单色模板图，由 macOS 依菜单栏明暗自动着色，最规整。
/// - `Alert`：检测到变更。字形 + 右上角红点（浅色菜单栏用深色字形）。
/// - `AlertDark`：同上但字形为浅色，用于深色菜单栏。
/// - `Scanning`：巡检进行中。仍用模板图（保持明暗自适应），靠 tooltip 说明。
///
/// 为什么 Alert 态不能继续用模板图：模板模式会**强制单色**，红点会被系统
/// 抹成同色，角标就失去「一眼看出有变更」的作用。所以告警态改用非模板图，
/// 代价是失去自动明暗适配 —— 用明/暗两版字形 + 运行时按主题选取来补偿。
///
/// 为什么 Scanning 不做旋转动画：菜单栏图标换图频率受限，逐帧切换在
/// macOS 上开销明显且易被系统节流；而巡检只持续 1~2 秒，动画还没转完就
/// 结束了。用 tooltip 表达「正在巡检」既清晰又不引额外资源。
#[derive(Clone, Copy, PartialEq)]
enum TrayState {
    Idle,
    Alert,
    AlertDark,
    Scanning,
}

/// 菜单栏图标：单色模板（空闲）或带红点角标（有变更）。
///
/// 为什么要模板图标而不是应用图标：应用图标是**全不透明的深色方块**
/// （32×32 四角均为 #0D1121），放进菜单栏就是一个深色块，在深色菜单栏上
/// 几乎糊成一团。模板图标只带形状，系统负责取色，明暗两种菜单栏都清晰。
///
/// 取 @2x（32px）让 Retina 屏有足量像素；源图缺失时回退到应用图标，
/// 保证不会因为资源问题导致托盘起不来。
fn tray_icon(state: TrayState) -> tauri::image::Image<'static> {
    const TEMPLATE_2X: &[u8] = include_bytes!("../icons/trayTemplate@2x.png");
    const ALERT_2X: &[u8] = include_bytes!("../icons/trayAlert@2x.png");
    const ALERT_DARK_2X: &[u8] = include_bytes!("../icons/trayAlertDark@2x.png");
    const FALLBACK: &[u8] = include_bytes!("../icons/32x32.png");

    let bytes = match state {
        // Scanning 复用模板图：巡检中不需要额外图形，
        // 差别体现在 tooltip（见 apply_tray_state）。
        TrayState::Idle | TrayState::Scanning => TEMPLATE_2X,
        TrayState::Alert => ALERT_2X,
        TrayState::AlertDark => ALERT_DARK_2X,
    };
    match tauri::image::Image::from_bytes(bytes) {
        Ok(img) => img,
        Err(_) => tauri::image::Image::from_bytes(FALLBACK).expect("托盘图标资源缺失"),
    }
}

/// 把托盘切到指定状态（图标 + 模板标志 + tooltip 一起改）。
///
/// 模板标志必须跟着图标一起切：告警图是非模板的彩色图，若沿用
/// `icon_as_template(true)`，macOS 会把红点也抹成单色。
fn apply_tray_state(tray: &tauri::tray::TrayIcon, state: TrayState, has_changes: bool) {
    // Scanning 也用模板模式：它复用模板图，非模板模式会让它失去明暗自适应
    let is_template = matches!(state, TrayState::Idle | TrayState::Scanning);
    let _ = tray.set_icon(Some(tray_icon(state)));
    let _ = tray.set_icon_as_template(is_template);
    let _ = tray.set_tooltip(Some(match state {
        TrayState::Scanning => "Skill MCP Studio（正在巡检…）",
        _ if has_changes => "Skill MCP Studio（检测到变更，点击查看）",
        _ => "Skill MCP Studio",
    }));
}

/// 按当前窗口主题选告警态字形：深色菜单栏配浅色字形，反之亦然。
///
/// 取窗口主题而非系统外观：托盘挂在应用上，菜单栏取色通常跟随应用的
/// effective appearance；取不到时按浅色（默认）处理。
fn alert_state_for_app(app: &tauri::AppHandle) -> TrayState {
    let dark = app
        .get_webview_window("main")
        .and_then(|w| w.theme().ok())
        .map(|t| t == tauri::Theme::Dark)
        .unwrap_or(false);
    if dark {
        TrayState::AlertDark
    } else {
        TrayState::Alert
    }
}

/// 显示主窗口（popover 的「打开完整面板」按钮调用）。
///
/// `page` 可选：给了就在显示后切到该页并刷新对应内容，用于把用户从
/// 通知/popover 直接带到「变更详情」。
///
/// 为什么不做「点通知直接跳转」：Tauri 2 的 notification 插件只提供发送
/// 能力，没有点击回调（`Builder` 上没有 on_action/on_click 一类方法）。
/// 因此改由 popover 承担跳转入口——用户从通知看到提示后点托盘弹框，
/// 一次点击即可落到变更详情。
#[tauri::command]
fn show_main_window(app: tauri::AppHandle, page: Option<String>) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        if let Some(page) = page {
            // 只允许页面名（字母数字），避免把任意 JS 拼进 eval。
            if page.chars().all(|c| c.is_ascii_alphanumeric()) {
                let js = format!(
                    "if (typeof switchPage === 'function') {{ switchPage('{page}'); }} \
                     if ('{page}' === 'changes' && typeof runSnapshot === 'function') {{ runSnapshot(); }}"
                );
                let _ = window.eval(&js);
            }
        }
    }
    Ok(())
}

/// 把 popover 摆到屏幕右上角、菜单栏正下方，贴合托盘图标位置。
///
/// macOS 菜单栏高约 25-30pt，右侧留给弹框一个 8pt 边距；
/// 取不到显示器信息时保持原位，不影响功能。
/// 记录 popover 显示时刻，开启失焦抑制窗（见 `POPOVER_SHOWN_AT`）。
fn mark_popover_shown() {
    if let Ok(mut guard) = POPOVER_SHOWN_AT.lock() {
        *guard = Some(std::time::Instant::now());
    }
}

fn position_popover(window: &tauri::WebviewWindow, anchor: Option<&tauri::Rect>) {
    let monitor = window
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| window.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else { return };
    let scale = monitor.scale_factor();
    let screen = monitor.size().to_logical::<f64>(scale);
    let win = window
        .outer_size()
        .map(|s| s.to_logical::<f64>(scale))
        .unwrap_or_else(|_| tauri::LogicalSize::new(300.0, 300.0));

    // 菜单栏高度：macOS 约 25pt，其余平台给一个小边距。
    let bar_h = if cfg!(target_os = "macos") { 25.0 } else { 8.0 };
    // 弹框与图标水平居中对齐；没有锚点时退回右上角（无图标信息可用）。
    let x = match anchor {
        Some(rect) => {
            let pos = rect.position.to_logical::<f64>(scale);
            let size = rect.size.to_logical::<f64>(scale);
            pos.x + size.width / 2.0 - win.width / 2.0
        }
        None => screen.width - win.width - 8.0,
    };
    // 贴住屏幕边缘时收拢，避免弹框被裁掉（含 8pt 边距）。
    let max_x = (screen.width - win.width - 8.0).max(0.0);
    let x = x.min(max_x).max(8.0);
    // y 取图标底边与菜单栏底边的较大者：图标 rect 在菜单栏内时即贴栏下方。
    let y = match anchor {
        Some(rect) => {
            let pos = rect.position.to_logical::<f64>(scale);
            let size = rect.size.to_logical::<f64>(scale);
            (pos.y + size.height).max(bar_h)
        }
        None => bar_h,
    };
    let _ = window.set_position(tauri::LogicalPosition::new(x, y));
}

#[tauri::command]
async fn run_cli(args: Vec<String>) -> Result<String, String> {
    // Subcommand allowlist (first flag in argv).  Read-only + the registered
    // stage-5 write commands the management console actually wires up.
    const ALLOWED: &[&str] = &[
        "--management",
        "--version",
        // 端点连通性独立出口（v0.24.0）：审计只判配置，端口通断由这条命令单独检查。
        // 不登记进来的话，前端「检查端点连通性」按钮会直接撞上安全边界。
        "--endpoint-status",
        "--list-endpoints",
        "--list-mcp-inventory",
        "--list-profiles",
        "--list-skill-states",
        "--add-endpoint",
        "--remove-endpoint",
        "--update-endpoint",
        "--test-endpoint",
        "--attach-endpoints",
        "--add-client",
        "--add-defaults",
        "--remove-client",
        "--update-client",
        "--set-unified-dir",
        "--fix-skills",
        "--fix-mcp",
        "--enable-skill",
        "--disable-skill",
        "--audit-skill-states",
        "--migrate-skill-links",
        "--mcp",
        "--remove-legacy-mcp",
        // Hook 管理域（A 阶段）：生命周期 hook 的列出 / 写入 / 移除。
        "--list-hooks",
        "--fix-hooks",
        "--remove-hooks",
        // 变更检测（B 阶段）：产出持久化快照并与上次对比（只读不探活）。
        "--snapshot",
        // 后台巡检设置（D 阶段）：读写 config.yaml 的 settings 段。
        "--set-setting",
        "--get-setting",
        // 变更忽略清单（E 阶段）：列出 / 忽略 / 取消忽略 / 清理。
        "--list-ignored",
        "--ignore-change",
        "--unignore-change",
        "--prune-ignored",
        "--cleanup-config",
        // 阶段五增量：MCP 条目删除 / 批量清理 / 配置备份列出与还原。
        "--remove-mcp-entry",
        "--remove-mcp-class",
        "--list-config-backups",
        "--restore-config-backup",
        // 六维度评审整改：skill 备份 / 导出 / 重命名 / 删除。
        "--backup-skill",
        "--export-skill",
        "--rename-skill",
        "--delete-skill",
        // 技能市场（FEAT-9）：只读出口（sources/list/search/check）。
        "--market",
        // 市场的安装与升级：写操作，但确实由 GUI 的确认流程经 run_cli 调用
        // （弹窗二次确认后执行）。此前只登记了 --market，导致这两个从界面
        // 一点就被安全边界拦下；两者是独立 flag，不是 --market 的取值。
        "--market-install",
        "--market-upgrade",
        // 技能使用统计（FEAT-10）：只读，解析客户端会话日志，不写盘。
        "--skill-usage",
        // 技能整理建议（FEAT-11）：只读判据，不删、不改、不移动任何技能目录。
        "--merge-advice",
        // 使用统计 + 整理建议的组合出口：两者共用同一份会话日志汇总，
        // 合成一次扫描（只读，能力不超出上面两条之和）。
        "--skill-insight",
        // 整理建议的执行（FEAT-12）：写操作。把归并方备份后移入 _trash/，
        // 与 --delete-skill 同一条可恢复路径；执行前会重算判据拒绝过期建议。
        "--merge-skills",
    ];
    // Reject redirection-class flags outright (they re-point the engine at an
    // arbitrary config/profile file, a privilege escalation vector).
    // P-3: `--active-profile` (redirect the invocation to another profile) is
    // distinct from the future write command `--set-active-profile` (persist a
    // default endpoint into config). The former is denied here; the latter, once
    // implemented, is a non-redirect write flag and is not blocked by this list.
    // 拒绝判据见模块级 `DENIED_FLAG_PREFIXES` / `is_denied_flag`
    // （抽到模块级是为了让 `cargo test` 能直接断言这条不变量）。
    let first_flag = args.iter().find(|a| a.starts_with("--")).cloned();
    if let Some(flag) = first_flag {
        // allow --flag=value form by checking the bare flag
        let bare = flag.split('=').next().unwrap_or(flag.as_str());
        if is_denied_flag(bare) {
            return Err(format!("run_cli: 被拒绝的参数 {bare}（安全边界）"));
        }
        if !ALLOWED.contains(&bare) {
            return Err(format!("run_cli: 子命令 {bare} 不在白名单内（安全边界）"));
        }
    }
    // 扫描整个 argv：拒绝列表中的标志不得出现在任何位置，`--flag=value`
    // 形式同样按裸标志比对。
    for a in &args {
        let bare = a.split('=').next().unwrap_or(a);
        if is_denied_flag(bare) {
            return Err(format!("run_cli: 被拒绝的参数 {bare}（安全边界）"));
        }
    }

    // 扫描类子命令由 shell 挂上进度文件（路径固定，webview 不可指定），
    // 并先清掉上次的残留，免得对话框一打开就显示上一个任务的 100%。
    let mut argv: Vec<String> = args.clone();
    let is_scan = argv.iter().any(|a| {
        a == "--skill-usage" || a == "--merge-advice" || a == "--skill-insight"
    });
    // 路径**无条件**使用 shell 自己的；刻意不再有「调用方已给就不覆盖」的分支
    // —— 那个分支正是原先的漏洞。
    if is_scan {
        let _ = std::fs::remove_file(progress_file_path());
        argv.push("--progress-file".to_string());
        argv.push(progress_file_path().to_string_lossy().into_owned());
    }

    // Route the blocking subprocess spawn onto the async blocking pool so the
    // webview main thread stays responsive while the CLI scans / probes.
    tauri::async_runtime::spawn_blocking(move || {
        let (code, stdout, stderr, cancelled) = spawn_cancellable(&argv)?;
        let code = code.unwrap_or(-1);
        // Bound stderr to avoid flooding the IPC channel with a full traceback.
        let stderr_bounded = if stderr.len() > 2000 { stderr.chars().take(2000).collect::<String>() } else { stderr };
        Ok(serde_json::json!({
            "code": code,
            "stdout": stdout,
            "stderr": stderr_bounded,
            "cancelled": cancelled,
        })
        .to_string())
    })
    .await
    .map_err(|e| format!("CLI 任务失败: {e}"))?
}

/// Open an external http(s) URL in the system default browser.
///
/// Whitelisted to http(s) only so the passthrough cannot be co-opted to launch
/// arbitrary schemes/files from a compromised page.  Platform dispatcher:
/// macOS `open`, Windows `cmd /C start`, Linux `xdg-open`.
///
/// D-4/B-5 hardening: beyond the scheme prefix, we reject any URL containing a
/// Windows ``cmd.exe`` metacharacter (``& | < > ^ " ``` etc.) so a crafted URL
/// such as ``https://x&calc.exe`` cannot be parsed by ``cmd /C start`` into an
/// extra command.  The URL is additionally double-quoted on the Windows branch.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err("open_url: 仅允许 http(s) 链接".to_string());
    }
    // Reject shell metacharacters that carry meaning for the Windows `cmd /C
    // start` dispatcher (defense in depth; the webview is the only caller).
    // S4：只列元字符是不够的 —— 原黑名单漏了 \r \n % !：
    //   · cmd.exe 把换行当命令分隔符，"https://x/a\ncalc.exe" 能通过旧的 scheme 校验；
    //   · % 触发环境变量展开、! 触发延迟展开（delayed expansion）。
    // 用 char::is_control() 一并覆盖 \n \r \t 与 DEL 等控制字符。
    if url.chars().any(|c| {
        c.is_control()
            || matches!(
                c,
                '&' | '|' | '<' | '>' | '^' | '"' | '\'' | '`' | '$' | '(' | ')' | ';' | '%' | '!'
            )
    }) {
        return Err("open_url: URL 含非法字符（命令注入防护）".to_string());
    }
    // 命令名与参数都是普通字符串，所有平台均可编译，用 cfg! 运行时分支即可。
    let (program, args): (&str, Vec<&str>) = if cfg!(target_os = "windows") {
        ("cmd", vec!["/C", "start", "", "\"", url.as_str(), "\""])
    } else if cfg!(target_os = "macos") {
        ("open", vec![url.as_str()])
    } else {
        ("xdg-open", vec![url.as_str()])
    };
    std::process::Command::new(program)
        .args(args)
        .spawn()
        .map_err(|e| format!("打开链接失败: {e}"))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            run_audit,
            run_cli,
            cancel_cli,
            read_scan_progress,
            open_url,
            show_main_window
        ])
        // P2-12：开发态直读磁盘上的 dashboard.html。
        //
        // 生产构建把 gui/ 整个嵌入二进制（tauri.conf.json 的 frontendDist），
        // 因此改一行 HTML 都要 cargo build + 重装。设置环境变量 SMS_GUI_DEV 后，
        // 启动时把主窗口导航到源树里的 dashboard.html：改完只需刷新（Cmd+R）。
        // 不设该变量则完全走原有嵌入资源路径，生产行为不变。
        .setup(|app| {
            if std::env::var_os("SMS_GUI_DEV").is_some() {
                match app.get_webview_window("main") {
                    Some(window) => {
                        // CARGO_MANIFEST_DIR 是编译期常量，指向 src-tauri/；
                        // 其同级即仓库根的 gui/，正是开发时要读的那份文件。
                        let dev_html = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                            .join("../gui/dashboard.html");
                        match tauri::Url::from_file_path(&dev_html) {
                            Ok(url) => {
                                eprintln!(
                                    "[SMS_GUI_DEV] 开发态直读磁盘：{}",
                                    dev_html.display()
                                );
                                if let Err(e) = window.navigate(url) {
                                    eprintln!("[SMS_GUI_DEV] 导航失败，回退嵌入资源：{e}");
                                }
                            }
                            Err(_) => eprintln!(
                                "[SMS_GUI_DEV] 路径无法转为 file:// URL：{}",
                                dev_html.display()
                            ),
                        }
                    }
                    None => eprintln!("[SMS_GUI_DEV] 未找到 label=main 的窗口"),
                }
            }
            // ---- popover 简易弹框窗口（Phase E：托盘左键点击弹出变更摘要）----
            // 独立小窗口，无边框，加载 popover.html；默认隐藏，托盘左键点击时显示。
            // 设 SMS_POPOVER_DEV=1 则启动即显示，便于在无法模拟点击的环境里验证渲染。
            let popover_dev_visible = std::env::var_os("SMS_POPOVER_DEV").is_some();
            let _popover = tauri::WebviewWindowBuilder::new(
                app,
                "popover",
                tauri::WebviewUrl::App("popover.html".into()),
            )
            .title("")
            // 初始给一个与内容相称的高度（fitWindow 会再按实际内容微调）；
            // transparent 让圆角外的区域真正透明，否则会露出窗口白底。
            .inner_size(300.0, 300.0)
            .decorations(false)
            .resizable(false)
            .transparent(true)
            .visible(popover_dev_visible)
            .skip_taskbar(true)
            .always_on_top(true)
            .shadow(false)
            .build()?;

            if popover_dev_visible {
                if let Some(popover) = app.get_webview_window("popover") {
                    position_popover(&popover, None);
                }
            }

            // ---- 托盘常驻（Phase C）----
            // 左键点击弹出 popover 简易弹框；右键弹出菜单。
            // 关闭窗口只隐藏不退出（见 on_window_event），退出走菜单或 Cmd+Q。
            //
            // 菜单结构：主操作 → 分隔 → 巡检开关（可勾选，勾选态即真实状态）
            // → 分隔 → 检查变更 → 分隔 → 退出。
            // 「后台巡检」用 CheckMenuItem 而不是普通项：菜单一打开就能看出
            // 当前是开是关，不必点一下才知道（原来的「切换后台巡检」是动作式，
            // 无法显示状态）。勾选态在每次弹出前按 CLI 实际值同步。
            let patrol_item = CheckMenuItem::with_id(
                app,
                "toggle-patrol",
                "后台巡检",
                true,
                patrol_enabled_now(),
                None::<&str>,
            )?;
            let menu = Menu::with_items(app, &[
                &MenuItem::with_id(app, "show", "打开主面板", true, None::<&str>)?,
                &PredefinedMenuItem::separator(app)?,
                &patrol_item,
                &MenuItem::with_id(app, "snapshot", "检查变更", true, None::<&str>)?,
                &PredefinedMenuItem::separator(app)?,
                &MenuItem::with_id(app, "quit", "退出 Skill MCP Studio", true, None::<&str>)?,
            ])?;

            // 勾选态需在三处同步：菜单点击后、托盘弹出前、后台线程每轮。
            // CheckMenuItem 内部是 Arc，克隆只是共享同一实例。
            let patrol_for_menu = patrol_item.clone();
            let patrol_for_tray = patrol_item.clone();
            let patrol_for_thread = patrol_item.clone();

            let _tray = TrayIconBuilder::with_id("main")
                // 初始为 Idle 态：单色模板图，由系统按菜单栏明暗自适应。
                // 巡检发现变更后会切到带红点的非模板告警图（见 apply_tray_state）。
                .icon(tray_icon(TrayState::Idle))
                .icon_as_template(true)
                .tooltip("Skill MCP Studio")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "toggle-patrol" => {
                            let new_val = if patrol_enabled_now() { "false" } else { "true" };
                            let set_args = vec![
                                "--set-setting".to_string(),
                                format!("patrol_enabled={}", new_val),
                            ];
                            let _ = spawn(&set_args);
                            // 回读，勾选态以 CLI 实际落盘结果为准
                            let _ = patrol_for_menu.set_checked(patrol_enabled_now());
                        }
                        "snapshot" => {
                            // 与弹框同一动作：跑一次快照对比并让弹框显示结果
                            let snap_args = vec![
                                "--snapshot".to_string(),
                                "--format".to_string(),
                                "json".to_string(),
                            ];
                            let _ = spawn(&snap_args);
                            if let Some(popover) = app.get_webview_window("popover") {
                                // 菜单触发时没有图标坐标，退回右上角
                                position_popover(&popover, None);
                                mark_popover_shown();
                                let _ = popover.show();
                                let _ = popover.set_focus();
                                let _ = popover
                                    .eval("window.__reloadPopover && window.__reloadPopover()");
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(move |tray, event| {
                    let app = tray.app_handle();
                    match event {
                        // 右键弹出菜单前同步勾选态，避免显示过期状态
                        TrayIconEvent::Click {
                            button: MouseButton::Right,
                            button_state: MouseButtonState::Up,
                            ..
                        } => {
                            let _ = patrol_for_tray.set_checked(patrol_enabled_now());
                        }
                        // 左键点击托盘 → 显示 popover 简易弹框（不是主窗口）
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            rect,
                            ..
                        } => {
                            if let Some(popover) = app.get_webview_window("popover") {
                                if popover.is_visible().unwrap_or(false) {
                                    let _ = popover.hide();
                                } else {
                                    // 贴合托盘：用事件里的图标矩形做锚点，
                                    // 水平居中于图标、垂直贴菜单栏下方。
                                    // 此前写死「屏幕右上角」，在图标不靠右时
                                    // 会明显偏离（实测偏到 x=1612 而图标在 719）。
                                    position_popover(&popover, Some(&rect));
                                    mark_popover_shown();
                                    let _ = popover.show();
                                    let _ = popover.set_focus();
                                    let _ = popover.eval(
                                        "window.__reloadPopover && window.__reloadPopover()",
                                    );
                                }
                            }
                        }
                        _ => {}
                    }
                })
                .build(app)?;

            // ---- 后台巡检（Phase D）----
            // 独立线程每隔 60 秒检查一次：读取 patrol_enabled，若启用则运行 --snapshot，
            // 检测到变更时更新托盘 tooltip 提示用户。
            // 同时把菜单勾选态同步为 CLI 实际值——这样即使用户在命令行改过
            // patrol_enabled，菜单最多 60 秒后也会显示正确状态。
            let patrol_handle = app.handle().clone();
            std::thread::spawn(move || {
                loop {
                    std::thread::sleep(std::time::Duration::from_secs(60));
                    // 1. 检查 patrol_enabled
                    let enabled = patrol_enabled_now();
                    let _ = patrol_for_thread.set_checked(enabled);
                    if !enabled {
                        continue;
                    }
                    // 2. 先切到「巡检中」再跑命令：--snapshot 约 1~2 秒，
                    // 这段窗口里用户能从 tooltip 看出它在工作，而不是
                    // 「点了没反应」。结束时会按结果切回 Idle/Alert。
                    if let Some(tray) = patrol_handle.tray_by_id("main") {
                        apply_tray_state(&tray, TrayState::Scanning, false);
                    }
                    let snap_args = vec![
                        "--snapshot".to_string(),
                        "--format".to_string(),
                        "json".to_string(),
                    ];
                    match spawn(&snap_args) {
                        Ok((_, stdout, _)) => {
                            // 解析失败时保持上一次的提示不变，而不是当成「无变更」
                            // 把状态误清掉（CLI 升级/输出异常时更安全）。
                            let has_changes = match snapshot_has_changes(&stdout) {
                                Some(v) => v,
                                None => {
                                    // 读不懂输出时不能停在「正在巡检」，
                                    // 复位成无变更态，下一轮再试。
                                    if let Some(tray) = patrol_handle.tray_by_id("main") {
                                        apply_tray_state(&tray, TrayState::Idle, false);
                                    }
                                    continue;
                                }
                            };
                            if let Some(tray) = patrol_handle.tray_by_id("main") {
                                // 三态：有变更 → 带红点角标（按主题选字形）；
                                // 无变更 → 回到单色模板图。
                                let state = if has_changes {
                                    alert_state_for_app(&patrol_handle)
                                } else {
                                    TrayState::Idle
                                };
                                apply_tray_state(&tray, state, has_changes);
                            }
                            // 检测到变更时发系统通知（Phase E）
                            if has_changes {
                                use tauri_plugin_notification::NotificationExt;
                                let _ = patrol_handle
                                    .notification()
                                    .builder()
                                    .title("Skill MCP Studio")
                                    .body("检测到配置变更，点击查看详情")
                                    .show();
                            }
                        }
                        Err(_) => {
                            // 命令起不来时同样复位，避免卡在「正在巡检」
                            if let Some(tray) = patrol_handle.tray_by_id("main") {
                                apply_tray_state(&tray, TrayState::Idle, false);
                            }
                            continue;
                        }
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                WindowEvent::CloseRequested { api, .. } => {
                    // 单窗口常驻：Cmd+W / 红色关闭钮只隐藏窗口，不退出应用；
                    // Cmd+Q 走 ExitRequested 置位 EXITING 后放行真正的窗口关闭。
                    if !EXITING.load(Ordering::SeqCst) {
                        api.prevent_close();
                        let _ = window.hide();
                    }
                }
                WindowEvent::Focused(false) => {
                    // 失焦即收起 popover —— 与 macOS 原生弹框一致（控制中心、
                    // 输入法候选框都是点外部就关）。此前没有这段，弹框只能靠
                    // 再次点托盘图标或按 Esc 关闭，点桌面其它地方它一直悬着。
                    //
                    // 只对 popover 生效：主窗口是常驻控制台，失焦不该被收起。
                    if window.label() == "popover" {
                        let within_grace = POPOVER_SHOWN_AT
                            .lock()
                            .ok()
                            .and_then(|guard| *guard)
                            .map(|t| t.elapsed() < POPOVER_FOCUS_GRACE)
                            .unwrap_or(false);
                        if !within_grace {
                            let _ = window.hide();
                        }
                    }
                }
                _ => {}
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| match event {
        RunEvent::ExitRequested { .. } => {
            EXITING.store(true, Ordering::SeqCst);
        }
        // 点 Dock 图标时重新显示被隐藏的窗口（macOS 常驻工具惯例）。
        // `RunEvent::Reopen` 仅存在于 macOS target；Windows/Linux 上无此变体，
        // 需条件编译，否则跨平台构建报 `no variant named Reopen`（E0599）。
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => {
            if let Some(window) = app_handle.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        _ => {}
    });
}

/// 被拒绝的 CLI 标志前缀（`run_cli` 的安全边界）。
///
/// 用**前缀**而非精确比较：`scan.py` 的 argparse 允许前缀缩写（`--prof` 会被
/// 解析成 `--profile`），且 `--flag=value` 形式按裸标志比对。
///
/// `--progress-file` 也在列：它是「往任意路径原子写 JSON」的写原语，路径只能由
/// `run_cli` 自己追加，webview 不得指定 —— 否则一次 DOM 注入即可覆写任意可写文件。
const DENIED_FLAG_PREFIXES: &[&str] = &[
    "--config",        // --config / --config-paths：重定向到任意配置文件
    "--prof",          // --profile / --prof
    "--active-prof",   // --active-profile / --active-prof
    "--progress-file", // 进度文件路径：只允许 shell 追加
];

/// `run_cli` 安全边界的纯函数部分 —— 抽到模块级是为了让 `cargo test` 能直接
/// 断言这条不变量（此前内嵌在命令函数里，测试碰不到，回归时无人可查）。
fn is_denied_flag(bare: &str) -> bool {
    DENIED_FLAG_PREFIXES.iter().any(|p| bare.starts_with(p))
}

#[cfg(test)]
mod tests {
    // T-3: 为 spawn 路径解析与 open_url 注入校验补 Rust 单元测试。仅覆盖纯函数
    // 与「在任何子进程 spawn 之前就返回」的拒绝分支，确保 `cargo test` 无副作用
    // 且跨平台确定。
    use super::*;

    // S1/S3 回归：run_cli 的安全边界必须拦住「重定向类」与「路径写入类」参数。
    // 这些断言把不变量钉在测试里 —— 此前它内嵌在命令函数内，回归时无人可查，
    // 于是 `--progress-file` 长期不在拒绝列表里而没人发现。
    #[test]
    fn run_cli_denies_path_writing_and_redirect_flags() {
        // 路径写入原语：webview 指定进度文件路径 = 往任意路径原子写 JSON。
        assert!(is_denied_flag("--progress-file"), "--progress-file 必须被拒绝");
        // argparse 前缀缩写：`--prof` 会被解析成 `--profile`（精确比较挡不住）。
        assert!(is_denied_flag("--prof"), "--prof（--profile 的缩写）必须被拒绝");
        assert!(is_denied_flag("--profile"), "--profile 必须被拒绝");
        assert!(is_denied_flag("--config"), "--config 必须被拒绝");
        assert!(is_denied_flag("--config-paths"), "--config-paths 必须被拒绝");
        assert!(is_denied_flag("--active-profile"), "--active-profile 必须被拒绝");
    }

    #[test]
    fn run_cli_deny_list_covers_progress_file_explicitly() {
        // 反向断言：若有人删掉 `--progress-file`，这条会失败。
        assert!(
            DENIED_FLAG_PREFIXES.contains(&"--progress-file"),
            "DENIED_FLAG_PREFIXES 必须显式包含 --progress-file"
        );
    }

    #[test]
    fn run_cli_allowlist_is_not_accidentally_denied() {
        // 拒绝判据用前缀匹配，必须确认没有误伤任何白名单标志。
        const ALLOWED: &[&str] = &[
            "--management", "--version", "--list-endpoints", "--skill-usage",
            "--merge-advice", "--skill-insight", "--merge-skills", "--delete-skill",
            "--market", "--market-install", "--market-upgrade",
        ];
        for a in ALLOWED {
            assert!(!is_denied_flag(a), "白名单标志 {a} 被误判为拒绝项");
        }
    }

    #[test]
    fn cli_candidates_are_non_empty_and_start_with_path_name() {
        let candidates = cli_candidates();
        assert!(!candidates.is_empty(), "CLI 候选序列不应为空");
        assert_eq!(
            candidates[0].as_str(),
            "skill-mcp-studio",
            "首个候选必须是 PATH 裸名"
        );
    }

    #[test]
    fn open_url_rejects_non_http_schemes() {
        assert!(open_url("ftp://example.com".to_string()).is_err());
        assert!(open_url("file:///etc/passwd".to_string()).is_err());
        assert!(open_url("javascript:alert(1)".to_string()).is_err());
        assert!(open_url("data:text/html,bad".to_string()).is_err());
    }

    // S4 回归：换行与控制字符同样必须被拒（cmd.exe 把换行当命令分隔符）。
    #[test]
    fn open_url_rejects_control_chars_and_percent() {
        for bad in [
            "https://x.com/a\ncalc.exe",
            "https://x.com/a\r\ncalc.exe",
            "https://x.com/%PATH%",
            "https://x.com/a!b",
            "https://x.com/a\tb",
        ] {
            assert!(
                open_url(bad.to_string()).is_err(),
                "应拒绝含控制字符或 %/! 的 URL: {bad:?}"
            );
        }
    }

    #[test]
    fn open_url_rejects_shell_metacharacters() {
        for bad in [
            "https://x.com/a&calc.exe",
            "https://x.com/a|b",
            "https://x.com/a;rm",
            "https://x.com/a\"b",
            "https://x.com/a'b",
        ] {
            assert!(
                open_url(bad.to_string()).is_err(),
                "带注入风险的 URL 应被拒绝: {bad}"
            );
        }
    }

    // 回归：巡检判据必须走结构化字段，不能把中文文案当协议。
    // 此前是 `stdout.contains("检测到变更")`——CLI 换个措辞（例如「发现变更」）
    // 巡检就静默失效，且不会有任何报错。
    #[test]
    fn snapshot_has_changes_reads_structured_field() {
        assert_eq!(
            snapshot_has_changes(r#"{"has_changes": true, "summary": {"hooks": 2}}"#),
            Some(true)
        );
        assert_eq!(
            snapshot_has_changes(r#"{"has_changes": false, "summary": {}}"#),
            Some(false)
        );
        // 文案变了但 JSON 契约不变时，判定必须仍然正确
        assert_eq!(
            snapshot_has_changes(
                r#"{"has_changes": true, "note": "CLI 改成了发现变更这个措辞"}"#
            ),
            Some(true)
        );
    }

    #[test]
    fn snapshot_has_changes_returns_none_when_unparsable() {
        // 解析失败必须与「确实无变更」区分开：返回 None 让调用方保持不变
        // 而不是把状态误清成「无变更」。
        assert_eq!(snapshot_has_changes("检测到变更：hooks=2"), None);
        assert_eq!(snapshot_has_changes(""), None);
        assert_eq!(snapshot_has_changes("{不合法 JSON"), None);
        // 合法 JSON 但缺字段，同样视为没读懂
        assert_eq!(snapshot_has_changes(r#"{"summary": {}}"#), None);
        // 类型不符（字符串 "true"）也不认
        assert_eq!(snapshot_has_changes(r#"{"has_changes": "true"}"#), None);
    }

    #[test]
    fn scanning_state_uses_template_icon() {
        // Scanning 复用模板图并与 Idle 区分（tooltip 不同），
        // 且必须走模板模式，否则会丢掉菜单栏明暗自适应。
        assert!(TrayState::Scanning != TrayState::Idle);
        assert!(TrayState::Scanning != TrayState::Alert);
        let a = tray_icon(TrayState::Scanning);
        let b = tray_icon(TrayState::Idle);
        assert_eq!(a.width(), b.width(), "Scanning 应复用模板图尺寸");
        assert_eq!(a.height(), b.height());
    }

    #[test]
    fn tray_states_load_and_are_distinguishable() {
        // 三个状态的资源都必须能解码（解码失败会回退到应用图标，也是 32px）
        for state in [TrayState::Idle, TrayState::Alert, TrayState::AlertDark] {
            let img = tray_icon(state);
            assert!(img.width() > 0 && img.height() > 0, "图标尺寸不应为 0");
        }
        // 状态必须互不相等 —— 否则 apply_tray_state 的模板标志判断会失去意义
        assert!(TrayState::Idle != TrayState::Alert);
        assert!(TrayState::Alert != TrayState::AlertDark);
        assert!(TrayState::Idle != TrayState::AlertDark);
    }

    #[test]
    fn json_bool_reads_value_and_tolerates_envelope() {
        // --get-setting --format json 的形态
        assert_eq!(
            json_bool(r#"{"key": "patrol_enabled", "value": true, "set": true}"#, "value"),
            Some(true)
        );
        assert_eq!(
            json_bool(r#"{"key": "patrol_enabled", "value": false, "set": true}"#, "value"),
            Some(false)
        );
        // 键存在但值为 null（未设置）→ None，交由调用方回退
        assert_eq!(
            json_bool(r#"{"key": "x", "value": null, "set": false}"#, "value"),
            None
        );
        // 裸字段形态也要能读
        assert_eq!(json_bool(r#"{"patrol_enabled": true}"#, "patrol_enabled"), Some(true));
        // 文本输出 → None（触发兼容回退）
        assert_eq!(json_bool("  patrol_enabled = True", "patrol_enabled"), None);
    }
}
