# libvirt with virt-manager; hosts opt in by importing nixos.libvirt and adding users to the libvirtd group
{
  flake.modules.nixos.libvirt = {
    virtualisation.libvirtd.enable = true;
    programs.virt-manager.enable = true;
    # virsh and virt-manager use the system connection, where the VMs of this module live, not the empty per-user one
    environment.sessionVariables.LIBVIRT_DEFAULT_URI = "qemu:///system";
  };
}
