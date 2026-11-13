# Video meetings and remote desktop; users opt in by importing homeManager.meetings
{
  flake.modules.homeManager.meetings =
    { pkgs, ... }:
    {
      # Teams does not flash its window in the task bar for every notification
      xdg.configFile."teams-for-linux/config.json".text = builtins.toJSON { disableNotificationWindowFlash = true; };

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
