# Common laptop hardware
#
# What it is    Firmware, Bluetooth, Thunderbolt authorisation and disk-health monitoring
# Who uses it   A NixOS host by importing nixos.laptop
# A host adds   Its machine-specific hardware configuration beside this shared module
# Protected     No: these services support hardware but do not define disk layout, boot or accounts
{
  flake.modules.nixos.laptop = {
    # Firmware for Wi-Fi, Bluetooth, audio and graphics
    hardware.enableRedistributableFirmware = true;

    # Enable the Bluetooth controller for peripherals and audio devices
    hardware.bluetooth.enable = true;

    # Authorise Thunderbolt docks through the daemon used by Plasma's settings page
    services.hardware.bolt.enable = true;

    # Watch SMART disk health and send a desktop warning when a disk starts to fail
    services.smartd = {
      # Start the disk-health monitor
      enable = true;

      # Deliver its warnings through the desktop notification bus
      notifications.systembus-notify.enable = true;
    };
  };
}
