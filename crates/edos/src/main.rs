//! eduardOS diagnostic CLI — deliberately non-privileged and read-only.
//! Installer authorization, disk writes and credentials are NOT exposed here.

use std::{env, fs, path::Path, process::ExitCode};

const RELEASE: &str = "/etc/eduardos/live-release";
const OS_RELEASE: &str = "/etc/os-release";

#[derive(Debug, PartialEq, Eq)]
enum Command {
    Version,
    Status,
    Doctor,
    Help,
}

fn parse(args: &[String]) -> Result<Command, &'static str> {
    match args {
        [] => Ok(Command::Help),
        [arg] if arg == "--help" || arg == "-h" || arg == "help" => Ok(Command::Help),
        [arg] if arg == "--version" || arg == "-V" || arg == "version" => Ok(Command::Version),
        [arg] if arg == "status" => Ok(Command::Status),
        [arg] if arg == "doctor" => Ok(Command::Doctor),
        _ => Err("unknown command or unexpected arguments"),
    }
}

fn release_name(contents: &str) -> Option<String> {
    // The marker is descriptive, not a trusted source of authorization.
    contents.lines().map(str::trim).find(|line| !line.is_empty())
        .map(str::to_owned)
}

fn os_pretty_name(contents: &str) -> Option<String> {
    contents.lines().find_map(|line| {
        let raw = line.strip_prefix("PRETTY_NAME=")?;
        let value = raw.trim().trim_matches('"');
        if value.is_empty() { None } else { Some(value.to_string()) }
    })
}

fn status(release: Option<&str>, os_release: Option<&str>) -> String {
    let name = release.and_then(release_name)
        .or_else(|| os_release.and_then(os_pretty_name))
        .unwrap_or_else(|| "Unknown Linux system".to_owned());
    format!("eduardOS system status\nSystem: {name}\nCLI: {}\nMode: read-only\n", env!("CARGO_PKG_VERSION"))
}

fn doctor(release_present: bool, os_release_present: bool) -> String {
    let release = if release_present { "present" } else { "not present" };
    let os = if os_release_present { "present" } else { "not present" };
    format!(
        "eduardOS diagnostics (read-only)\nLive release marker: {release}\nOS release metadata: {os}\nInstaller operations: unavailable\n"
    )
}

fn usage() -> &'static str {
    "eduardOS — Forged in Neon\nUsage: edos <command>\n\nCommands:\n  status   Display read-only system information\n  doctor   Check local release metadata without modifying anything\n  version  Show CLI version\n  help     Show this help\n"
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    match parse(&args) {
        Ok(Command::Help) => print!("{}", usage()),
        Ok(Command::Version) => println!("edos {}", env!("CARGO_PKG_VERSION")),
        Ok(Command::Status) => {
            let release = fs::read_to_string(Path::new(RELEASE)).ok();
            let os_release = fs::read_to_string(Path::new(OS_RELEASE)).ok();
            print!("{}", status(release.as_deref(), os_release.as_deref()));
        }
        Ok(Command::Doctor) => {
            print!("{}", doctor(Path::new(RELEASE).is_file(), Path::new(OS_RELEASE).is_file()));
        }
        Err(problem) => {
            eprintln!("edos: {problem}\n{}", usage());
            return ExitCode::from(2);
        }
    }
    ExitCode::SUCCESS
}

#[cfg(test)]
mod tests {
    use super::*;

    fn words(args: &[&str]) -> Vec<String> {
        args.iter().map(|s| (*s).to_owned()).collect()
    }

    #[test]
    fn strict_commands() {
        assert_eq!(parse(&words(&[])), Ok(Command::Help));
        assert_eq!(parse(&words(&["--version"])), Ok(Command::Version));
        assert_eq!(parse(&words(&["status"])), Ok(Command::Status));
        assert_eq!(parse(&words(&["doctor"])), Ok(Command::Doctor));
        assert!(parse(&words(&["status", "--execute"])).is_err());
        assert!(parse(&words(&["install"])).is_err());
    }

    #[test]
    fn release_metadata_has_safe_fallbacks() {
        assert_eq!(release_name(" \n eduardOS Alpha 0.1\n").as_deref(), Some("eduardOS Alpha 0.1"));
        assert_eq!(os_pretty_name("NAME=NixOS\nPRETTY_NAME=\"NixOS 26.05\"\n").as_deref(), Some("NixOS 26.05"));
        assert!(status(None, None).contains("Unknown Linux system"));
        assert!(status(Some("eduardOS Alpha\n"), None).contains("eduardOS Alpha"));
        assert!(status(None, Some("PRETTY_NAME=\"NixOS\"")).contains("NixOS"));
    }

    #[test]
    fn diagnostics_deny_privileged_actions() {
        let result = doctor(false, true);
        assert!(result.contains("Installer operations: unavailable"));
        assert!(result.contains("Live release marker: not present"));
    }
}
