// Prevents a console window opening alongside the app on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod vault;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            vault::list_notes,
            vault::read_note,
            vault::write_note,
            vault::rename_note,
            vault::delete_note,
            vault::read_sync_state,
            vault::write_sync_state,
            vault::load_settings,
            vault::save_settings,
            vault::default_vault,
        ])
        .run(tauri::generate_context!())
        .expect("WikiForge failed to start");
}
