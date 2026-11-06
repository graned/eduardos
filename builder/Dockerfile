# CLI-only container; the x86_64 OS is built remotely on nixbuild.net.
# We deliberately use linux/amd64 in Compose for predictable Nix CLI availability
# on Apple Silicon. Only evaluation/client work runs under emulation.
FROM nixos/nix:latest

RUN nix --extra-experimental-features 'nix-command flakes' profile install nixpkgs#openssh

RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh \
 && printf '%s\n' 'eu.nixbuild.net ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPIQCZc54poJ8vqawd8TraNryQeJnvH1eLpIDgbiqymM' > /root/.ssh/known_hosts \
 && printf '%s\n' \
   'Host eu.nixbuild.net' \
   '  User root' \
   '  IdentityFile /run/secrets/nixbuild_key' \
   '  IdentitiesOnly yes' \
   '  BatchMode yes' \
   '  StrictHostKeyChecking yes' \
   '  ServerAliveInterval 60' > /root/.ssh/config \
 && chmod 600 /root/.ssh/known_hosts /root/.ssh/config

COPY builder/build.sh /usr/local/bin/edos-build
RUN chmod 755 /usr/local/bin/edos-build

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/edos-build"]
