# Rootless Docker; hosts opt in by importing nixos.docker
{
  flake.modules.nixos.docker = {
    # Containers run with the user's own permissions: there is no root daemon and no docker group, which would be root-equivalent
    virtualisation.docker.rootless = {
      enable = true;
      # Points DOCKER_HOST at the user's rootless daemon, so `docker` works without sudo
      setSocketVariable = true;
    };
  };
}
