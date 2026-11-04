# Isenguard.nvim on eduardOS

**Milestone:** v0.3 — Summoning the Agents (part 2)

Use `isenguard` to run Neovim with `NVIM_APPNAME=isenguard` rather
than replacing the normal `nvim` profile.

## Reproducible upstream source

- Repository: https://github.com/graned/isenguard.nvim
- Pinned commit: `4a83a2626aef9ea6c992854ce37d0969cc9abf57`

On first launch, the wrapper copies the pinned configuration into
`$XDG_CONFIG_HOME/isenguard` (normally `~/.config/isenguard`).
This is a **writable copy** instead of a symlink into the read-only Nix store.
An existing configuration is never automatically overwritten.

```sh
isenguard
isenguard myfile.go
```

The copy, installed plugins, and user caches survive a system reinstall
when the user's /home is retained. Upgrading the pinned source alone does
not overwrite a previously customized user profile.

## Known limitations

- The upstream configuration uses a plugin manager which can fetch
  plugins on first interactive startup, requiring internet access.
  Individual plugins and language servers have not yet been validated.
- The pinned editor source is not a full offline plugin closure.
- Future Home Manager integration should manage versioned configuration
  and support intentional migrations without destroying user overrides.
- A Nerd Font is recommended for proper icon glyphs.
- CI validates basic bootstrap and CLI startup, not interactive editor UX.

No privileged agent or global user-dotfile overwrite is introduced.
