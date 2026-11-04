# OpenCode on eduardOS

**Milestone:** v0.3 — Summoning the Agents (part 1)

OpenCode is installed as a system package from the locked Nixpkgs revision.
It does not run automatically as a server, and no API credentials or model
providers are configured by default.

After logging into the eduardOS VM, verify:

```sh
opencode --version
```

OpenCode's user configuration and its credentials should be configured
through supported user-level flows. Never store plaintext provider tokens
in Nix expressions or commit them to this repository.

## Agent access and trust

An AI coding agent may execute tools and modify files. eduardOS should
default to user-scoped operation and explicit permission policies, not
unrestricted root access. A privileged service is **not** required for
the standard terminal agent workflow.

## Follow-up

- Integrate Home Manager for durable user configuration.
- Package Isenguard.nvim from an immutable, pinned source revision.
- Add an isolated user-level agent smoke test (without API credentials).
- Add opt-in agent profiles and MCP setup screens.

The v0.3 milestone is incomplete until those follow-ups land.
