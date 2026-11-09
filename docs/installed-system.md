# Installed eduardOS target profile (PR #27)

**This is a declarative target system, not an installation command. No ISO
build and no physical disk writes are introduced by this PR.**

Previous milestones established a bootable Alpha 0.1 live ISO and a
destructive QEMU test-lab installation profile. The lab profile uses
`/dev/vda` and is deliberately unsuitable for physical hardware.
The new `hosts/installed/default.nix` describes an eventual real
installation without inheriting the lab/live environment's demo account,
hard-coded disk selection or public password.

## Required inputs

The flake exports an **evaluation-only factory** under
`lib.x86_64-linux.mkInstalledSystem`:

- `diskDevice`: an explicit `/dev/disk/by-id/...` identifier;
  `/dev/sda` and `/dev/vda` are rejected.
- `username`: an unprivileged Linux login name; reserved users
  (`root`, `nixbld`, `forge`, `greeter`) are rejected.
- `hostname`: an explicit lowercase host name.

Illustrative Nix evaluation only (the disk identifier below does not
exist and must never be used for actual installation):

```nix
let
  flake = builtins.getFlake "/path/to/eduardos";
  target = flake.lib.x86_64-linux.mkInstalledSystem {
    diskDevice = "/dev/disk/by-id/wwn-0xEDOS-NONEXISTENT-FIXTURE";
    username = "testpilot";
    hostname = "edos-installed-preview";
  };
in target.config.networking.hostName
```

No preconfigured physical installation closure is exported in
`nixosConfigurations`. Callers must supply all required values. The
existing lab system and its disposable QEMU-only executor remain
unchanged.

## Target behavior

- Same declarative GPT, 1 GiB EFI, LUKS2 + Btrfs Disko layout and all
  six mountpoints as the lab installation.
- UEFI/systemd-boot with a systemd initrd and interactive LUKS unlock.
- Hyprland, Ghostty, Catppuccin-themed Zsh and the existing eduardOS
  desktop/development modules.
- Interactive `greetd` / `tuigreet` login; no auto-login and **no**
  public `forge` demonstration account.
- A normal wheel/network/audio/video user plus a minimal personalized
  Home Manager profile at `home/installed.nix`.
- Immutable declarative users; root password login is disabled.
  Wheel requires the user's password for sudo.

## Password provisioning is deliberately NOT included

The installed user has a **runtime-only hashed-password file path**:

```text
/persist/eduardos/credentials/<username>.hash
```

It is an ordinary path *string* in Nix configuration, never a path literal
copied into the world-readable Nix store. A future privileged installer
must create the directory with safe ownership/mode and write a properly
salted password hash (one line, mode 0600) **on the encrypted target
filesystem**, before the first activation. It must validate this file
and never pass a plaintext password or hash via command-line arguments,
environment variables, logs or the Nix store.

**The installed system will not be login-ready until the credential
provisioner is implemented and tested.** PR #27 does not collect or
transport credentials, and it cannot be used to erase a target disk.

## Fast tests without an ISO

```sh
nix build --no-link -L .#checks.x86_64-linux.installed-profile-config
```

The Nix evaluation check uses a deliberately nonexistent stable disk
path. It validates UEFI, GPT/LUKS2/Btrfs configuration, generated mounts,
a non-lab username/hostname, correct Home Manager targeting, disabled
root password login, the runtime hashed-password file, and a configured
interactive greeter. It neither builds the complete OS closure nor
creates/opens any disk.

## Remaining milestones toward installable Alpha 0.2

1. Independently privileged, narrowly authorized disk writer with
   last-moment identity/boot-media and device-handle checks.
2. Secure LUKS and account credential handoff and provisioning.
3. Connect the graphical wizard to the guarded installer protocol.
4. Install the *new* target profile in a disposable VM; cold boot
   with its user, LUKS unlock and Home Manager activation.
5. Run full ISO/UTM integration testing at the strategic Alpha 0.2
   release milestone, not on every PR.

**No real-machine installation should be attempted yet.**
