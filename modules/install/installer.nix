# Isolated physical-host installer
#
# What it is    A host command and networkless VM that can see only the chosen target disk and host Nix store
# Who uses it   The owner through config install, following docs/INSTALL.md
# A host adds   nixos.disk, a name in hosts below and the secrets needed by its built system
# Protected     Yes: this tool erases, formats and installs a real disk (docs/UPKEEP.md)
{
  inputs,
  config,
  lib,
  ...
}:
let
  ## Part 1. Installable hosts and fixed limits
  # Keep the complete flake outputs available inside per-system package definitions
  topLevel = config;

  # List only hosts that import nixos.disk and are safe to install through this workflow
  hosts = [
    "mimir"
    "odin"
  ];

  # Keep each refusal independent so the check can prove that no missing input is hidden by another
  missingOdinFacts =
    {
      systemDiskById,
      hostId,
      networkDevices,
      keyExists,
      secretsExist,
    }:
    lib.optional (
      systemDiskById == null
    ) "hostSpec.odin.systemDiskById in modules/hosts/odin/default.nix"
    ++ lib.optional (hostId == null) "hostSpec.odin.hostId in modules/hosts/odin/default.nix"
    ++ lib.optional (
      networkDevices == [ ]
    ) "hostSpec.odin.networkDevices in modules/hosts/odin/default.nix"
    ++ lib.optional (!keyExists) "ssh/odin_authorized_keys in the nixos-secrets input"
    ++ lib.optional (!secretsExist) "secrets/odin.yaml in the nixos-secrets input";

  missingFactsOf =
    host:
    if host != "odin" then
      [ ]
    else
      let
        cfg = config.flake.nixosConfigurations.odin.config;
      in
      missingOdinFacts {
        inherit (cfg.hostSpec.odin) systemDiskById hostId networkDevices;
        keyExists = builtins.pathExists cfg.hostSpec.tailscaleSsh.authorizedKeysFile;
        secretsExist = builtins.pathExists "${inputs.nixos-secrets}/secrets/odin.yaml";
      };

  # Publish payloads only for hosts whose production inputs exist; the command gives the actionable refusal first
  readyHosts = builtins.filter (host: missingFactsOf host == [ ]) hosts;

  # Give the selected target one fixed device name inside the isolated VM
  installDevice = "/dev/disk/by-id/virtio-target";

  # Require enough space for EFI, swap, the system and useful working room
  minimumBytes = 96 * 1024 * 1024 * 1024;
