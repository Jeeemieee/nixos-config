#include "text.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>

#include <ftxui/screen/string.hpp>

namespace watch {

namespace {

constexpr char32_t replacement = 0xFFFD;
constexpr std::string_view cutMark = "…";

// Reads one code point of strict UTF-8; on a fault it takes one byte and returns the replacement character
char32_t decodeNext(std::string_view raw, std::size_t& position) {
  const auto byteAt = [&](std::size_t index) { return static_cast<unsigned char>(raw[index]); };
  const unsigned char first = byteAt(position);
  if (first < 0x80) {
    ++position;
    return first;
  }

  // The length and the smallest code point allowed for it, which rules out overlong forms
  std::size_t length = 0;
  char32_t smallest = 0;
  char32_t codePoint = 0;
  if ((first & 0xE0) == 0xC0) {
    length = 2;
    smallest = 0x80;
    codePoint = first & 0x1F;
  } else if ((first & 0xF0) == 0xE0) {
    length = 3;
    smallest = 0x800;
    codePoint = first & 0x0F;
  } else if ((first & 0xF8) == 0xF0) {
    length = 4;
    smallest = 0x10000;
    codePoint = first & 0x07;
  } else {
    ++position;
    return replacement;
  }
  if ((raw.size() - position) < length) {
    ++position;
    return replacement;
  }
  for (std::size_t index = 1; index < length; ++index) {
    const unsigned char next = byteAt(position + index);
    if ((next & 0xC0) != 0x80) {
      ++position;
      return replacement;
    }
    codePoint = (codePoint << 6) | (next & 0x3F);
  }

  // Overlong forms, surrogates and values beyond Unicode are not characters
  const bool surrogate = (codePoint >= 0xD800) && (codePoint <= 0xDFFF);
  if ((codePoint < smallest) || surrogate || (codePoint > 0x10FFFF)) {
    ++position;
    return replacement;
  }
  position += length;
  return codePoint;
}

void appendUtf8(std::string& out, char32_t codePoint) {
  if (codePoint < 0x80) {
    out.push_back(static_cast<char>(codePoint));
  } else if (codePoint < 0x800) {
    out.push_back(static_cast<char>(0xC0 | (codePoint >> 6)));
    out.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
  } else if (codePoint < 0x10000) {
    out.push_back(static_cast<char>(0xE0 | (codePoint >> 12)));
    out.push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
  } else {
    out.push_back(static_cast<char>(0xF0 | (codePoint >> 18)));
    out.push_back(static_cast<char>(0x80 | ((codePoint >> 12) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
  }
}

// Characters that move the cursor, change the terminal's state, reorder the line or cannot be seen
bool isUnsafe(char32_t codePoint) {
  struct Range {
    char32_t first;
    char32_t last;
  };
  static constexpr std::array<Range, 16> ranges = {{
      {0x00, 0x1F},        // C0 controls, with the escape character
      {0x7F, 0x9F},        // delete and the C1 controls
      {0xAD, 0xAD},        // soft hyphen
      {0x061C, 0x061C},    // Arabic letter mark
      {0x180E, 0x180E},    // Mongolian vowel separator
      {0x200B, 0x200F},    // zero-width characters and direction marks
      {0x2028, 0x202E},    // line and paragraph separators, direction overrides
      {0x2060, 0x206F},    // invisible operators, direction isolates
      {0xFEFF, 0xFEFF},    // byte order mark
      {0xFFF9, 0xFFFB},    // interlinear annotation
      {0xFFFE, 0xFFFF},    // not characters
      {0x1BCA0, 0x1BCA3},  // shorthand format controls
      {0x1D173, 0x1D17A},  // musical format controls
      {0xE0000, 0xE0FFF},  // tags
      {0xE000, 0xF8FF},    // private use, which a font may draw as anything
      {0xF0000, 0x10FFFF}, // private use planes
  }};
  return std::any_of(ranges.begin(), ranges.end(), [codePoint](const Range& range) {
    return (codePoint >= range.first) && (codePoint <= range.last);
  });
}

// The cells one code point takes: 0 for a combining mark, 2 for a wide character
int codePointWidth(char32_t codePoint) {
  if ((codePoint >= 0x20) && (codePoint < 0x7F)) {
    return 1;
  }
  std::string one;
  appendUtf8(one, codePoint);
  return ftxui::string_width(one);
}

std::string formatFixed(double value, int decimals) {
  std::array<char, 64> buffer{};
  std::snprintf(buffer.data(), buffer.size(), "%.*f", decimals, value);
  return buffer.data();
}

constexpr int largestUnit = 4;

double inUnit(double bytes, int unit) {
  return bytes / std::pow(1024.0, unit);
}

bool isAmount(double value) {
  return std::isfinite(value) && (value >= 0.0);
}

}  // namespace

std::string cleanText(std::string_view raw, std::size_t limit) {
  std::string out;
  std::size_t position = 0;
  std::size_t taken = 0;
  // More than two marks on one character would grow over the lines above and below
  int marksInRow = 0;

  while (position < raw.size()) {
    if (taken == limit) {
      out.append(cutMark);
      break;
    }
    char32_t codePoint = decodeNext(raw, position);

    // White space of any kind becomes one space; everything else that is unsafe becomes the replacement character
    if ((codePoint == '\t') || (codePoint == '\n') || (codePoint == '\r')) {
      codePoint = ' ';
    } else if (isUnsafe(codePoint)) {
      codePoint = replacement;
    }

    if (codePointWidth(codePoint) <= 0) {
      ++marksInRow;
      if ((taken == 0) || (marksInRow > 2)) {
        continue;
      }
    } else {
      marksInRow = 0;
    }
    appendUtf8(out, codePoint);
    ++taken;
  }
  return out;
}

int textWidth(std::string_view text) {
  int width = 0;
  std::size_t position = 0;
  while (position < text.size()) {
    width += std::max(0, codePointWidth(decodeNext(text, position)));
  }
  return width;
}

std::string cutText(std::string_view text, int width) {
  if (width <= 0) {
    return "";
  }
  if (textWidth(text) <= width) {
    return std::string(text);
  }

  // Keep what fits before the mark, which takes one cell
  std::string out;
  int used = 0;
  std::size_t position = 0;
  while (position < text.size()) {
    const std::size_t start = position;
    const int cells = std::max(0, codePointWidth(decodeNext(text, position)));
    if ((used + cells) > (width - 1)) {
      break;
    }
    out.append(text.substr(start, position - start));
    used += cells;
  }
  out.append(cutMark);
  return out;
}

std::string fitText(std::string_view text, int width, bool rightAligned) {
  if (width <= 0) {
    return "";
  }
  std::string out = cutText(text, width);
  const std::string padding(static_cast<std::size_t>(std::max(0, width - textWidth(out))), ' ');
  return rightAligned ? (padding + out) : (out + padding);
}

int sizeUnit(double bytes) {
  int unit = 0;
  while ((unit < largestUnit) && (inUnit(bytes, unit) >= 1024.0)) {
    ++unit;
  }
  return unit;
}

std::string sizeUnitName(int unit) {
  static constexpr std::array<const char*, largestUnit + 1> names = {"B", "KiB", "MiB", "GiB", "TiB"};
  return names[static_cast<std::size_t>(std::clamp(unit, 0, largestUnit))];
}

std::string formatSizeIn(double bytes, int unit) {
  if (!isAmount(bytes)) {
    return "–";
  }
  const double value = inUnit(bytes, unit);
  const bool decimal = (unit > 0) && (value < 99.95);
  return formatFixed(value, decimal ? 1 : 0);
}

std::string formatSizeLong(double bytes) {
  if (!isAmount(bytes)) {
    return "–";
  }
  const int unit = sizeUnit(bytes);
  return formatSizeIn(bytes, unit) + " " + sizeUnitName(unit);
}

std::string formatDurationShort(double seconds) {
  if (!std::isfinite(seconds)) {
    return "–";
  }
  // A time after the document's own time is shown as no time at all; the cap keeps the conversion defined
  const auto whole = static_cast<long long>(std::clamp(seconds, 0.0, 1e12));
  if (whole < 60) {
    return std::to_string(whole) + " s";
  }
  if (whole < 3600) {
    return std::to_string(whole / 60) + " m";
  }
  if (whole < 86400) {
    return std::to_string(whole / 3600) + " h";
  }
  return std::to_string(whole / 86400) + " d";
}

std::string formatDurationLong(double seconds) {
  if (!std::isfinite(seconds)) {
    return "–";
  }
  const auto whole = static_cast<long long>(std::clamp(seconds, 0.0, 1e12));
  if (whole < 3600) {
    return formatDurationShort(seconds);
  }
  if (whole < 86400) {
    const long long minutes = (whole % 3600) / 60;
    return std::to_string(whole / 3600) + " h " + ((minutes < 10) ? "0" : "") + std::to_string(minutes) + " m";
  }
  return std::to_string(whole / 86400) + " d " + std::to_string((whole % 86400) / 3600) + " h";
}

std::string formatCount(double value) {
  if (!std::isfinite(value)) {
    return "–";
  }
  return formatFixed(std::clamp(std::round(value), -1e15, 1e15), 0);
}

std::string formatShare(double value) {
  if (!std::isfinite(value)) {
    return "–";
  }
  return formatFixed(std::clamp(value, -1e6, 1e6), 1);
}

}  // namespace watch
