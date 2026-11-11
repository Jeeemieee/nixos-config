# Full TeX Live distribution; users opt in by importing homeManager.tex
{
  flake.modules.homeManager.tex =
    { pkgs, ... }:
    {
      home.packages = [ pkgs.texliveFull ];
    };
}