in
{
  perSystem =
    { pkgs, ... }:
    (
      let
        ## Part 2. Target-specific build inputs
        # Look up the already declared NixOS configuration for an allowed host
        targetOf = host: topLevel.flake.nixosConfigurations.${host};

        # Rebuild only the disk scripts for the VM's fixed device name
        # The installed system later finds these partitions by label rather than by that name
        diskScriptsOf =
          host:
          ((targetOf host).extendModules {
            modules = [ { hostSpec.disk.device = lib.mkForce installDevice; } ];
          }).config.system.build;

        # Bundle the built system path, store registration and required secret names for the VM
        payloadOf =
          host:
          let
            cfg = (targetOf host).config;
          in
          pkgs.runCommand "install-payload-${host}"
            {
              closure = pkgs.closureInfo { rootPaths = [ cfg.system.build.toplevel ]; };
              secrets = builtins.toJSON (
                lib.unique (
                  lib.mapAttrsToList (_: secret: {
                    file = "${secret.sopsFile}";
                    inherit (secret) key;
                  }) cfg.sops.secrets
                )
              );
              passAsFile = [ "secrets" ];
            }
            ''
              ## Step 1. Write the built system and its closure registration
              mkdir "$out"
              echo ${cfg.system.build.toplevel} > "$out/system"
              ln -s "$closure/registration" "$out/registration"
              ## Step 2. Add the secret files and keys that the target must decrypt
              cp "$secretsPath" "$out/secrets.json"
            '';

        ## Part 3. Commands available inside the installer VM
        # Read target scripts and payload paths from the host's shared /install folder
        installFormat = pkgs.writeShellApplication {
          name = "install-format";
          runtimeInputs = with pkgs; [
            age
            coreutils
            util-linux
          ];
          text = ''
            ## Step 1. Confirm the VM received the selected target
            [ -e ${installDevice} ] || { echo "install-format: no target disk is attached"; exit 1; }
            echo "Formatting the target disk ($(lsblk -dn -o SIZE ${installDevice} | tr -d ' ')). Choose the disk passphrase when asked."
            ## Step 2. Erase and format the already confirmed disk
            "$(cat /install/format-script)" --yes-wipe-all-disks

            ## Step 3. Generate this machine's age identity on its encrypted disk
            key=/mnt/var/lib/sops-nix/key.txt
            install -d -m 700 /mnt/var/lib/sops-nix
            if [ ! -e "$key" ]; then
              (umask 077 && age-keygen -o "$key" 2> /dev/null)
            fi
            ## Step 4. Show only the public key needed for enrolment
            echo
            echo "The disk is formatted and mounted at /mnt. This machine's public key:"
            echo
            echo "    $(age-keygen -y "$key")"
            echo
            echo "Enroll it in nixos-secrets, then run 'install system' on the host and 'install-system' here (docs/INSTALL.md)."
          '';
        };

        installMount = pkgs.writeShellApplication {
          name = "install-mount";
          text = ''
            # Reuse the target's declared mount script rather than duplicating the disk layout
            "$(cat /install/mount-script)"
            echo "The target is mounted at /mnt."
          '';
        };

        installSystem = pkgs.writeShellApplication {
          name = "install-system";
          runtimeInputs = with pkgs; [
            coreutils
            jq
            nix
            nixos-install-tools
            sops
            util-linux
          ];
          text = ''
            ## Step 1. Refuse missing host payload, mount or machine key
            payload=$(cat /install/payload 2> /dev/null) || { echo "install-system: run 'install system' on the host first"; exit 1; }
            mountpoint -q /mnt || { echo "install-system: the target is not mounted; run install-mount"; exit 1; }
            key=/mnt/var/lib/sops-nix/key.txt
            [ -s "$key" ] || { echo "install-system: $key is missing; run install-format"; exit 1; }

            ## Step 2. Prove the new machine can decrypt every secret its system needs
            # The login password is decrypted while accounts are created during the first boot
            failed=0
            while IFS=$'\t' read -r file name; do
              if SOPS_AGE_KEY_FILE=$key sops decrypt --extract "[\"$name\"]" "$file" > /dev/null 2>&1; then
                echo "can decrypt: $name"
              else
                echo "CANNOT DECRYPT: $name in ''${file##*/}"
                failed=1
              fi
            done < <(jq -r '.[] | [.file, .key] | @tsv' "$payload/secrets.json")
            if [ "$failed" != 0 ]; then
              echo "install-system: this machine's key is not enrolled for every secret of the built system."
              echo "Enroll $(age-keygen -y "$key"), update the nixos-secrets input, and run 'install system' on the host again."
              exit 1
            fi

            ## Step 3. Register the host-built system in the installer's view of the shared store
            nix-store --load-db < "$payload/registration"
            ## Step 4. Copy the system from the shared host store to the target
            # A step of its own, with Nix's copy command, which passes every path on as it reads it and stays below
            # 100 MiB. Left to nixos-install, the same copy is made by Nix's substitution, which held up to 7 GiB of it
            # in memory in two dry runs: the installer was stopped for memory and the system half copied
            system=$(cat "$payload/system")
            nix --extra-experimental-features nix-command copy --no-check-sigs --to 'local?root=/mnt' "$system"

            ## Step 5. Install what is now on the target, without contacting a binary cache
            nixos-install --root /mnt --system "$system" --no-root-passwd --no-channel-copy --option substituters ""
            echo
            echo "Installed. Run install-finish to unmount the target and power off."
          '';
        };

        installFinish = pkgs.writeShellApplication {
          name = "install-finish";
          runtimeInputs = with pkgs; [
            coreutils
            systemd
          ];
          text = ''
            # Export the pool and close encryption so the installed system can import it cleanly
            "$(cat /install/unmount-script)"
            sync
            echo "The target is unmounted. Powering off."
            systemctl poweroff
          '';
        };

        ## Part 4. Isolated installer VM
        # Give the VM no network or own disk, only the read-only host store and selected target
        installerOf =
          host:
          inputs.nixpkgs.lib.nixosSystem {
            modules = [
              "${inputs.nixpkgs}/nixos/modules/virtualisation/qemu-vm.nix"
              {
                nixpkgs.pkgs = pkgs;
                system.stateVersion = "26.05";
                # Give logs and the prompt a clear temporary machine name
                networking.hostName = "installer";

                # Create the pool under the target host ID so the installed system imports it without force
                networking.hostId = (targetOf host).config.networking.hostId;
                # Keep the short-lived installer image smaller by omitting local documentation
                documentation.enable = false;

                # Include ZFS support but never force-import an unexpected pool
                boot.supportedFilesystems.zfs = true;
                boot.zfs.forceImportRoot = false;

                # Enter the isolated console directly because the VM holds no reusable login credentials
                services.getty.autologinUser = "root";
                users.motd = ''

                  Installer for ${host}. The target disk is ${installDevice}; nothing else of the host is visible.

                    install-format   erase and format the target (asks for the disk passphrase), create this machine's key
                    install-mount    mount an already formatted target again (after restarting the installer)
                    install-system   install the system built on the host
                    install-finish   unmount the target and power off

                '';
                # Put the four workflow commands and their manual recovery tools in the VM
                environment.systemPackages = [
                  installFormat
                  installMount
                  installSystem
                  installFinish
                  pkgs.age
                  pkgs.sops
                  pkgs.cryptsetup
                ];

                virtualisation = {
                  # Use the starting terminal as the console so the public key can be copied
                  graphics = false;
                  # Give formatting and installation enough memory and parallel build capacity
                  memorySize = 8192;
                  cores = 8;
                  # Keep the VM's root file system in memory so it cannot confuse another disk with the target
                  diskImage = null;
                  # Remove networking because the system comes from the host store
                  # No credentials need to enter the VM
                  qemu.networkingOptions = lib.mkForce [ "-nic none" ];
                  # Share only the selected host's scripts and payload through /install
                  sharedDirectories.install = {
                    source = ''"$INSTALL_SHARE"'';
                    target = "/install";
                    securityModel = "none";
                  };
                };
              }
            ];
          };

        # Use Secure Boot-capable firmware for rehearsal boots
        ovmf = pkgs.OVMF.override { secureBoot = true; };

        # Select the VM and disk scripts for the host named on the command line
        perHost = host: ''
          ${host})
            installerVm=${(installerOf host).config.system.build.vm}/bin/run-installer-vm
            formatScript=${lib.getExe (diskScriptsOf host).destroyFormatMount}
            mountScript=${lib.getExe (diskScriptsOf host).mount}
            unmountScript=${lib.getExe (diskScriptsOf host).unmount}
            missingFacts=${lib.escapeShellArg (lib.concatStringsSep "\n" (missingFactsOf host))}
            expectedDisk=${lib.escapeShellArg ((targetOf host).config.hostSpec.odin.systemDiskById or "")}
            ;;
        '';

        ## Part 5. Command run on the host
        installHost = pkgs.writeShellApplication {
          name = "install-host";
          runtimeInputs = with pkgs; [
            coreutils
            jq
            util-linux
            qemu_kvm
          ];
          text = ''
            ## Step 1. Define command-line help and failures
            usage() {
              cat <<'USAGE'
            Usage:
              install start <host> --disk <device>     erase a real disk (confirmed by its serial number) and start the installer
              install start <host> --image <file>      the same for a disk image file, for a rehearsal (created when missing)
              install system <host>                    build the host's system and hand it to the running installer
              install boot <host> --image <file>       boot an installed image with Secure Boot firmware in setup mode (rehearsal)
            Hosts: ${lib.concatStringsSep ", " hosts}
            USAGE
              exit 2
            }
            fail() {
              echo "install: $1" >&2
              exit 1
            }

            ## Step 2. Select an allowed host and its built scripts
            [ "$#" -ge 2 ] || usage
            command=$1
            host=$2
            shift 2
            case "$host" in
            ${lib.concatMapStrings perHost hosts}
              *) fail "unknown host $host; known hosts: ${lib.concatStringsSep ", " hosts}" ;;
            esac

            # Refuse missing Odin facts and private files before creating installer state, a target or a payload
            if { [ "$command" = start ] || [ "$command" = system ]; } && [ -n "$missingFacts" ]; then
              echo "install: $host is not ready to install; provide:" >&2
              while IFS= read -r missing; do echo "  - $missing" >&2; done <<< "$missingFacts"
              exit 1
            fi

            ## Step 3. Prepare the host's persistent installer handover folder
            state=''${XDG_STATE_HOME:-$HOME/.local/state}/nixos-install/$host
            share=$state/share
            mkdir -p "$share"

            ## Step 4. Read either a real disk or rehearsal image option
            target=
            kind=
            while [ "$#" -gt 0 ]; do
              case "$1" in
                --disk | --image)
                  [ "$#" -ge 2 ] || fail "$1 needs a path"
                  kind=''${1#--}
                  target=$2
                  shift 2
                  ;;
                *) usage ;;
              esac
            done

            ## Step 5. Run the chosen workflow command
            case "$command" in
              start)
                # Refuse an unconfirmed target before starting the destructive installer VM
                [ -n "$target" ] || usage
                if [ "$kind" = disk ]; then
                  [ -b "$target" ] || fail "$target is not a block device"
                  device=$(realpath "$target")
                  if [ -n "$expectedDisk" ]; then
                    [ -e "$expectedDisk" ] || fail "the configured system disk $expectedDisk does not exist"
                    [ "$device" = "$(realpath "$expectedDisk")" ] || fail "$target is not hostSpec.odin.systemDiskById ($expectedDisk)"
                  fi
                  description=$(lsblk --json --bytes -o NAME,PATH,TYPE,SIZE,RO,MODEL,SERIAL,MOUNTPOINTS,FSTYPE "$device")
                  verdict=$(jq -r --arg minBytes ${toString minimumBytes} -f ${../../install/validate-disk.jq} <<< "$description")
                  [ "$verdict" = ok ] || fail "$verdict"
                  serial=$(jq -r '.blockdevices[0].serial' <<< "$description")
                  echo "This disk will be ERASED completely:"
                  echo
                  lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MODEL,SERIAL "$device"
                  echo
                  read -r -p "Type its serial number to confirm: " answer
                  [ "$answer" = "$serial" ] || fail "the serial number does not match; nothing was changed"
                  [ -w "$device" ] || fail "no write access to $device; grant it for this session with: sudo setfacl -m u:$USER:rw $device"
                else
                  if [ -e "$target" ]; then
                    [ -f "$target" ] || fail "$target is not a regular file"
                    if [ "$(du -k "$target" | cut -f1)" -gt 0 ]; then
                      read -r -p "$target already holds data and will be ERASED. Type erase to confirm: " answer
                      [ "$answer" = erase ] || fail "not confirmed; nothing was changed"
                    fi
                  fi
                  # Use a sparse rehearsal image that consumes only written space
                  # Match the physical disk size so the real /home reservation still fits
                  rm -f "$target"
                  truncate -s 2000G "$target"
                  device=$(realpath "$target")
                fi

                # Hand the selected host's scripts to the isolated VM
                echo "$host" > "$share/host"
                echo "$formatScript" > "$share/format-script"
                echo "$mountScript" > "$share/mount-script"
                echo "$unmountScript" > "$share/unmount-script"
                rm -f "$share/payload"

                # Attach only the confirmed target and handover folder
                # Then replace this process with QEMU
                echo "Starting the installer. Leave it with install-finish (or Ctrl-a x to abort)."
                export INSTALL_SHARE=$share
                export QEMU_OPTS="-drive file=$device,format=raw,if=none,id=target,discard=unmap,detect-zeroes=unmap -device virtio-blk-pci,drive=target,serial=target ''${INSTALL_QEMU_OPTS:-}"
                exec "$installerVm"
                ;;

              system)
                # Build from the commit exported by config install, or from this checkout when run directly
                flake=''${INSTALL_FLAKE:-$PWD}
                [ -e "$flake/flake.nix" ] || fail "run this in the nixos-config checkout"
                [ -e "$share/format-script" ] || fail "no installer was started for $host"
                echo "Building the system of $host ..."
                payload=$(nix --extra-experimental-features 'nix-command flakes' build --no-link --print-out-paths "path:$flake#install-payload-$host")
                echo "$payload" > "$share/payload"
                echo "Built: $(cat "$payload/system")"
                echo "Now run install-system in the installer."
                ;;

              boot)
                [ "$kind" = image ] && [ -f "$target" ] || fail "boot needs --image <file> of an installed system"
                # Attach the image like physical hardware
                # The first boot stage lacks virtual-disk drivers
                # Use USB by default or NVMe when INSTALL_DISK_BUS=nvme
                case "''${INSTALL_DISK_BUS:-usb}" in
                  usb) disk="-device usb-storage,drive=disk,bus=xhci.0" ;;
                  nvme) disk="-device nvme,drive=disk,serial=rehearsal" ;;
                  *) fail "INSTALL_DISK_BUS must be usb or nvme" ;;
                esac
                # Persist firmware variables between rehearsals and begin without keys in setup mode
                variables=$state/rehearsal-efi-vars.fd
                if [ ! -e "$variables" ]; then
                  cp ${ovmf.variables} "$variables"
                  chmod u+w "$variables"
                fi
                # Keep the rehearsal offline unless requested
                # This avoids spending the host's single-use VPN key
                network="-nic none"
                if [ "''${INSTALL_NETWORK:-0}" = 1 ]; then network="-nic user,model=virtio-net-pci"; fi
                # shellcheck disable=SC2086
                exec qemu-system-x86_64 -name "$host-rehearsal" \
                  -machine q35,smm=on,accel=kvm -cpu host -smp 4 -m 8192 \
                  -global driver=cfi.pflash01,property=secure,value=on \
                  -drive if=pflash,format=raw,unit=0,readonly=on,file=${ovmf.firmware} \
                  -drive if=pflash,format=raw,unit=1,file="$variables" \
                  -drive file="$target",format=raw,if=none,id=disk,discard=unmap \
                  -device qemu-xhci,id=xhci $disk \
                  -device virtio-vga -display gtk -device usb-tablet -device virtio-rng-pci \
                  $network ''${INSTALL_QEMU_OPTS:-}
                ;;

              *) usage ;;
            esac
          '';
        };
      in
      {
        ## Part 6. Flake outputs and validation
        # Publish the host command under packages.install
        packages = {
          install = installHost;
        }
        // lib.genAttrs' readyHosts (host: lib.nameValuePair "install-payload-${host}" (payloadOf host));

        # Refuse every target except a free, whole, writable, large enough disk with a serial number
        checks.install-disk-validation =
          pkgs.runCommand "install-disk-validation-check" { nativeBuildInputs = [ pkgs.jq ]; }
            ''
              ## Step 1. Evaluate one independent disk-description fixture
              verdict() {
                jq -r --arg minBytes ${toString minimumBytes} -f ${../../install/validate-disk.jq} ${../../install/fixtures}/$1.json
              }
              ## Step 2. Compare each verdict with its pre-declared pattern
              expect() {
                actual=$(verdict "$1")
                case "$actual" in
                  $2) echo "$1: $actual" ;;
                  *) echo "FAIL $1: expected $2, got: $actual"; exit 1 ;;
                esac
              }
              ## Step 3. Cover both accepted host-sized disks and every refusal reason
              expect free-disk "ok"
              expect odin-free-disk "ok"
              expect system-disk "refused: * is in use (*"
              expect mounted-partition "refused: * is in use (*"
              expect active-swap "refused: * is in use (*"
              expect partition "refused: * not a whole disk"
              expect too-small "refused: * is too small (*"
              expect no-serial "refused: * reports no serial number*"
              expect read-only "refused: * is read-only"
              touch "$out"
            '';

        # Refuse Odin until every production fact and private input named by the handoff exists
        checks.install-odin-preflight =
          let
            complete = {
              systemDiskById = "/dev/disk/by-id/test";
              hostId = "8425e349";
              networkDevices = [ "eth0" ];
              keyExists = true;
              secretsExist = true;
            };
          in
          assert
            missingFactsOf "odin" == [
              "hostSpec.odin.systemDiskById in modules/hosts/odin/default.nix"
              "hostSpec.odin.hostId in modules/hosts/odin/default.nix"
              "hostSpec.odin.networkDevices in modules/hosts/odin/default.nix"
              "ssh/odin_authorized_keys in the nixos-secrets input"
              "secrets/odin.yaml in the nixos-secrets input"
            ];
          assert missingOdinFacts complete == [ ];
          assert
            missingOdinFacts (complete // { systemDiskById = null; }) == [
              "hostSpec.odin.systemDiskById in modules/hosts/odin/default.nix"
            ];
          assert
            missingOdinFacts (complete // { hostId = null; }) == [
              "hostSpec.odin.hostId in modules/hosts/odin/default.nix"
            ];
          assert
            missingOdinFacts (complete // { networkDevices = [ ]; }) == [
              "hostSpec.odin.networkDevices in modules/hosts/odin/default.nix"
            ];
          assert
            missingOdinFacts (complete // { keyExists = false; }) == [
              "ssh/odin_authorized_keys in the nixos-secrets input"
            ];
          assert
            missingOdinFacts (complete // { secretsExist = false; }) == [
              "secrets/odin.yaml in the nixos-secrets input"
            ];
          pkgs.runCommand "install-odin-preflight-check" { nativeBuildInputs = [ installHost ]; } ''
            ## Step 1. Run the real command and require refusal before an image is created
            if install-host start odin --image "$PWD/target.raw" > actual 2>&1; then
              echo "FAIL: the incomplete Odin host was accepted"
              exit 1
            fi
            test ! -e "$PWD/target.raw"

            ## Step 2. Require the build handover to refuse for the same reason, before creating installer state
            if install-host system odin > actual-system 2>&1; then
              echo "FAIL: the incomplete Odin payload build was accepted"
              exit 1
            fi
            test ! -e "$HOME/.local/state/nixos-install/odin"

            ## Step 3. Require every actionable destination in both refusals
            grep -F "odin is not ready to install" actual
            grep -F "odin is not ready to install" actual-system
            grep -F "hostSpec.odin.systemDiskById in modules/hosts/odin/default.nix" actual
            grep -F "hostSpec.odin.hostId in modules/hosts/odin/default.nix" actual
            grep -F "hostSpec.odin.networkDevices in modules/hosts/odin/default.nix" actual
            grep -F "ssh/odin_authorized_keys in the nixos-secrets input" actual
            grep -F "secrets/odin.yaml in the nixos-secrets input" actual
            touch "$out"
          '';

        # Build the command and all installer dependencies as a flake check
        checks.install-tool = installHost;
      }
    );
}
