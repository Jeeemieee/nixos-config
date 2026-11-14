# Raspberry Pi Imager
#
# What it is    The graphical tool used to write Raspberry Pi system images to SD cards
# Who uses it   A Home Manager user by importing homeManager.rpi; the workstation account imports it
# A user adds   Nothing; removable-media access comes from the desktop session
# Protected     No: this is an ordinary user application
{
  flake.modules.homeManager.rpi =
    { pkgs, ... }:
    {
      # Keep the image-writing tool available without adding the wider Raspberry Pi toolchain
      home.packages = [ pkgs.rpi-imager ];
    };
}
