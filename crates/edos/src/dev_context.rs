//! Non-secret, local project context for editors and optional AI tools.
//! Purely offline: no manifest parsing, subprocesses, network or file writes.
use std::{fs, path::Path};
use crate::dev_inspect;

const MARKERS: &[(&str, &str)] = &[
    ("go.mod", "go"),
    ("Cargo.toml", "rust"),
    ("package.json", "node"),
    ("pyproject.toml", "python"),
    ("flake.nix", "nix"),
    ("devshell.toml", "devshell"),
    ("compose.yaml", "compose"),
    ("compose.yml", "compose"),
    ("docker-compose.yaml", "compose"),
    ("docker-compose.yml", "compose"),
];

fn ecosystems(path: &Path) -> Vec<&'static str> {
    let mut found = Vec::new();
    for &(marker, ecosystem) in MARKERS {
        if fs::symlink_metadata(path.join(marker))
            .is_ok_and(|metadata| metadata.file_type().is_file())
            && !found.contains(&ecosystem) {
            found.push(ecosystem);
        }
    }
    found
}

/// Report only fixed, known ecosystem labels. Paths, environment variables,
/// manifest contents and potential credentials are never emitted.
pub fn context(path: &str) -> Result<String, &'static str> {
    dev_inspect::inspect(Path::new(path))
        .map_err(|_| "unsafe or unreadable project directory")?;
    let labels = ecosystems(Path::new(path));
    let state = if labels.is_empty() { "none".to_owned() } else { labels.join(", ") };
    Ok(format!(
        "eduardOS developer context (local, read-only)\n\
         Detected ecosystems: {state}\n\
         No project contents, paths, credentials or environment values were read or exported.\n\
         No editor or AI tool was launched; no data was sent externally.\n"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{env, time::{SystemTime, UNIX_EPOCH}};
    fn fixture() -> std::path::PathBuf {
        let seed = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = env::temp_dir().join(format!("edos-context-{}-{seed}", std::process::id()));
        fs::create_dir(&dir).unwrap();
        dir
    }
    #[test]
    fn reports_only_known_labels_and_never_manifest_text() {
        let dir = fixture();
        fs::write(dir.join("go.mod"), "super_secret_access_token").unwrap();
        fs::write(dir.join("compose.yaml"), "password: do-not-echo").unwrap();
        let report = context(dir.to_str().unwrap()).unwrap();
        assert!(report.contains("go, compose"));
        assert!(!report.contains("super_secret"));
        assert!(!report.contains("do-not-echo"));
        assert!(!report.contains(dir.to_str().unwrap()));
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn empty_and_symlinked_manifests_are_safe() {
        let dir = fixture();
        assert!(context(dir.to_str().unwrap()).unwrap().contains("none"));
        #[cfg(unix)] {
            std::os::unix::fs::symlink("/etc/passwd", dir.join("package.json")).unwrap();
            assert!(!context(dir.to_str().unwrap()).unwrap().contains("node"));
        }
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn directory_traversal_is_rejected() {
        assert!(context("../elsewhere").is_err());
    }
}
