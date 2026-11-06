# Building eduardOS with Docker and nixbuild.net

This is the recommended **Apple Silicon Mac** build path for the x86_64
eduardOS Alpha ISO. No host Nix installation, Nix daemon, macOS SSH
configuration changes, or GitHub Actions build is required.

Nix runs as a client **inside Docker**; nixbuild.net executes x86_64
derivations via SSH. The resulting ISO is copied into `out/` on your Mac.

## Requirements

- Docker Desktop (or compatible Docker/Compose) installed and running.
- An active nixbuild.net account with an SSH **public key** registered.
- The matching private key on your Mac (prefer a dedicated unencrypted
  build-only key; do not give Docker access to your general-purpose SSH
  identity). A passphrase-protected key won't work with unattended SSH.
- Enough free **Docker Desktop disk capacity** for downloaded Nix outputs
  and an ISO: start with 30–50 GiB, and increase if required. A remote
  build still downloads the final store output to the container.
- `git` locally to clone the repository. No other host tooling is required.

## One-time setup

Clone the repository, if not already present:

```sh
git clone https://github.com/graned/eduardos.git
cd eduardos
git switch fix/live-iso-runner-disk-space
```

If you don't yet have a dedicated key, create one locally (this only
creates two files, and doesn't modify SSH configuration):

```sh
ssh-keygen -t ed25519 -N '' -f "$HOME/.ssh/eduardos_nixbuild" -C eduardos-nixbuild
```

Register **only the contents of** `~/.ssh/eduardos_nixbuild.pub` on
nixbuild.net. Never upload the private key.

Select the private key you actually registered (existing keys also work):

```sh
export NIXBUILD_SSH_KEY="$HOME/.ssh/eduardos_nixbuild"
```

The key path **must be absolute**. Docker mounts this private key
read-only into the container at `/run/secrets/nixbuild_key`.
It is not copied into the image, the repo, or the ISO. The published
nixbuild.net SSH host key is pinned inside the image, so no changes to
`~/.ssh/config` or macOS known_hosts are necessary.

## Build the live ISO

From the repository root:

```sh
docker compose -f builder/compose.yml run --build --rm iso
```

On success, the files are:

- `out/eduardos-alpha.iso`
- `out/SHA256SUMS`

Verify the image on macOS:

```sh
cd out
shasum -a 256 eduardos-alpha.iso
cat SHA256SUMS
```

Compare the hashes. The ISO can then be attached to a UTM x86_64
**emulated** guest or a native x86_64 QEMU/KVM VM; see `docs/live-iso.md`.

## How it works

- `builder/Dockerfile` uses the official Nix container plus OpenSSH.
- `builder/compose.yml` runs its Nix client as `linux/amd64` using
  Docker Desktop's emulation support on Apple Silicon.
- `builder/build.sh` sets `--max-jobs 0` and **only one** x86_64
  SSH builder, so x86_64 compilation is not executed locally.
- `nix-data` is a persistent Docker volume for the container's Nix
  installation and downloaded build results.
- Source files are mounted read-only and output artifacts go to `out/`.
- No host SSH configuration, macOS Nix installation, or GitHub secrets.

Even if all derivations build remotely, evaluating flakes in an
emulated amd64 CLI can be slower than on a native Linux system.
The Docker disk allocation must be large enough for the Nix store and
ISO. nixbuild.net build usage can consume free CPU-hour credits.

## Troubleshooting

**SSH: Permission denied (publickey)**: Ensure the private key selected
by `NIXBUILD_SSH_KEY` matches the registered public key and is usable
without an interactive passphrase.

**SSH host key mismatch**: Stop. Verify nixbuild.net's official published
host key before changing `builder/Dockerfile`:
https://docs.nixbuild.net/getting-started/

**Not enough free disk space**: Increase Docker Desktop's disk image limit
and available host storage. The previous GitHub-hosted build ran out of
space when `xorriso` tried to write a 2.5+ GiB ISO.

**Nix tries building locally**: The Docker command explicitly sets
`--max-jobs 0`. If remote scheduling fails, inspect the builder
authentication/error rather than enabling local builds.

**Docker doesn't have permission to share the key**: Give Docker Desktop
access to that specific file path, or create the dedicated key under
`~/.ssh` and mount it using the absolute path shown above.

**Need to reclaim space**: `docker compose -f builder/compose.yml down`
stops services but keeps the persistent Nix volume. Removing that volume
will delete cached Nix data and force future downloads. `out/` is a
normal host directory and is not removed automatically.

## Security and scope

The container can read the mounted private key while it runs, so use a
separate key registered with nixbuild.net and revoke it there if needed.
The build image pulls Nix packages to install OpenSSH and contacts
nixbuild.net to execute builds. Do not run builds on untrusted branches
with sensitive credentials mounted.

The ISO itself is still **experimental**; Docker does not prove it boots
or that Hyprland can render in UTM. This replaces the convenience of
GitHub-hosted ISO builds, not the need for VM validation.
