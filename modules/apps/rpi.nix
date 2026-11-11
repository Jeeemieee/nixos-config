# Raspberry Pi Imager for writing SD cards; users opt in by importing homeManager.rpi
{
  flake.modules.homeManager.rpi =
    { pkgs, ... }:
    {
      home.packages = [ pkgs.rpi-imager ];
    };
}
