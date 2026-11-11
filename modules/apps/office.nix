# Office, desktop publishing and presentation tools; users opt in by importing homeManager.office
{
  flake.modules.homeManager.office =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        libreoffice-qt6-still
        scribus
        pympress

        # Lands in /etc/profiles/per-user/<user>/share/hunspell: LibreOffice's wrapper adds each $NIX_PROFILES/share/hunspell to DICPATH,
        # and KDE's Sonnet searches hunspell/ under $XDG_DATA_DIRS
        hunspellDicts.en_US
      ];
    };
}
