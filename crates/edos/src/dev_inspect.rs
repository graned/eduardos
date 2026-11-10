//! Offline project detection, no manifest parsing or evaluation.
//! This never executes project code, follows symlinked project roots or
//! manifest files, downloads dependencies, or modifies the filesystem.
use std::{env, fs, path::{Component, Path, PathBuf}};

const MANIFESTS: &[(&str, &str)] = &[
    ("flake.nix", "Nix flake"),
    ("devshell.toml", "devshell"),
    ("go.mod", "Go"),
    ("Cargo.toml", "Rust/Cargo"),
    ("package.json", "Node.js"),
    ("pnpm-workspace.yaml", "pnpm workspace"),
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python requirements"),
    ("Pipfile", "Pipenv"),
    ("uv.lock", "uv lockfile"),
    ("compose.yaml", "Docker Compose"),
    ("compose.yml", "Docker Compose"),
    ("docker-compose.yaml", "Docker Compose"),
    ("docker-compose.yml", "Docker Compose"),
];

#[derive(Debug, PartialEq, Eq)]
pub enum Error { Missing, Symlink, NotDirectory, ParentTraversal, Unreadable }

fn validated_directory(path: &Path) -> Result<PathBuf, Error> {
    if path.components().any(|part| matches!(part, Component::ParentDir)) {
        return Err(Error::ParentTraversal);
    }
    let full = if path.is_absolute() { path.to_path_buf() }
        else { env::current_dir().map_err(|_| Error::Unreadable)?.join(path) };
    // Examine each directory component with lstat; a symlink in any
    // component would redirect the scan outside the requested tree.
    let mut checked = PathBuf::new();
    for component in full.components() {
        checked.push(component.as_os_str());
        let meta = fs::symlink_metadata(&checked).map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound { Error::Missing } else { Error::Unreadable }
        })?;
        if meta.file_type().is_symlink() { return Err(Error::Symlink); }
        if !meta.is_dir() { return Err(Error::NotDirectory); }
    }
    Ok(full)
}

pub fn inspect(path: &Path) -> Result<String, Error> {
    let directory = validated_directory(path)?;
    let mut found = Vec::new();
    let mut suspicious = Vec::new();
    for &(filename, label) in MANIFESTS {
        let candidate = directory.join(filename);
        match fs::symlink_metadata(&candidate) {
            Ok(meta) if meta.file_type().is_symlink() => suspicious.push(filename),
            Ok(meta) if meta.is_file() => found.push((filename, label)),
            Ok(_) => suspicious.push(filename),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {},
            Err(_) => suspicious.push(filename),
        }
    }
    let mut out = String::from("eduardOS project inspection (offline, read-only)\n");
    // Do not echo the user-supplied path: it can contain credentials.
    if found.is_empty() {
        out.push_str("No recognized project manifests at this directory level.\n");
    }
    for (file, label) in found {
        out.push_str(&format!("Detected: {label} ({file})\n"));
    }
    if !suspicious.is_empty() {
        out.push_str(&format!("Skipped unsafe or unreadable manifest entries: {}\n",
            suspicious.join(", ")));
    }
    out.push_str("No manifest content was read or executed; no tools were launched.\n");
    Ok(out)
}

pub fn message(error: &Error) -> &'static str {
    match error {
        Error::Missing => "project directory does not exist",
        Error::Symlink => "project path contains a symbolic link; use a real directory",
        Error::NotDirectory => "project path is not a directory",
        Error::ParentTraversal => "parent-directory traversal is not accepted",
        Error::Unreadable => "project directory cannot be inspected safely",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn tempdir() -> PathBuf {
        let seed = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let p = env::temp_dir().join(format!("edos-inspect-{}-{seed}", std::process::id()));
        fs::create_dir(&p).unwrap();
        p
    }

    #[test]
    fn detects_multiple_languages_without_reading_contents() {
        let dir = tempdir();
        fs::write(dir.join("go.mod"), "module example\n").unwrap();
        fs::write(dir.join("Cargo.toml"), "not even valid TOML").unwrap();
        fs::write(dir.join("compose.yaml"), "untrusted shell content").unwrap();
        let report = inspect(&dir).unwrap();
        assert!(report.contains("Go (go.mod)"));
        assert!(report.contains("Rust/Cargo (Cargo.toml)"));
        assert!(report.contains("Docker Compose (compose.yaml)"));
        assert!(report.contains("no tools were launched"));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn missing_and_empty_folders_are_handled() {
        let dir = tempdir();
        assert!(inspect(&dir).unwrap().contains("No recognized"));
        assert_eq!(inspect(&dir.join("missing")), Err(Error::Missing));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn rejects_parent_traversal_and_symlink_roots() {
        let dir = tempdir();
        assert_eq!(inspect(Path::new("../project")), Err(Error::ParentTraversal));
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(&dir, dir.join("alias")).unwrap();
            assert_eq!(inspect(&dir.join("alias")), Err(Error::Symlink));
            std::os::unix::fs::symlink("/etc/passwd", dir.join("package.json")).unwrap();
            let report = inspect(&dir).unwrap();
            assert!(report.contains("Skipped unsafe"));
            assert!(!report.contains("Node.js (package.json)"));
        }
        fs::remove_dir_all(dir).unwrap();
    }
}
