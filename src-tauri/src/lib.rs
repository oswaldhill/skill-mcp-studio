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

use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};

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
        // 安装与升级不经此通道：它们需要二次确认，且属于写操作。
        "--market",
        // 技能使用统计（FEAT-10）：只读，解析客户端会话日志，不写盘。
        "--skill-usage",
        // 技能整理建议（FEAT-11）：只读判据，不删、不改、不移动任何技能目录。
        "--merge-advice",
    ];
    // Reject redirection-class flags outright (they re-point the engine at an
    // arbitrary config/profile file, a privilege escalation vector).
    // P-3: `--active-profile` (redirect the invocation to another profile) is
    // distinct from the future write command `--set-active-profile` (persist a
    // default endpoint into config). The former is denied here; the latter, once
    // implemented, is a non-redirect write flag and is not blocked by this list.
    const DENIED_FLAGS: &[&str] = &["--config", "--profile", "--active-profile"];

    let first_flag = args.iter().find(|a| a.starts_with("--")).cloned();
    if let Some(flag) = first_flag {
        if DENIED_FLAGS.contains(&flag.as_str()) {
            return Err(format!("run_cli: 被拒绝的重定向参数 {flag}（安全边界）"));
        }
        let sub = flag.as_str();
        // allow --flag=value form by checking the bare flag
        let bare = sub.split('=').next().unwrap_or(sub);
        if !ALLOWED.contains(&bare) {
            return Err(format!("run_cli: 子命令 {bare} 不在白名单内（安全边界）"));
        }
    }
    // Also scan the whole argv for denied flags appearing later (e.g. appended).
    for a in &args {
        let bare = a.split('=').next().unwrap_or(a);
        if DENIED_FLAGS.contains(&bare) {
            return Err(format!("run_cli: 被拒绝的重定向参数 {bare}（安全边界）"));
        }
    }

    // Route the blocking subprocess spawn onto the async blocking pool so the
    // webview main thread stays responsive while the CLI scans / probes.
    tauri::async_runtime::spawn_blocking(move || {
        let (code, stdout, stderr) = spawn(&args)?;
        let code = code.unwrap_or(-1);
        // Bound stderr to avoid flooding the IPC channel with a full traceback.
        let stderr_bounded = if stderr.len() > 2000 { stderr.chars().take(2000).collect::<String>() } else { stderr };
        Ok(serde_json::json!({
            "code": code,
            "stdout": stdout,
            "stderr": stderr_bounded,
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
        .invoke_handler(tauri::generate_handler![run_audit, run_cli, open_url])
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

#[cfg(test)]
mod tests {
    // T-3: 为 spawn 路径解析与 open_url 注入校验补 Rust 单元测试。仅覆盖纯函数
    // 与「在任何子进程 spawn 之前就返回」的拒绝分支，确保 `cargo test` 无副作用
    // 且跨平台确定。
    use super::*;

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