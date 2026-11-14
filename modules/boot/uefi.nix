# UEFI boot
#
# What it is    systemd-boot for choosing generations and systemd in the encrypted-disk boot stage
# Who uses it   A NixOS host by importing nixos.boot; physical hosts pair it with their disk module
# A host adds   A UEFI system partition and, when wanted, nixos.secure-boot for signed boot files
# Protected     Yes: a wrong boot setting can make the machine inaccessible (docs/SECURE-BOOT.md)
{
  flake.modules.nixos.boot = {
    ## Part 1. Boot menu
    boot.loader = {
      systemd-boot = {
        # Use the simple boot menu supported by the Secure Boot module
        enable = true;

        # Keep older generations selectable without letting the EFI partition fill up
        configurationLimit = 20;
      };
      # Allow NixOS to register the boot loader with the machine's UEFI firmware
      efi.canTouchEfiVariables = true;
    };

    ## Part 2. Encrypted-disk prompt
    # Use systemd in the first boot stage so it can ask for the disk passphrase
    boot.initrd.systemd.enable = true;
  };
}
