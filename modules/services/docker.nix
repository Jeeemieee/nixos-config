# Rootless containers
#
# What it is    Docker running entirely under the user's account rather than through a root daemon
# Who uses it   A NixOS host by importing nixos.docker; the workstation profile imports it
# A host adds   Nothing; users do not join a root-equivalent docker group
# Protected     No: the deliberately rootless service does not grant system privileges
{
  flake.modules.nixos.docker = {
    # Run containers with the user's permissions and avoid both a root daemon and root-equivalent group
    virtualisation.docker.rootless = {
      # Start Docker's per-user daemon instead of the system daemon
      enable = true;

      # Point Docker commands at the rootless socket so they work without sudo
      setSocketVariable = true;
    };
  };
}
