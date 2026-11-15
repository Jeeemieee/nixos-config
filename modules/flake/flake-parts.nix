{
  inputs,
  lib,
  flake-parts-lib,
  ...
}:
{
  imports = [ inputs.flake-parts.flakeModules.modules ];

  # Functions that several modules define and use (flake.lib.devShell, flake.lib.mkSandbox); without a declared option only one module could set flake.lib
  options.flake = flake-parts-lib.mkSubmoduleOptions {
    lib = lib.mkOption {
      type = lib.types.lazyAttrsOf lib.types.raw;
      default = { };
      description = "Functions for the modules of this flake and for the flakes that use it.";
    };
  };
}
