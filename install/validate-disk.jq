# Installer disk refusal
#
# What it is    The independent decision that a selected block device is safe for the installer to erase
# Who uses it   install start for a real disk and the install-disk-validation fixture check
# A caller adds lsblk's JSON for one selected device and $minBytes as the smallest acceptable size
# Protected     Yes: a wrong acceptance could erase the wrong disk (docs/INSTALL.md)

## Part 1. Flatten the selected device and its children
# Include partitions and mappings so any mounted child makes the whole disk unsafe
def nodes: recurse(.children[]?);

## Part 2. Refuse every unsafe shape or state
# Require exactly the one device requested by the installer
if (.blockdevices | length) != 1 then
  "refused: expected exactly one device"
else
  # Keep the selected top-level device and collect every child that is mounted
  .blockdevices[0] as $disk
  | [ $disk | nodes | { path, mountpoints: [ (.mountpoints // [])[] | select(. != null) ] } | select(.mountpoints | length > 0) ] as $mounted

  # Refuse a partition or mapping because the installer must own the whole disk
  | if $disk.type != "disk" then
      "refused: \($disk.path) is a \($disk.type), not a whole disk"
    # Refuse any mounted part because erasing it would damage a running system or active data
    elif ($mounted | length) > 0 then
      "refused: \($disk.path) is in use (\($mounted | map("\(.path) at \(.mountpoints | join(", "))") | join("; ")))"
    # Refuse read-only media because formatting cannot complete safely
    elif $disk.ro == true then
      "refused: \($disk.path) is read-only"
    # Refuse a disk too small for the declared partitions and useful working space
    elif $disk.size < ($minBytes | tonumber) then
      "refused: \($disk.path) is too small (\($disk.size / 1073741824 | floor) GiB, at least \(($minBytes | tonumber) / 1073741824 | floor) GiB needed)"
    # Refuse a disk that cannot be confirmed by typing its stable serial number
    elif ($disk.serial // "") == "" then
      "refused: \($disk.path) reports no serial number, so it cannot be confirmed"
    # Accept only after every refusal above has been ruled out
    else
      "ok"
    end
end
