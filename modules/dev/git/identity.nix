# Git identity
#
# What it is    The public commit identity, default branch name and global ignored cache folder
# Who uses it   A Home Manager user by importing homeManager.git; the workstation account imports it
# A user adds   Nothing; GitHub transport and host trust are added by github.nix
# Protected     Yes: this file decides the identity written into commits (docs/UPKEEP.md)
{
  flake.modules.homeManager.git = {
    programs.git = {
      # Install Git's user configuration through Home Manager
      enable = true;

      settings = {
        # GitHub's noreply address keeps the personal address out of commits
        user = {
          name = "Jeeemieee";
          email = "95027589+Jeeemieee@users.noreply.github.com";
        };
        # Use the repository's normal branch name for newly created repositories
        init.defaultBranch = "main";
      };

      # Prevent nix-direnv's generated per-project cache from entering a repository
      ignores = [ ".direnv/" ];
    };
  };
}
