//! Offline, read-only Nix dev-shell inspection. No Nix process is started.
use std::{fs, path::Path};
use crate::dev_inspect;

pub fn preview(path: &str) -> Result<String, &'static str> {
    // Reuse existing root/symlink/traversal checks from offline inspection.
    dev_inspect::inspect(Path::new(path)).map_err(|_| "unsafe or unreadable project directory")?;
    let root = Path::new(path);
    let flake = root.join("flake.nix");
    let devshell = root.join("devshell.toml");
    let file = if regular_file(&flake) { "flake.nix" }
        else if regular_file(&devshell) { "devshell.toml" }
        else { return Err("no safe flake.nix or devshell.toml found in this directory"); };
    // Do not emit the path as a shell command: hostile file names can contain
    // shell syntax. Do not evaluate the manifest or even read its content.
    Ok(format!(
        "eduardOS development environment preview (offline)\nDetected: {file}\n         Trust boundary: the project's Nix configuration and shell hooks may execute code,          access files and use the network when activated.\n         No Nix command was executed and no dependencies were downloaded.\n         Inspect and trust the project yourself before manually entering its environment.\n"
    ))
}
fn regular_file(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|meta| meta.file_type().is_file())
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::{env, time::{SystemTime, UNIX_EPOCH}};
    fn fixture() -> std::path::PathBuf {
        let seed = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = env::temp_dir().join(format!("edos-env-{}-{seed}", std::process::id()));
        fs::create_dir(&path).unwrap();
        path
    }
    #[test] fn flake_preview_does_not_evaluate_content() {
        let dir = fixture();
        fs::write(dir.join("flake.nix"), "this is invalid Nix and must never run").unwrap();
        let out = preview(dir.to_str().unwrap()).unwrap();
        assert!(out.contains("Detected: flake.nix"));
        assert!(out.contains("No Nix command was executed"));
        fs::remove_dir_all(dir).unwrap();
    }
    #[test] fn absent_and_symlinked_manifests_are_refused() {
        let dir = fixture();
        assert!(preview(dir.to_str().unwrap()).is_err());
        #[cfg(unix)] {
            std::os::unix::fs::symlink("/etc/passwd", dir.join("flake.nix")).unwrap();
            assert!(preview(dir.to_str().unwrap()).is_err());
        }
        fs::remove_dir_all(dir).unwrap();
    }
    #[test] fn rejects_parent_traversal() {
        assert!(preview("../sneaky").is_err());
    }
}
