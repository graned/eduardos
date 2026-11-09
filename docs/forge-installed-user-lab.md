# PR #32 — Installed-user profile and login inside disposable QEMU

**Test-lab integration only. No physical-disk installer, GUI install action,
ISO rebuild, or downloadable image.** This milestone exercises the same
parameterized installed-system profile introduced in PR #27 with the
credential hash staging introduced in PR #28.

## Real installed-system profile in the test VM

The manual/nightly full-installation test now builds and installs a
QEMU-instrumented instance of `mkInstalledSystem` with:

- Explicit installed user: `testpilot`
- Hostname: `edos-installed-lab`
- Disk ID: `/dev/disk/by-id/virtio-root`, provided by NixOS QEMU's
  root-drive serial `root`.
- Encrypted `/@persist` mounted during initrd via
  `fileSystems."/persist".neededForBoot = true`, because NixOS immutable
  user activation reads `hashedPasswordFile` before ordinary stage-2 mounts.
  This avoids creating a locked account when the hash file is present
  on disk but unavailable during early activation.
- A local interactive `greetd` greeter; **no auto-login**.
- Root password login disabled, sudo requiring the user's password,
  no live-ISO demo `forge` account.
- Home Manager loaded for `/home/testpilot`.
- `pamtester` installed **only in the QEMU fixture** to test actual
  PAM password challenges with the privileges of the real login daemon.

The physical profile's required by-id identifier, account identity and
host name validation are not weakened. The original formatter remains
hard-locked to **disposable QEMU /dev/vda**; no physical-target
parameter was added.

## Runtime password hash staging

The QEMU-only executor now requires `--user-password-stdin` in execute
mode and reads one valid password from the caller's standard input.
Missing, empty, malformed, too-short, line-break-containing, or
oversized input is rejected **before the test disk is formatted**.

The full integration test supplies a **public, disposable fixture
password** from a private `/run` tmpfs file. This known value appears
in test sources solely to validate login and MUST NEVER be reused as a
real account password.

After Disko has formatted the disposable target, the executor:

1. Re-runs the real encrypted mount audit for the six expected
   Btrfs/EFI mountpoints and proves their backing device is `/dev/vda`.
2. Opens the mounted `/mnt` directory without following symlinks.
3. Verifies root and persist directory **kernel mount IDs** from
   `/proc/self/fdinfo` match the audited `/proc/self/mountinfo` entries;
   requires root ownership. This is Btrfs subvolume-safe.
4. Hashes the password using salted SHA-512-crypt via OpenSSL stdin.
   No password/hash is added to CLI argv, environment variables or Nix
   evaluation, and the hash is not embedded in the store.
5. Rechecks the disk/mount audit, then atomically creates the 0600 hash
   file in the 0700 credentials directory on encrypted `@persist`.
6. Only after staging succeeds, invokes the existing
   `nixos-install --system <installed-user-closure>`.

The public fixture input file is deleted immediately after installation.

## Actual full-boot validation

In `checks.x86_64-linux.uefi-installed-boot` (the existing
manual/nightly GitHub Actions workflow), the disposable disk is:

- Partitioned via the existing guarded Disko lab executor.
- Verified to contain the user hash on encrypted `/persist` with 0600
  permissions and private credential directories.
- Cold-booted with OVMF, unlocking LUKS2 interactively.
- Checked for `testpilot`, active `greetd`, absent `forge`, and a
  nonempty shadow password hash.
- Authenticated through both the **greetd** and **login** PAM stacks
  with a privileged PAM caller (as the real greetd/login daemons use).
  The correct public fixture credential MUST succeed and an incorrect
  credential MUST fail for each stack. Running the test as `nobody`
  would trigger `unix_chkpwd`'s cross-account privilege restriction,
  producing a false failure rather than testing greetd's actual path.
- Written to as `testpilot`, shut down and cold-booted a second time.
- Checked for persistence of encrypted user-home files and the account
  password hash after the second boot.

This tests the operating-system password/PAM path, including a negative
password challenge; it does **not**
simulate clicking or typing into the graphical tuigreet interface.
Actual GUI login automation remains for a future milestone.

## Build and verification policy

Fast PR CI runs the existing mocked lab executor tests and a new
Nix evaluation check:

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-installer-lab-tests
nix build --no-link -L .#checks.x86_64-linux.installed-user-lab-config
```

The expensive full installed-system/QEMU test remains in
`.github/workflows/full-install.yml`, which is manually dispatchable
on the PR branch or runs nightly on `main`.

```sh
nix build --no-link -L .#checks.x86_64-linux.uefi-installed-boot
```

**Do not interpret green fast CI alone as a successful real-user boot.**
Run the full installation workflow on this PR's branch before merging,
as with PR #31. No multi-GB ISO build is performed in either workflow.

## Still required before Alpha 0.2

- An independently reviewed physical-disk installer trust boundary,
  live-media protection and narrow privileged execution service.
- Production-only secure credential collection/transport, without the
  publicly known QEMU test fixture or plaintext tmpfs rehearsal file.
- GUI installation execution integration and recovery/failure UX.
- Interactive desktop greeter testing and final installable-ISO
  validation in a disposable VM and UTM/physical test machine.

**Never use the lab executor on a physical disk.**
