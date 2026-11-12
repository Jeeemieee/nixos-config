# Lowercase XDG user directories (downloads, documents, …); users opt in by importing homeManager.user-dirs
{
  flake.modules.homeManager.user-dirs =
    { config, ... }:
    let
      home = config.home.homeDirectory;
    in
    {
      # Applications find these folders through ~/.config/user-dirs.dirs, which Home Manager writes read-only
      xdg.userDirs = {
        enable = true;
        createDirectories = true;
        # Set explicitly so it does not depend on home.stateVersion (the default changed in 26.05); applications read user-dirs.dirs, not XDG_*_DIR variables
        setSessionVariables = false;
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
