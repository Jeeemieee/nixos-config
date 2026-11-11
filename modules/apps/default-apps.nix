# Default applications for links and file types; users opt in by importing homeManager.default-apps
{
  flake.modules.homeManager.default-apps = {
    # Desktop file names as installed by brave, okular, thunderbird and vscodium
    xdg.mimeApps = {
      enable = true;
      defaultApplications = {
        "x-scheme-handler/http" = "brave-browser.desktop";
        "x-scheme-handler/https" = "brave-browser.desktop";
        "application/pdf" = "okularApplication_pdf.desktop";
        "x-scheme-handler/mailto" = "thunderbird.desktop";
        "text/x-tex" = "codium.desktop";
      };
    };

    # Plasma and other programs rewrite mimeapps.list; replacing it makes the declared defaults win at every activation
    xdg.configFile."mimeapps.list".force = true;
  };
}
