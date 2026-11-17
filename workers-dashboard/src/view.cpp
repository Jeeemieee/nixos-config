#include "view.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <ctime>
#include <iterator>
#include <set>
#include <tuple>
#include <utility>

#include "text.hpp"

namespace watch {

namespace {

using ftxui::Color;
using ftxui::Decorator;
using ftxui::Element;
using ftxui::Elements;

constexpr int smallestWidth = 80;
constexpr int smallestHeight = 24;
// From this width the columns stand two cells apart and the detail has two columns
constexpr int roomyWidth = 130;
// The share of a limit from which a figure is coloured, and from which it is marked
constexpr double towardsLimit = 0.7;
constexpr double nearLimit = 0.9;

constexpr const char* roleNames[] = {"implementer", "reviewer", "deep-reviewer", "manager", "plain"};
constexpr const char* stateNames[] = {"planned", "approved", "implementing", "ready for review",
                                      "reviewed", "merged", "removable", "idle"};

struct Piece {
  std::string text;
  Decorator look = ftxui::nothing;
};
using Pieces = std::vector<Piece>;

// A look that applies only under a condition
Decorator lookIf(bool condition, Decorator look) {
  return condition ? look : Decorator(ftxui::nothing);
}

// Builds one line of the screen from pieces of text and keeps count of the cells used
class LineBuilder {
 public:
  LineBuilder& add(std::string text, Decorator look = ftxui::nothing) {
    used_ += textWidth(text);
    pieces_.push_back({std::move(text), std::move(look)});
    return *this;
  }

  LineBuilder& add(const Pieces& pieces) {
    for (const Piece& piece : pieces) {
      add(piece.text, piece.look);
    }
    return *this;
  }

  LineBuilder& add(const LineBuilder& other) { return add(other.pieces_); }

  // A cell of a table: cut or padded to its width, numbers at the right
  LineBuilder& cell(const std::string& text, int width, bool rightAligned = false, Decorator look = ftxui::nothing) {
    return add(fitText(text, width, rightAligned), std::move(look));
  }

  // Spaces up to a column, so that what follows is aligned
  LineBuilder& padTo(int column) {
    if (column > used_) {
      add(std::string(static_cast<std::size_t>(column - used_), ' '));
    }
    return *this;
  }

  int used() const { return used_; }

  // The same line, cut to a width
  LineBuilder cut(int width) const {
    LineBuilder result;
    for (const Piece& piece : pieces_) {
      if (result.used_ >= width) {
        break;
      }
      result.add(cutText(piece.text, width - result.used_), piece.look);
    }
    return result;
  }

  Element build(int width, Decorator look = ftxui::nothing) const {
    Elements cells;
    for (const Piece& piece : cut(width).pieces_) {
      cells.push_back(ftxui::text(piece.text) | piece.look);
    }
    return ftxui::hbox(std::move(cells)) | look;
  }

 private:
  Pieces pieces_;
  int used_ = 0;
};
using Lines = std::vector<LineBuilder>;

// What every drawing function knows about the window, and the one place that decides how things look
struct Canvas {
  const Document& document;
  int width;
  bool colour;

  Decorator tint(Color shade) const { return lookIf(colour, ftxui::color(shade)); }

  static bool isOwnWords(Source source) { return (source == Source::Claimed) || (source == Source::SelfReported); }

  // The agent's own words never look like a measured value: dim and italic, or marked where there is no colour
  Decorator lookOf(Source source) const {
    return lookIf(isOwnWords(source) && colour, Decorator(ftxui::dim) | ftxui::italic);
  }
  std::string marked(const std::string& value, Source source) const {
    return (isOwnWords(source) && !colour) ? ("~" + value) : value;
  }

  // Colour only where it points at something: from 70 % of a limit
  Decorator levelLook(double share) const {
    if (share >= nearLimit) {
      return tint(Color::Red);
    }
    return lookIf(share >= towardsLimit, tint(Color::Yellow));
  }

  Decorator testLook(const std::string& value) const {
    if (value == "failed") {
      return tint(Color::Red) | ftxui::bold;
    }
    return lookIf(value == "stale", tint(Color::Yellow));
  }

