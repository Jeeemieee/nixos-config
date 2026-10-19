# Reusable, fully declarative VS Code; hosts and users opt in by importing homeManager.vscode
{
  flake.modules.homeManager.vscode =
    { pkgs, ... }:
    {
      programs.vscode = {
        enable = true;
        package = pkgs.vscode;

        # Extensions come only from Nix; the extension directory is read-only
        mutableExtensionsDir = false;

        profiles.default = {
          # Nix provides every version, so VS Code must not update itself or its extensions
          enableUpdateCheck = false;
          enableExtensionUpdateCheck = false;

          extensions = with pkgs.vscode-extensions; [
            jnoortheen.nix-ide
            ms-python.python
            ms-python.vscode-pylance
            ms-python.debugpy
            ms-toolsai.jupyter
            ms-toolsai.jupyter-keymap
            ms-toolsai.jupyter-renderers
            ms-toolsai.vscode-jupyter-cell-tags
            ms-toolsai.vscode-jupyter-slideshow
            ms-vscode.cpptools
          ];

          # Read-only settings.json: changes made in the settings UI do not persist
          userSettings = {
            "telemetry.telemetryLevel" = "off";
            "chat.disableAIFeatures" = true;
            "workbench.colorTheme" = "Default Dark Modern";

            # The Nix extension needs a language server, supplied by the Nix store
            "nix.enableLanguageServer" = true;
            "nix.serverPath" = "${pkgs.nil}/bin/nil";
          };
        };
      };
    };
}
