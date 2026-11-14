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
      # VSCodium's own module writes to VSCodium's paths (~/.config/VSCodium, ~/.vscode-oss); programs.vscode would write to VS Code's
      programs.vscodium = {
        enable = true;

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
            # Writing: LaTeX with latexmk from the TeX Live of homeManager.tex, and spell checking
            # LaTeX Workshop brings its own PDF viewer and reports other PDF extensions as incompatible
            james-yu.latex-workshop
            streetsidesoftware.code-spell-checker
            ms-vscode.cmake-tools
            # Shows CadQuery models live from Python; the project needs the matching package: uv add ocp-vscode==4.2.0
            (pkgs.vscode-utils.buildVscodeMarketplaceExtension {
              mktplcRef = {
                publisher = "bernhard-42";
                name = "ocp-cad-viewer";
                version = "4.2.0";
                hash = "sha256-q3Pi4MApNEXNJ25+aQbtd3S8bFxT0UEwnXkM2W7lwIg=";
              };
              meta.license = pkgs.lib.licenses.asl20;
            })
          ];

          # Read-only settings.json: changes made in the settings UI do not persist
          userSettings = {
            "telemetry.telemetryLevel" = "off";
            "chat.disableAIFeatures" = true;
            # The theme's current name: VSCodium rewrites the older "Default Dark Modern" at every start, which fails on read-only settings
            "workbench.colorTheme" = "Dark Modern";

            # Carried over from the VS Code setup on Ubuntu
            "security.workspace.trust.untrustedFiles" = "open";
            "git.openRepositoryInParentFolders" = "always";
            "git.enableSmartCommit" = true;
            "git.suggestSmartCommit" = false;
            "explorer.compactFolders" = false;
            "diffEditor.hideUnchangedRegions.enabled" = true;
            "editor.largeFileOptimizations" = false;
            "workbench.editor.tabSizing" = "fixed";
            "workbench.editor.tabSizingFixedMaxWidth" = 180;
            "window.menuBarVisibility" = "compact";
            "notebook.lineNumbers" = "on";
            "notebook.output.wordWrap" = true;
            "jupyter.askForKernelRestart" = false;
            "cSpell.language" = "en-GB";
            # Any PDF opens in LaTeX Workshop's viewer
            "workbench.editorAssociations"."*.pdf" = "latex-workshop-pdf-hook";

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
