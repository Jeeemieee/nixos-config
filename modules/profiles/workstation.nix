# Personal workstation: the account, desktop, applications and services shared by every personal machine
# Hosts import nixos.workstation and add their hardware, storage and state versions; it needs hostSpec.hasSecrets (Wi-Fi, Tailscale)
{ config, ... }:
let
  inherit (config.flake) modules;
in
{
  flake.modules.nixos.workstation =
    { lib, pkgs, ... }:
    {
      imports = [
        modules.nixos.desktop-kde
        modules.nixos.direnv
        modules.nixos.browser
        modules.nixos.search
        modules.nixos.fonts
        modules.nixos.vpn
        modules.nixos.wifi
        modules.nixos.docker
        modules.nixos.libvirt
      ];

      networking = {
        networkmanager.enable = true;
        useDHCP = false;
        firewall.enable = true;
      };
      services.openssh.enable = false;

      time.timeZone = "Europe/Amsterdam";
      # British English as the language; Dutch formats for numbers, currency, paper size and units
      # Dates and the clock are British too, so that the names of days and months are English: 14/11/2026, 24-hour clock, weeks start on Monday
      i18n.defaultLocale = "en_GB.UTF-8";
      i18n.extraLocaleSettings = {
        LC_TIME = "en_GB.UTF-8";
      }
      // lib.genAttrs [
        "LC_NUMERIC"
        "LC_MONETARY"
        "LC_PAPER"
        "LC_NAME"
        "LC_ADDRESS"
        "LC_TELEPHONE"
        "LC_MEASUREMENT"
        "LC_IDENTIFICATION"
      ] (_: "nl_NL.UTF-8");
      services.xserver.xkb.layout = "us";

      environment.systemPackages = with pkgs; [ git ];

      users.users.jeeemieee = {
        isNormalUser = true;
        uid = 1000;
        description = "jeeemieee";
        # libvirtd manages system VMs and is close to root; docker is rootless and needs no group
        extraGroups = [
          "wheel"
          "networkmanager"
          "libvirtd"
        ];
      };
      users.users.root.hashedPassword = "!";
      security.sudo = {
        enable = true;
        wheelNeedsPassword = true;
      };

      home-manager.users.jeeemieee.imports = [
        modules.homeManager.desktop-kde
        modules.homeManager.vscode
        modules.homeManager.git
        modules.homeManager.ssh
        modules.homeManager.office
        modules.homeManager.mail
        modules.homeManager.notes
        modules.homeManager.graphics
        modules.homeManager.engineering
        modules.homeManager.media
        modules.homeManager.passwords
        modules.homeManager.cli
        modules.homeManager.default-apps
        modules.homeManager.meetings
        modules.homeManager.tex
        modules.homeManager.rpi
        modules.homeManager.user-dirs
        modules.homeManager.pi
      ];

      nix.settings.experimental-features = [
        "nix-command"
        "flakes"
      ];
    };
}
