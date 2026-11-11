# Video meetings and remote desktop; users opt in by importing homeManager.meetings
{
  flake.modules.homeManager.meetings =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        # Unofficial Teams client around Teams for the web; Microsoft has no native Linux client
        teams-for-linux
        # Unfree, allowed in modules/flake/nixpkgs.nix
        zoom-us
        # RustDesk's Flutter client; the rustdesk attribute uses the legacy interface built on the unfree libsciter
        rustdesk-flutter
      ];
    };
}
