# Private web search
#
# What it is    A loopback-only SearXNG service combining several search engines without advertising
# Who uses it   A NixOS host by importing nixos.search; nixos.browser then points Brave at it
# A host adds   Nothing; the service creates its own local signing key on first start
# Protected     Yes: the module carries the test that proves the service is private (docs/UPKEEP.md)
{ inputs, ... }@topLevel:
{
  ## Part 1. Search service
  flake.modules.nixos.search =
    { pkgs, ... }:
    let
      # Bind only to this machine and avoid SearXNG's default port because Jupyter also uses it
      address = "127.0.0.1";
      port = 8877;

      # Keep SearXNG's internal signing key in a private state directory generated on first start
      keyDirectory = "searx-secret";
      keyFile = "/var/lib/${keyDirectory}/env";
    in
    {
      services.searx = {
        # Start the local meta-search service
        enable = true;

        # Read the generated signing key without placing it in the Nix store
        environmentFile = keyFile;
        settings = {
          # Begin with SearXNG's maintained set of general and reference search engines
          use_default_settings = true;
          server = {
            bind_address = address;
            inherit port;
            # Replace this placeholder from the private environment file when the service starts
            secret_key = "$SEARX_SECRET_KEY";
            # Put the query in the address so browser history and the back button remain useful
            method = "GET";
            # Avoid the public-instance rate limiter and its database on this single-user service
            limiter = false;
            public_instance = false;
          };
          search = {
            # Send nothing to an external engine while the user is still typing
            autocomplete = "";
            formats = [ "html" ];
          };
          # Disable the slow Wikidata side panel because the results page waits for it
          # It measured about 0.9 seconds where Google and Brave took 0.3 to 0.5 seconds
          engines = [
            {
              name = "wikidata";
              disabled = true;
            }
          ];
        };
      };

      # Create the signing key before SearXNG prepares its runtime settings
      systemd.services.searx-secret-key = {
        description = "Generate SearXNG's secret key on first start";
        before = [ "searx-init.service" ];
        requiredBy = [ "searx-init.service" ];
        serviceConfig = {
          # Run once per boot and remain active as a dependency of searx-init
          Type = "oneshot";
          RemainAfterExit = true;

          # Keep the generated environment file in a root-only state directory
          StateDirectory = keyDirectory;
          StateDirectoryMode = "0700";
        };
        script = ''
          if [ ! -s ${keyFile} ]; then
            umask 077
            printf 'SEARX_SECRET_KEY=%s\n' "$(${pkgs.openssl}/bin/openssl rand -hex 32)" > ${keyFile}
          fi
        '';
      };
    };

  ## Part 2. Privacy and fallback test
  perSystem =
    { pkgs, ... }:
    let
      # Reuse the package library and this flake's named NixOS modules in the test configurations
      inherit (pkgs) lib;
      modules = topLevel.config.flake.modules.nixos;

      # Evaluate a browser-only host to prove it retains Brave Search as its fallback
      withoutSearch =
        (inputs.nixpkgs.lib.nixosSystem {
          modules = [
            modules.browser
            { nixpkgs.pkgs = pkgs; }
          ];
        }).config.programs.chromium;
    in
    {
      # Prove offline that the service starts, stays local and keeps its generated key out of the Nix store
      # Results from real engines still require the manual internet check in docs/APPS.md
      checks.search =
        assert lib.hasPrefix "https://search.brave.com/" withoutSearch.defaultSearchProviderSearchURL;
        assert builtins.elem "brave" (map (site: site.shortcut) withoutSearch.extraOpts.SiteSearchSettings);
        pkgs.testers.runNixOSTest {
          name = "search";

          nodes.machine = {
            # Test the public module without the wider workstation profile
            imports = [ modules.search ];

            # Disable the firewall so only SearXNG's own loopback binding can make the privacy test pass
            networking.firewall.enable = false;
          };
          nodes.other = { };

          testScript =
            { nodes, ... }:
            let
              server = nodes.machine.services.searx.settings.server;
              port = toString server.port;
            in
            ''
              ## Step 1. Start both machines and wait for the local service
              start_all()
              machine.wait_for_unit("searx.service")
              machine.wait_for_open_port(${port}, "127.0.0.1")
              other.wait_for_unit("multi-user.target")

              ## Step 2. Prove the local start page and search endpoint answer
              with subtest("S1: the start page and a search answer on this machine"):
                  machine.succeed("curl --fail --silent --max-time 20 -o /tmp/start.html http://127.0.0.1:${port}/ && grep -qi searxng /tmp/start.html")
                  machine.succeed("curl --fail --silent --max-time 60 -o /dev/null 'http://127.0.0.1:${port}/search?q=test'")

              ## Step 3. Prove another machine cannot reach the service with the firewall off
              with subtest("S2: another machine cannot reach it, although the firewall is off"):
                  other.succeed("ping -c 1 machine")
                  other.fail("curl --silent --max-time 5 -o /dev/null http://machine:${port}/")
                  # Read the local-address column from ss to check the exact listener
                  listeners = machine.succeed("ss -Hltn 'sport = :${port}' | awk '{print $4}'").split()
                  assert listeners == ["127.0.0.1:${port}"], listeners

              ## Step 4. Prove the key is local, private and absent from the store template
              with subtest("S3: the key is generated here, private, and not in the Nix store"):
                  assert machine.succeed("stat -c '%a %U' /var/lib/searx-secret/env").strip() == "600 root"
                  key = machine.succeed("sed -n 's/^SEARX_SECRET_KEY=//p' /var/lib/searx-secret/env").strip()
                  assert len(key) == 64, len(key)
                  # Inspect the store template read by the service that fills in the key at start
                  template = machine.succeed("grep -oh '/nix/store/[a-z0-9]*-settings.yml' $(systemctl show -p ExecStart --value searx-init.service | grep -o '/nix/store/[^ ;]*' | head -n 1)").strip()
                  machine.succeed(f"grep -q 'SEARX_SECRET_KEY' {template}")
                  machine.fail(f"grep -q {key} {template}")
                  machine.succeed(f"grep -q {key} /run/searx/settings.yml")

              ## Step 5. Prove the same key survives a restart
              with subtest("S4: the key survives a restart"):
                  machine.shutdown()
                  machine.start()
                  machine.wait_for_unit("searx.service")
                  assert machine.succeed("sed -n 's/^SEARX_SECRET_KEY=//p' /var/lib/searx-secret/env").strip() == key
            '';
        };
    };
}
