topLevel:
let
  inherit (topLevel) lib;

  hostOptions = {
    # Configuration Settings
    isVM = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Used to indicate a VM host";
    };
    isServer = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Used to indicate a server host";
    };
    isWork = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Used to indicate a host that uses work resources";
    };
    isMobile = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Used to indicate a mobile host";
    };
    hasSecrets = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Whether this host's age recipient is enrolled in the pinned encrypted secrets, so that its
        configured secrets are enabled. Leave false to generate the host's age key and enrol it first.

        Several inherited modules under modules/users, modules/core and modules/services (for example
        users/mkusers, core/networking, caddy, tailscale, pocket-id and opencloud) also read this flag and
        expect the removed futura-secrets data. Do not set it on a host that imports them.
      '';
    };
    hasZfs = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether this host has ZFS, used for disko and syncoid client aggregation";
    };
    hasZfsStorage = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether this host has ZFS storage, used for disko syncoid client aggregation";
    };
    nixpkgs = lib.mkOption {
      type = lib.types.str;
      default = "stable";
      description = "nixpkgs to use for the host";
    };
    users = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule ({ ... }: {
        options = {
          name = lib.mkOption {
            type = lib.types.str;
            default = "";
            description = "Full name of the user";
          };
          email = lib.mkOption {
            type = lib.types.attrsOf lib.types.str;
            default = {};
            description = "Named email addresses (work, personal, etc.)";
          };
          authorizedKeys = lib.mkOption {
            type = with lib.types; listOf str;
            default = [];
            description = "List of SSH authorized keys of the user";
          };
          isAdmin = lib.mkOption {
            type = lib.types.bool;
            default = false;
            description = "Whether the user should be an admin";
          };
        };
      }));
      default = { };
      description = ''
        List of non-system users that should be declared for the host.
      '';
      # check = lib.mkCheck (users: 
      #   let
      #     adminUsers = lib.filterAttrs (_: u: u.isAdmin) users;
      #   in
      #     if builtins.length (builtins.attrNames users) == 0 then
      #       throw "hostSpec.users: At least one system user must be specified"
      #     else if builtins.length (builtins.attrNames adminUsers) == 0 then
      #       throw "hostSpec.users: At least one user must be marked as isAdmin = true"
      #     else true
      # );
    };
    # Networking (freeform — can take entire secrets structure)
    networking = lib.mkOption {
      type = lib.types.submodule ({ ... }: {
        freeformType = lib.types.attrsOf lib.types.anything;
        options = {}; # no fixed options, everything comes from secrets
      });
      default = {};
      description = "Host networking (subnets, hosts, ports, ssh, dns, etc.)";
    };
     # Services (freeform — can take entire secrets structure)
    services = lib.mkOption {
      type = lib.types.submodule ({ ... }: {
        options = {
          syncoid = {
            isBackupServer = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = ''
                will run syncoid and backup other nixos hosts
              '';
            };
            extraDatasets = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              description = ''
                list of extra datasets syncoid has access to on client
              '';
            };
          };
          adguardhome = {
            splitHorizonSubdomains = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [];
              description = "Subdomains to add to adguardhome list of split horizon subdomains";
            };
            sharedSplitHorizonSubdomains = lib.mkOption {
              type = lib.types.listOf (lib.types.submodule {
                options = {
                  subdomain = lib.mkOption { type = lib.types.str; };
                  ip = lib.mkOption { type = lib.types.str; };
                  tailip = lib.mkOption { type = lib.types.str; };
                };
              });
              default = [];
            };
          };
          ### tailscale is an integral part of this configuration. I'm using the module designed by @yomaq
          tailscale = {
            extraUpFlags = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [
                "--ssh=true"
                "--reset=true"
                "--accept-dns=true"
              ];
              description = ''
                Extra flags to pass to tailscale up.
              '';
            };
            useRoutingFeatures = lib.mkOption {
              type = lib.types.enum [
                "none"
                "client"
                "server"
                "both"
              ];
              default = "none";
              example = "server";
              description = lib.mdDoc ''
                Enables settings required for Tailscale's routing features like subnet routers and exit nodes.

                To use these these features, you will still need to call `sudo tailscale up` with the relevant flags like `--advertise-exit-node` and `--exit-node`.

                When set to `client` or `both`, reverse path filtering will be set to loose instead of strict.
                When set to `server` or `both`, IP forwarding will be enabled.
              '';
            };
            tailnetName = lib.mkOption {
              type = lib.types.str;
              default = "";
              description = ''
                The name of the tailnet
              '';
            };
            authKeyFile = lib.mkOption {
              type = lib.types.nullOr lib.types.path;
              default = null;
              description = ''
                allow you to specify a key, or set null to disable
              '';
            };
          };
          caddy = {
            pocketIdApplications = lib.mkOption {
              type = lib.types.attrsOf (
                lib.types.submodule {
                  options = {
                    subdomain = lib.mkOption {
                      type = lib.types.str;
                      description = "Subdomain of the proxied service";
                    };
                  };
                }
              );
              default = { };
              description = "Applications to protect with Pocket ID OIDC via caddy-security";
            };
          };
        };
        freeformType = lib.types.attrsOf lib.types.anything;
      });
      default = {};
    };
  };
in
{
  flake.modules.nixos.hostSpec =
    { ... }:
    {
      # Hosts supply their own metadata without a mandatory private flake
      options.hostSpec = hostOptions;
    };

  flake.modules.homeManager.hostSpec =
    { config, lib, ... }:
    {
      options.hostSpec = hostOptions;
    };

  # I think I have this covered by doing this in modules/flake/host-machines.nix by importing hostSpec under sharedModules
  # flake.modules.nixos.hostSpec-share-home =
  #   { config, ... }:
  #   {
  #     config = {
  #       home-manager = {
  #         sharedModules = [
  #           {
  #             hostSpec.impermanence = config.hostSpec.impermanence;
  #           }
  #         ];
  #       };
  #     };
  #   };
}
