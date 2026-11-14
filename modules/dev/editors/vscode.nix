# VSCodium editor
#
# What it is    A fully declared editor with free extensions, fixed settings and a corrected Jupyter package
# Who uses it   A Home Manager user by importing homeManager.vscode; the workstation account imports it
# A user adds   Project language tools through each development shell, not through editor downloads
# Protected     No: this is an ordinary user application and its extensions
{
  flake.modules.homeManager.vscode =
    { pkgs, ... }:
    let
      ## Part 1. Jupyter extension correction
      # nixpkgs currently fetches a VSIX whose bundled ZeroMQ library is only for Linux on ARM
      # Without an x86-64 library, direct kernels fail
      # The extension then falls back to a separate Jupyter server
      # Fetch the Linux x86-64 VSIX, keep its glibc library and patch that library for the Nix store
      # When mimir-vm-config reports a mismatch, copy nixpkgs' new version here and refresh the hash
      # Remove this override when nixpkgs itself fetches the Linux x86-64 VSIX
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

        # Make the remaining native library find libstdc++ and glibc in the Nix store
        nativeBuildInputs = old.nativeBuildInputs ++ [ pkgs.autoPatchelfHook ];
        buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.stdenv.cc.cc.lib ];

        # Remove ZeroMQ builds for other architectures and musl because this workstation cannot load them
        postPatch = old.postPatch + ''
          find dist/node_modules/zeromq*/prebuilds -type f ! -path '*/prebuilds/linux-x64/node.napi.glibc.node' -delete
          find dist/node_modules/zeromq*/prebuilds -mindepth 1 -type d -empty -delete
        '';
      });
    in
    {
      ## Part 2. Editor and extensions
      # Use VSCodium's module so settings go to its own paths rather than those of Microsoft VS Code
      programs.vscodium = {
        # Install VSCodium and let Home Manager maintain its profile
        enable = true;

        # Keep the extension directory read-only so every extension comes from Nix
        mutableExtensionsDir = false;

        profiles.default = {
          # Let Nix provide every editor and extension update instead of VSCodium
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
            # Use latexmk from homeManager.tex and LaTeX Workshop's own compatible PDF viewer
            # Add spell checking for prose and source files
            james-yu.latex-workshop
            streetsidesoftware.code-spell-checker
            ms-vscode.cmake-tools
            # Show CadQuery models live when the project supplies the matching ocp-vscode 4.2.0 package
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

          ## Part 3. Fixed editor settings
          # Keep settings.json read-only so changes made in the settings screen do not drift from this file
          userSettings = {
            "telemetry.telemetryLevel" = "off";
            "chat.disableAIFeatures" = true;
            # Use the current theme name because VSCodium cannot rewrite the older name in read-only settings
            "workbench.colorTheme" = "Dark Modern";

            # Preserve the familiar editing behaviour from the previous editor setup
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
