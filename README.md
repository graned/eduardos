# eduardOS — Forged in Neon ⚡

An experimental NixOS-based Linux distribution with an Aztec-inspired
neon desktop, Hyprland, Ghostty, Catppuccin and the read-only Rust `edos`
diagnostic CLI.

**Current releases:** Alpha 0.1 live preview exists. Alpha 0.2 is currently a
**VM-only release candidate**, not yet built and accepted as a release. Its
explicit installer is guarded for disposable QEMU `/dev/vda` and is **never
supported on a physical disk**. See [Alpha 0.2 VM ISO checkpoint](docs/alpha-0.2-vm-iso-checkpoint.md).

## Preview the system

The [manual live ISO workflow](.github/workflows/live-iso.yml) builds the
current live image and verifies a diskless QEMU boot. See
[Preview ISO instructions](docs/live-iso-preview-checkpoint.md) to download,
verify, reassemble and visually review the artifact.

Build locally on a Linux system with Nix flakes:

```sh
nix build --out-link result -L .#live-iso
```

Try the Rust CLI without building the entire ISO:

```sh
nix run .#edos -- status
nix run .#edos -- doctor
```

The CLI remains read-only; the existing Python Forge code handles the
separate experimental installer and safety tests.

Track development in [ROADMAP.md](ROADMAP.md). The final release target is
**Alpha 2.0**, with a usable installable Alpha 0.2 as the next major milestone.
