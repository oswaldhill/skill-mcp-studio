// Prevents an additional console window on Windows in release; macOS keeps the
// standard entrypoint. The real logic lives in `skill_mcp_studio_lib::run()`.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    skill_mcp_studio_lib::run()
}
