{ ... }:

{
  # IMPORTANT: this NixOS configuration is ONLY for disposable QEMU
  # installation evaluation. It is not an installer or physical host profile.
  networking.hostName = "eduardos-uefi-lab";
  system.stateVersion = "26.05";

  eduardos.storage.device = "/dev/vda";
  eduardos.storage.allowUnstableDeviceName = true;

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = false;
  boot.initrd.systemd.enable = true;
  boot.initrd.availableKernelModules = [
    "virtio_pci"
    "virtio_blk"
    "nvme"
    "xhci_pci"
    "usb_storage"
    "sd_mod"
  ];
  # The Disko module provides /boot, /, /home, /nix, /persist,
  # /.snapshots and the encrypted initrd unlocking configuration.
  services.fstrim.enable = true;
}
