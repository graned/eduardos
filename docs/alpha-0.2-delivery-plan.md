# eduardOS Alpha 0.2 delivery plan — Rust developer engine + safe installation

**Status:** proposed execution baseline; updated 2026-11-10. **Ultimate goal:** Alpha 2.0.
**Release criterion:** an installable, encrypted eduardOS ISO with a useful, safe,
reproducible developer experience, verified end-to-end in disposable QEMU and
on a tightly scoped real-UEFI hardware matrix.

The PR numbers below are **planning slots**, not created GitHub PRs or
guaranteed issue numbers. Rebase/resequence if GitHub assigns numbers
differently. One reviewable deliverable per PR; if an integration needs
splitting to keep CI green, update this table rather than claiming it done.

## Product vision: a developer-focused NixOS distro

A developer should be able to clone a project, understand its environment,
bring up explicitly trusted services, inspect their health and cleanly stop
them without configuring the entire machine manually.

- **NixOS/Nix:** reproducible package versions, environments, generations,
  ISO images, and rollback primitives.
- **Rust:** lightweight, unprivileged `edos` CLI with project detection,
  developer environment orchestration, process ownership, observability,
  and eventual versioned interfaces.
- **Python:** retain Forge installer, existing safety logic and test harness;
  introduce a typed interface only when a concrete cross-language need exists.
- **systemd/cgroups:** ownership, limits and supervision of user services,
  not a custom Linux process scheduler.
- **Docker/Podman:** optional existing engines for project-defined containers;
  no forced global daemon, no silent container startup.
- **Ghostty/Isenguard/OpenCode:** optional integrations for terminal,
  editor and AI-assisted workflows. No background AI agent or automatic
  external data transfer.
- **Home Manager:** user-controlled dotfiles and per-user configuration.
  Never overwrite an existing unmanaged configuration without consent.

### Alpha 0.2 developer-engine MVP — required, not just an idea

1. `edos doctor`: genuinely useful **read-only** checks of OS generation,
   shell/desktop session, available dev tooling, basic resource status;
   clear failure and missing-component reporting.
2. `edos dev inspect [path]`: **read-only, offline** recognition of
   `flake.nix`, `devshell.toml`, `go.mod`, `Cargo.toml`, Node manifests,
   Python manifests and Compose files. Never execute untrusted repository
   configuration to inspect it; report ambiguous/conflicting detections.
3. `edos dev init`: opt-in template generation only, explicit previews,
   refuse overwrite, and support Go, Rust, Node and Python. No hardcoded
   personal paths or credentials.
4. `edos dev up/down/status`: scoped process/Compose lifecycle for
   explicitly approved, project-owned manifests; no arbitrary shell commands
   in a privileged daemon, no implicit `docker compose up` just from
   opening a repo; stable exit/error propagation and cancellation.
5. `edos dev stats`: inspect owned process and cgroup resource usage
   where available, with safe fallback and meaningful output, without
   constantly running a resource-hungry watcher.
6. `edos workspace open` and `edos dev context`: a safe optional
   workspace launch and local structured environment summary for editors
   or OpenCode. Redact credentials and paths that could leak secrets;
   no uploads, no telemetry, and no automatic model requests.
7. Dedicated unit/integration CI, Nix packaging and user documentation for
   all shipped commands, plus an ISO smoke test. **No requirement to port
   Python Forge to Rust or use PyO3.**

### Explicit non-goals for Alpha 0.2

- Kernel modifications, faster fork/exec claims or replacing systemd.
- A privileged Rust daemon, automatic system tuning, opaque scheduler
  behavior, hidden process killers, or live resource profiling by default.
- Universal automatic detection of every project language/framework.
- Automatic `nix develop`, execution of flake-provided shell hooks, network
  downloads, or container starts before informed user approval.
- AI autonomy, sending project contents externally, or storing API secrets
  in the Nix store. Advanced AI and adaptive CPU profiles can be Alpha 0.3+.

## Full remaining PR sequence to Alpha 0.2

