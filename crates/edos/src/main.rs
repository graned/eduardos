//! eduardOS diagnostic CLI — deliberately non-privileged and read-only.
//! Installer authorization, disk writes and credentials are NOT exposed here.

use std::{env, fs, path::Path, process::ExitCode};

mod diagnostics;
mod dev_inspect;
mod dev_init;
mod dev_env;
mod dev_compose;

const RELEASE: &str = "/etc/eduardos/live-release";
const OS_RELEASE: &str = "/etc/os-release";

#[derive(Debug, PartialEq, Eq)]
enum Command {
    Version,
    Status,
    Doctor,
    DevInspect(String),
    DevInit(Vec<String>),
    DevEnv(String),
    DevCompose(String),
    Shortcuts,
    Help,
}

fn parse(args: &[String]) -> Result<Command, &'static str> {
    match args {
        [] => Ok(Command::Help),
        [arg] if arg == "--help" || arg == "-h" || arg == "help" => Ok(Command::Help),
        [arg] if arg == "--version" || arg == "-V" || arg == "version" => Ok(Command::Version),
        [arg] if arg == "status" => Ok(Command::Status),
        [arg] if arg == "doctor" => Ok(Command::Doctor),
        [dev, inspect] if dev == "dev" && inspect == "inspect" => Ok(Command::DevInspect(".".to_owned())),
        [dev, inspect, path] if dev == "dev" && inspect == "inspect" => Ok(Command::DevInspect(path.clone())),
        [dev, init, rest @ ..] if dev == "dev" && init == "init" => Ok(Command::DevInit(rest.to_vec())),
        [dev, envcmd] if dev == "dev" && envcmd == "env" => Ok(Command::DevEnv(".".to_owned())),
        [dev, envcmd, path] if dev == "dev" && envcmd == "env" => Ok(Command::DevEnv(path.clone())),
        [dev, compose] if dev == "dev" && compose == "compose" => Ok(Command::DevCompose(".".to_owned())),
        [dev, compose, path] if dev == "dev" && compose == "compose" => Ok(Command::DevCompose(path.clone())),
        [arg] if arg == "shortcuts" => Ok(Command::Shortcuts),
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

fn usage() -> &'static str {
    "eduardOS — Forged in Neon\nUsage: edos <command>\n\nCommands:\n  status   Display read-only system information\n  doctor   Inspect Nix generation, desktop, developer tools and resources\n  dev inspect [path]  Detect project manifests offline\n  dev init <template> <name> [--write]  Preview or create a local project\n  dev env [path]  Preview project Nix environment without running it\n  dev compose [path]  Inspect Compose manifests without starting containers\n  version  Show CLI version\n  shortcuts  List desktop keybindings\n  help     Show this help\n"
}

fn shortcuts() -> &'static str {
    "eduardOS desktop shortcuts\nSuper + Enter: Ghostty\nSuper + D: Fuzzel launcher\nSuper + Shift + D: system diagnostics\nPrint: screen screenshot to clipboard\nSuper + Shift + S: region screenshot to clipboard\nSuper + Q: close window\nSuper + F: fullscreen\nSuper + Space: floating\nSuper + 1/2/3: switch workspace\nSuper + Shift + 1/2/3: move window\nSuper + Shift + E: exit Hyprland\n"
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    match parse(&args) {
        Ok(Command::Help) => print!("{}", usage()),
        Ok(Command::Version) => println!("edos {}", env!("CARGO_PKG_VERSION")),
        Ok(Command::Shortcuts) => print!("{}", shortcuts()),
        Ok(Command::Status) => {
            let release = fs::read_to_string(Path::new(RELEASE)).ok();
            let os_release = fs::read_to_string(Path::new(OS_RELEASE)).ok();
            print!("{}", status(release.as_deref(), os_release.as_deref()));
        }
        Ok(Command::DevInspect(path)) => {
            match dev_inspect::inspect(Path::new(&path)) {
                Ok(report) => print!("{report}"),
                Err(error) => {
                    eprintln!("edos: {}", dev_inspect::message(&error));
                    return ExitCode::from(1);
                }
            }
        }
        Ok(Command::DevInit(args)) => {
            match dev_init::init(&args) {
                Ok(report) => print!("{report}"),
                Err(error) => { eprintln!("edos: {error}"); return ExitCode::from(2); }
            }
        }
        Ok(Command::DevEnv(path)) => {
            match dev_env::preview(&path) {
                Ok(report) => print!("{report}"),
                Err(error) => { eprintln!("edos: {error}"); return ExitCode::from(1); }
            }
        }
        Ok(Command::DevCompose(path)) => {
            match dev_compose::plan(&path) {
                Ok(report) => print!("{report}"),
                Err(error) => { eprintln!("edos: {error}"); return ExitCode::from(1); }
            }
        }
        Ok(Command::Doctor) => {
            print!("{}", diagnostics::doctor(Path::new(RELEASE), Path::new(OS_RELEASE), Path::new("/run/current-system")));
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
        assert_eq!(parse(&words(&["dev", "inspect"])), Ok(Command::DevInspect(".".to_owned())));
        assert_eq!(parse(&words(&["dev", "inspect", "project"])), Ok(Command::DevInspect("project".to_owned())));
        assert!(parse(&words(&["dev", "inspect", "project", "extra"])).is_err());
        assert_eq!(parse(&words(&["dev", "init", "go", "demo"])), Ok(Command::DevInit(words(&["go", "demo"]))));
        assert_eq!(parse(&words(&["dev", "env"])), Ok(Command::DevEnv(".".into())));
        assert_eq!(parse(&words(&["dev", "env", "project"])), Ok(Command::DevEnv("project".into())));
        assert!(parse(&words(&["dev", "env", "project", "--execute"])).is_err());
        assert_eq!(parse(&words(&["dev", "compose"])), Ok(Command::DevCompose(".".into())));
        assert_eq!(parse(&words(&["dev", "compose", "project"])), Ok(Command::DevCompose("project".into())));
        assert!(parse(&words(&["dev", "compose", "a", "b"])).is_err());
        assert_eq!(parse(&words(&["shortcuts"])), Ok(Command::Shortcuts));
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
    fn shortcuts_are_discoverable() {
        assert!(shortcuts().contains("Super + Shift + S"));
        assert!(shortcuts().contains("screenshot to clipboard"));
    }

    #[test]
    fn diagnostics_deny_privileged_actions() {
        let result = diagnostics::doctor(
            Path::new("/nonexistent/edos-live-marker"),
            Path::new("/nonexistent/edos-os-marker"),
            Path::new("/nonexistent/edos-generation"),
        );
        assert!(result.contains("Installer operations: unavailable"));
        assert!(result.contains("Live release marker: not present"));
    }
}
