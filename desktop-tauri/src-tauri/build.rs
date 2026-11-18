fn main() {
    if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
        let repo_root = std::path::Path::new(&manifest_dir)
            .join("..")
            .join("..")
            .canonicalize();
        if let Ok(path) = repo_root {
            println!(
                "cargo:rustc-env=OPENDCF_REPO_ROOT_BUILD={}",
                path.to_string_lossy()
            );
        }
    }
    tauri_build::build()
}
