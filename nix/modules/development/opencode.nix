{ pkgs, ... }:

{
  # OpenCode is packaged in the pinned Nixpkgs snapshot.
  # The CLI is installed; no agent daemon or remote server is started.
  environment.systemPackages = [ pkgs.opencode ];

  # Provider API keys, tokens and per-user settings must NOT be placed
  # into world-readable Nix store derivations or system declarations.
}
