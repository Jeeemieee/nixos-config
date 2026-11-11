# libvirt with virt-manager; hosts opt in by importing nixos.libvirt and adding users to the libvirtd group
{
  flake.modules.nixos.libvirt = {
    virtualisation.libvirtd.enable = true;
    programs.virt-manager.enable = true;
  };
}
