# eduardOS CLI: Rust and Python together

`edos` is the first Rust workspace crate in the eduardOS flake.
It is a **non-privileged, read-only** user-facing CLI.

```sh
nix run .#edos -- version
nix run .#edos -- status
nix run .#edos -- doctor
nix build --no-link -L .#checks.x86_64-linux.edos-cli-tests
nix build --no-link -L .#checks.x86_64-linux.edos-cli-smoke
```

The CLI is available in the **live ISO, VM and installed desktop profiles**
through the shared desktop modules. It reads the optional
`/etc/eduardos/live-release` marker and standard `/etc/os-release`.
If the eduardOS marker is absent, it falls back to generic OS metadata.
The `doctor` command additionally reads `/run/current-system`, `/proc/meminfo`,
`/proc/loadavg`, session-presence environment variables and executable
metadata on `PATH`. It reports Nix generation availability, detected
Wayland/Hyprland session, developer-tool presence (git, nix, cargo, go,
node, python3 and docker), available memory and load average. Results
are informational; absent commands or headless/SSH sessions are reported
without failing or changing the system. It never executes detected tools,
reads secret values or exposes environment variable contents.

It does not require root privileges, spawn Python, enumerate disks,
read credentials, or authorize installation.

## Language boundaries

- **Rust**: compiled system-facing tooling when it improves reliability,
  performance, process control, or resource ownership. The CLI starts here.
- **Python**: existing Forge installer prototypes, threat-model fixtures,
  backend and QEMU safety tests. These remain in place; no rewrite is
  required merely to standardize a language.
- **Nix**: declarative system configuration and composition of both.
- **Interop**: where needed later, use typed, versioned process or IPC
  protocols with allowlisted operations, rather than exposing privileged
  Python APIs or arbitrary commands through `edos`.

## Security and limitations

The CLI does **not** install eduardOS, format disks, run Disko, escalate
privileges, or bridge the Forge UI to the root-only execution path.
The existing QEMU-only installer and its separate safety gates are unchanged.
Adding commands that write files or alter system state requires separate
review and tests.

The Cargo workspace has no external Rust dependencies. Its isolated Nix
source includes only `Cargo.toml`, `Cargo.lock` and `crates/edos`, to
avoid rebuilding Rust binaries when unrelated themes and docs change.

## Next checkpoint

After this change, `edos dev inspect` is the next planned read-only Rust
feature (PR #54): offline project manifest detection. No project code
should be executed during detection. The live preview is not the unfinished
physically installable Alpha 0.2.
