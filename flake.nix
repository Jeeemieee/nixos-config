{
  description = "Personal NixOS configuration for Mimir";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    # The development-environment blocks in dev-env/ (PETSc 3.25, CUDA); the hosts use nixpkgs
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";

    # pi, which 26.05 ships too old; its own pin, because pi is released far more often than the blocks should move
    nixpkgs-pi.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };

    import-tree.url = "github:vic/import-tree";

    treefmt-nix.url = "github:numtide/treefmt-nix";

    # Declares KDE Plasma settings through Home Manager
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.home-manager.follows = "home-manager";
    };

    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    lanzaboote = {
      url = "github:nix-community/lanzaboote/v1.2.0";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixos-secrets = {
      url = "git+https://github.com/Jeeemieee/nixos-secrets.git?ref=main";
      flake = false;
    };
  };

  outputs = inputs: inputs.flake-parts.lib.mkFlake { inherit inputs; } (inputs.import-tree ./modules);
}
