# Rust developer project detection

`edos dev inspect [path]` is **offline, read-only and unprivileged**.
It checks only whether recognized manifest **regular files** exist in the
specified top-level directory; it does **not parse, evaluate or execute**
`flake.nix`, Compose, Cargo manifests, shell hooks, scripts or package
installers. A cloned repository is always treated as untrusted.

Supported markers include `go.mod`, `Cargo.toml`, `package.json`,
`pyproject.toml`, `requirements.txt`, `Pipfile`,
`uv.lock`, `flake.nix`, `devshell.toml`, `compose.yaml`,
`compose.yml` and `docker-compose.yml/yaml`.

The command reports every detected ecosystem instead of arbitrarily
choosing a language. Symlinked roots, intermediate symlinks and
`..` path traversal are rejected; symlinked or unreadable manifest
entries are skipped. No project or secret path is echoed in the result.
No state is created and no network request is made.

```sh
edos dev inspect
edos dev inspect ./my-project
```

This deliberately does **not** create environments, install dependencies,
start containers or evaluate Nix. Those capabilities require separate,
opt-in follow-up PRs.

Test it with `cargo test -p edos` or
`nix build .#checks.x86_64-linux.edos-cli-tests -L`.
