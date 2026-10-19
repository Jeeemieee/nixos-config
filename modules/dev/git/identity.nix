# Minimal declared Git identity; hosts and users opt in by importing homeManager.git
{
  flake.modules.homeManager.git = {
    programs.git = {
      enable = true;
      settings = {
        # GitHub's noreply address keeps the personal address out of commits
        user = {
          name = "Jeeemieee";
          email = "95027589+Jeeemieee@users.noreply.github.com";
        };
        init.defaultBranch = "main";
      };
    };
  };
}
