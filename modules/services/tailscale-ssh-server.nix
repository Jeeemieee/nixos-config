# Tailscale-only OpenSSH server
#
# What it is    One-user, key-only SSH whose firewall exception exists only on tailscale0
# Who uses it   Odin, for remote simulations from another personal machine
# A host adds   A public key file in the private input; the private key remains in Bitwarden
# Protected     Yes: this module controls incoming access
{ inputs, ... }:
{
  flake.modules.nixos.tailscale-ssh-server =
    { config, lib, ... }:
    let
      cfg = config.hostSpec.tailscaleSsh;
      keyAvailable = builtins.pathExists cfg.authorizedKeysFile;
    in
    {
      options.hostSpec.tailscaleSsh.authorizedKeysFile = lib.mkOption {
        type = lib.types.str;
        default = "${inputs.nixos-secrets}/ssh/odin_authorized_keys";
        description = "Plain private-input file containing the public SSH keys admitted by the Tailscale-only server.";
      };

      config = {
        # Override the workstation's deliberate no-server default only on a host that imports this module
        services.openssh = {
          enable = lib.mkForce true;
          openFirewall = false;
          settings = {
            PasswordAuthentication = false;
            KbdInteractiveAuthentication = false;
            PermitRootLogin = "no";
            AllowUsers = [ "jeeemieee" ];
          };
        };

        # OpenSSH listens normally; the firewall is the stable interface-based enforcement boundary
        networking.firewall.interfaces.tailscale0.allowedTCPPorts = [ 22 ];

        # Public key material comes from the private input, while the private half stays in Bitwarden
        users.users.jeeemieee.openssh.authorizedKeys.keyFiles =
          lib.optional keyAvailable cfg.authorizedKeysFile;

        # Keep the system buildable before enrolment, but refuse to start the server with no approved key
        systemd.services.sshd.preStart = lib.mkIf (!keyAvailable) (
          lib.mkBefore ''
            echo "tailscale-ssh-server: ssh/odin_authorized_keys is missing from the nixos-secrets input" >&2
            exit 1
          ''
        );
      };
    };
}
