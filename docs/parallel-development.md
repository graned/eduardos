# Parallel development discipline for eduardOS

Two active lanes after merged PR #53:

- **Rust developer engine:** PR #54 offline project inspection. Follow-up
  feature PRs can proceed after their CLI interface is reviewed.
- **Installer safety:** PR #55 real QEMU after-review mount race. Future
  identity/hotplug tests proceed independently of Rust and never enable
  physical writes before authorization tests pass.

Each feature branch starts from main. Prefer files disjoint between lanes;
only the release-roadmap coordination PR updates shared status files.
Avoid stacking a new feature PR atop an unrelated in-progress PR.
Use a separate selective workflow for expensive QEMU fault injection,
while retaining fast CI and mandatory full-install checks for changes
that alter the actual disk writer, credentials or installed profile.

Parallel **implementation** does not weaken release gates: no merge if
required checks are red, cancelled or pending; no physical installer
writes until independent device rechecks, root authorization, secret
transport, interruption/recovery and disposable-QEMU acceptance pass.

Review and merge order is determined by real dependencies and green CI,
not GitHub PR numbers. Update delivery-plan planning slots when a parallel
PR takes a number previously reserved for another item.
