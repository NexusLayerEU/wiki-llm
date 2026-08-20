//! The local vault: notes as plain .md files on disk.
//!
//! Notes are files, not rows in a database the app owns. That is the whole point of
//! being local-first: the user can open the folder in any editor, back it up, put it
//! in git, or stop using this app entirely without losing anything.
//!
//! Layout:
//!   <vault>/<project-slug>/note-name.md
//!   <vault>/<project-slug>/.wikiforge-sync.json   sync state, per project

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Component, Path, PathBuf};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Note {
    pub name: String,
    pub path: String,
    pub size: u64,
    pub hash: String,
    /// Seconds since the epoch, so the UI can sort by recency without a date crate.
    pub modified: u64,
}

/// Refuse anything that could climb out of the vault.
///
/// Note names reach here from the UI and from a server response, so neither is
/// trusted. Rejecting separators and `..` outright is simpler to reason about than
/// canonicalising and comparing prefixes, and a note name has no business
/// containing either.
fn safe_name(name: &str) -> Result<String, String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err("A note needs a name.".into());
    }
    if trimmed.len() > 180 {
        return Err("That name is too long.".into());
    }
    let candidate = Path::new(trimmed);
    if candidate.components().count() != 1
        || candidate
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
    {
        return Err("A note name cannot contain slashes or '..'.".into());
    }
    if trimmed.starts_with('.') {
        return Err("A note name cannot start with a dot.".into());
    }
    let with_ext = if trimmed.to_lowercase().ends_with(".md") {
        trimmed.to_string()
    } else {
        format!("{trimmed}.md")
    };
    Ok(with_ext)
}

fn hash_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn project_dir(vault: &str, project: &str) -> Result<PathBuf, String> {
    let slug = safe_slug(project)?;
    let dir = PathBuf::from(vault).join(slug);
    fs::create_dir_all(&dir).map_err(|e| format!("Could not open {}: {e}", dir.display()))?;
    Ok(dir)
}

fn safe_slug(slug: &str) -> Result<String, String> {
    if slug.is_empty()
        || slug.contains('/')
        || slug.contains('\\')
        || slug.contains("..")
    {
        return Err("That project folder name is not valid.".into());
    }
    Ok(slug.to_string())
}

fn seconds(path: &Path) -> u64 {
    fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

#[tauri::command]
pub fn list_notes(vault: String, project: String) -> Result<Vec<Note>, String> {
    let dir = project_dir(&vault, &project)?;
    let mut notes = Vec::new();

    for entry in fs::read_dir(&dir).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let is_md = path
            .extension()
            .map(|e| e.eq_ignore_ascii_case("md"))
            .unwrap_or(false);
        if !is_md {
            continue;
        }
        let bytes = match fs::read(&path) {
            Ok(b) => b,
            Err(_) => continue, // a file we cannot read is skipped, not fatal
        };
        notes.push(Note {
            name: path.file_name().unwrap_or_default().to_string_lossy().into(),
            path: path.to_string_lossy().into(),
            size: bytes.len() as u64,
            hash: hash_bytes(&bytes),
            modified: seconds(&path),
        });
    }

    notes.sort_by(|a, b| b.modified.cmp(&a.modified));
    Ok(notes)
}

#[tauri::command]
pub fn read_note(vault: String, project: String, name: String) -> Result<String, String> {
    let path = project_dir(&vault, &project)?.join(safe_name(&name)?);
    fs::read_to_string(&path).map_err(|e| format!("Could not read {name}: {e}"))
}

#[tauri::command]
pub fn write_note(
    vault: String,
    project: String,
    name: String,
    content: String,
) -> Result<Note, String> {
    let filename = safe_name(&name)?;
    let path = project_dir(&vault, &project)?.join(&filename);

    // Write to a temp file in the same directory, then rename over the target.
    // A crash or full disk mid-write then leaves the previous note intact rather
    // than a half-written one — these are the user's notes.
    let temp = path.with_extension("md.tmp");
    fs::write(&temp, content.as_bytes()).map_err(|e| format!("Could not save {filename}: {e}"))?;
    fs::rename(&temp, &path).map_err(|e| format!("Could not save {filename}: {e}"))?;

    Ok(Note {
        name: filename,
        path: path.to_string_lossy().into(),
        size: content.len() as u64,
        hash: hash_bytes(content.as_bytes()),
        modified: seconds(&path),
    })
}

#[tauri::command]
pub fn rename_note(
    vault: String,
    project: String,
    from: String,
    to: String,
) -> Result<Note, String> {
    let dir = project_dir(&vault, &project)?;
    let old = dir.join(safe_name(&from)?);
    let new_name = safe_name(&to)?;
    let new = dir.join(&new_name);
    if new.exists() {
        return Err(format!("{new_name} already exists."));
    }
    fs::rename(&old, &new).map_err(|e| format!("Could not rename: {e}"))?;
    let bytes = fs::read(&new).unwrap_or_default();
    Ok(Note {
        name: new_name,
        path: new.to_string_lossy().into(),
        size: bytes.len() as u64,
        hash: hash_bytes(&bytes),
        modified: seconds(&new),
    })
}

#[tauri::command]
pub fn delete_note(vault: String, project: String, name: String) -> Result<(), String> {
    let path = project_dir(&vault, &project)?.join(safe_name(&name)?);
    fs::remove_file(&path).map_err(|e| format!("Could not delete {name}: {e}"))
}

/// Per-project sync state, kept beside the notes so moving the folder moves it too.
#[tauri::command]
pub fn read_sync_state(vault: String, project: String) -> Result<String, String> {
    let path = project_dir(&vault, &project)?.join(".wikiforge-sync.json");
    match fs::read_to_string(&path) {
        Ok(text) => Ok(text),
        // No state yet is the normal first-run case, not an error.
        Err(_) => Ok("{}".to_string()),
    }
}

#[tauri::command]
pub fn write_sync_state(vault: String, project: String, state: String) -> Result<(), String> {
    let path = project_dir(&vault, &project)?.join(".wikiforge-sync.json");
    fs::write(&path, state).map_err(|e| format!("Could not save sync state: {e}"))
}

/// Settings live next to the app's own data, not in the vault: the vault is the
/// user's documents and should contain nothing but notes.
fn settings_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    use tauri::Manager;
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("No config directory available: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("settings.json"))
}

#[tauri::command]
pub fn load_settings(app: tauri::AppHandle) -> Result<String, String> {
    let path = settings_path(&app)?;
    Ok(fs::read_to_string(path).unwrap_or_else(|_| "{}".to_string()))
}

#[tauri::command]
pub fn save_settings(app: tauri::AppHandle, settings: String) -> Result<(), String> {
    let path = settings_path(&app)?;
    fs::write(&path, settings).map_err(|e| format!("Could not save settings: {e}"))
}

#[tauri::command]
pub fn default_vault(app: tauri::AppHandle) -> Result<String, String> {
    use tauri::Manager;
    let base = app
        .path()
        .document_dir()
        .or_else(|_| app.path().home_dir())
        .map_err(|e| format!("No home directory available: {e}"))?;
    Ok(base.join("WikiForge").to_string_lossy().into())
}

