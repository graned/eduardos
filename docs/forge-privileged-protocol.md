# PR #33 — Forge privileged preflight protocol v1 (NO DISK WRITES)

## Roadmap position

PR #32 validated encrypted installation and real-user PAM authentication
inside disposable QEMU. PR #33 creates an independently reviewable,
**one-shot root-side preflight request contract** that can later be used
by a narrowly scoped privileged installer.

This is **not** a hardware installer and **does not** bridge the GUI to
root or enable physical disk modification. The only destructive path
remains the separate guarded QEMU lab executor from PRs #22–#32.

## Trust boundary

The optional package `forge-privileged-protocol` executes a single
operation, `attest-target`. It reads one bounded JSON request from
standard input and returns a single JSON response on standard output.

It must already be launched by a trusted root process. It does **not**
run `sudo`, `polkit`, `pkexec`, a Unix/TCP socket, or a service, and
does not itself create a privilege escalation path.

**Request schema:** `eduardos.forge.privileged.v1`

```json
{
  "version": "eduardos.forge.privileged.v1",
  "operation": "attest-target",
  "review": {
    "snapshot": {
      "schema": "eduardos.disk-review.v1",
      "boot_id": "<current boot UUID>",
      "stable_id": "/dev/disk/by-id/<exact reviewed device>",
      "device": { "<field>": "<reviewed lsblk field>" },
      "layout": [],
      "eligible": true,
      "blockers": []
    },
    "sha256": "<lowercase SHA-256 of reviewed snapshot>",
    "write_operations_enabled": false
  },
  "confirmation": "ERASE /dev/disk/by-id/<exact reviewed device>",
  "username": "testpilot",
  "hostname": "edos-installed"
}
```

The example illustrates field shape only: actual review data MUST be
captured using the existing `forge-disk-review` tool from the current
boot session and verified again by the root backend. No example request
is authorization to erase anything.

## Checks performed

- Root effective UID is mandatory **before reading the request**.
- Single UTF-8 JSON payload, maximum 64 KiB, rejecting duplicate keys,
  invalid JSON, unknown fields, non-finite numbers and unsupported versions.
- Only `attest-target` is accepted. No `execute`, `format`, `mount`,
  `password`, `command`, `target`, `token`, `stage-account`,
  `write_operations_enabled=true` or arbitrary extensions.
- Exact stable `/dev/disk/by-id/...` identifier and explicit matching
  `ERASE <identifier>` phrase.
- Strictly validated non-reserved username and hostname.
- Existing `forge_backend.prepare_target` independently revalidates the
  reviewed disk identity against current boot, lsblk data, active mounts
  and swap ancestry, the live-media source and the by-id symlink.
- The root backend temporarily holds **a read-only disk descriptor**;
  it is closed before response. The helper returns **no FD**, token,
  authorization capability, password, hash or executable action.
- Both success and refusal responses explicitly carry
  `write_operations_enabled=false`,
  `destructive_disk_operations_enabled=false`,
  `credential_writes_enabled=false` and
  `authorization_to_write=false`. Refusal output never echoes the
  untrusted request or device identifier.

## Security policy

A successful attestation is evidence for a **single completed read-only
operation**, not a persistent authorization. In particular, a hash of
a review snapshot is not a cryptographic signature, and the helper
is not safe to expose to untrusted users over a browser, socket, or
polkit action without a separately designed trust boundary.

No secrets are accepted. No QEMU lab install function is imported.
No filesystem write, formatting, mounted-device change, or physical
installation can be requested.

## Verification

Fast PR CI runs:

```sh
nix build --no-link -L .#checks.x86_64-linux.forge-privileged-protocol-tests
```

The test suite covers exact protocol acceptance, incorrect version,
unsupported operation, bad confirmation, non-root denial, nested
unknown fields, malformed or oversized JSON, duplicate keys and
ineligible reviews. The only success test mocks the existing root
backend and checks that the returned report grants no write authority.

**This PR does not need a full destructive QEMU installation rerun.**
It does not modify the lab executor, installed profile, storage
formatting configuration, or UEFI boot behavior. The existing
manual/nightly full-install workflow remains intact.

## Next milestones

1. Design and audit the actual privileged physical-install executor
   (separate PR), including narrowly approved Disko operations,
   binding execution to the same held disk identity, root/boot/swap
   ancestry and safe failure/recovery behavior.
2. Design secure handoff of user-entered LUKS and account secrets to
   a local root process without plaintext in Nix/store, process args,
   environment or browser APIs.
3. Integrate graphical setup only after the privileged boundary is
   independently reviewed and exhaustively tested in disposable VMs.
4. Produce and validate an Alpha 0.2 installable ISO and hardware
   compatibility matrix.

**Forge in Neon. Fail closed.**
