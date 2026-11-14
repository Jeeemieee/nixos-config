# Office applications
#
# What it is    Tools for office documents, desktop publishing and presenting PDFs
# Who uses it   A Home Manager user by importing homeManager.office; the workstation account imports it
# A user adds   Nothing; the module includes the spelling dictionaries used by the desktop
# Protected     No: these are ordinary user applications
{
  flake.modules.homeManager.office =
    { pkgs, ... }:
    {
      # Install the document, publishing and presentation applications together
      home.packages = with pkgs; [
        libreoffice-qt6-still
        scribus
        pympress

        # Put British and Dutch dictionaries where LibreOffice and KDE's Sonnet both search
        # LibreOffice uses each profile's hunspell folder, while Sonnet follows the desktop data paths
        hunspellDicts.en_GB-ise
        hunspellDicts.nl_NL
      ];
    };
}
