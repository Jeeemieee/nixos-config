# Admin shell for this repository, loaded by .envrc through direnv
{
  perSystem =
    { config, pkgs, ... }:
    {
      devShells.default = pkgs.mkShell {
        packages = with pkgs; [
          # Checks, guarded commits and updates of this repository and nixos-secrets (docs/UPKEEP.md)
          config.packages.config
          # Editing and inspecting the encrypted nixos-secrets
          sops
          age
          # Password hashes for nixos-secrets (mkpasswd -m yescrypt)
          mkpasswd
        ];

        # The admin key is passphrase-protected; sops' own prompt goes through gpg-agent, so age asks in the terminal instead
        shellHook = ''
          export SOPS_AGE_KEY_CMD="${pkgs.age}/bin/age --decrypt $HOME/.config/sops/age/admin.age"
        '';
      };
    };
}
