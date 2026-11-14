# Supported build system
#
# What it is    The one processor and operating-system pair evaluated by flake-parts
# Who uses it   Every per-system package, check, formatter and development shell
# A maintainer adds Another system only when all outputs and hosts support it
# Protected     Yes: this controls which package sets and checks the flake exposes (docs/UPKEEP.md)
{
  # Evaluate only the architecture used by every current host
  systems = [ "x86_64-linux" ];
}
