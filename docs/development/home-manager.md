# Home Manager foundation (v0.3)

Home Manager provides declarative **user configuration**, while NixOS
manages system services and machine-level settings. It is integrated into
NixOS using a pinned `release-26.05` input that follows the same Nixpkgs
revision as the system.

The first prototype is deliberately conservative:

- The **VM-only** `forge` account receives a Home Manager profile.
- It creates `~/.config/eduardos/managed-by-home-manager`.
- It does **not** modify Isenguard, OpenCode, SSH, browser or Git settings.
- Packages installed by Home Manager use per-user profiles.
- The module is imported only for the VM and its automated boot test.

This marker is intentionally small: before we migrate existing user
configuration, we must establish safe replacement and backup policies.

## Why this matters for persistence

With `/home` mounted on a persistent Btrfs subvolume in a future
installable edition, the user's application data remains in place.
Home Manager reconstructs the *declared* configuration after a fresh
OS install. Those are complementary mechanisms, not interchangeable.

Home Manager normally refuses to replace unexpected unmanaged files.
We should provide explicit diff, backup and migration tooling through
the future `edos` CLI rather than forcing overwrites.

## Verification

The NixOS integration test now boots a guest and waits for the managed
marker to appear in the VM user's home. The test does not validate a real
disk reinstall or Btrfs preservation; those require separate VM tests.

## Next

- Manage selected shell/editor defaults in non-destructive modules.
- Define configurable profiles and identities rather than hardcode users.
- Introduce a controlled Isenguard migration from the existing
  first-run editable copy to optional declarative management.
- Validate persistent-home reinstall with Btrfs before promising it.
