#pragma once

#include <cstddef>
#include <string>
#include <string_view>

namespace watch {

// The longest text taken from a document, in characters
inline constexpr std::size_t textLimit = 200;
// The longest name (project, branch, worker, role, state), in characters
inline constexpr std::size_t nameLimit = 40;

// The only way a string from a document, a path or a library's message reaches the screen:
// valid UTF-8 without control or invisible characters, cut to the limit
std::string cleanText(std::string_view raw, std::size_t limit = textLimit);

// The number of terminal cells a cleaned text takes
int textWidth(std::string_view text);

// Cut to the width with a mark, without padding
std::string cutText(std::string_view text, int width);

// Cut or padded to exactly the width; padded on the left when rightAligned
std::string fitText(std::string_view text, int width, bool rightAligned = false);

// Binary sizes: "8.5 GiB", "112 GiB" (one decimal below 100)
std::string formatSizeLong(double bytes);

// The index of the unit in which a size is at least 1, and the size in a given unit without its name
int sizeUnit(double bytes);
std::string formatSizeIn(double bytes, int unit);
std::string sizeUnitName(int unit);

// "25 m", "2 h", "3 d"
std::string formatDurationShort(double seconds);

// "25 m", "2 h 46 m", "3 d 4 h"
std::string formatDurationLong(double seconds);

// A whole number, or a number with one decimal
std::string formatCount(double value);
std::string formatShare(double value);

}  // namespace watch
