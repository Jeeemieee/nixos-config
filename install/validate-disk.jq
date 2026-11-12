# Decide whether a block device may be erased by the installer
# Input: `lsblk --json --bytes -o NAME,PATH,TYPE,SIZE,RO,MODEL,SERIAL,MOUNTPOINTS,FSTYPE <device>`
# Arguments: $minBytes (smallest usable size), $needSerial ("yes" for real disks, which are confirmed by serial number)
# Output: "ok", or the reason for the refusal
def nodes: recurse(.children[]?);
if (.blockdevices | length) != 1 then
  "refused: expected exactly one device"
else
  .blockdevices[0] as $disk
  | [ $disk | nodes | { path, mountpoints: [ (.mountpoints // [])[] | select(. != null) ] } | select(.mountpoints | length > 0) ] as $mounted
  | if $disk.type != "disk" then
      "refused: \($disk.path) is a \($disk.type), not a whole disk"
    elif ($mounted | length) > 0 then
      "refused: \($disk.path) is in use (\($mounted | map("\(.path) at \(.mountpoints | join(", "))") | join("; ")))"
    elif $disk.ro == true then
      "refused: \($disk.path) is read-only"
    elif $disk.size < ($minBytes | tonumber) then
      "refused: \($disk.path) is too small (\($disk.size / 1073741824 | floor) GiB, at least \(($minBytes | tonumber) / 1073741824 | floor) GiB needed)"
    elif $needSerial == "yes" and (($disk.serial // "") == "") then
      "refused: \($disk.path) reports no serial number, so it cannot be confirmed"
    else
      "ok"
    end
end
