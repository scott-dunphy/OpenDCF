#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};

fn is_repo_root(path: &Path) -> bool {
    path.join("src").join("main.py").exists() && path.join(".venv").exists()
}

fn search_ancestors_for_repo(start: &Path) -> Option<PathBuf> {
    for ancestor in start.ancestors() {
        if is_repo_root(ancestor) {
            return Some(ancestor.to_path_buf());
        }
    }
    None
}

fn find_repo_root() -> Option<PathBuf> {
    if let Ok(from_env) = std::env::var("OPENDCF_REPO_ROOT") {
        let p = PathBuf::from(from_env);
        if is_repo_root(&p) {
            return Some(p);
        }
    }

    if let Some(from_build) = option_env!("OPENDCF_REPO_ROOT_BUILD") {
        let p = PathBuf::from(from_build);
        if is_repo_root(&p) {
            return Some(p);
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        if let Some(p) = search_ancestors_for_repo(&cwd) {
            return Some(p);
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            if let Some(p) = search_ancestors_for_repo(parent) {
                return Some(p);
            }
        }
    }

    None
}

fn python_path(repo_root: &Path) -> PathBuf {
    if cfg!(target_os = "windows") {
        repo_root.join(".venv").join("Scripts").join("python.exe")
    } else {
        repo_root.join(".venv").join("bin").join("python")
    }
}

fn start_backend(repo_root: &Path) -> Result<Child, String> {
    let python = python_path(repo_root);
    if !python.exists() {
        return Err(format!("Python runtime not found at {}", python.to_string_lossy()));
    }

    Command::new(python)
        .args([
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8011",
        ])
        .current_dir(repo_root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to start backend: {e}"))
}

fn main() {
    let mut backend_child = match find_repo_root() {
        Some(repo_root) => match start_backend(&repo_root) {
            Ok(child) => Some(child),
            Err(err) => {
                eprintln!("[OpenDCF Desktop] {err}");
                None
            }
        },
        None => {
            eprintln!("[OpenDCF Desktop] Could not locate repository root; backend not started.");
            None
        }
    };

    tauri::Builder::default()
        .build(tauri::generate_context!())
        .expect("error while building OpenDCF desktop shell")
        .run(move |_app_handle, event| {
            if matches!(event, tauri::RunEvent::ExitRequested { .. }) {
                if let Some(child) = backend_child.as_mut() {
                    let _ = child.kill();
                }
            }
        });
}
