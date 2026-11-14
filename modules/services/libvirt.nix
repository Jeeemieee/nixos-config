# System virtual machines
#
# What it is    libvirt's system service and the virt-manager desktop application
# Who uses it   A NixOS host by importing nixos.libvirt; the workstation profile imports it
# A host adds   Trusted users to the libvirtd group because managing system VMs is close to root
# Protected     No: account membership remains in the protected workstation profile
{
  flake.modules.nixos.libvirt = {
    # Start the service that owns and runs system-wide virtual machines
    virtualisation.libvirtd.enable = true;

    # Install the graphical manager used to create and control those machines
    programs.virt-manager.enable = true;
    # Point virsh and virt-manager at the system connection where these VMs live
    environment.sessionVariables.LIBVIRT_DEFAULT_URI = "qemu:///system";
  };
}
