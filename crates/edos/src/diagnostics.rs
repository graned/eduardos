//! Read-only Linux / developer-environment diagnostics.
//! No shell execution, credential inspection, privileged APIs, or disk writes.
use std::{env, fs, path::{Path, PathBuf}};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum State { Ok, Missing, Unknown }
impl State {
    fn tag(self) -> &'static str {
        match self { Self::Ok => "OK", Self::Missing => "MISSING", Self::Unknown => "UNKNOWN" }
    }
}

struct Check { name: &'static str, state: State, detail: String }
impl Check {
    fn new(name: &'static str, state: State, detail: impl Into<String>) -> Self {
        Self { name, state, detail: detail.into() }
    }
}

fn parse_mem_available(kib_text: &str) -> Option<u64> {
    kib_text.lines().find_map(|line| {
        let value = line.strip_prefix("MemAvailable:")?;
        let mut fields = value.split_whitespace();
        let kib = fields.next()?.parse::<u64>().ok()?;
        if fields.next()? != "kB" { return None; }
        kib.checked_mul(1024 * 1024).map(|bytes_kib| bytes_kib / 1024)
    })
}

fn mem_available_mib(contents: &str) -> Option<u64> {
    // Linux reports kB (KiB for meminfo); compute MiB without overflow.
    contents.lines().find_map(|line| {
        let mut fields = line.strip_prefix("MemAvailable:")?.split_whitespace();
        let kib = fields.next()?.parse::<u64>().ok()?;
        if fields.next()? != "kB" { return None; }
        Some(kib / 1024)
    })
}

fn path_has_executable(command: &str, path: Option<&str>) -> bool {
    if command.contains('/') || command.is_empty() { return false; }
    let Some(path) = path else { return false; };
    env::split_paths(path).any(|directory| {
        // Only test file mode, never attempt to run the executable.
        let candidate = directory.join(command);
        let Ok(meta) = fs::metadata(candidate) else { return false; };
        if !meta.is_file() { return false; }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            meta.permissions().mode() & 0o111 != 0
        }
        #[cfg(not(unix))]
        { false }
    })
}

fn tool_group(path: Option<&str>, tools: &[&str]) -> Check {
    let present: Vec<&str> = tools.iter().copied().filter(|name| path_has_executable(name, path)).collect();
    let absent: Vec<&str> = tools.iter().copied().filter(|name| !path_has_executable(name, path)).collect();
    let state = if absent.is_empty() { State::Ok } else { State::Missing };
    Check::new("Developer tools", state, format!("present: {}; missing: {}",
        if present.is_empty() { "none".to_string() } else { present.join(", ") },
        if absent.is_empty() { "none".to_string() } else { absent.join(", ") }))
}

fn desktop_session(wayland: Option<&str>, session_type: Option<&str>, desktop: Option<&str>) -> Check {
    // Do not print environment values; only report whether a session is detected.
    let wayland = wayland.is_some_and(|s| !s.is_empty()) || session_type == Some("wayland");
    let compositor = desktop.is_some_and(|s| s.split(':').any(|part| part.eq_ignore_ascii_case("hyprland")));
    match (wayland, compositor) {
        (true, true) => Check::new("Desktop session", State::Ok, "Wayland / Hyprland detected"),
        (true, false) => Check::new("Desktop session", State::Ok, "Wayland detected (compositor not verified)"),
        (false, _) => Check::new("Desktop session", State::Unknown, "no Wayland session found; normal on TTY or SSH"),
    }
}

fn generation(path: &Path) -> Check {
    match fs::read_link(path) {
        Ok(link) => {
            // Do not print store paths or home directories.
            let is_nix_store = link.starts_with("/nix/store/");
            Check::new("Nix generation", if is_nix_store { State::Ok } else { State::Unknown },
                if is_nix_store { "active system generation link present" } else { "unrecognized system link" })
        },
        Err(_) => Check::new("Nix generation", State::Unknown, "active system generation unavailable"),
    }
}

