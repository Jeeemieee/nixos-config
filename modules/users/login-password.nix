# The login password from nixos-secrets; hosts opt in by importing nixos.login-password
# The hash is user_password_hash in secrets/shared.yaml, the same on every personal machine
{ inputs, ... }@topLevel:
{
  flake.modules.nixos.login-password =
    { config, ... }:
    {
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      # Accounts and passwords come from the configuration only; passwd does not persist
      users.mutableUsers = false;

      # Decrypted before the accounts are created, so the machine's age key must already be on disk and enrolled at the first boot
      sops.secrets.user_password_hash = {
        sopsFile = "${inputs.nixos-secrets}/secrets/shared.yaml";
        neededForUsers = true;
      };
      users.users.jeeemieee.hashedPasswordFile = config.sops.secrets.user_password_hash.path;
    };
}
