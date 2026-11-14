# TeX toolchain
#
# What it is    The complete TeX Live distribution for writing and building TeX documents
# Who uses it   A Home Manager user by importing homeManager.tex; the workstation account imports it
# A user adds   Nothing; the full distribution avoids missing-package setup per document
# Protected     No: this is an ordinary user toolchain
{
  flake.modules.homeManager.tex =
    { pkgs, ... }:
    {
      # Prefer the full distribution so documents build without adding TeX packages one by one
      home.packages = [ pkgs.texliveFull ];
    };
}
