# Personal workstation
#
# What it is    The account, desktop, applications and services shared by every personal machine
# Who uses it   Both hosts, the laptop (mimir) and the test VM (mimir-vm), by importing nixos.workstation
# A host adds   Its hardware, disk, state version and the secrets key needed by Wi-Fi and Tailscale
# Protected     Yes: this file sets the account, sudo and the firewall (docs/UPKEEP.md)
{ config, ... }:
let
  # Every other module of this repository, by name: modules.nixos.<name> and modules.homeManager.<name>
  inherit (config.flake) modules;
in
{
  flake.modules.nixos.workstation =
    { lib, pkgs, ... }:
    {

      ## Part 1. What the system gets
      # Each name is a module in modules/: add a line here to give every personal machine something new
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

      # The one program every user of the machine has, also root
      environment.systemPackages = with pkgs; [ git ];

      # Flakes and the new nix command, which this repository is built on
      nix.settings.experimental-features = [
        "nix-command"
        "flakes"
      ];

      ## Part 2. The network
      # NetworkManager handles Wi-Fi and cables
      networking.networkmanager.enable = true;

      # Nothing reaches the machine from outside: the firewall is on and no SSH server runs
      networking.firewall.enable = true;
      services.openssh.enable = false;

      ## Part 3. Language, formats and keyboard
      time.timeZone = "Europe/Amsterdam";

      # British English as the language
      i18n.defaultLocale = "en_GB.UTF-8";

      # British dates and clock keep English day and month names, 24-hour time and Monday as the first day
      # Numbers, currency, paper size and units are Dutch
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

      # US keyboard layout
      services.xserver.xkb.layout = "us";

      ## Part 4. The account, and who may become root
      users.users.jeeemieee = {
        isNormalUser = true;
        uid = 1000;
        description = "jeeemieee";
        # wheel: may use sudo. networkmanager: may change connections
        # libvirtd: manages system VMs, which is close to root. Docker is rootless and needs no group
        extraGroups = [
          "wheel"
          "networkmanager"
          "libvirtd"
        ];
      };

      # Nobody logs in as root: "!" is a password that matches nothing
      users.users.root.hashedPassword = "!";

      # sudo asks for your password every time
      security.sudo = {
        enable = true;
        wheelNeedsPassword = true;
      };

      ## Part 5. What your own account gets
      # Each name is a Home Manager module in modules/
      # These settings and programs belong to you rather than the whole system
      home-manager.users.jeeemieee.imports = [
        modules.homeManager.desktop-kde
        modules.homeManager.vscode
        modules.homeManager.git
        modules.homeManager.ssh
        modules.homeManager.config-tool
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
    };
}
