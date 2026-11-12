# UEFI boot with systemd-boot; hosts opt in by importing nixos.boot
{
  flake.modules.nixos.boot = {
    boot.loader = {
      systemd-boot = {
        enable = true;
        # Older system generations stay selectable in the boot menu; the limit keeps the EFI partition from filling up
        configurationLimit = 20;
      };
      efi.canTouchEfiVariables = true;
    };

    # systemd in the first boot stage asks for the disk passphrase
    boot.initrd.systemd.enable = true;
  };
}
