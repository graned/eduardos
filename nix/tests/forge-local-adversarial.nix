{ pkgs }:

# Dedicated disposable NixOS guest. Tests REAL root/nobody, SO_PEERCRED,
# pidfds, SOCK_SEQPACKET, and private Unix-socket permissions.
# The physical disk backend is mocked and no writer is installed.
pkgs.testers.runNixOSTest {
  name = "eduardos-forge-adversarial-root-peers";
  meta.timeout = 600;

  nodes.machine = { ... }: {
    networking.hostName = "edos-forge-adversarial";
    system.stateVersion = "26.05";

    virtualisation.memorySize = 1024;
    virtualisation.cores = 2;
    environment.systemPackages = [ pkgs.python3 ];
    system.extraDependencies = [ ../../installer ];
  };

  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.succeed("test \"$(id -u)\" = 0")
    machine.succeed("test -c /dev/tty1")
    with subtest("Real-kernel root/non-root installer boundary attacks"):
        machine.succeed(
            "${pkgs.python3}/bin/python3 -B "
            "${../../installer}/test_forge_vm_adversarial.py",
            timeout=180,
        )
    machine.succeed("test ! -e /run/eduardos/forge-preflight.sock")
    machine.succeed("test ! -e /dev/vdb1")
  '';
}
