//! Offline Compose project discovery. This module never invokes Docker/Podman,
//! evaluates YAML, starts containers, reads secrets or modifies the project.
use std::{fs, path::Path};
use crate::dev_inspect;

const CANDIDATES: &[&str] = &[
    "compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"
];

fn is_regular_file(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|meta| meta.file_type().is_file())
}

/// Reports what a trusted operator would need to review before a future
/// explicit Compose launch. No host-shell command is constructed from paths.
pub fn plan(path: &str) -> Result<String, &'static str> {
    dev_inspect::inspect(Path::new(path))
        .map_err(|_| "unsafe or unreadable project directory")?;
    let available: Vec<_> = CANDIDATES.iter()
        .filter(|name| is_regular_file(&Path::new(path).join(name)))
        .copied().collect();
    if available.is_empty() {
        return Err("no safe Compose manifest found at this directory level");
    }
    let mut out = String::from("eduardOS Compose project inspection (offline, no containers started)\n");
    for file in &available {
        out.push_str(&format!("Detected Compose manifest: {file}\n"));
    }
    if available.len() > 1 {
        out.push_str("Multiple manifest candidates exist; select one explicitly before any future execution.\n");
    }
    out.push_str(
        "Trust boundary: Compose can build images, run commands, mount host paths and access credentials.\n\
         Review the manifest and select a container engine before explicitly starting services.\n\
         No Compose YAML was read or evaluated; no Docker or Podman commands were executed.\n"
    );
    Ok(out)
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::{env, time::{SystemTime, UNIX_EPOCH}};
    fn fixture() -> std::path::PathBuf {
        let seed = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = env::temp_dir().join(format!("edos-compose-{}-{seed}", std::process::id()));
        fs::create_dir(&dir).unwrap();
        dir
    }
    #[test]
    fn detects_manifests_without_parsing_or_execution() {
        let dir = fixture();
        fs::write(dir.join("compose.yaml"), "not valid yaml and must not be parsed").unwrap();
        let text = plan(dir.to_str().unwrap()).unwrap();
        assert!(text.contains("Detected Compose manifest: compose.yaml"));
        assert!(text.contains("no containers started"));
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn refuses_symlinked_and_missing_manifests() {
        let dir = fixture();
        assert!(plan(dir.to_str().unwrap()).is_err());
        #[cfg(unix)] {
            std::os::unix::fs::symlink("/etc/passwd", dir.join("compose.yaml")).unwrap();
            assert!(plan(dir.to_str().unwrap()).is_err());
        }
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn flags_ambiguous_manifests() {
        let dir = fixture();
        fs::write(dir.join("compose.yml"), "").unwrap();
        fs::write(dir.join("compose.yaml"), "").unwrap();
        assert!(plan(dir.to_str().unwrap()).unwrap().contains("Multiple manifest candidates"));
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn rejects_parent_traversal() {
        assert!(plan("../other").is_err());
    }
}
