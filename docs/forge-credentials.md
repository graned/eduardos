# Forge Installer — Credential Provisioning (PR #28)

**Library and fixture tests only. No runnable credential writer, disk partitioning, GUI write route, or ISO build.**

PR #27's installed profile expects the user hash at:

    /persist/eduardos/credentials/<username>.hash

PR #28 adds two deliberately separate building blocks for the future trusted installer.

## User-password hashing and atomic staging

- installer/forge_credentials.py exposes hash_user_password(password), which creates a randomly salted SHA-512-crypt Linux-compatible hash through OpenSSL standard input. The password is never placed in argv, environment variables, the Nix store, or logs.
- write_user_hash(target_root_fd, username, digest) takes a trusted, already-open target-root directory descriptor rather than an arbitrary path selected by a browser or shell. It checks the user name, hash format, directory ownership and permissions, and refuses symlinks or missing /persist.
- Private root-owned credential directories (0700) and a temporary 0600 hash file are created beneath persist/eduardos/credentials. The new file is fsynced, published atomically with a create-only link, and the temporary name removed. Existing account hashes are never overwritten. An interruption must not publish a partial hash file.
- The function returns only the installed path; it does not echo password material or create the user itself.

**Critical caller responsibility:** This library does not verify that the trusted root directory descriptor points at a Disko-installed, LUKS2-encrypted filesystem. The future privileged installer MUST establish the correct mount topology and disk identity before calling it. Empty private directories may remain after a failed stage.

## Ephemeral LUKS passphrase handoff

sealed_luks_fd(passphrase) uses Linux memfd_create to hold the passphrase as a scoped anonymous file descriptor. It enables close-on-exec and applies seals against writing, growing or shrinking the secret after creation. The descriptor is closed on normal completion and exceptions, and a temporary mutable Python buffer is wiped on a best-effort basis.

The eventual privileged installer can explicitly hand this descriptor to cryptsetup via inherited file descriptors without putting the passphrase into process arguments, environment variables, or persistent files. **This PR intentionally does not invoke cryptsetup or format disks.**

These are security primitives, not a complete secrets vault: Python strings and subprocess/kernel buffers cannot be guaranteed zeroized, and privileged process introspection remains possible. Consider moving the final credential boundary to a small Rust helper.

## Validation without an ISO build

    nix build --no-link -L .#checks.x86_64-linux.forge-credentials-tests

The existing all-installer fixture check also runs this suite. CI tests cover real salted hashes, stdin-only transport, permissions, directory and symlink refusal, atomic publication failure, existing-hash preservation, malformed usernames/hashes, sealed memfd lifecycle, and failure when the kernel feature is unavailable.

All tests operate inside temporary directories with unprivileged users. No real disk is opened, mounted or modified, and no ISO is compiled.

## What remains

PR #29 will establish a narrowly privileged installation backend that independently verifies selected disks, mounted target filesystems and boot-media protection before touching any device. Later milestones can integrate secure credential collection, actually provision and activate the installed profile, and test cold boot and LUKS unlock in disposable VMs. Only then do we build the Alpha 0.2 release ISO.
