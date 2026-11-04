# eduardOS — Architecture (Draft)

> **v1.0 codename:** Forged in Chaos  
> **Motto:** The machine shall obey.  
> **CLI:** `edos`  
> **Status:** Design proposal, not an installed or production-ready system.

## Vision

eduardOS is a developer-first, AI-ready Linux distribution based on NixOS, designed to remain comfortable for everyday activities such as browsing, watching videos, and listening to music. It must be reproducible, recoverable, configurable, and visually distinctive.

## Core principles

1. **Applications are declared; data persists; the operating system is replaceable.**
2. **Prefer upstream components over custom forks.** Keep NixOS, the Linux kernel, systemd, Hyprland, and container runtimes maintained upstream.
3. **Safe defaults, explicit choices.** Never erase or reformat existing storage without a clearly reviewed operation.
4. **Measure before optimizing.** Rust is for eduardOS tooling, not a blanket rewrite.
5. **Daily-driver first.** Audio, video, network, suspend/resume, and GPU support matter as much as build performance.

## Architecture

| Layer | Planned implementation |
| --- | --- |
| Base OS | NixOS, pinned through `flake.lock` |
| Desktop | Hyprland, UWSM, Waybar, launcher, notifications, lock screen |
| User environment | Home Manager; Isenguard.nvim configured with `NVIM_APPNAME=isenguard` |
| AI development | OpenCode installed by default; providers and credentials configured securely at first run |
| Toolchains | Nix development shells and optional per-project tooling |
| Containers | Docker or Podman; compatible Compose provider selection |
| Persistence | Btrfs subvolumes for root, Nix state, home, and optional containers/models |
| Control plane | Rust-based `edos` CLI and optional lightweight storage monitor |
| Visual identity | Obsidian Forge theme; future optional Blood Moon and Valhalla themes |

## Storage plan

The preferred v1 layout uses EFI plus an encrypted Btrfs filesystem with separate subvolumes:

```text
EFI system partition
Btrfs filesystem
├── @root        -> /
├── @nix         -> /nix
├── @home        -> /home
├── @models      -> /var/lib/eduardos/models (optional)
└── @containers  -> engine-specific location (optional)
```

Subvolumes **share filesystem free space** unless quotas are explicitly configured. They are not separate fixed-capacity partitions: a large Python or LLM download should not require resizing the root subvolume. Preserving `/home` means standard XDG config, cache, and data locations normally survive reinstall without symlinks.

Preserving `/nix` may allow reuse of downloaded packages, but configuration and profiles must still be reconstructed/validated; reinstallation is not equivalent to preserving a running system. Virtual environments and application binaries may require rebuilding after upgrades.

**Reinstall safety:** explicit choose-create-versus-reuse storage flow; never format a preserved volume; maintain stable user UID ownership; verify encryption unlock, mounts, backups and recovery before a destructive change. Btrfs snapshots are **not backups**. Design the installer to accommodate existing partitions and external backup targets.

**Storage Guardian (Rust, planned):** report actual free space, Nix generations, model caches, container data, and disk pressure. Notify at configurable thresholds, using free bytes as well as percentage; do not automatically delete personal data, models, or volumes. Any cleanup must be reviewable.

## Developer defaults

- **OpenCode:** install a pinned version; store tokens/secrets outside the Nix store.
- **Isenguard.nvim:** use its upstream repository as a pinned input, not a copied, stale configuration.
- **Containers:** start with Docker Engine + Compose V2; allow Podman and a compatible Compose provider as an alternative. Validate exact runtime/Compose combinations and rootless access.
- **Toolchains:** Git, Neovim, Ghostty, Go, Rust, Node.js, Python/uv and container tooling should be exposed through configurable profiles.
- **Media:** PipeWire/WirePlumber, browser, `mpv`, hardware acceleration where supported, Bluetooth, video calls/screen sharing and power management.

## `edos` CLI: initial scope

Proposed interfaces, **not yet implemented**:

```text
edos status
edos storage status
edos storage analyze
edos rebuild
edos generations
edos rollback
edos containers configure
edos theme set obsidian-forge
```

`edos` should validate and generate declarative configuration, delegate package resolution/rebuilds to NixOS, and avoid unsafe direct edits to system state. Split internal Rust crates by responsibility only when there is a demonstrated need.

## Planned milestones

| Milestone | Outcome |
| --- | --- |
| 0.1 | NixOS flake and bootable VM with basic Hyprland |
| 0.2 | Obsidian Forge desktop, audio, browser and media |
| 0.3 | OpenCode, Isenguard, and selectable container development profile |
| 0.4 | Persistent Btrfs subvolumes and documented safe reinstall tests |
| 0.5 | Initial Rust `edos` commands and storage reporting |
| 0.6 | Custom installation ISO, automated smoke tests, recovery tests |
| 1.0 | Daily-driver candidate after hardware, security, update and recovery validation |

## Non-goals for v1

- Writing a custom kernel or replacing systemd/Nix/Hyprland.
- A new package manager.
- Automatic repartitioning of user disks.
- Promising every old virtual environment or binary survives major upgrades.
- Automatic deletion of valuable data under storage pressure.

## Next engineering steps

1. Establish a pinned flake with a minimal NixOS VM target.
2. Implement basic Hyprland/session/audio modules and VM smoke tests.
3. Add OpenCode and the Isenguard package/configuration integration.
4. Prototype Btrfs `@root`, `@nix`, and `@home` on a throwaway VM disk.
5. Add a minimal Rust `edos status` command with tests.

---

This document records initial decisions; implementation should be validated against current upstream NixOS and application modules before deployment.
