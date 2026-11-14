# Laptop hardware services; hosts opt in by importing nixos.laptop
{
  flake.modules.nixos.laptop = {
    # Firmware for Wi-Fi, Bluetooth, audio and graphics
    hardware.enableRedistributableFirmware = true;

    hardware.bluetooth.enable = true;

    # Authorises Thunderbolt docks; Plasma's settings page talks to this daemon
    services.hardware.bolt.enable = true;

    # Watches the disks' health (SMART) and warns on the desktop when a disk starts to fail
    services.smartd = {
      enable = true;
      notifications.systembus-notify.enable = true;
    };
  };
}
