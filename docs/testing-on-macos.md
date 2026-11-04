# Testing eduardOS from macOS

eduardOS currently defines an **x86_64-linux** VM target. It cannot run
as a complete desktop in Docker; Docker is useful for evaluation and
build checks, while UTM is appropriate for full OS experiments.

## Recommended: GitHub Actions

Every PR to this repository runs the Linux build workflow
(`.github/workflows/nixos-vm.yml`) on an Ubuntu x86_64 runner.

The workflow checks the flake and attempts to build the VM launcher.
A successful workflow **does not prove** that Hyprland can start or that
the guest's graphics/audio/suspend behavior is correct. A boot smoke test
will be a separate milestone.

This is the most straightforward path on Apple Silicon because the
existing flake currently targets x86_64 Linux.

## Optional: Docker Desktop on Mac

With Docker Desktop running, check out the PR branch, then:

```sh
git clone git@github.com:graned/eduardos.git
cd eduardos
git switch feat/nixos-vm-foundation

docker run --rm -it \
  --platform linux/amd64 \
  -v "$PWD:/workspace" \
  -w /workspace \
  -e NIX_CONFIG="experimental-features = nix-command flakes" \
  nixos/nix:latest \
  sh -lc 'nix flake check --show-trace'
```

On Apple Silicon this emulates the **amd64** container architecture,
which can be significantly slower than native ARM code. For large builds,
prefer the GitHub Linux runner. Docker containers do not get a
bootable NixOS system or Hyprland window session from this command.

The Docker image's Nix version and cache behavior may vary; treat this
as a convenient configuration check, not a full release test.

## Full GUI testing with UTM

- Intel Mac: an x86_64 Linux VM can run with native architecture.
- Apple Silicon: create a **virtualized aarch64-linux** guest for
  reasonable performance, but this requires a separate aarch64 NixOS
  configuration; the current eduardOS flake targets only x86_64.
- Emulating an x86_64 guest on Apple Silicon is possible with QEMU/UTM
  but will be significantly slower and Hyprland GPU support may be poor.
- Hyprland's Wayland compositor requires working virtual graphics.
  A functional Linux console does not guarantee the graphical desktop.

Official installation images are available from https://nixos.org/download/ .
UTM: https://mac.getutm.app/

**Do not install the test VM configuration onto a physical Mac.**
The initial VM profile has intentionally insecure test credentials.
