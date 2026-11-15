#pragma once

#include <array>
#include <string>
#include <vector>

#include <ftxui/dom/elements.hpp>

#include "model.hpp"

namespace watch {

// What the loader hands to the screen: the last readable document and what is wrong now
struct Snapshot {
  bool haveDocument = false;
  Document document;
  // Why the newest document could not be read; empty when it could
  std::string notice;
  // Where the document comes from, for the title line
  std::string origin;
  // The age in seconds from which the document counts as outdated; none when 0
  double staleAfter = 0.0;
};

enum class Key {
  Up,
  Down,
  PageUp,
  PageDown,
  First,
  Last,
  Toggle,
  Close,
  Previous,
  Next,
  Sort,
  FilterProject,
  FilterBranch,
  FilterRole,
  FilterState,
  ClearFilters,
  Help,
};

// What the user chose with the keys; nothing of it is stored anywhere
struct ViewState {
  enum class Sort { Name, Role, State };
  Sort sort = Sort::Name;
  // Project, branch, role and state; empty means all
  std::array<std::string, 4> filters;
  int selected = 0;
  // The selected worker is followed by its name when the list changes
  std::string selectedKey;
  int scroll = 0;
  bool detail = false;
  int detailScroll = 0;
  // The list of all keys and marks is shown instead of the workers
  bool help = false;
};

// The workers that pass the filters, in the order of the rows, as indices into the document
std::vector<std::size_t> visibleWorkers(const Document& document, const ViewState& state);

void applyKey(ViewState& state, Key key, const Snapshot& snapshot, int height);

// One whole frame; it also keeps the selection and the scrolling inside what exists.
// Without colour, the agent's own words carry a mark instead of their dim and italic look
ftxui::Element drawFrame(const Snapshot& snapshot, ViewState& state, int width, int height, double now, bool colour);

// Whether the document is older than its producer should let it get; the frame then says so
bool isOverdue(const Snapshot& snapshot, double now);

}  // namespace watch
