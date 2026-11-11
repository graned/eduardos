//! Read-only, unprivileged resource snapshot for a specific same-user PID.
//! No process signals, shell execution, polling, telemetry or privileged access.
use std::{fs, path::PathBuf};

fn field<'a>(status: &'a str, name: &str) -> Option<&'a str> {
    status.lines().find_map(|line| line.strip_prefix(name).map(str::trim))
}
fn owner_ids(status: &str) -> Option<(u32, u32)> {
    let ids: Vec<_> = field(status, "Uid:")?.split_whitespace().take(2)
        .map(str::parse::<u32>).collect::<Result<_, _>>().ok()?;
    if ids.len() == 2 { Some((ids[0], ids[1])) } else { None }
}
fn safe_pid(raw: &str) -> Result<u32, &'static str> {
    if raw.is_empty() || !raw.bytes().all(|b| b.is_ascii_digit()) {
        return Err("PID must be a positive decimal integer");
    }
    let pid: u32 = raw.parse().map_err(|_| "invalid PID")?;
    if pid == 0 { return Err("PID zero is not a process"); }
    Ok(pid)
}
fn summarize(target: &str, self_status: &str, pid: u32) -> Result<String, &'static str> {
    let (self_real, self_effective) = owner_ids(self_status).ok_or("cannot verify current UID")?;
    let (target_real, target_effective) = owner_ids(target).ok_or("cannot verify process UID")?;
    if self_effective == 0 || self_real == 0 || self_real != target_real ||
        self_effective != target_effective {
        return Err("only processes owned by the current non-root user can be inspected");
    }
    let rss = field(target, "VmRSS:").unwrap_or("unavailable");
    let size = field(target, "VmSize:").unwrap_or("unavailable");
    let threads = field(target, "Threads:").unwrap_or("unavailable");
    Ok(format!(
        "eduardOS process resource snapshot (read-only)\nPID: {pid}\n\
         Resident memory: {rss}\nVirtual memory: {size}\nThreads: {threads}\n\
         Scope: selected process, not its children or entire Compose project.\n\
         No monitoring daemon, telemetry or process control is enabled.\n"
    ))
}
pub fn stats(raw: &str) -> Result<String, String> {
    let pid = safe_pid(raw).map_err(str::to_owned)?;
    let self_status = fs::read_to_string("/proc/self/status")
        .map_err(|_| "cannot access current process credentials")?;
    let path = PathBuf::from(format!("/proc/{pid}/status"));
    let target = fs::read_to_string(path)
        .map_err(|_| "process does not exist or procfs denies access")?;
    summarize(&target, &self_status, pid).map_err(str::to_owned)
}
#[cfg(test)]
mod tests {
    use super::*;
    const SELF: &str = "Uid:\t1000\t1000\t1000\t1000\n";
    const OTHER: &str = "Uid:\t1001\t1001\t1001\t1001\n";
    const TARGET: &str = "Uid:\t1000\t1000\t1000\t1000\nVmRSS:\t1234 kB\nVmSize:\t9999 kB\nThreads:\t3\n";
    #[test] fn parses_only_decimal_pid() {
        for bad in ["", "0", "-1", "../self", "1;id", "12a", "4294967296"] {
            assert!(safe_pid(bad).is_err());
        }
        assert_eq!(safe_pid("42"), Ok(42));
    }
    #[test] fn refuses_other_user_and_root() {
        assert!(summarize(OTHER, SELF, 12).is_err());
        assert!(summarize(TARGET, "Uid:\t0\t0\t0\t0\n", 12).is_err());
        assert!(summarize(TARGET, "Uid:\t1000\t0\t0\t0\n", 12).is_err());
    }
    #[test] fn displays_read_only_resource_snapshot() {
        let output = summarize(TARGET, SELF, 123).unwrap();
        assert!(output.contains("1234 kB"));
        assert!(output.contains("Threads: 3"));
        assert!(output.contains("not its children"));
    }
    #[test] fn fields_are_optional() {
        assert!(summarize(SELF, SELF, 9).unwrap().contains("unavailable"));
    }
}
