# Default applications
#
# What it is    The programs that open web links, documents, email links and TeX files
# Who uses it   A Home Manager user by importing homeManager.default-apps; the workstation account imports it
# A user adds   The matching Brave, Okular, Thunderbird and VSCodium modules
# Protected     No: these choices only decide which desktop application opens a file or link
{
  flake.modules.homeManager.default-apps = {
    # Use the desktop file names installed by Brave, Okular, Thunderbird and VSCodium
    xdg.mimeApps = {
      # Ask the desktop to honour the declared application choices
      enable = true;

      # Keep each commonly used link or document type tied to its intended program
      defaultApplications = {
        "x-scheme-handler/http" = "brave-browser.desktop";
        "x-scheme-handler/https" = "brave-browser.desktop";
        "text/html" = "brave-browser.desktop";
        "application/xhtml+xml" = "brave-browser.desktop";
        "application/pdf" = "okularApplication_pdf.desktop";
        "x-scheme-handler/mailto" = "thunderbird.desktop";
        "text/x-tex" = "codium.desktop";
      };
    };

    # Replace changes made by Plasma or applications so these defaults win at every activation
    xdg.configFile."mimeapps.list".force = true;
  };
}
