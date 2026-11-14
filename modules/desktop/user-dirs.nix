# User folders
#
# What it is    Lowercase desktop, document, download and media folders announced through XDG
# Who uses it   A Home Manager user by importing homeManager.user-dirs; the workstation account imports it
# A user adds   Nothing; Home Manager creates the folders and the file applications read
# Protected     No: these paths organise user files but do not control backup or disk layout
{
  flake.modules.homeManager.user-dirs =
    { config, ... }:
    let
      # Build every folder path from the account's Home Manager home directory
      home = config.home.homeDirectory;
    in
    {
      # Publish the folder locations in the read-only user-dirs.dirs file that applications use
      xdg.userDirs = {
        # Ask Home Manager to maintain the XDG folder declaration
        enable = true;

        # Create each declared folder when it does not exist yet
        createDirectories = true;

        # Avoid a default that changed in 26.05
        # Applications read user-dirs.dirs rather than session variables
        setSessionVariables = false;

        # Keep the familiar folder names lowercase and independent of the desktop language
        desktop = "${home}/desktop";
        documents = "${home}/documents";
        download = "${home}/downloads";
        music = "${home}/music";
        pictures = "${home}/pictures";
        projects = "${home}/projects";
        publicShare = "${home}/public";
        templates = "${home}/templates";
        videos = "${home}/videos";
      };
    };
}
