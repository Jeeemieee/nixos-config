# Keyboard-driven Plasma
#
# What it is    Private named desktops, shortcuts, window placement and KRunner web searches
# Who uses it   The Home Manager desktop-kde module beside settings.nix
# A user adds   A private desktop/desktops.json list in the nixos-secrets input
# Protected     No: private names stay outside this repository and these settings only arrange the desktop
{ inputs, ... }:
{
  flake.modules.homeManager.desktop-kde =
    { lib, ... }:
    let
      ## Part 1. Private desktop names and shortcut positions
      # Read the private ordered names from the secrets input rather than publishing them here
      # Meta+position switches desktop, while Meta+Shift+position moves the active window
      # A Brave window named "<desktop>: <topic>" returns to that desktop after a browser restart
      desktopsFile = "${inputs.nixos-secrets}/desktop/desktops.json";
      # Return an empty list when an old secrets pin lacks the file
      # The assertion below then gives a clear message
      desktops = lib.optionals (builtins.pathExists desktopsFile) (lib.importJSON desktopsFile);

      # Give each desktop the one-based position used in Plasma's shortcut names
      positions = lib.range 1 (builtins.length desktops);

      # Spell Shift+digit as the symbol produced by the configured US keyboard layout
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
      # Build each position-indexed Plasma setting from the same ordered desktop list
      perPosition = entry: lib.listToAttrs (map entry positions);
    in
    {
      ## Part 2. Input checks
      assertions = [
        # Refuse an old secrets pin instead of quietly creating a desktop with no private names
        {
          assertion = desktops != [ ];
          message = "homeManager.desktop-kde needs desktop/desktops.json (a list of names) in the nixos-secrets input: update its pin with 'nix flake update nixos-secrets'";
        }
        # Refuse more desktops than the available Meta+digit shortcuts can reach
        {
          assertion = (builtins.length desktops) <= (builtins.length shifted);
          message = "homeManager.desktop-kde: Meta+<digit> reaches at most ${toString (builtins.length shifted)} desktops";
        }
      ];

      ## Part 3. Desktops and shortcuts
      programs.plasma = {
        # Keep all named desktops in one row and in the private file's order
        kwin.virtualDesktops = {
          rows = 1;
          names = desktops;
        };

        # Reserve Meta+digit for desktops instead of Plasma's default task-manager entries
        shortcuts = {
          kwin =
            perPosition (n: lib.nameValuePair "Switch to Desktop ${toString n}" "Meta+${toString n}")
            // perPosition (
              n: lib.nameValuePair "Window to Desktop ${toString n}" "Meta+${builtins.elemAt shifted (n - 1)}"
            );
          # Clear Plasma's conflicting shortcut that starts or focuses the numbered task entry
          plasmashell = perPosition (n: lib.nameValuePair "activate task manager entry ${toString n}" [ ]);
        };

        ## Part 4. Brave window placement
        # Let KWin restore Brave windows by their names because Wayland gives the browser no placement control
        # plasma-manager stores each target under the internal name Desktop_<position>
        window-rules =
          lib.imap1 (n: name: {
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
            # Keep the rule forced so naming an existing window moves it immediately and remains effective
            apply.desktops = {
              value = "Desktop_${toString n}";
              apply = "force";
            };
          }) desktops
          ++ [
            # Bitwarden's SSH approval must appear on whichever desktop asked for it, not on the desktop where Bitwarden started
            # An empty desktop list is KWin's "All Desktops"; the class is matched case-insensitively because its case differs between X11 and Wayland
            {
              description = "Bitwarden on all desktops, so that its approval appears where it is asked for";
              match.window-class = {
                value = "(?i)bitwarden";
                type = "regex";
                match-whole = false;
              };
              apply.desktops = {
                value = "";
                apply = "force";
              };
            }
          ];

        # Restore Plasma's centred default if a machine had previously saved maximised placement
        # Keep Plasma's default Meta shortcuts for maximising and half-screen tiling
        configFile.kwinrc.Windows.Placement = "Centered";

        ## Part 5. KRunner searches
        # Add the missing searches used as <keyword>:<text> after opening KRunner with Alt+Space
        # Plasma already supplies DuckDuckGo, Wikipedia, GitHub, DOI, PyPI, nixpkgs and many more
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