| Slot | Track | Deliverable | Acceptance gate |
| --- | --- | --- | --- |
| **#49 (open)** | Installer | Mounted-target refusal in disposable QEMU | Disk and sentinel remain intact; Disko not invoked; all CI green |
| **#50 (this plan)** | Roadmap | Commit agreed developer vision and delivery gates | User reviews PR list and scope; docs-only CI |
| **#51** | Rust | `edos doctor` v2: real read-only OS, session and tool diagnostics | Unit tests + missing subsystem graceful fallbacks; build under Nix |
| **#52** | Rust | `edos dev inspect`: offline project/manifests detection | Go/Rust/Node/Python/Nix/Compose fixtures; symlink/path traversal and no-execution tests |
| **#53** | Rust | `edos dev init`: preview/consent, project templates | No overwrite; no secret injection; deterministic fixture outputs |
| **#54** | Rust | Explicit Nix dev-shell integration with trust boundaries | Show planned command, require consent before evaluation/execution; safe cancellation |
| **#55** | Rust | `edos dev up/down/status` for approved project processes and Compose | Child process groups stopped on exit; errors surfaced; no rogue services |
| **#56** | Rust | `edos dev stats`: project-aware resource inspection | Read-only cgroup/process tests, no elevated privileges or idle daemon |
| **#57** | Rust | `edos workspace open` + `edos dev context`, developer UX docs | Opt-in editor launch; redaction tests; no network/AI invocation |
| **#58** | Installer | QEMU after-review mount/hotplug/identity-change and cancellation boundary tests | Refuse before irreversible write; existing encrypted install still passes |
| **#59** | Installer | Trusted root executor: independently authorize exact device and operation | Allowlist; physical disk writes still disabled; adversarial root/non-root tests |
| **#60** | Installer | Persistent attempt state, lock, refusal and recovery policy | Reboot/interruption tests; no automatic destructive retry |
| **#61** | Installer | Secure runtime LUKS/account credential consumption in executor | No plaintext argv/env/Nix store; FD ownership/zeroization and denial tests |
| **#62** | Installer | Wire Forge GUI to narrowly scoped service / consent sequence | GUI is never root; spoofing and invalid request tests |
| **#63** | Installer | GUI setup: disk identity, hostname, user, encryption and full preview | Unambiguous irreversible confirmation; safe edits/cancellation |
| **#64** | Installer | Progress, cancellation and partial-failure recovery UX | Honest phase states; no retry after partial format |
| **#65** | Integration | First physical-write-capable **gated** installation in disposable QEMU | Only VM image gets written; real encrypted boot/login; no host device access |
| **#66** | Integration | Build installable Alpha 0.2 ISO and automate GUI-to-boot smoke | ISO contains real installer, Rust dev engine, selected desktop; repeated encrypted cold boots |
| **#67** | Release | Controlled UEFI real-hardware qualification, documentation and checksums | Explicit test matrix, safe target identification, backup warning, signed/hashed artifacts policy |
| **#68** | Release | Alpha 0.2 release-candidate gate | All release tests green, hardware evidence recorded, known limitations published |

**Current plan: 20 slots (#49–#68 inclusive): one already open, one
roadmap change, seven Rust implementation slots, eight installer/integration
slots and two release slots, plus any safety follow-ups.** Counting is
indicative; schedule changes are made explicitly in this file.

## Execution order and strict dependencies

- Finish #49 first; #50 may merge independently because it is documentation.
- Ship #51–#57 before release (the agreed developer-first identity).
  Keep the Rust tools usable without root and without replacing Python.
- #58 must pass before enabling any real physical disk execution.
- #59–#61 are security gates; a manifest or UI confirmation alone must
  never authorize writes. No generic shell command RPC.
- #62–#64 connect UI to independently validated service operations.
- #65 must operate only in isolated, disposable QEMU. Do not claim
  a VM pass implies safe arbitrary physical hardware.
- #66–#68 validate the **same distribution artifact** that would ship.
  Only then consider a public Alpha 0.2 release.
- If any gate fails, pause subsequent unsafe work, fix it in the same PR,
  and add a regression test. **User merges every PR**.

## Release checklist (everything required before declaring Alpha 0.2)

- [ ] All #49–#68 scope items merged or explicitly rescheduled with
      release criteria preserved.
- [ ] Rust developer commands shipped in live and installed profiles;
      CLI/tests/documentation verified.
- [ ] Developer engine does not silently execute a newly cloned repo's
      Nix flake, Compose configuration, scripts, or AI integrations.
- [ ] Physical executor re-verifies selected disk, protected root/boot/
      swap ancestry, topology and current consent immediately before write.
- [ ] No plaintext LUKS/user secrets in argv, environment, logs or Nix store.
- [ ] GUI is non-root; consent is explicit and independently validated.
- [ ] Fault injection covers mount changes, hotplug, cancellation,
      partial formatting and cold-boot recovery in disposable QEMU.
- [ ] Alpha 0.2 installable ISO successfully completes GUI-to-encrypted-
      boot-to-user-login repeatedly in isolated QEMU.
- [ ] Hardware qualification and honest release limitations documented.
- [ ] ISO checksums/provenance, installation/recovery instructions and
      release artifact verification published.

## Later milestones

**Alpha 0.3:** enhanced recovery, multi-generational rollback, Btrfs snapshot
policy, broader hardware support, system updates, advanced workspace profiles
and optional resource controls.

**Alpha 1.x:** daily-driver UX, user configuration migration, polished
multi-monitor/laptop support, container workflows, better AI editor
integration, signing and release-channel reliability.

**Alpha 2.0:** production-grade installation/update/rollback/recovery,
hardware coverage, audit-ready trust boundaries and reproducible releases.

⚡ eduardOS — Forged in Neon.