  Decorator alarm() const { return tint(Color::Red) | ftxui::bold; }
};

std::string repeated(const char* glyph, int times) {
  std::string out;
  for (int index = 0; index < times; ++index) {
    out += glyph;
  }
  return out;
}

std::string count(const Number& value) {
  return value ? formatCount(*value) : "–";
}

std::string share(const Number& value) {
  return value ? formatShare(*value) : "–";
}

std::string sizeLong(const Number& value) {
  return value ? formatSizeLong(*value) : "";
}

// Ages count from the document's own time, so that a frame of a fixed document never changes
std::string age(const Canvas& canvas, const Number& time, bool longForm) {
  if (!time || !canvas.document.generated) {
    return "";
  }
  const double seconds = *canvas.document.generated - *time;
  return longForm ? formatDurationLong(seconds) : formatDurationShort(seconds);
}

// Facts of one line, joined by a quiet dot; empty ones are left out
std::string joined(std::initializer_list<std::string> facts) {
  std::string out;
  for (const std::string& fact : facts) {
    if (!fact.empty()) {
      out += (out.empty() ? "" : " · ") + fact;
    }
  }
  return out;
}

// How full something is: now and at its highest, as shares of the limit
struct Level {
  bool known = false;
  double used = 0.0;
  double peak = 0.0;
};

Level levelOf(const Number& used, const Number& limit, const Number& peak = std::nullopt) {
  Level level;
  if (!used || !limit || (*limit <= 0.0)) {
    return level;
  }
  level.known = true;
  level.used = std::clamp(*used / *limit, 0.0, 1.0);
  level.peak = peak ? std::clamp(*peak / *limit, level.used, 1.0) : level.used;
  return level;
}

Level levelOf(const Amount& amount) {
  return levelOf(amount.used, amount.limit, amount.peak);
}

// A meter is useful only when it calls attention to a limit; ordinary values stay as plain figures
Pieces bar(const Canvas& canvas, int cells, const Level& level) {
  if (!level.known || (level.peak < towardsLimit)) {
    return {{fitText("", cells)}};
  }
  const int now = static_cast<int>(std::lround(level.used * cells));
  const int highest = std::max(now, static_cast<int>(std::lround(level.peak * cells)));
  return {
      {repeated("█", now), canvas.levelLook(level.used)},
      {repeated("▒", highest - now), canvas.levelLook(level.peak)},
      {fitText("", cells - highest)},
  };
}

bool isNearLimit(const Level& level) {
  return level.known && (level.peak >= nearLimit);
}

// Wraps cleaned text at words, with the last allowed line carrying the cut mark when more remains
std::vector<std::string> wrapText(const std::string& text, int width, int mostLines) {
  if (text.empty() || (width <= 0) || (mostLines <= 0)) {
    return {""};
  }
  std::vector<std::string> lines;
  std::string left = text;
  while (!left.empty() && (static_cast<int>(lines.size()) < mostLines)) {
    const bool last = (static_cast<int>(lines.size()) == (mostLines - 1));
    if (textWidth(left) <= width) {
      lines.push_back(left);
      left.clear();
      break;
    }
    if (last) {
      lines.push_back(cutText(left, width));
      left.clear();
      break;
    }

    // Find the longest UTF-8 prefix that fits, then prefer the last whole word in it
    std::size_t end = 0;
    for (std::size_t next = 1; next <= left.size(); ++next) {
      if ((next < left.size()) && ((static_cast<unsigned char>(left[next]) & 0xC0U) == 0x80U)) {
        continue;
      }
      if (textWidth(std::string_view(left).substr(0, next)) > width) {
        break;
      }
      end = next;
    }
    if (end == 0) {
      lines.push_back(cutText(left, width));
      left.clear();
      break;
    }
    const std::size_t space = left.rfind(' ', end - 1);
    const std::size_t taken = (space == std::string::npos) ? end : space;
    lines.push_back(left.substr(0, taken));
    left.erase(0, (space == std::string::npos) ? end : (space + 1));
    left.erase(0, left.find_first_not_of(' '));
  }
  return lines.empty() ? std::vector<std::string>{""} : lines;
}

std::string workerKey(const Worker& worker) {
  return worker.project + "/" + worker.branch + "/" + worker.name;
}

template <std::size_t Size>
std::size_t rankIn(const char* const (&names)[Size], const std::string& value) {
  return static_cast<std::size_t>(std::find(std::begin(names), std::end(names), value) - std::begin(names));
}

const std::string& filterField(const Worker& worker, std::size_t filter) {
  const std::string* fields[] = {&worker.project, &worker.branch, &worker.role, &worker.state};
  return *fields[filter];
}

// Keeps the selection on the same worker when the list changed, and inside the list
void settle(ViewState& state, const Document& document, const std::vector<std::size_t>& order) {
  if (order.empty()) {
    state.selected = 0;
    state.detail = false;
    return;
  }
  const auto keyAt = [&](int row) { return workerKey(document.workers[order[static_cast<std::size_t>(row)]]); };
  const int last = static_cast<int>(order.size()) - 1;
  const bool inside = (state.selected >= 0) && (state.selected <= last);
  if (!state.selectedKey.empty() && (!inside || (keyAt(state.selected) != state.selectedKey))) {
    for (int row = 0; row <= last; ++row) {
      if (keyAt(row) == state.selectedKey) {
        state.selected = row;
        break;
      }
    }
  }
  state.selected = std::clamp(state.selected, 0, last);
  state.selectedKey = keyAt(state.selected);
}

//// The header: five small tables side by side, or four lines where they do not fit

constexpr int headerBar = 10;
constexpr int blockGap = 3;

// A title line and three rows
using Block = std::array<LineBuilder, 4>;

// One row of a table with a bar: what it is, how full it is, and its figures; one figure may carry the limit mark
struct Meter {
  std::string label;
  Level level;
  std::vector<Number> figures;
  std::size_t markedFigure;
};

// A table of bars with its figures right-aligned under their heads; sizes share one unit, named once in the title
Block meterBlock(const Canvas& canvas, std::string title, std::initializer_list<const char*> heads,
                 const std::vector<Meter>& meters, bool sizes) {
  // The unit is that of the smallest limit, the last figure of a row, so that no row loses its digits
  double smallest = 0.0;
  for (const Meter& meter : meters) {
    const double limit = meter.figures.back().value_or(0.0);
    smallest = ((smallest > 0.0) && (limit > 0.0)) ? std::min(smallest, limit) : std::max(smallest, limit);
  }
  const int unit = sizes ? sizeUnit(smallest) : 0;
  if (sizes && (smallest > 0.0)) {
    title += " " + sizeUnitName(unit);
  }

  Block block;
  block[0].cell(title, 8 + headerBar, false, ftxui::bold);
  for (const char* head : heads) {
    block[0].cell(head, 6, true, ftxui::dim).add(" ");
  }
  for (std::size_t row = 0; row < meters.size(); ++row) {
    const Meter& meter = meters[row];
    LineBuilder& line = block[row + 1];
    line.cell(meter.label, 8).add(bar(canvas, headerBar, meter.level));
    for (std::size_t index = 0; index < meter.figures.size(); ++index) {
      const Number& figure = meter.figures[index];
      const bool mark = (index == meter.markedFigure) && isNearLimit(meter.level);
      line.cell(figure ? (sizes ? formatSizeIn(*figure, unit) : formatShare(*figure)) : "–", 6, true,
                lookIf(mark, canvas.levelLook(meter.level.peak)));
      line.add(mark ? "!" : " ", canvas.alarm());
    }
  }
  return block;
}

std::string timingText(const Machine& machine) {
  return "timing cores " + machine.timingCores.value_or("–") +
         (machine.timingReserved ? (*machine.timingReserved ? " reserved" : " not reserved") : "");
}

// "stopped 2× · last 2 h 46 m ago · alpha/solver/w1 (job)", or that nothing was stopped
LineBuilder stopsLine(const Canvas& canvas, bool withLast) {
  const Machine& machine = canvas.document.machine;
  LineBuilder line;
  if (!machine.stopCount) {
    return line;
  }
  if (*machine.stopCount <= 0.0) {
    return line.add("never stopped for memory", ftxui::dim);
  }
  line.add("stopped " + count(machine.stopCount) + "×", canvas.alarm());
  // The schema has the newest first
  if (withLast && !machine.stops.empty()) {
    const MemoryStop& newest = machine.stops.front();
    const std::string when = age(canvas, newest.time, true);
    line.add(" · " + joined({when.empty() ? "" : ("last " + when + " ago"),
                             newest.worker.value_or("") + (newest.what ? (" (" + *newest.what + ")") : "")}));
  }
  return line;
}

struct Totals {
  std::size_t workers = 0;
  std::size_t running = 0;
  std::size_t jobs = 0;
};

Totals totalsOf(const Document& document) {
  Totals totals;
  totals.workers = document.workers.size();
  for (const Worker& worker : document.workers) {
    totals.running += worker.running.value_or(false) ? 1U : 0U;
    totals.jobs += worker.jobs.size();
  }
  return totals;
}

std::string jobsWord(const Totals& totals) {
  return (totals.jobs == 1) ? " job" : " jobs";
}

std::string waitingText(const Machine& machine) {
  return machine.waiting ? (", " + count(machine.waiting) + " waiting") : "";
}

Lines headerBlocks(const Canvas& canvas) {
  const Machine& machine = canvas.document.machine;
  const Totals totals = totalsOf(canvas.document);
  std::array<Block, 5> blocks;

  // Step 1. The workers, and the three tables with bars
  blocks[0][0].add("WORKERS", ftxui::bold);
  blocks[0][1].cell(std::to_string(totals.workers), 3, true).add(" in all");
  blocks[0][2].cell(std::to_string(totals.running), 3, true).add(" running");
  blocks[0][3].cell(std::to_string(totals.jobs), 3, true).add(jobsWord(totals) + waitingText(machine));
  // A memory's mark stands at its peak, a disk's and the processors' at their use
  const auto withPeak = [](const std::string& label, const Amount& amount) {
    return Meter{label, levelOf(amount), {amount.used, amount.peak, amount.limit}, 1};
  };
  const auto plain = [](const std::string& label, const Number& used, const Number& limit) {
    return Meter{label, levelOf(used, limit), {used, limit}, 0};
  };
  blocks[1] = meterBlock(canvas, "MEMORY", {"now", "peak", "limit"},
                         {withPeak("workers", machine.memory), withPeak("agents", machine.agentsMemory)}, true);
  blocks[2] = meterBlock(canvas, "DISK", {"used", "limit"},
                         {plain("workers", machine.diskWorkers.used, machine.diskWorkers.limit),
                          plain("scratch", machine.diskScratch.used, machine.diskScratch.limit)},
                         true);
  blocks[3] = meterBlock(canvas, "PROCESSORS" + (machine.cpuCount ? (" (" + count(machine.cpuCount) + ")") : ""),
                         {"now", "limit"}, {plain("agents", machine.agentsCpuShare, machine.agentsCpuLimit)}, false);
  blocks[3][2].add(timingText(machine));

  // Step 2. The queue: what is taken of what; a job that holds the whole machine is named in the title
  const bool exclusive = machine.exclusive.value_or(false);
  blocks[4][0]
      .cell(exclusive ? "EXCLUSIVE" : "QUEUE", 10, false, lookIf(exclusive, canvas.tint(Color::Yellow)) | ftxui::bold)
      .cell("taken", 5, true, ftxui::dim)
      .cell("of", 5, true, ftxui::dim);
  const std::pair<const char*, const Taken*> tokens[] = {
      {"slots", &machine.slots}, {"parallel", &machine.parallel}, {"timing", &machine.timing}};
  for (std::size_t row = 0; row < std::size(tokens); ++row) {
    blocks[4][row + 1].cell(tokens[row].first, 10).cell(count(tokens[row].second->taken), 5, true).cell(
        count(tokens[row].second->total), 5, true);
  }

  // Step 3. Side by side, each table as wide as its widest row; the stops come last, since they may run on under
  // the tables beside the memory, whose last rows are empty
  std::array<int, 5> offsets{};
  int offset = 1;
  for (std::size_t index = 0; index < blocks.size(); ++index) {
    offsets[index] = offset;
    int widest = 0;
    for (const LineBuilder& row : blocks[index]) {
      widest = std::max(widest, row.used());
    }
    offset += widest + blockGap;
  }
  if ((offset - blockGap) > canvas.width) {
    return {};
  }
  blocks[1][3] = stopsLine(canvas, true).cut(offsets[4] - offsets[1] - blockGap);
  Lines lines(4);
  for (std::size_t row = 0; row < lines.size(); ++row) {
    for (std::size_t index = 0; index < blocks.size(); ++index) {
      lines[row].padTo(offsets[index]).add(blocks[index][row]);
    }
  }
  return lines;
}

// "5.7 of 18.0 GiB, peak 7.4!"
std::string amountText(const Amount& amount) {
  if (!amount.used && !amount.limit && !amount.peak) {
    return "–";
  }
  const int unit =
      sizeUnit(std::max({amount.used.value_or(0.0), amount.limit.value_or(0.0), amount.peak.value_or(0.0)}));
  return (amount.used ? formatSizeIn(*amount.used, unit) : "–") +
         (amount.limit ? (" of " + formatSizeIn(*amount.limit, unit)) : "") + " " + sizeUnitName(unit) +
         (amount.peak ? (", peak " + formatSizeIn(*amount.peak, unit)) : "") +
         (isNearLimit(levelOf(amount)) ? "!" : "");
}

Lines headerLines(const Canvas& canvas) {
  const Machine& machine = canvas.document.machine;
  const Totals totals = totalsOf(canvas.document);
  Lines lines(4);
  lines[0].add(std::to_string(totals.workers) + " workers · " + std::to_string(totals.running) + " running · " +
               std::to_string(totals.jobs) + jobsWord(totals) + waitingText(machine) + "   ");
  lines[0].add(stopsLine(canvas, false));
  lines[1].add("Memory  workers " + amountText(machine.memory) + "   agents " + amountText(machine.agentsMemory));
  lines[2].add("Disk    workers " + amountText(machine.diskWorkers) + "   scratch " + amountText(machine.diskScratch) +
               "   processors " + share(machine.agentsCpuShare) + " of " + share(machine.agentsCpuLimit));
  lines[3].add("Queue   slots " + count(machine.slots.taken) + "/" + count(machine.slots.total) + " · parallel " +
               count(machine.parallel.taken) + "/" + count(machine.parallel.total) + " · timing " +
               count(machine.timing.taken) + "/" + count(machine.timing.total) +
               (machine.exclusive.value_or(false) ? " · exclusive" : "") + "   " + timingText(machine));
  return lines;
}

bool isOverdueAt(const Snapshot& snapshot, double now) {
  const Number& generated = snapshot.document.generated;
  return snapshot.haveDocument && (snapshot.staleAfter > 0.0) && generated &&
         ((now - *generated) > snapshot.staleAfter);
}

// The time of day of a moment, with the date when it is not today's
std::string clockTime(double moment, double now) {
  const auto momentSeconds = static_cast<std::time_t>(std::clamp(moment, 0.0, 1e11));
  const auto nowSeconds = static_cast<std::time_t>(std::clamp(now, 0.0, 1e11));
  std::tm local{};
  std::tm today{};
  if ((::localtime_r(&momentSeconds, &local) == nullptr) || (::localtime_r(&nowSeconds, &today) == nullptr)) {
    return "an unknown time";
  }
  const bool sameDay = (local.tm_year == today.tm_year) && (local.tm_yday == today.tm_yday);
  std::array<char, 32> buffer{};
  std::strftime(buffer.data(), buffer.size(), sameDay ? "%H:%M:%S" : "%Y-%m-%d %H:%M", &local);
  return buffer.data();
}

// What is wrong with the newest document, with the one that is shown, and with its age
void addNotices(Elements& lines, const Canvas& canvas, const Snapshot& snapshot, double now) {
  if (!snapshot.notice.empty()) {
    // Which document is on the screen comes first, since a long reason is cut at the end
    lines.push_back(LineBuilder()
                        .add((snapshot.haveDocument ? "Unreadable, so the last readable document is shown: "
                                                    : "Unreadable: ") +
                                 snapshot.notice,
                             canvas.alarm())
                        .build(canvas.width));
  }
  if (isOverdueAt(snapshot, now)) {
    lines.push_back(LineBuilder()
                        .add("Overdue: the newest document is of " + clockTime(*snapshot.document.generated, now) +
                                 "; the status command may be counting a large project's history",
                             canvas.tint(Color::Yellow) | ftxui::bold)
                        .build(canvas.width));
  }
  if (canvas.document.problemCount > 0) {
    std::string text = "Problems (" + std::to_string(canvas.document.problemCount) + "): ";
    for (std::size_t index = 0; index < canvas.document.problems.size(); ++index) {
      text += ((index > 0) ? "; " : "") + canvas.document.problems[index];
    }
    lines.push_back(LineBuilder().add(text, canvas.tint(Color::Yellow)).build(canvas.width));
  }
}

//// The overview

enum class Field { Name, Role, State, Steps, Todo, Changed, Tests, Reviews, Memory, Cpu, Folder, Scratch };

// A column of the list. Optional columns give way in step order; names, roles, states and work stay
struct Column {
  Field field;
  const char* head;
  int width;
  int step = 0;
};

constexpr int hierarchyWidth = 4;
constexpr int memoryBar = 6;
constexpr int diskBar = 4;
constexpr int longestName = 24;
constexpr int roleWidth = 13;
constexpr int todoLines = 2;

bool isDirectWorker(const Worker& worker) {
  return (worker.role == "manager") || (worker.role == "plain");
}

int nameWidthFor(const Document& document, const std::vector<std::size_t>& order) {
  int wanted = 8;
  for (const std::size_t index : order) {
    const Worker& worker = document.workers[index];
    const int allowance = isDirectWorker(worker) ? 2 : 0;
    wanted = std::max(wanted, textWidth(worker.name) - allowance);
  }
  return std::clamp(wanted, 8, longestName);
}

// The cells left for the to-do item: the width without the hierarchy, the other columns and their gaps
int todoWidth(const std::vector<Column>& columns, int width, int gap) {
  int fixed = hierarchyWidth + (static_cast<int>(columns.size()) - 1) * gap;
  for (const Column& column : columns) {
    fixed += column.width;
  }
  return std::max(1, width - fixed);
}

std::vector<Column> columnsFor(int width, int nameWidth) {
  std::vector<Column> columns = {
      {Field::Name, "NAME", nameWidth},
      {Field::Role, "ROLE", roleWidth},
      {Field::State, "STATE", 18},
      {Field::Steps, "STEPS", 7, 8},
      {Field::Todo, "IN WORK", 0},
      {Field::Changed, "CHANGED", 7, 6},
      {Field::Tests, "TESTS", 6, 7},
      {Field::Reviews, "REVIEWS", 9, 5},
      {Field::Memory, "MEM GiB now peak", memoryBar + 13, 4},
      {Field::Cpu, "CPU", 4, 3},
      {Field::Folder, "FOLDER GiB", diskBar + 6, 2},
      {Field::Scratch, "SCRATCH", diskBar + 6, 1},
  };
  // Names and roles keep their room first; work gets enough room to read across two bounded lines
  const int gap = (width >= roomyWidth) ? 2 : 1;
  const int wanted = (width >= 160) ? 50 : ((width >= roomyWidth) ? 40 : 18);
  for (int step = 1; (step <= 8) && (todoWidth(columns, width, gap) < wanted); ++step) {
    std::erase_if(columns, [step](const Column& column) { return column.step == step; });
  }
  return columns;
}

// A size in the unit of the column's head (GiB); nothing for nothing
std::string gibibytes(const Number& bytes) {
  constexpr int unit = 3;
  if (!bytes) {
    return "–";
  }
  if (*bytes <= 0.0) {
    return "";
  }
  const std::string shown = formatSizeIn(*bytes, unit);
  return (shown == "0.0") ? "<0.1" : shown;
}

Pieces diskCell(const Canvas& canvas, const Amount& amount, int width) {
  Pieces pieces = bar(canvas, diskBar, levelOf(amount));
  pieces.push_back({fitText(gibibytes(amount.used), width - diskBar, true)});
  return pieces;
}

Pieces cellOf(const Canvas& canvas, const Worker& worker, Field field, int width) {
  const Steps& steps = worker.steps;
  switch (field) {
    case Field::Name:
      return {{fitText(worker.name, width)}};
    case Field::Role:
      return {{fitText(worker.role, width)}};
    case Field::State: {
      const std::string mark = worker.running ? (*worker.running ? "▶ " : "  ") : "? ";
      return {{mark + fitText(canvas.marked(worker.state, worker.stateSource), width - 2)}};
    }
    case Field::Steps:
      return {{fitText((steps.done || steps.total)
                           ? canvas.marked(count(steps.done) + "/" + count(steps.total), steps.source)
                           : "",
                       width, true),
               canvas.lookOf(steps.source)}};
    case Field::Todo:
      return {{fitText(steps.current ? canvas.marked(*steps.current, steps.source) : "", width),
               canvas.lookOf(steps.source)}};
    case Field::Changed:
      return {{fitText(age(canvas, steps.changed, false), width, true)}};
    case Field::Tests: {
      const std::string value = worker.acceptance.value.value_or("");
      // No run yet is no result: a quiet dash
      const bool none = (value == "never run");
      return {{fitText(none ? "–" : value, width), none ? Decorator(ftxui::dim) : canvas.testLook(value)}};
    }
    case Field::Reviews: {
      const Reviews& reviews = worker.reviews;
      if (!reviews.count) {
        return {{fitText("", width)}};
      }
      if (*reviews.count <= 0.0) {
        return {{fitText("–", width), ftxui::dim}};
      }
      const bool outdated = (reviews.outdated.value_or(0.0) > 0.0);
      return {{fitText(count(reviews.count) + (outdated ? (", " + count(reviews.outdated) + " old") : ""), width),
               lookIf(outdated, canvas.tint(Color::Yellow))}};
    }
    case Field::Memory: {
      const Level level = levelOf(worker.memory);
      Pieces pieces = bar(canvas, memoryBar, level);
      if (width > (memoryBar + 3)) {
        pieces.push_back({" " + fitText(gibibytes(worker.memory.used), 4, true) + " "});
        pieces.push_back({fitText(gibibytes(worker.memory.peak), 4, true), canvas.levelLook(level.peak)});
      }
      // A stop for memory is the stronger news than a peak near the limit
      const bool stopped = (worker.memoryStops.value_or(0.0) > 0.0);
      pieces.push_back({fitText(stopped ? (" ✕" + count(worker.memoryStops)) : (isNearLimit(level) ? "!" : ""), 3),
                        canvas.alarm()});
      return pieces;
    }
    case Field::Cpu:
      return {{fitText((worker.cpuShare.value_or(0.0) > 0.0) ? share(worker.cpuShare) : "", width, true)}};
    case Field::Folder:
      return diskCell(canvas, worker.folder, width);
    case Field::Scratch:
      return diskCell(canvas, worker.scratch, width);
  }
  return {};
}

void addOverview(Elements& lines, const Canvas& canvas, ViewState& state, const std::vector<std::size_t>& order,
                 int height, bool haveDocument) {
  const Document& document = canvas.document;
  const int width = canvas.width;
  const int gap = (width >= roomyWidth) ? 2 : 1;
  const int nameWidth = nameWidthFor(document, order);
  const std::vector<Column> columns = columnsFor(width, nameWidth);
  const auto widthOf = [&](const Column& column) {
    return (column.width > 0) ? column.width : todoWidth(columns, width, gap);
  };
  const auto todoColumn = std::find_if(columns.begin(), columns.end(),
                                       [](const Column& column) { return column.field == Field::Todo; });
  const int todoCellWidth = widthOf(*todoColumn);

  // Step 1. The heads align with branch workers, while managers use the two spare hierarchy cells for their names
  LineBuilder heads;
  heads.add(std::string(static_cast<std::size_t>(hierarchyWidth), ' '));
  for (const Column& column : columns) {
    const bool right = (column.field == Field::Changed) || (column.field == Field::Cpu);
    heads.cell(column.head, widthOf(column), right).add(std::string(static_cast<std::size_t>(gap), ' '));
  }
  lines.push_back(heads.build(width, ftxui::dim));
  if (order.empty()) {
    lines.push_back(ftxui::text(haveDocument ? "  No worker passes the filters." : "  Nothing to show yet."));
    return;
  }

  // Step 2. Projects keep two blank lines between them; branches and the managers above them keep one
  enum class Kind { Air, Project, Branch, Ordinary, Worker };
  struct Row {
    Kind kind;
    std::size_t position;
    int continuation = 0;
  };
  std::vector<Row> rows;
  bool ordinaryStarted = false;
  for (std::size_t position = 0; position < order.size(); ++position) {
    const Worker& worker = document.workers[order[position]];
    const Worker* previous = (position > 0) ? &document.workers[order[position - 1]] : nullptr;
    const bool ordinary = (worker.role == "plain");
    const bool newProject = !ordinary && ((previous == nullptr) || (previous->role == "plain") ||
                                           (previous->project != worker.project));
    if (ordinary) {
      if (!ordinaryStarted) {
        if (!rows.empty()) {
          rows.push_back({Kind::Air, position});
          rows.push_back({Kind::Air, position});
        }
        rows.push_back({Kind::Ordinary, position});
        ordinaryStarted = true;
      }
      const bool newOrdinaryProject = (previous == nullptr) || (previous->role != "plain") ||
                                      (previous->project != worker.project);
      if (newOrdinaryProject) {
        if ((previous != nullptr) && (previous->role == "plain")) {
          rows.push_back({Kind::Air, position});
        }
        rows.push_back({Kind::Branch, position});
      }
    } else if (newProject) {
      if (!rows.empty()) {
        rows.push_back({Kind::Air, position});
        rows.push_back({Kind::Air, position});
      }
      rows.push_back({Kind::Project, position});
    } else if ((worker.role != "manager") &&
               ((previous->role == "manager") || (previous->branch != worker.branch))) {
      rows.push_back({Kind::Air, position});
    }
    if (!ordinary && (worker.role != "manager") &&
        (newProject || (previous->role == "manager") || (previous->branch != worker.branch))) {
      rows.push_back({Kind::Branch, position});
    }

    const std::string todo = worker.steps.current
                                 ? canvas.marked(*worker.steps.current, worker.steps.source)
                                 : "";
    const std::vector<std::string> wrapped = wrapText(todo, todoCellWidth, todoLines);
    for (std::size_t line = 0; line < wrapped.size(); ++line) {
      rows.push_back({Kind::Worker, position, static_cast<int>(line)});
    }
  }
  const Worker& lastWorker = document.workers[order.back()];
  if (lastWorker.role != "manager") {
    rows.push_back({Kind::Air, order.size() - 1});
  }
  const int room = std::max(1, height - static_cast<int>(lines.size()));
  const auto selectedAt = std::find_if(rows.begin(), rows.end(), [&](const Row& row) {
    return (row.kind == Kind::Worker) && (row.continuation == 0) &&
           (static_cast<int>(row.position) == state.selected);
  });
  const int selectedRow = static_cast<int>(selectedAt - rows.begin());

  // Step 3. Scroll through physical lines, including wrapped work, without dropping the hierarchy or its air
  const int total = static_cast<int>(rows.size());
  state.scroll = std::min(state.scroll, std::max(0, selectedRow - 1));
  state.scroll = std::max(state.scroll, selectedRow - room + 1);
  state.scroll = std::clamp(state.scroll, 0, std::max(0, total - room));

  // Step 4. Draw only the lines in sight; every document string was cleaned by the reader before it reached here
  for (int index = state.scroll; (index < total) && (index < (state.scroll + room)); ++index) {
    const Row& row = rows[static_cast<std::size_t>(index)];
    const Worker& worker = document.workers[order[row.position]];
    if (row.kind == Kind::Air) {
      lines.push_back(ftxui::text(""));
    } else if (row.kind == Kind::Project) {
      lines.push_back(LineBuilder().add("PROJECT " + worker.project).build(width, ftxui::bold));
    } else if (row.kind == Kind::Ordinary) {
      lines.push_back(LineBuilder().add("Ordinary sessions").build(width, ftxui::bold));
    } else if (row.kind == Kind::Branch) {
      lines.push_back(LineBuilder().add("  " + ((worker.role == "plain") ? worker.project : worker.branch))
                          .build(width, ftxui::bold));
    } else {
      const bool selected = (static_cast<int>(row.position) == state.selected);
      const int indent = isDirectWorker(worker) ? 2 : hierarchyWidth;
      const int workerNameWidth = nameWidth + hierarchyWidth - indent;
      const std::string todo = worker.steps.current
                                   ? canvas.marked(*worker.steps.current, worker.steps.source)
                                   : "";
      const std::vector<std::string> wrapped = wrapText(todo, todoCellWidth, todoLines);
      LineBuilder line;
      line.add((selected && (row.continuation == 0)) ? "> " : "  ");
      line.add(std::string(static_cast<std::size_t>(indent - 2), ' '));
      for (const Column& column : columns) {
        const int cellWidth = (column.field == Field::Name) ? workerNameWidth : widthOf(column);
        const int end = line.used() + cellWidth;
        if (column.field == Field::Name) {
          if (row.continuation == 0) {
            line.add(cellOf(canvas, worker, column.field, cellWidth));
          } else {
            line.cell("", cellWidth);
          }
        } else if (column.field == Field::Todo) {
          const std::size_t wrappedLine = static_cast<std::size_t>(row.continuation);
          line.add(Pieces{{fitText((wrappedLine < wrapped.size()) ? wrapped[wrappedLine] : "", cellWidth),
                           canvas.lookOf(worker.steps.source)}});
        } else if (row.continuation == 0) {
          line.add(cellOf(canvas, worker, column.field, cellWidth));
        } else {
          line.cell("", cellWidth);
        }
        line.padTo(end + gap);
      }
      lines.push_back(line.cut(width).padTo(width).build(width, lookIf(selected, ftxui::inverted)));
    }
  }
}

//// The detail of one worker: what the agent says, what the tools recorded or derived, what the system measured

constexpr int labelWidth = 13;
constexpr int detailBar = 20;

LineBuilder labelled(const std::string& label) {
  LineBuilder line;
  line.cell(label, labelWidth);
  return line;
}

LineBuilder titled(const std::string& title) {
  LineBuilder line;
  line.add(title, ftxui::bold);
  return line;
}

// A value of the agent's own words, in a place where a reader may take it for the tools'
LineBuilder& addOwnWords(LineBuilder& line, const Canvas& canvas, const std::string& value, Source source) {
  return line.add(canvas.marked(value, source), canvas.lookOf(source));
}

std::string commitText(const Flag& onCurrentCommit) {
  return onCurrentCommit ? (*onCurrentCommit ? "on the current commit" : "on an older commit") : "";
}

Lines agentBlock(const Canvas& canvas, const Worker& worker) {
  const Steps& steps = worker.steps;
  const Decorator look = canvas.lookOf(steps.source);
  Lines lines;
  lines.push_back(titled("THE AGENT SAYS"));
  lines.emplace_back();

  // Step 1. The to-do list: the whole list when the document has it, otherwise the one item in work
  LineBuilder head = labelled("steps");
  if (!steps.done && !steps.total && !steps.current && steps.items.empty()) {
    lines.push_back(head.add("–", ftxui::dim));
  } else {
    addOwnWords(head, canvas, count(steps.done) + " of " + count(steps.total), steps.source);
    const std::string changed = age(canvas, steps.changed, true);
    head.add(changed.empty() ? "" : ("   changed " + changed + " ago"));
    // The title says claimed; any other source of the list is named
    head.add((steps.source == Source::Claimed) ? "" : ("   (" + sourceName(steps.source) + ")"), ftxui::dim);
    lines.push_back(head);
    if (steps.items.empty() && steps.current) {
      lines.push_back(addOwnWords(labelled("").add("▶ ", ftxui::bold), canvas, *steps.current, steps.source));
    }
    for (const StepItem& item : steps.items) {
      const std::string state = item.state.value_or("");
      const bool inWork = (state == "in work");
      const char* mark = inWork ? "▶ " : ((state == "done") ? "✓ " : ((state == "open") ? "  " : "? "));
      lines.push_back(labelled("")
                          .add(mark, inWork ? Decorator(ftxui::bold) : Decorator(ftxui::dim))
                          .add(canvas.marked(item.text.value_or("–"), steps.source),
                               inWork ? Decorator(ftxui::bold) : look));
    }
  }

  // Step 2. Its claim, and what was asked inside its sandbox
  lines.emplace_back();
  LineBuilder claim = labelled("claim");
  lines.push_back(worker.claim ? addOwnWords(claim, canvas, *worker.claim, worker.claimSource)
                               : claim.add("–", ftxui::dim));
  if (worker.commits.uncommitted) {
    const Source source = worker.commits.uncommittedSource;
    LineBuilder line = labelled("uncommitted");
    addOwnWords(line, canvas, *worker.commits.uncommitted ? "yes" : "no", source);
    line.add((source == Source::SelfReported) ? ", asked inside its sandbox" : ("   (" + sourceName(source) + ")"),
             ftxui::dim);
    lines.push_back(line);
  }
  return lines;
}

LineBuilder runLine(const Canvas& canvas, const Run& run, const std::string& label) {
  LineBuilder line = labelled(label);
  const std::string took = run.duration ? formatDurationLong(*run.duration) : "";
  const std::string when = age(canvas, run.time, true);
  line.add(joined({run.mode.value_or(""), "exit " + count(run.exit), took, when.empty() ? "" : (when + " ago"),
                   commitText(run.onCurrentCommit)}),
           lookIf(run.exit.value_or(0.0) != 0.0, canvas.tint(Color::Red)));
  if (run.command) {
    // The command is the agent's text
    addOwnWords(line.add("   "), canvas, *run.command, Source::Claimed);
  }
  return line;
}

Lines toolsBlock(const Canvas& canvas, const Worker& worker) {
  Lines lines;
  lines.push_back(titled("THE TOOLS RECORDED OR DERIVED"));
  lines.emplace_back();

  const bool ordinary = (worker.role == "plain");

  // Step 1. The intent and the tests
  const Intent& intent = worker.intent;
  LineBuilder intentLine = labelled("intent");
  if (ordinary) {
    intentLine.add("an ordinary session has none", ftxui::dim);
  } else if (!intent.approved) {
    intentLine.add("–", ftxui::dim);
  } else if (!*intent.approved) {
    intentLine.add("not approved");
  } else {
    const std::string when = age(canvas, intent.approvedAt, true);
    intentLine.add(joined({"approved" + (when.empty() ? "" : (" " + when + " ago")),
                           intent.approach ? ("approach " + count(intent.approach)) : ""}));
    if (intent.changedSinceApproval) {
      const bool changed = *intent.changedSinceApproval;
      intentLine.add(" · ").add(changed ? "CHANGED since" : "unchanged since",
                                lookIf(changed, canvas.alarm()));
    }
  }
  lines.push_back(intentLine);

  const Acceptance& acceptance = worker.acceptance;
  const std::string result = acceptance.value.value_or("");
  const std::string tested = age(canvas, acceptance.time, true);
  LineBuilder tests = labelled("tests");
  if (ordinary) {
    tests.add("an ordinary session has none", ftxui::dim);
  } else {
    tests.add(result.empty() ? "–" : result, result.empty() ? Decorator(ftxui::dim) : canvas.testLook(result));
    const std::string where = joined({commitText(acceptance.onCurrentCommit), tested.empty() ? "" : (tested + " ago")});
    tests.add(where.empty() ? "" : (" " + where));
  }
  lines.push_back(tests);

  // Step 2. The runs, newest first; the last run alone when the document has no list
  std::vector<const Run*> runs;
  for (const Run& run : worker.runs) {
    runs.push_back(&run);
  }
  if (runs.empty() && worker.lastQueuedRun.known) {
    runs.push_back(&worker.lastQueuedRun);
  }
  if (runs.empty()) {
    lines.push_back(labelled("runs").add("none", ftxui::dim));
  }
  for (std::size_t index = 0; index < runs.size(); ++index) {
    lines.push_back(runLine(canvas, *runs[index], (index == 0) ? "runs" : ""));
  }

  // Step 3. The commits and the reviews; a verdict is a reviewer's own words
  const Commits& commits = worker.commits;
  if (ordinary) {
    lines.push_back(labelled("commits").add("an ordinary session has none", ftxui::dim));
  } else if (commits.pending.value_or(false)) {
    lines.push_back(labelled("commits").add("not known yet", ftxui::dim));
  } else {
    lines.push_back(labelled("commits").add((commits.ahead || commits.behind)
                                                ? (count(commits.ahead) + " ahead · " + count(commits.behind) + " behind")
                                                : "–"));
  }
  const Reviews& reviews = worker.reviews;
  const bool outdated = (reviews.outdated.value_or(0.0) > 0.0);
  LineBuilder reviewLine = labelled("reviews");
  if (ordinary) {
    reviewLine.add("an ordinary session has none", ftxui::dim);
  } else if (reviews.count.value_or(0.0) <= 0.0) {
    reviewLine.add(reviews.count ? "none" : "–", ftxui::dim);
  } else {
    reviewLine.add(count(reviews.count))
        .add(outdated ? (" · " + count(reviews.outdated) + " outdated") : "",
             lookIf(outdated, canvas.tint(Color::Yellow)));
  }
  lines.push_back(reviewLine);
  for (const Verdict& verdict : reviews.verdicts) {
    LineBuilder line = labelled("");
    line.cell(verdict.by.value_or("–"), 8).add(" ");
    lines.push_back(addOwnWords(line, canvas, verdict.value.value_or("–"), verdict.source));
  }
  lines.push_back(labelled("removable").add(
      ordinary ? "an ordinary session has none" : (worker.removable ? (*worker.removable ? "yes" : "no") : "–"),
      ordinary ? Decorator(ftxui::dim) : Decorator(ftxui::nothing)));
  if (worker.nextStep.command) {
    lines.push_back(labelled("next command").add(*worker.nextStep.command));
  }
  if (!worker.reviewRelation.implementers.empty() || worker.reviewRelation.removableWithMerged) {
    std::string followed;
    for (const std::string& implementer : worker.reviewRelation.implementers) {
      followed += (followed.empty() ? "" : ", ") + implementer;
    }
    lines.push_back(labelled("follows").add(followed.empty() ? "not known" : followed));
    if (worker.reviewRelation.removableWithMerged) {
      lines.push_back(labelled("removal").add(
          *worker.reviewRelation.removableWithMerged
              ? "workers remove --merged would take this reviewer now"
              : "workers remove --merged: not now"));
    }
  }
  if (worker.removal.value) {
    lines.push_back(labelled("removal").add(*worker.removal.value));
  }
  return lines;
}

Lines placesBlock(const Worker& worker) {
  Lines lines;
  lines.push_back(titled("PLACES FROM THE TOOLS"));
  lines.emplace_back();
  const bool ordinary = (worker.role == "plain");
  const auto place = [&](const std::string& label, const Words& value, const std::string& absent) {
    return labelled(label).add(value.value_or(absent), value ? Decorator(ftxui::nothing) : Decorator(ftxui::dim));
  };
  lines.push_back(place("copy", worker.places.copy,
                        ordinary ? "an ordinary session has no folder" : "not known"));
  lines.push_back(place("reports", worker.places.reports,
                        ordinary ? "an ordinary session has none" : "not known"));
  lines.push_back(place("records", worker.places.records, "not known"));
  lines.push_back(place("task file", worker.places.task,
                        ordinary ? "an ordinary session has none"
                                 : ((worker.role == "manager") ? "a manager has no task file" : "not known")));
  lines.push_back(place("scratch", worker.places.scratch, "not known"));
  return lines;
}

Lines systemBlock(const Canvas& canvas, const Worker& worker) {
  constexpr int figure = 9;
  Lines lines;

  // Step 1. The agent's own sandbox against its limits
  LineBuilder head = titled("THE SYSTEM MEASURED");
  head.padTo(labelWidth + detailBar);
  for (const char* name : {"now", "peak", "limit"}) {
    head.cell(name, figure, true, ftxui::dim);
  }
  lines.push_back(head);
  lines.emplace_back();
  const auto resource = [&](const std::string& label, const Amount& amount, bool withPeak) {
    const Level level = levelOf(amount);
    LineBuilder line = labelled(label);
    line.add(bar(canvas, detailBar, level))
        .cell(amount.used ? sizeLong(amount.used) : "–", figure, true)
        .cell(withPeak ? sizeLong(amount.peak) : "", figure, true, canvas.levelLook(level.peak))
        .cell(sizeLong(amount.limit), figure, true);
    return line;
  };
  LineBuilder memory = resource("memory", worker.memory, true);
  memory.add(isNearLimit(levelOf(worker.memory)) ? "!" : " ", canvas.alarm());
  if (worker.memoryStops.value_or(0.0) > 0.0) {
    memory.add("  stopped " + count(worker.memoryStops) + "×", canvas.alarm());
  }
  lines.push_back(memory);
  lines.push_back(resource("folder", worker.folder, false));
  lines.push_back(resource("scratch", worker.scratch, false));
  lines.push_back(labelled("processors")
                      .add(joined({worker.cpuShare ? (share(worker.cpuShare) + " now") : "–",
                                   worker.cpuSeconds ? (count(worker.cpuSeconds) + " s used") : ""}))
                      .add(worker.gpuMemory ? ("        gpu memory  " + formatSizeLong(*worker.gpuMemory)) : ""));

  // Step 2. Its queued jobs, which count against the workers' memory and have no limit of their own
  lines.emplace_back();
  if (worker.jobs.empty()) {
    lines.push_back(labelled("jobs").add("none", ftxui::dim));
    return lines;
  }
  lines.push_back(labelled("jobs")
                      .cell("mode", 7, false, ftxui::dim)
                      .cell("state", 9, false, ftxui::dim)
                      .cell("for", 5, true, ftxui::dim)
                      .cell("memory", figure + 1, true, ftxui::dim)
                      .cell("peak", figure, true, ftxui::dim)
                      .cell("cpu", 6, true, ftxui::dim)
                      .add("   command (the agent's)", ftxui::dim));
  for (const Job& job : worker.jobs) {
    LineBuilder line = labelled("");
    line.cell(job.mode.value_or("–"), 7)
        .cell(job.state.value_or("–"), 9)
        .cell(age(canvas, job.since, false), 5, true)
        .cell(sizeLong(job.memoryUsed), figure + 1, true)
        .cell(sizeLong(job.memoryPeak), figure, true)
        .cell(share(job.cpuShare), 6, true)
        .add("   ");
    lines.push_back(addOwnWords(line, canvas, job.command.value_or("–"), Source::Claimed));
  }
  return lines;
}

void addDetail(Elements& lines, const Canvas& canvas, const Worker& worker, ViewState& state, int height) {
  const int width = canvas.width;

  // Step 1. The title line stays; everything below it scrolls
  LineBuilder title;
  title.add("  " + worker.project + " / " + worker.branch + " / " + worker.name + "     " + worker.role + "     ",
            ftxui::bold);
  title.add((worker.running.value_or(false) ? "▶ " : "") + canvas.marked(worker.state, worker.stateSource),
            ftxui::bold);
  if (Canvas::isOwnWords(worker.stateSource)) {
    title.add(" (" + sourceName(worker.stateSource) + ")", ftxui::dim);
  }
  const std::string since = age(canvas, worker.running.value_or(false) ? worker.runningSince : worker.lastRun, true);
  if (worker.running) {
    title.add("     " + std::string(*worker.running ? "running" : "not running") +
              (since.empty() ? "" : (*worker.running ? (" for " + since) : (", last started " + since + " ago"))));
  }
  lines.push_back(title.build(width));
  lines.push_back(ftxui::text(""));

  // Step 2. Two columns where there is room: the agent's words at the left, the tools and the system at the right
  Lines right = toolsBlock(canvas, worker);
  right.emplace_back();
  for (LineBuilder& line : placesBlock(worker)) {
    right.push_back(std::move(line));
  }
  right.emplace_back();
  for (LineBuilder& line : systemBlock(canvas, worker)) {
    right.push_back(std::move(line));
  }
  Lines content = agentBlock(canvas, worker);
  if (width >= roomyWidth) {
    const int leftWidth = (width / 2) - 12;
    content.resize(std::max(content.size(), right.size()));
    for (std::size_t index = 0; index < right.size(); ++index) {
      content[index] =
          LineBuilder().add("  ").add(content[index].cut(leftWidth)).padTo(leftWidth + 4).add(right[index]);
    }
    for (std::size_t index = right.size(); index < content.size(); ++index) {
      content[index] = LineBuilder().add("  ").add(content[index]);
    }
  } else {
    content.emplace_back();
    for (LineBuilder& line : right) {
      content.push_back(std::move(line));
    }
    for (LineBuilder& line : content) {
      line = LineBuilder().add("  ").add(line);
    }
  }

  // Step 3. Show the part that fits
  const int room = std::max(1, height - static_cast<int>(lines.size()));
  const int total = static_cast<int>(content.size());
  state.detailScroll = std::clamp(state.detailScroll, 0, std::max(0, total - room));
  for (int index = state.detailScroll; (index < total) && (index < (state.detailScroll + room)); ++index) {
    lines.push_back(content[static_cast<std::size_t>(index)].build(width));
  }
}

//// The list of all keys and marks, and the last line of the window

void addHelp(Elements& lines, const Canvas& canvas) {
  static constexpr std::pair<const char*, const char*> entries[] = {
      {"KEYS", ""},
      {"↑ ↓  j k", "move through the workers; scroll in the detail"},
      {"PgUp PgDn", "a page up and down; Home and End: the first and the last worker"},
      {"Enter", "open the detail of the worker; Enter or Esc closes it"},
      {"← →", "in the detail: the worker before and after"},
      {"s", "sort inside the groups by name, role or state"},
      {"p  b  r  t", "step the filter for project, branch, role or state through its values"},
      {"x", "clear the filters"},
      {"?", "this list; any key closes it"},
      {"q", "quit"},
      {"", ""},
      {"MARKS", ""},
      {"▶", "the worker's sandbox runs"},
      {"dim italic, ~", "the agent's own words, claimed or self-reported: never a measured value; ~ without colour"},
      {"█ ▒", "a limit meter appears from 70 %: now, then up to the peak"},
      {"yellow", "yellow means warning: nearing a limit, stale evidence, or an outdated result"},
      {"red", "red means trouble: a failure, a memory stop, an unreadable source, or 90 % of a limit"},
      {"magenta", "reserved for a future needs you state; the current document has no such signal"},
      {"!", "the highest value reached 90 % of its limit"},
      {"✕2", "stopped for memory twice"},
      {"–", "nothing yet: no test run, no review, or not known"},
      {"", ""},
      {"THE DETAIL", ""},
      {"agent says", "claimed by the agent, or asked inside its sandbox (self-reported)"},
      {"tools", "recorded by the broker, or derived by the tools from their records"},
      {"system", "measured by the system's own accounting"},
  };
  for (const auto& [name, meaning] : entries) {
    const bool title = (meaning[0] == '\0');
    lines.push_back(
        LineBuilder().add("  ").cell(name, 16, false, lookIf(title, ftxui::bold)).add(meaning).build(canvas.width));
  }
}

// The sorting and the filters, shown only when they are not the usual ones
std::string choicesText(const ViewState& state) {
  static constexpr const char* sorts[] = {"", "sorted by role", "sorted by state"};
  static constexpr const char* names[] = {"project", "branch", "role", "state"};
  std::string filters;
  for (std::size_t filter = 0; filter < state.filters.size(); ++filter) {
    if (!state.filters[filter].empty()) {
      filters += (filters.empty() ? "only " : ", ") + std::string(names[filter]) + " " + state.filters[filter];
    }
  }
  return joined({sorts[static_cast<std::size_t>(state.sort)], filters});
}

Element footer(const Canvas& canvas, const ViewState& state, const std::string& origin) {
  const char* keys = state.help ? "any key closes this list"
                                : (state.detail ? "↑↓ scroll   ←→ other worker   Esc back   ? all keys   q quit"
                                                : "↑↓ move   ⏎ detail   ? all keys   q quit");
  const std::string right = joined({choicesText(state), origin});
  const int rightWidth = std::min(textWidth(right), canvas.width / 2);
  return LineBuilder()
      .add(" ")
      .add(keys)
      .cut(canvas.width - rightWidth - 2)
      .padTo(canvas.width - rightWidth)
      .cell(right, rightWidth, true)
      .build(canvas.width, ftxui::dim);
}

}  // namespace

std::vector<std::size_t> visibleWorkers(const Document& document, const ViewState& state) {
  // Step 1. Keep the workers that pass every filter, apart from ordinary sessions which form the last block
  std::vector<std::size_t> workers;
  std::vector<std::size_t> ordinary;
  for (std::size_t index = 0; index < document.workers.size(); ++index) {
    bool passes = true;
    for (std::size_t filter = 0; filter < state.filters.size(); ++filter) {
      const std::string& wanted = state.filters[filter];
      passes = passes && (wanted.empty() || (filterField(document.workers[index], filter) == wanted));
    }
    if (passes) {
      ((document.workers[index].role == "plain") ? ordinary : workers).push_back(index);
    }
  }

  const auto rank = [&state](const Worker& worker) {
    switch (state.sort) {
      case ViewState::Sort::Role:
        return rankIn(roleNames, worker.role);
      case ViewState::Sort::State:
        return rankIn(stateNames, worker.state);
      case ViewState::Sort::Name:
        break;
    }
    return std::size_t{0};
  };
  const auto inside = [&](std::size_t one, std::size_t other) {
    const Worker& left = document.workers[one];
    const Worker& right = document.workers[other];
    return std::forward_as_tuple(rank(left), left.name) < std::forward_as_tuple(rank(right), right.name);
  };

  // Step 2. Each project: managers by name, then each branch's implementers, reviewers and deep reviewers
  std::vector<std::size_t> order;
  std::set<std::string> projects;
  for (const std::size_t index : workers) {
    projects.insert(document.workers[index].project);
  }
  for (const std::string& project : projects) {
    std::vector<std::size_t> managers;
    std::set<std::string> branches;
    for (const std::size_t index : workers) {
      const Worker& worker = document.workers[index];
      if (worker.project != project) {
        continue;
      }
      if (worker.role == "manager") {
        managers.push_back(index);
      } else {
        branches.insert(worker.branch);
      }
    }
    std::stable_sort(managers.begin(), managers.end(), inside);
    order.insert(order.end(), managers.begin(), managers.end());

    for (const std::string& branch : branches) {
      std::vector<std::size_t> implementers;
      std::vector<std::size_t> reviewers;
      std::vector<std::size_t> deepReviewers;
      std::vector<std::size_t> others;
      for (const std::size_t index : workers) {
        const Worker& worker = document.workers[index];
        if ((worker.project != project) || (worker.branch != branch) || (worker.role == "manager")) {
          continue;
        }
        if (worker.role == "implementer") {
          implementers.push_back(index);
        } else if (worker.role == "reviewer") {
          reviewers.push_back(index);
        } else if (worker.role == "deep-reviewer") {
          deepReviewers.push_back(index);
        } else {
          others.push_back(index);
        }
      }
      std::stable_sort(implementers.begin(), implementers.end(), inside);
      std::stable_sort(reviewers.begin(), reviewers.end(), inside);
      std::stable_sort(deepReviewers.begin(), deepReviewers.end(), inside);
      std::stable_sort(others.begin(), others.end(), inside);
      order.insert(order.end(), implementers.begin(), implementers.end());
      order.insert(order.end(), reviewers.begin(), reviewers.end());
      order.insert(order.end(), deepReviewers.begin(), deepReviewers.end());
      order.insert(order.end(), others.begin(), others.end());
    }
  }

  // Step 3. Ordinary sessions are one block of their own, last
  std::stable_sort(ordinary.begin(), ordinary.end(), [&](std::size_t one, std::size_t other) {
    const Worker& left = document.workers[one];
    const Worker& right = document.workers[other];
    return std::forward_as_tuple(left.project, rank(left), left.name) <
           std::forward_as_tuple(right.project, rank(right), right.name);
  });
  order.insert(order.end(), ordinary.begin(), ordinary.end());
  return order;
}

void applyKey(ViewState& state, Key key, const Snapshot& snapshot, int height) {
  // Any key closes the list of keys
  if (state.help || (key == Key::Help)) {
    state.help = !state.help;
    return;
  }
  const Document& document = snapshot.document;
  const std::vector<std::size_t> order = visibleWorkers(document, state);
  settle(state, document, order);
  const int page = std::max(1, height - 10);

  // Selects another worker and remembers it by its name
  const auto select = [&](int row) {
    if (order.empty()) {
      return;
    }
    state.selected = std::clamp(row, 0, static_cast<int>(order.size()) - 1);
    state.selectedKey = workerKey(document.workers[order[static_cast<std::size_t>(state.selected)]]);
    state.detailScroll = 0;
  };

  // Steps a filter to the next value that occurs in the document, and after the last one back to all
  const auto stepFilter = [&](std::size_t filter) {
    std::set<std::string> values;
    for (const Worker& worker : document.workers) {
      values.insert(filterField(worker, filter));
    }
    const auto next = values.upper_bound(state.filters[filter]);
    state.filters[filter] = (next == values.end()) ? "" : *next;
    state.scroll = 0;
  };

  // How far a key moves: through the workers in the overview, through the lines in the detail
  const int line = (key == Key::Up) ? -1 : ((key == Key::Down) ? 1 : 0);
  const int move = (key == Key::PageUp) ? -page : ((key == Key::PageDown) ? page : line);
  const int beside = (key == Key::Previous) ? -1 : ((key == Key::Next) ? 1 : 0);

  // Step 1. In the detail the arrows scroll, left and right change the worker, Enter and Esc close it
  if (state.detail) {
    if ((key == Key::Toggle) || (key == Key::Close)) {
      state.detail = false;
    } else if (beside != 0) {
      select(state.selected + beside);
    } else {
      // The lower end is known only when the detail is drawn
      state.detailScroll = (key == Key::First) ? 0 : std::max(0, state.detailScroll + move);
    }
    return;
  }

  // Step 2. In the overview
  switch (key) {
    case Key::First:
      select(0);
      break;
    case Key::Last:
      select(static_cast<int>(order.size()) - 1);
      break;
    case Key::Toggle:
      state.detail = !order.empty();
      state.detailScroll = 0;
      break;
    case Key::Sort:
      state.sort = static_cast<ViewState::Sort>((static_cast<int>(state.sort) + 1) % 3);
      break;
    case Key::FilterProject:
    case Key::FilterBranch:
    case Key::FilterRole:
    case Key::FilterState:
      stepFilter(static_cast<std::size_t>(key) - static_cast<std::size_t>(Key::FilterProject));
      break;
    case Key::ClearFilters:
      state.filters = {};
      state.scroll = 0;
      break;
    default:
      select(state.selected + move + beside);
      break;
  }
}

bool isOverdue(const Snapshot& snapshot, double now) {
  return isOverdueAt(snapshot, now);
}

ftxui::Element drawFrame(const Snapshot& snapshot, ViewState& state, int width, int height, double now, bool colour) {
  if ((width < smallestWidth) || (height < smallestHeight)) {
    return ftxui::text(cutText("workers-watch needs a window of 80 by 24; this one is " + std::to_string(width) +
                                   " by " + std::to_string(height),
                               std::max(1, width)));
  }
  const Canvas canvas{snapshot.document, width, colour};

  // Step 1. The header, with air below it where the window is high enough, and what is wrong;
  // the list of keys needs the whole of a small window
  Elements lines;
  Lines header = state.help ? Lines() : headerBlocks(canvas);
  if (header.empty() && !state.help) {
    header = headerLines(canvas);
  }
  for (const LineBuilder& line : header) {
    lines.push_back(line.build(width));
  }
  addNotices(lines, canvas, snapshot, now);
  if ((height >= 30) && !state.help) {
    lines.push_back(ftxui::text(""));
  }

  // Step 2. The list, the detail or the keys, in the room that the last line leaves
  const std::vector<std::size_t> order = visibleWorkers(snapshot.document, state);
  settle(state, snapshot.document, order);
  const int room = height - 1;
  if (state.help) {
    addHelp(lines, canvas);
  } else if (state.detail) {
    addDetail(lines, canvas, snapshot.document.workers[order[static_cast<std::size_t>(state.selected)]], state, room);
  } else {
    addOverview(lines, canvas, state, order, room, snapshot.haveDocument);
  }

  // Step 3. The last line of the window stays the last, whatever stands above it
  lines.resize(std::min(lines.size(), static_cast<std::size_t>(room)));
  while (static_cast<int>(lines.size()) < room) {
    lines.push_back(ftxui::text(""));
  }
  lines.push_back(footer(canvas, state, snapshot.origin));
  return ftxui::vbox(std::move(lines));
}

}  // namespace watch
