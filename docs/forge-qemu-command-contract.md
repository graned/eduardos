# PR #42 — Reviewed QEMU execution contract (no new writer)

**eduardOS — Forged in Neon** | Alpha 0.2 → Alpha 2.0

## Why this PR exists

PR #41 completed the non-destructive integration of operator consent,
read-only physical disk reviews and authenticated sealed credential
transport. eduardOS already has a separate QEMU-only lab formatter
(`forge_executor_lab.py`), proven through a full encrypted install and
cold reboot with a real user. Before evolving that test path toward a
production physical installer, the *exact actions at the irreversible
boundary* need a reviewable, CI-enforced command contract.

PR #42 defines that contract and **does not connect it to a new
executor**. No root socket permissions, GUI, ISO, Disko layout, boot
profile, credential handling or destructive QEMU runner are changed.

## Static allowlist (not authorization)

The new `installer/forge_lab_command_policy.py` is a PURE
non-executable library. It imports no `subprocess` module and cannot
run or authorize commands.

`review_commands(disko_script, system_closure)` validates that both
inputs are under `/nix/store`, rejects traversal, shell-like values
or symlinks resolving outside the store, checks the expected file vs.
directory types, and produces exactly two immutable descriptions:

1. **Disposable QEMU Disko layout**: the selected immutable script
   with the exact existing `--yes-wipe-all-disks` option.
2. **Disposable QEMU NixOS installation**: `nixos-install` with
   `--root /mnt --system <Nix-store-closure> --no-root-passwd`.

These are snapshots of the **existing** lab executor behavior, not
commands newly introduced or executed by the policy. The tool cannot
choose a target disk: `TARGET` is hardcoded to `/dev/vda` and the
review explicitly carries `executable: false`,
`write_operations_enabled: false` and
`authorization_to_write: false`.

A Nix store path and a manifest hash are **not proof of root-side
permission to erase a disk**. The future execution service must have
an independently audited local authorization policy.

## Irreversible boundary precondition

The separate read-only `review_kernel_boundary` helper accepts
fresh, caller-supplied kernel `lsblk`, mountinfo, swap and loop
backing evidence. It invokes the existing audited
`forge_privileged_guard.guard_topology` with the **fixed QEMU-only**
`/dev/vda` target.

It refuses if:

- The selected kernel major:minor has changed or is malformed.
- The root, live ISO backing media, mounted filesystems, or active
  swap can be traced to the target disk.
- The kernel topology cannot be established unambiguously.
- Any check claims that writes were authorized.

It returns **only** a fixed, redacted, read-only evidence result;
no FD, secret, executable callback, consent token or writer handle.

**Important:** This helper is NOT yet wired to the destructive
formatter. A future integration PR must call it with *real fresh kernel
evidence* **immediately before** Disko, while independently holding
and revalidating the target's O_RDONLY block device descriptor.
It must not substitute fixture data for real kernel state.

## CI policy regression tripwire

The fast `forge-lab-command-contract-tests` check:

- Asserts that the two reviewed argv tuples match the **actual
  `subprocess.run` command lists** currently present inside
  `forge_executor_lab.install`. An unexpected argument or command
  name change must therefore fail CI rather than silently drifting.
- Refuses non-store paths, parent traversal, arbitrary CLI arguments
  and symlinks escaping the Nix store.
- Tests wrong major:minor, an altered target, and refused swap or
  mount ancestry responses.
- Verifies root-owned session gates remain in the lab executor and
  all resulting preview flags are non-executable.
- Asserts the new contract has no subprocess, Disko invocation,
  formatting or installation entrypoint.

```sh
nix build --no-link --print-build-logs \
  .#checks.x86_64-linux.forge-lab-command-contract-tests
```

Regular PR CI also keeps the real root/non-root adversarial QEMU test,
encrypted persistence, Hyprland and other security fixtures enabled.

The separate full encrypted QEMU installation workflow does not need
to rerun **for this review-only PR** because the actual destructive
lab code and installed system are unchanged.

## Next PR — live disposable-QEMU irreversible-boundary integration

Bind this reviewed policy to the existing guarded formatter by
freshly checking kernel mount, swap, disk identity and boot-device
ancestry **inside its held-FD lifetime just before the first write**.
Test changed targets, lost mount evidence, failure during formatting
and non-replay with disposable QEMU; run the full encrypted installation
workflow on that branch before merging.

Only after the end-to-end QEMU path succeeds should we consider a
separately reviewed *physical-hardware* service with explicit local
user presence, safely authenticated credentials, a fixed operation
allowlist, and recovery behavior.

**No physical disk writes are enabled by PR #42.**
