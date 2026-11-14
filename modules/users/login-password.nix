# Login password
#
# What it is    The shared account's password hash decrypted from nixos-secrets during account creation
# Who uses it   A NixOS host by importing nixos.login-password
# A host adds   Its age recipient to the shared encrypted file before the first boot
# Protected     Yes: this controls login credentials and makes declared accounts immutable (docs/SECRETS.md)
{ inputs, ... }@topLevel:
{
  flake.modules.nixos.login-password =
    { config, ... }:
    {
      # Add sops-nix and the machine's local age identity service
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      # Keep accounts and passwords entirely declarative so a passwd change cannot drift from this repository
      users.mutableUsers = false;

      # Decrypt before account creation, which requires the machine's enrolled age key on disk at first boot
      sops.secrets.user_password_hash = {
        sopsFile = "${inputs.nixos-secrets}/secrets/shared.yaml";
        neededForUsers = true;
      };
      # Give the declared account the root-only decrypted hash without putting it in the Nix store
      users.users.jeeemieee.hashedPasswordFile = config.sops.secrets.user_password_hash.path;
    };
}
