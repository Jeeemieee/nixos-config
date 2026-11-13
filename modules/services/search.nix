# SearXNG: a private meta-search on this machine that asks several search engines and shows their results together, without ads
# Hosts opt in by importing nixos.search; Brave's address bar then searches through it (decided in modules/apps/browser.nix)
{ inputs, ... }@topLevel:
{
  flake.modules.nixos.search =
    { pkgs, ... }:
    let
      # Reachable from this machine only; 8888, SearXNG's own default, is also Jupyter's
      address = "127.0.0.1";
      port = 8877;

      # SearXNG signs its internal links with this key; it is generated on the machine at the first start, so there is no secret to enter
      keyDirectory = "searx-secret";
      keyFile = "/var/lib/${keyDirectory}/env";
    in
    {
      services.searx = {
        enable = true;
        environmentFile = keyFile;
        settings = {
          # Start from SearXNG's own defaults, which enable Google, DuckDuckGo, Brave, Startpage, Wikipedia and more
          use_default_settings = true;
          server = {
            bind_address = address;
            inherit port;
            # Replaced by the generated key when the service starts; the key itself never reaches the Nix store
            secret_key = "$SEARX_SECRET_KEY";
            # The query is part of the address, so the browser's back button and history work
            method = "GET";
            # The rate limiter protects public instances and needs a database; this one has a single user
            limiter = false;
            public_instance = false;
          };
          search = {
            # Nothing is sent to a search engine while typing
            autocomplete = "";
            formats = [ "html" ];
          };
          # Wikidata only fills the information box beside the results, and the page waits for it: measured, it took 0.9 s where Google and Brave took 0.3 to 0.5 s
          engines = [
            {
              name = "wikidata";
              disabled = true;
            }
          ];
        };
      };

      systemd.services.searx-secret-key = {
        description = "Generate SearXNG's secret key on first start";
        before = [ "searx-init.service" ];
        requiredBy = [ "searx-init.service" ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
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

  perSystem =
    { pkgs, ... }:
    let
      inherit (pkgs) lib;
      modules = topLevel.config.flake.modules.nixos;

      # A host with the browser but without nixos.search keeps Brave Search in the address bar
      withoutSearch =
        (inputs.nixpkgs.lib.nixosSystem {
          modules = [
            modules.browser
            { nixpkgs.pkgs = pkgs; }
          ];
        }).config.programs.chromium;
    in
    {
      # The service in a virtual machine without internet: it starts, answers on this machine only, and keeps its generated key out of the Nix store
      # Results from the real search engines need the internet and are tested by hand (docs/APPS.md)
      checks.search =
        assert lib.hasPrefix "https://search.brave.com/" withoutSearch.defaultSearchProviderSearchURL;
        assert builtins.elem "brave" (map (site: site.shortcut) withoutSearch.extraOpts.SiteSearchSettings);
        pkgs.testers.runNixOSTest {
          name = "search";

          nodes.machine = {
            imports = [ modules.search ];
            # Open on purpose: the test must show that the service itself does not listen for other machines
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
              start_all()
              machine.wait_for_unit("searx.service")
              machine.wait_for_open_port(${port}, "127.0.0.1")
              other.wait_for_unit("multi-user.target")

              with subtest("S1: the start page and a search answer on this machine"):
                  machine.succeed("curl --fail --silent --max-time 20 -o /tmp/start.html http://127.0.0.1:${port}/ && grep -qi searxng /tmp/start.html")
                  machine.succeed("curl --fail --silent --max-time 60 -o /dev/null 'http://127.0.0.1:${port}/search?q=test'")

              with subtest("S2: another machine cannot reach it, although the firewall is off"):
                  other.succeed("ping -c 1 machine")
                  other.fail("curl --silent --max-time 5 -o /dev/null http://machine:${port}/")
                  # The fourth column of ss is the local address
                  listeners = machine.succeed("ss -Hltn 'sport = :${port}' | awk '{print $4}'").split()
                  assert listeners == ["127.0.0.1:${port}"], listeners

              with subtest("S3: the key is generated here, private, and not in the Nix store"):
                  assert machine.succeed("stat -c '%a %U' /var/lib/searx-secret/env").strip() == "600 root"
                  key = machine.succeed("sed -n 's/^SEARX_SECRET_KEY=//p' /var/lib/searx-secret/env").strip()
                  assert len(key) == 64, len(key)
                  # The template in the Nix store, as read by the unit that fills in the key at start
                  template = machine.succeed("grep -oh '/nix/store/[a-z0-9]*-settings.yml' $(systemctl show -p ExecStart --value searx-init.service | grep -o '/nix/store/[^ ;]*' | head -n 1)").strip()
                  machine.succeed(f"grep -q 'SEARX_SECRET_KEY' {template}")
                  machine.fail(f"grep -q {key} {template}")
                  machine.succeed(f"grep -q {key} /run/searx/settings.yml")

              with subtest("S4: the key survives a restart"):
                  machine.shutdown()
                  machine.start()
                  machine.wait_for_unit("searx.service")
                  assert machine.succeed("sed -n 's/^SEARX_SECRET_KEY=//p' /var/lib/searx-secret/env").strip() == key
            '';
        };
    };
}
