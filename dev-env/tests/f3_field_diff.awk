# Compare the internal field of one OpenFOAM field file (ASCII) in two cases, value by value
#
#   awk -v tol=1e-6 -f f3_field_diff.awk serial/0.5/U parallel/0.5/U
#
# Prints the number of values, how many differ as written, the largest absolute
# difference and that difference relative to the largest magnitude in the first file
# Fails when the files hold different numbers of values, when the relative difference
# exceeds tol, or, with -v strict=1, when any value differs as written

# A new file: count it and wait for its internalField
FNR == 1 { file++; state = 0 }

# The entry is followed by the number of values, an opening and a closing parenthesis
state == 0 && /^internalField[ \t]+nonuniform/ { state = 1; next }
state == 1 && /^[0-9]+$/ { state = 2; next }
state == 2 && /^\($/ { state = 3; next }
state == 3 && /^\)$/ { state = 4; next }

# One line per cell; vectors are written in parentheses
state == 3 {
    gsub(/[()]/, " ")
    for (i = 1; i <= NF; i++) value[file, ++count[file]] = $i
}

END {
    if (file != 2 || count[1] == 0 || count[1] != count[2]) {
        printf "expected two fields with the same number of values, got %d and %d\n", count[1], count[2]
        exit 1
    }
    for (i = 1; i <= count[1]; i++) {
        if ((value[1, i] "") != (value[2, i] "")) differing++
        difference = value[1, i] - value[2, i]
        if (difference < 0) difference = -difference
        if (difference > largestDifference) largestDifference = difference
        magnitude = value[1, i] + 0
        if (magnitude < 0) magnitude = -magnitude
        if (magnitude > largestMagnitude) largestMagnitude = magnitude
    }
    relative = (largestMagnitude > 0) ? largestDifference / largestMagnitude : largestDifference
    printf "%s: %d values, %d differ as written, largest difference %.3e, relative to the largest magnitude %.3e: %.3e\n", \
        FILENAME, count[1], differing, largestDifference, largestMagnitude, relative
    if (relative > tol) exit 1
    if (strict && differing > 0) exit 1
}
