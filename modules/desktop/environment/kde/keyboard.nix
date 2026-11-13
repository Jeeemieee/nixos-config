# Keyboard-driven Plasma: one named virtual desktop per project, shortcuts to reach them and web searches from KRunner
# Part of homeManager.desktop-kde, next to settings.nix
{ inputs, ... }:
{
  flake.modules.homeManager.desktop-kde =
    { lib, ... }:
    let
      # One virtual desktop per project, in this order: Meta+<position> switches to it, Meta+Shift+<position> moves the active window to it
      # A Brave window named "<desktop>: <topic>" (right-click the tab strip, Name window) moves to that desktop and stays there, also after Brave restarts
      # The names are private, so they come from nixos-secrets (plain, not encrypted): a JSON list of names
      desktopsFile = "${inputs.nixos-secrets}/desktop/desktops.json";
      desktops = lib.optionals (builtins.pathExists desktopsFile) (lib.importJSON desktopsFile);
      positions = lib.range 1 (builtins.length desktops);

      # Shift+<digit> on the US layout, which is how Plasma stores a shortcut with Shift and a digit
      shifted = [
        "!"
        "@"
        "#"
        "$"
        "%"
        "^"
        "&"
        "*"
        "("
      ];
      perPosition = entry: lib.listToAttrs (map entry positions);
    in
    {
      assertions = [
        # Without this, a nixos-secrets pin from before the file existed would quietly give a desktop without the named desktops
        {
          assertion = desktops != [ ];
          message = "homeManager.desktop-kde needs desktop/desktops.json (a list of names) in the nixos-secrets input: update its pin with 'nix flake update nixos-secrets'";
        }
        {
          assertion = (builtins.length desktops) <= (builtins.length shifted);
          message = "homeManager.desktop-kde: Meta+<digit> reaches at most ${toString (builtins.length shifted)} desktops";
        }
      ];

      programs.plasma = {
        kwin.virtualDesktops = {
          rows = 1;
          names = desktops;
        };

        shortcuts = {
          kwin =
            perPosition (n: lib.nameValuePair "Switch to Desktop ${toString n}" "Meta+${toString n}")
            // perPosition (
              n: lib.nameValuePair "Window to Desktop ${toString n}" "Meta+${builtins.elemAt shifted (n - 1)}"
            );
          # Plasma's default for Meta+<digit> starts or focuses the n-th task manager entry
          plasmashell = perPosition (n: lib.nameValuePair "activate task manager entry ${toString n}" [ ]);
        };

        # Wayland gives a program no way to put its windows back on a desktop, so KWin does it by window name
        # plasma-manager names the desktops Desktop_<position>
        window-rules = lib.imap1 (n: name: {
          description = "Brave windows named \"${name}: ...\" belong on desktop ${toString n}";
          match = {
            window-class = {
              value = "brave-browser";
              type = "exact";
              match-whole = false;
            };
            title = {
              value = "^${lib.escapeRegex name}: ";
              type = "regex";
            };
          };
          # Forced, not only initially: KWin matches the rule again when a title changes, so naming an existing window moves it at once
          apply.desktops = {
            value = "Desktop_${toString n}";
            apply = "force";
          };
        }) desktops;

        # New windows open centred in their own size, which is Plasma's default; declared so that a machine that had "maximised" returns to it
        # Meta+PgUp maximises, Meta+Left and Meta+Right tile to a half (Plasma defaults)
        configFile.kwinrc.Windows.Placement = "Centered";

        # KRunner (Alt+Space): "<keyword>:<text>" opens a web search in the browser
        # Plasma ships dd (DuckDuckGo), wp, gh, doi, pypi, nixpkgs and some 150 more; the ones below are added
        searchPlugins.webSearchKeywords.extra = {
          scholar = {
            name = "Google Scholar";
            keys = [
              "scholar"
              "gs"
            ];
            query = "https://scholar.google.com/scholar?q=\\{@}";
          };
          arxiv = {
            name = "arXiv";
            keys = [ "arxiv" ];
            query = "https://arxiv.org/search/?searchtype=all&query=\\{@}";
          };
          nixos_options = {
            name = "NixOS options";
            keys = [ "nixopt" ];
            query = "https://search.nixos.org/options?query=\\{@}";
          };
        };
      };
    };
}
