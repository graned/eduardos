//! Opt-in workspace editor launch. No shell, project code execution, AI
//! automation, configuration writes, root privileges, or network APIs.
use std::{fs, path::Path, process::{Command, Stdio}};
use crate::dev_inspect;

fn same_user_nonroot() -> bool {
    let Ok(status) = fs::read_to_string("/proc/self/status") else { return false };
    let Some(uids) = status.lines().find_map(|l| l.strip_prefix("Uid:")) else { return false };
    let values: Vec<_> = uids.split_whitespace().take(2).collect();
    values.len() == 2 && values.iter().all(|v| *v != "0")
}
fn parse(args: &[String]) -> Result<(&str, bool), &'static str> {
    match args {
        [] => Ok((".", false)),
        [path] if path != "--run" => Ok((path, false)),
        [path, flag] if flag == "--run" && path != "--run" => Ok((path, true)),
        _ => Err("usage: edos workspace open [path] [--run]"),
    }
}
pub fn open(args: &[String]) -> Result<String, String> {
    let (path, run) = parse(args).map_err(str::to_owned)?;
    dev_inspect::inspect(Path::new(path))
        .map_err(|_| "unsafe or unreadable workspace directory")?;
    if !run {
        return Ok("eduardOS workspace preview\nEditor: Neovim\n\
                   Project directory: validated (path withheld)\n\
                   Preview only; use --run to open the editor. No project code was executed.\n".into());
    }
    if !same_user_nonroot() {
        return Err("workspace launch requires a non-root local user".into());
    }
    // A fixed editor, not a caller-supplied command, script, shell or AI agent.
    // Neovim may load user/project configuration; the operator must opt in.
    let status = Command::new("nvim").arg("--clean").arg(".")
        .current_dir(path).stdin(Stdio::inherit()).stdout(Stdio::inherit())
        .stderr(Stdio::inherit()).status()
        .map_err(|e| format!("Neovim could not be launched: {e}"))?;
    if !status.success() { return Err(format!("Neovim exited with status {status}")); }
    Ok("Editor session ended. No workspace metadata was persisted.\n".into())
}
#[cfg(test)]
mod tests {
    use super::*;
    fn a(xs: &[&str]) -> Vec<String> { xs.iter().map(|x| x.to_string()).collect() }
    #[test] fn preview_and_explicit_execution_are_distinct() {
        assert_eq!(parse(&a(&[])), Ok((".", false)));
        assert_eq!(parse(&a(&["src"])), Ok(("src", false)));
        assert_eq!(parse(&a(&["src", "--run"])), Ok(("src", true)));
        assert!(parse(&a(&["--run"])).is_err());
        assert!(parse(&a(&["src", "--run", "shell"])).is_err());
    }
    #[test] fn preview_never_starts_editor() {
        let result = open(&a(&["."])).unwrap();
        assert!(result.contains("Preview only"));
        assert!(result.contains("path withheld"));
    }
    #[test] fn refuses_path_traversal() {
        assert!(open(&a(&["../elsewhere"])).is_err());
    }
}