fn memory(meminfo: Option<&str>) -> Check {
    match meminfo.and_then(mem_available_mib) {
        Some(mib) => Check::new("Memory", State::Ok, format!("{mib} MiB available")),
        None => Check::new("Memory", State::Unknown, "memory information unavailable"),
    }
}

fn load(loadavg: Option<&str>) -> Check {
    let load = loadavg.and_then(|s| s.split_whitespace().next())
        .and_then(|s| s.parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value >= 0.0);
    match load {
        Some(value) => Check::new("System load", State::Ok, format!("1-minute load average: {value:.2}")),
        None => Check::new("System load", State::Unknown, "load average unavailable"),
    }
}

fn render(checks: &[Check], live_release: bool, os_release: bool) -> String {
    let mut output = String::from("eduardOS diagnostics (read-only)\n");
    output.push_str(if live_release { "Live release marker: present\n" } else { "Live release marker: not present\n" });
    output.push_str(if os_release { "OS release metadata: present\n" } else { "OS release metadata: not present\n" });
    for c in checks {
        output.push_str(&format!("[{}] {}: {}\n", c.state.tag(), c.name, c.detail));
    }
    output.push_str("Installer operations: unavailable\n");
    output
}

pub fn doctor(live_release: &Path, os_release: &Path, generation_path: &Path) -> String {
    let path = env::var_os("PATH").and_then(|p| p.into_string().ok());
    let meminfo = fs::read_to_string("/proc/meminfo").ok();
    let loadavg = fs::read_to_string("/proc/loadavg").ok();
    let checks = [
        generation(generation_path),
        desktop_session(
            env::var("WAYLAND_DISPLAY").ok().as_deref(),
            env::var("XDG_SESSION_TYPE").ok().as_deref(),
            env::var("XDG_CURRENT_DESKTOP").ok().as_deref()),
        tool_group(path.as_deref(), &["git", "nix", "cargo", "go", "node", "python3", "docker"]),
        memory(meminfo.as_deref()),
        load(loadavg.as_deref()),
    ];
    render(&checks, live_release.is_file(), os_release.is_file())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn memory_and_load_are_parsed_without_panicking() {
        assert_eq!(mem_available_mib("MemTotal: 16384 kB\nMemAvailable: 4096 kB\n"), Some(4));
        assert_eq!(mem_available_mib("MemAvailable: nope kB"), None);
        assert_eq!(memory(None).state, State::Unknown);
        assert_eq!(load(Some("0.25 0.20 0.12 1/2 12")).state, State::Ok);
        assert_eq!(load(Some("NaN 0.2")).state, State::Unknown);
    }

    #[test]
    fn session_is_safe_without_graphical_environment() {
        assert_eq!(desktop_session(None, None, None).state, State::Unknown);
        assert_eq!(desktop_session(Some("wayland-0"), Some("wayland"), Some("Hyprland")).state, State::Ok);
        assert!(!desktop_session(None, None, None).detail.contains("wayland-0"));
    }

    #[test]
    fn tools_do_not_execute_or_accept_paths_as_command_names() {
        assert!(!path_has_executable("/bin/sh", Some("/bin")));
        assert!(!path_has_executable("missing-edos-test-bin", Some("/bin:/usr/bin")));
        assert_eq!(tool_group(None, &["git"]).state, State::Missing);
    }

    #[test]
    fn report_remains_read_only_and_explains_unavailable_information() {
        let result = render(&[
            Check::new("Nix generation", State::Unknown, "unavailable"),
            Check::new("Desktop session", State::Ok, "Wayland detected"),
        ], false, true);
        assert!(result.contains("Live release marker: not present"));
        assert!(result.contains("[UNKNOWN] Nix generation: unavailable"));
        assert!(result.contains("Installer operations: unavailable"));
    }
}
