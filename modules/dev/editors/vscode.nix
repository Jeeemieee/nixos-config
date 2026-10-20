# Reusable, fully declarative VSCodium with free extensions only; hosts and users opt in by importing homeManager.vscode
{
  flake.modules.homeManager.vscode =
    { pkgs, ... }:
    let
      # nixpkgs downloads ms-toolsai.jupyter without a target platform, and that VSIX only contains linux-arm64 ZeroMQ libraries
      # Without x86-64 ZeroMQ the extension cannot talk to kernels directly and falls back to a Jupyter server that needs pip and notebook
      # This local override uses the linux-x64 VSIX, keeps only its glibc ZeroMQ libraries, and patches them against the Nix store
      # Bump: when mimir-vm-config reports a version mismatch with nixpkgs, set jupyterVersion to the nixpkgs version and refresh the hash
      # Remove: once nixpkgs downloads the linux-x64 VSIX itself, return to pkgs.vscode-extensions.ms-toolsai.jupyter
      jupyterVersion = "2025.9.1";
      jupyter = pkgs.vscode-extensions.ms-toolsai.jupyter.overrideAttrs (old: {
        version = jupyterVersion;
        src = pkgs.vscode-utils.fetchVsixFromVscodeMarketplace {
          publisher = "ms-toolsai";
          name = "jupyter";
          version = jupyterVersion;
          arch = "linux-x64";
          hash = "sha256-v5WsVVbz23Dy+Bb7r3NerlUBNDWElL0yOH/oZjYicRk=";
        };

        # Patch the remaining native libraries so they find libstdc++ and glibc in the Nix store
        nativeBuildInputs = old.nativeBuildInputs ++ [ pkgs.autoPatchelfHook ];
        buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.stdenv.cc.cc.lib ];

        # Keep only the linux-x64 glibc ZeroMQ builds; musl and other architectures cannot be patched or loaded here
        postPatch = old.postPatch + ''
          find dist/node_modules/zeromq*/prebuilds -type f ! -path '*/prebuilds/linux-x64/node.napi.glibc.node' -delete
          find dist/node_modules/zeromq*/prebuilds -mindepth 1 -type d -empty -delete
        '';
      });
    in
    {
      programs.vscode = {
        enable = true;
        package = pkgs.vscodium;

        # Extensions come only from Nix; the extension directory is read-only
        mutableExtensionsDir = false;

        profiles.default = {
          # Nix provides every version, so VSCodium must not update itself or its extensions
          enableUpdateCheck = false;
          enableExtensionUpdateCheck = false;

          extensions = with pkgs.vscode-extensions; [
            jnoortheen.nix-ide
            ms-python.python
            ms-python.debugpy
            jupyter
            ms-toolsai.jupyter-keymap
            ms-toolsai.jupyter-renderers
            ms-toolsai.vscode-jupyter-cell-tags
            ms-toolsai.vscode-jupyter-slideshow
            detachhead.basedpyright
            llvm-vs-code-extensions.vscode-clangd
            vadimcn.vscode-lldb
            mkhl.direnv
          ];

          # Read-only settings.json: changes made in the settings UI do not persist
          userSettings = {
            "telemetry.telemetryLevel" = "off";
            "chat.disableAIFeatures" = true;
            "workbench.colorTheme" = "Default Dark Modern";

            # The Nix extension needs a language server, supplied by the Nix store
            "nix.enableLanguageServer" = true;
            "nix.serverPath" = "${pkgs.nil}/bin/nil";

            # basedpyright is the only Python language server; the Python extension must not start its own
            "python.languageServer" = "None";
            "basedpyright.analysis.typeCheckingMode" = "standard";

            # clangd comes from each project's devShell, never from a download into global storage
            "clangd.checkUpdates" = false;
          };
        };
      };
    };
}
