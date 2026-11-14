# Repository admin shell
#
# What it is    The commands used to maintain this repository and its private input
# Who uses it   The owner through nix develop or automatically through the protected .envrc
# A user adds   The passphrase-protected admin age key at the path used by the shell hook
# Protected     Yes: this shell can decrypt secrets and run the guarded maintenance command (docs/UPKEEP.md)
{
  perSystem =
    { config, pkgs, ... }:
    {
      # Make this the default shell entered by nix develop and direnv
      devShells.default = pkgs.mkShell {
        packages = with pkgs; [
          # Provide checks, guarded commits, builds and updates described in docs/UPKEEP.md
          config.packages.config
          # Provide tools for editing and inspecting encrypted values in the private repository
          sops
          age
          # Create yescrypt password hashes for the private repository with mkpasswd -m yescrypt
          mkpasswd
        ];

        # Make age ask for the protected admin key's passphrase in the terminal instead of through gpg-agent
        shellHook = ''
          export SOPS_AGE_KEY_CMD="${pkgs.age}/bin/age --decrypt $HOME/.config/sops/age/admin.age"
        '';
      };
    };
}
