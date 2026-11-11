# Admin shell for this repository, loaded by .envrc through direnv
{
  perSystem =
    { pkgs, ... }:
    {
      devShells.default = pkgs.mkShell {
        packages = with pkgs; [
          # Editing and inspecting the encrypted nixos-secrets
          sops
          age
          ssh-to-age
        ];
      };
    };
}
