# Installation of a physical host from another Linux system, through a virtual machine that can only see the target disk
# The procedure is in docs/INSTALL.md; plain resources (the disk validation and its test cases) are in install/
{
  inputs,
  config,
  lib,
  ...
}:
let
  topLevel = config;

  # Hosts that can be installed this way: they import nixos.disk
  hosts = [ "mimir" ];

  # Inside the installer the target is always this device, whatever its name is on the machine that runs the installer
  installDevice = "/dev/disk/by-id/virtio-target";

  # Smallest target: the EFI and swap partitions, the system, and room to work
  minimumBytes = 96 * 1024 * 1024 * 1024;
in
{
  perSystem =
    { pkgs, system, ... }:
    lib.optionalAttrs (system == "x86_64-linux") (
      let
        targetOf = host: topLevel.flake.nixosConfigurations.${host};

        # The target's disk scripts, for the device as the installer sees it
        # The installed system does not depend on the device name: it finds its partitions by label
        diskScriptsOf =
          host:
          ((targetOf host).extendModules {
            modules = [ { hostSpec.disk.device = lib.mkForce installDevice; } ];
          }).config.system.build;

        # What the installer needs of the built system: its path, the registration of its closure, and its secrets
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
              mkdir "$out"
              echo ${cfg.system.build.toplevel} > "$out/system"
              ln -s "$closure/registration" "$out/registration"
              cp "$secretsPath" "$out/secrets.json"
            '';

        # Commands inside the installer; the paths of the target's scripts and system come from the shared folder /install
        installFormat = pkgs.writeShellApplication {
          name = "install-format";
          runtimeInputs = with pkgs; [
            age
            coreutils
            util-linux
          ];
          text = ''
            [ -e ${installDevice} ] || { echo "install-format: no target disk is attached"; exit 1; }
            echo "Formatting the target disk ($(lsblk -dn -o SIZE ${installDevice} | tr -d ' ')). Choose the disk passphrase when asked."
            # The disk was confirmed by its serial number before the installer started
            "$(cat /install/format-script)" --yes-wipe-all-disks

            # The machine's age identity is generated here, on the target disk, and never leaves it
            key=/mnt/var/lib/sops-nix/key.txt
            install -d -m 700 /mnt/var/lib/sops-nix
            if [ ! -e "$key" ]; then
              (umask 077 && age-keygen -o "$key" 2> /dev/null)
            fi
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
            payload=$(cat /install/payload 2> /dev/null) || { echo "install-system: run 'install system' on the host first"; exit 1; }
            mountpoint -q /mnt || { echo "install-system: the target is not mounted; run install-mount"; exit 1; }
            key=/mnt/var/lib/sops-nix/key.txt
            [ -s "$key" ] || { echo "install-system: $key is missing; run install-format"; exit 1; }

            # The login password is decrypted while the accounts are created at the first boot:
            # refuse to install a system whose secrets this machine cannot decrypt
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

            # The system was built on the host; its store is visible here, and this makes its paths known to this Nix
            nix-store --load-db < "$payload/registration"
            # Everything is copied from this store; without the option Nix first tries to reach the binary cache
            nixos-install --root /mnt --system "$(cat "$payload/system")" --no-root-passwd --no-channel-copy --option substituters ""
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
            # Unmounts, exports the pool and closes the encrypted container, so that the installed system can import the pool
            "$(cat /install/unmount-script)"
            sync
            echo "The target is unmounted. Powering off."
            systemctl poweroff
          '';
        };

        # The installer: no network, no disk of its own, the host's Nix store read-only, and the target disk
        installerOf =
          host:
          inputs.nixpkgs.lib.nixosSystem {
            modules = [
              "${inputs.nixpkgs}/nixos/modules/virtualisation/qemu-vm.nix"
              {
                nixpkgs.pkgs = pkgs;
                system.stateVersion = "26.05";
                networking.hostName = "installer";
                # The pool is created under the target's host ID, so the installed system imports it without force
                networking.hostId = (targetOf host).config.networking.hostId;
                documentation.enable = false;

                boot.supportedFilesystems.zfs = true;
                boot.zfs.forceImportRoot = false;

                services.getty.autologinUser = "root";
                users.motd = ''

                  Installer for ${host}. The target disk is ${installDevice}; nothing else of the host is visible.

                    install-format   erase and format the target (asks for the disk passphrase), create this machine's key
                    install-mount    mount an already formatted target again (after restarting the installer)
                    install-system   install the system built on the host
                    install-finish   unmount the target and power off

                '';
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
                  # The console is the terminal that started the installer, so the public key can be copied
                  graphics = false;
                  memorySize = 8192;
                  cores = 8;
                  # No disk of its own: the root file system is in memory
                  diskImage = null;
                  # No network: the system comes from the host's store, and no credentials enter the installer
                  qemu.networkingOptions = lib.mkForce [ "-nic none" ];
                  sharedDirectories.install = {
                    source = ''"$INSTALL_SHARE"'';
                    target = "/install";
                    securityModel = "none";
                  };
                };
              }
            ];
          };

        ovmf = pkgs.OVMF.override { secureBoot = true; };

        perHost = host: ''
          ${host})
            installerVm=${(installerOf host).config.system.build.vm}/bin/run-installer-vm
            formatScript=${lib.getExe (diskScriptsOf host).destroyFormatMount}
            mountScript=${lib.getExe (diskScriptsOf host).mount}
            unmountScript=${lib.getExe (diskScriptsOf host).unmount}
            ;;
        '';

        # The tool on the host
        installHost = pkgs.writeShellApplication {
          name = "install-host";
          runtimeInputs = with pkgs; [
            coreutils
            jq
            util-linux
            qemu_kvm
          ];
          text = ''
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

            [ "$#" -ge 2 ] || usage
            command=$1
            host=$2
            shift 2
            case "$host" in
            ${lib.concatMapStrings perHost hosts}
              *) fail "unknown host $host; known hosts: ${lib.concatStringsSep ", " hosts}" ;;
            esac

            state=''${XDG_STATE_HOME:-$HOME/.local/state}/nixos-install/$host
            share=$state/share
            mkdir -p "$share"

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

            case "$command" in
              start)
                [ -n "$target" ] || usage
                if [ "$kind" = disk ]; then
                  [ -b "$target" ] || fail "$target is not a block device"
                  device=$(realpath "$target")
                  description=$(lsblk --json --bytes -o NAME,PATH,TYPE,SIZE,RO,MODEL,SERIAL,MOUNTPOINTS,FSTYPE "$device")
                  verdict=$(jq -r --arg minBytes ${toString minimumBytes} --arg needSerial yes -f ${../../install/validate-disk.jq} <<< "$description")
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
                  # A sparse file: it only takes the space that is written
                  # As large as the laptop's 2 TB disk, so that the layout's reservation for /home fits as it must on the real disk
                  rm -f "$target"
                  truncate -s 2000G "$target"
                  device=$(realpath "$target")
                fi

                echo "$host" > "$share/host"
                echo "$formatScript" > "$share/format-script"
                echo "$mountScript" > "$share/mount-script"
                echo "$unmountScript" > "$share/unmount-script"
                rm -f "$share/payload"

                echo "Starting the installer. Leave it with install-finish (or Ctrl-a x to abort)."
                export INSTALL_SHARE=$share
                export QEMU_OPTS="-drive file=$device,format=raw,if=none,id=target,discard=unmap,detect-zeroes=unmap -device virtio-blk-pci,drive=target,serial=target ''${INSTALL_QEMU_OPTS:-}"
                exec "$installerVm"
                ;;

              system)
                # The folder the system is built from: the commit that `config install` exported, or this folder
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
                # The disk is attached as on a physical machine, whose first boot stage has no drivers for virtual disks:
                # through USB by default, or as an NVMe device with INSTALL_DISK_BUS=nvme
                case "''${INSTALL_DISK_BUS:-usb}" in
                  usb) disk="-device usb-storage,drive=disk,bus=xhci.0" ;;
                  nvme) disk="-device nvme,drive=disk,serial=rehearsal" ;;
                  *) fail "INSTALL_DISK_BUS must be usb or nvme" ;;
                esac
                # The firmware's variables persist between boots, like on a real machine; they start without keys (setup mode)
                variables=$state/rehearsal-efi-vars.fd
                if [ ! -e "$variables" ]; then
                  cp ${ovmf.variables} "$variables"
                  chmod u+w "$variables"
                fi
                # INSTALL_NETWORK=1 connects the guest; without it the host's single-use Tailscale key is not spent in a rehearsal
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
        packages = {
          install = installHost;
        }
        // lib.genAttrs' hosts (host: lib.nameValuePair "install-payload-${host}" (payloadOf host));

        apps.install = {
          type = "app";
          program = lib.getExe installHost;
          meta.description = "Install a host onto a disk through a virtual machine that can only see that disk";
        };

        # The disk validation refuses everything but a free, whole, writable, large enough disk with a serial number
        checks.install-disk-validation =
          pkgs.runCommand "install-disk-validation-check" { nativeBuildInputs = [ pkgs.jq ]; }
            ''
              verdict() {
                jq -r --arg minBytes ${toString minimumBytes} --arg needSerial yes -f ${../../install/validate-disk.jq} ${../../install/fixtures}/$1.json
              }
              expect() {
                actual=$(verdict "$1")
                case "$actual" in
                  $2) echo "$1: $actual" ;;
                  *) echo "FAIL $1: expected $2, got: $actual"; exit 1 ;;
                esac
              }
              expect free-disk "ok"
              expect system-disk "refused: * is in use (*"
              expect mounted-partition "refused: * is in use (*"
              expect active-swap "refused: * is in use (*"
              expect partition "refused: * not a whole disk"
              expect too-small "refused: * is too small (*"
              expect no-serial "refused: * reports no serial number*"
              expect read-only "refused: * is read-only"
              touch "$out"
            '';

        # The tool and the installer build
        checks.install-tool = installHost;
      }
    );
}
