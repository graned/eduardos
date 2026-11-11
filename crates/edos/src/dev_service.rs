//! Explicit Compose lifecycle commands. Never uses a shell, elevated privileges,
//! implicit manifest selection, or automatic project discovery/execution.
use std::{fs, path::{Path, PathBuf}, process::{Command, Stdio}};
use crate::dev_inspect;

const MANIFESTS: &[&str] = &[
    "compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml",
];

#[derive(Debug, PartialEq, Eq)]
pub enum Action { Up, Down, Status }

fn parse(args: &[String]) -> Result<(Action, &str, &str, bool, bool), &'static str> {
    let Some(first) = args.first() else {
        return Err("usage: edos dev service <up|down|status> --engine <docker|podman> --file <compose.yaml|compose.yml|docker-compose.yaml|docker-compose.yml> [--approve --run]");
    };
    let action = match first.as_str() {
        "up" => Action::Up, "down" => Action::Down, "status" => Action::Status,
        _ => return Err("unsupported Compose action"),
    };
    let mut engine = None;
    let mut file = None;
    let mut approved = false;
    let mut execute = false;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--engine" if engine.is_none() && i + 1 < args.len() => {
                engine = Some(args[i+1].as_str()); i += 2;
            }
            "--file" if file.is_none() && i + 1 < args.len() => {
                file = Some(args[i+1].as_str()); i += 2;
            }
            "--approve" if !approved => { approved = true; i += 1; }
            "--run" if !execute => { execute = true; i += 1; }
            _ => return Err("invalid or repeated option"),
        }
    }
    let engine = engine.ok_or("--engine must be docker or podman")?;
    if !matches!(engine, "docker"|"podman") { return Err("--engine must be docker or podman"); }
    let file = file.ok_or("--file must select one Compose manifest")?;
    if !MANIFESTS.contains(&file) { return Err("invalid Compose manifest name"); }
    if execute && !approved { return Err("--run requires explicit --approve after reviewing the project"); }
    Ok((action, engine, file, approved, execute))
}

fn check_manifest(file: &str) -> Result<PathBuf, &'static str> {
    // Reuse the established component-by-component project directory validation.
    dev_inspect::inspect(Path::new(".")).map_err(|_| "unsafe current project directory")?;
    let path = Path::new(file);
    let meta = fs::symlink_metadata(path).map_err(|_| "selected Compose manifest not found")?;
    if !meta.file_type().is_file() { return Err("Compose manifest must be a regular, non-symlink file"); }
    std::env::current_dir().map_err(|_| "cannot resolve project directory")
}

fn unprivileged() -> bool {
    // Linux-only eduardOS: UID from procfs (real and effective).
    let Ok(status) = fs::read_to_string("/proc/self/status") else { return false; };
    status.lines().find_map(|line| {
        let rest = line.strip_prefix("Uid:")?;
        let ids: Vec<_> = rest.split_whitespace().take(2).collect();
        Some(ids.len() == 2 && ids.iter().all(|id| *id != "0"))
    }).unwrap_or(false)
}

pub fn service(args: &[String]) -> Result<String, String> {
    let (action, engine, file, _, execute) = parse(args).map_err(str::to_string)?;
    let project = check_manifest(file).map_err(str::to_string)?;
    let subcommand = match action {
        Action::Up => "up -d",
        Action::Down => "down",
        Action::Status => "ps",
    };
    if !execute {
        return Ok(format!(
            "eduardOS Compose lifecycle PREVIEW ONLY\nEngine: {engine}\nManifest: {file}\n\
             Action: {subcommand}\nProject directory: validated (path suppressed)\n\
             Review the manifest, volumes, networks and secrets before running.\n\
             To execute, repeat with --approve --run. No action was performed.\n"
        ));
    }
    if !unprivileged() {
        return Err("Compose lifecycle refuses root and unavailable procfs UID checks".into());
    }
    // No shell, no user-supplied executable, no custom command arguments.
    // The project itself remains untrusted; --approve is an explicit opt-in.
    let mut command = Command::new(engine);
    command.arg("compose").arg("-f").arg(file)
        .current_dir(project)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    match action {
        Action::Up => { command.args(["up", "-d"]); }
        Action::Down => { command.arg("down"); }
        Action::Status => { command.arg("ps"); }
    }
    let status = command.status().map_err(|e| format!("could not run {engine} compose: {e}"))?;
    if !status.success() {
        return Err(format!("Compose command failed with status {status}"));
    }
    Ok(format!("Compose {subcommand} completed successfully. No installer privileges were used.\n"))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn argv(args: &[&str]) -> Vec<String> { args.iter().map(|x| x.to_string()).collect() }
    #[test]
    fn parsing_requires_explicit_engine_manifest_and_approval() {
        assert_eq!(parse(&argv(&["up", "--engine","docker","--file","compose.yaml"])).unwrap().0, Action::Up);
        assert!(parse(&argv(&["up","--engine","docker","--file","compose.yaml","--run"])).is_err());
        assert!(parse(&argv(&["up","--engine","bash","--file","compose.yaml"])).is_err());
        assert!(parse(&argv(&["down","--engine","docker","--file","../evil"])).is_err());
        assert!(parse(&argv(&["up","--engine","docker","--file","compose.yaml","--approve","--run"])).unwrap().4);
        assert!(parse(&argv(&["up","--engine","docker","--file","compose.yaml","--approve","--approve"])).is_err());
    }
    #[test]
    fn no_host_shell_or_arbitrary_exec_argument() {
        assert!(parse(&argv(&["up","--engine","/bin/sh","--file","compose.yaml"])).is_err());
        assert!(parse(&argv(&["up","--engine","podman","--file","compose.yaml","--build"])).is_err());
    }
}
