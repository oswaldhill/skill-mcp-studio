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

/// 置位后表示应用正在退出（Cmd+Q / ExitRequested），此时放行窗口关闭；
/// 否则单窗口的 CloseRequested（Cmd+W / 红色关闭钮）只隐藏窗口，不退出。
static EXITING: AtomicBool = AtomicBool::new(false);

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
#[tauri::command]
async fn run_cli(args: Vec<String>) -> Result<String, String> {
    // Subcommand allowlist (first flag in argv).  Read-only + the registered
    // stage-5 write commands the management console actually wires up.
    const ALLOWED: &[&str] = &[
        "--management",
        "--version",
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
    if url.chars().any(|c| matches!(c, '&' | '|' | '<' | '>' | '^' | '"' | '\'' | '`' | '$' | '(' | ')' | ';')) {
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
        .invoke_handler(tauri::generate_handler![
            run_audit,
            run_cli,
            cancel_cli,
            read_scan_progress,
            open_url
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
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // 单窗口常驻：Cmd+W / 红色关闭钮只隐藏窗口，不退出应用；
                // Cmd+Q 走 ExitRequested 置位 EXITING 后放行真正的窗口关闭。
                if !EXITING.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.hide();
                }
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
}
