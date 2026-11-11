//! Explicit, local-only project scaffolding. No manifest evaluation or subprocesses.
use std::{fs::{self, OpenOptions}, io::Write, path::Path};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Template { Go, Rust, Node, Python }
impl Template {
    fn parse(value: &str) -> Option<Self> {
        match value { "go" => Some(Self::Go), "rust" => Some(Self::Rust),
            "node" => Some(Self::Node), "python" => Some(Self::Python), _ => None }
    }
    fn files(self, name: &str) -> Vec<(&'static str, String)> {
        match self {
            Self::Go => vec![("go.mod", format!("module example.com/{name}\n\ngo 1.23\n")),
                ("main.go", "package main\n\nimport \"fmt\"\n\nfunc main() { fmt.Println(\"Hello from eduardOS\") }\n".into())],
            Self::Rust => vec![("Cargo.toml", format!("[package]\nname = \"{name}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n")),
                ("src/main.rs", "fn main() { println!(\"Hello from eduardOS\"); }\n".into())],
            Self::Node => vec![("package.json", format!("{{\n  \"name\": \"{name}\",\n  \"private\": true,\n  \"version\": \"0.1.0\",\n  \"scripts\": {{ \"start\": \"node index.js\" }}\n}}\n")),
                ("index.js", "console.log('Hello from eduardOS');\n".into())],
            Self::Python => vec![("pyproject.toml", format!("[project]\nname = \"{name}\"\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\n")),
                ("main.py", "print('Hello from eduardOS')\n".into())],
        }
    }
}
fn valid_name(name: &str) -> bool {
    !name.is_empty() && name.len() <= 64 &&
        name.bytes().next().is_some_and(|b| b.is_ascii_lowercase()) &&
        name.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_') &&
        !name.ends_with('-') && !name.ends_with('_')
}
pub fn init(args: &[String]) -> Result<String, String> {
    let [kind, name, rest @ ..] = args else {
        return Err("usage: edos dev init <go|rust|node|python> <name> [--write]".into());
    };
    let template = Template::parse(kind).ok_or("unsupported template: use go, rust, node or python")?;
    if !valid_name(name) { return Err("project name must start with a lowercase letter and contain only lowercase letters, digits, '-' or '_' (max 64)".into()); }
    let write = match rest { [] => false, [flag] if flag == "--write" => true,
        _ => return Err("expected only optional --write flag".into()) };
    let files = template.files(name);
    let mut report = format!("eduardOS project template: {kind} / {name}\n");
    for (path, _) in &files { report.push_str(&format!("  {name}/{path}\n")); }
    if !write { report.push_str("Preview only. Rerun with --write to create these files. No scripts or package managers will run.\n"); return Ok(report); }
    // Only a new direct child of cwd can be created; never overwrite existing content.
    let root = Path::new(name);
    fs::create_dir(root).map_err(|e| format!("cannot create new project (existing directories are never overwritten): {e}"))?;
    for (path, data) in files {
        let destination = root.join(path);
        if let Some(parent) = destination.parent() { fs::create_dir_all(parent).map_err(|e| format!("cannot create template directory: {e}"))?; }
        let mut file = OpenOptions::new().write(true).create_new(true).open(&destination)
            .map_err(|e| format!("refusing to overwrite template file: {e}"))?;
        file.write_all(data.as_bytes()).map_err(|e| format!("cannot write template file: {e}"))?;
    }
    report.push_str("Created locally. No commands were executed.\n");
    Ok(report)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn previews_are_deterministic_and_read_only() {
        for kind in ["go", "rust", "node", "python"] {
            let result = init(&[kind.into(), "my_app".into()]).unwrap();
            assert!(result.contains("Preview only"));
            assert!(result.contains("my_app/"));
        }
    }
    #[test] fn rejects_invalid_names_and_unknown_flags() {
        for name in ["../oops", "/tmp/oops", "A", ".config", "a/b", "a ", "x--$"] {
            assert!(init(&["go".into(), name.into()]).is_err());
        }
        assert!(init(&["go".into(), "test".into(), "--force".into()]).is_err());
        assert!(init(&["ruby".into(), "test".into()]).is_err());
    }
    #[test] fn does_not_overwrite_existing_target() {
        let unique = format!("edos-init-test-{}", std::process::id());
        let root = std::env::temp_dir().join(&unique);
        let _ = fs::remove_dir_all(&root);
        fs::create_dir(&root).unwrap();
        let previous = std::env::current_dir().unwrap();
        std::env::set_current_dir(&root).unwrap();
        let args = ["go".into(), "sample".into(), "--write".into()];
        assert!(init(&args).unwrap().contains("Created locally"));
        let original = fs::read_to_string("sample/go.mod").unwrap();
        assert!(init(&args).is_err());
        assert_eq!(fs::read_to_string("sample/go.mod").unwrap(), original);
        std::env::set_current_dir(previous).unwrap();
        fs::remove_dir_all(&root).unwrap();
    }
}
