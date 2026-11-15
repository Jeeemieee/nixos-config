#include <charconv>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <utility>

#include <unistd.h>

#include <ftxui/component/component.hpp>
#include <ftxui/component/event.hpp>
#include <ftxui/component/screen_interactive.hpp>
#include <ftxui/dom/elements.hpp>
#include <ftxui/dom/node.hpp>
#include <ftxui/screen/screen.hpp>
#include <ftxui/screen/terminal.hpp>

#include "model.hpp"
#include "source.hpp"
#include "text.hpp"
#include "view.hpp"

namespace {

using watch::Key;
using watch::Snapshot;
using watch::ViewState;

constexpr const char* usage =
    "workers-watch: the live overview of the workers. It only displays.\n"
    "\n"
    "  workers-watch [--file PATH] [--interval SECONDS]\n"
    "  workers-watch --once [--file PATH] [--width COLUMNS] [--height LINES] [--detail ROW]\n"
    "  workers-watch --validate [--file PATH]\n"
    "\n"
    "  --file PATH         read the status document from this file instead of the status command\n"
    "  --interval SECONDS  read it again this often (1 to 3600, default 2)\n"
    "  --once              print one frame as plain text and end\n"
    "  --validate          report whether the document follows the schema and end\n"
    "  --width COLUMNS     the width of that frame (default 160)\n"
    "  --height LINES      the height of that frame (default 50)\n"
    "  --detail ROW        that frame shows the detail of the worker in this row, counted from 0\n";

struct Options {
  std::string file;
  bool once = false;
  bool validate = false;
  bool help = false;
  int width = 160;
  int height = 50;
  int interval = 2;
  int detail = -1;
};

bool parseNumber(std::string_view text, int smallest, int largest, int& into) {
  int value = 0;
  const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
  if ((error != std::errc()) || (end != (text.data() + text.size())) || (value < smallest) || (value > largest)) {
    return false;
  }
  into = value;
  return true;
}

// The options, or nothing and the reason
std::optional<Options> parseOptions(int argc, char** argv, std::string& error) {
  Options options;
  bool widthGiven = false;
  bool heightGiven = false;
  bool intervalGiven = false;
  bool detailGiven = false;
  for (int index = 1; index < argc; ++index) {
    const std::string_view name = argv[index];
    if (name == "--once") {
      options.once = true;
      continue;
    }
    if (name == "--validate") {
      options.validate = true;
      continue;
    }
    if ((name == "--help") || (name == "-h")) {
      options.help = true;
      continue;
    }

    // Every other option takes one value
    const bool known = (name == "--file") || (name == "--width") || (name == "--height") || (name == "--interval") ||
                       (name == "--detail");
    if (!known) {
      error = "unknown option: " + watch::cleanText(name);
      return std::nullopt;
    }
    if ((index + 1) >= argc) {
      error = std::string(name) + " needs a value";
      return std::nullopt;
    }
    const std::string_view value = argv[++index];
    bool valid = true;
    if (name == "--file") {
      options.file = value;
      valid = !value.empty();
    } else if (name == "--width") {
      widthGiven = true;
      valid = parseNumber(value, 1, 1000, options.width);
    } else if (name == "--height") {
      heightGiven = true;
      valid = parseNumber(value, 1, 1000, options.height);
    } else if (name == "--interval") {
      intervalGiven = true;
      valid = parseNumber(value, 1, 3600, options.interval);
    } else {
      detailGiven = true;
      valid = parseNumber(value, 0, 100000, options.detail);
    }
    if (!valid) {
      error = "not a valid value for " + std::string(name) + ": " + watch::cleanText(value);
      return std::nullopt;
    }
  }
  if (!options.help && options.validate && (options.once || widthGiven || heightGiven || intervalGiven || detailGiven)) {
    error = "--validate may only be used with --file";
    return std::nullopt;
  }
  // Asking for the help needs no document
  if (!options.help && options.file.empty() && !watch::hasCommand()) {
    error = "this build has no status command; give --file PATH";
    return std::nullopt;
  }
  return options;
}

double nowSeconds() {
  return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
}

// What the title line calls the origin of the document
std::string originOf(const Options& options) {
  if (options.file.empty()) {
    return "status command";
  }
  const std::size_t slash = options.file.find_last_of('/');
  return watch::cleanText(options.file.substr((slash == std::string::npos) ? 0 : (slash + 1)), 30);
}

watch::Loaded load(const Options& options, int stopDescriptor) {
  return options.file.empty() ? watch::loadCommand(stopDescriptor) : watch::loadFile(options.file);
}

// What the screen shows for what was loaded; when it cannot be read, the last readable document stays, with the reason
Snapshot toSnapshot(const watch::Loaded& loaded, const Snapshot& previous) {
  std::string reason = loaded.error;
  if (loaded.ok) {
    watch::Parsed parsed = watch::parseDocument(loaded.bytes);
    if (parsed.readable) {
      Snapshot next;
      next.haveDocument = true;
      next.document = std::move(parsed.document);
      next.origin = previous.origin;
      next.staleAfter = previous.staleAfter;
      return next;
    }
    reason = parsed.reason;
  }
  Snapshot next = previous;
  next.notice = reason;
  return next;
}

int runValidate(const Options& options) {
  // The loader distinguishes a document that cannot be obtained from one whose fields are wrong
  const watch::Loaded loaded = load(options, -1);
  if (!loaded.ok) {
    std::cout << watch::cleanText(loaded.error) << "\n";
    return 2;
  }
  const watch::Parsed parsed = watch::validateDocument(loaded.bytes);
  if (!parsed.readable) {
    std::cout << watch::cleanText(parsed.reason) << "\n";
    return 2;
  }
  for (const std::string& problem : parsed.document.problems) {
    std::cout << watch::cleanText(problem) << "\n";
  }
  return parsed.document.problemCount == 0 ? 0 : 1;
}

int runOnce(const Options& options, const Snapshot& initial) {
  // Step 1. One frame, drawn by the same code as the live view
  const Snapshot snapshot = toSnapshot(load(options, -1), initial);
  ViewState state;
  if (options.detail >= 0) {
    state.selected = options.detail;
    state.detail = true;
  }
  // Plain text has no colour, so the agent's own words carry their mark
  const ftxui::Element frame = watch::drawFrame(snapshot, state, options.width, options.height, nowSeconds(), false);
  ftxui::Screen screen =
      ftxui::Screen::Create(ftxui::Dimension::Fixed(options.width), ftxui::Dimension::Fixed(options.height));
  ftxui::Render(screen, frame);

  // Step 2. Only the characters of the cells are printed: no colour and no other control sequence
  std::string out;
  for (int y = 0; y < options.height; ++y) {
    std::string line;
    for (int x = 0; x < options.width; ++x) {
      line += screen.PixelAt(x, y).character;
    }
    line.erase(line.find_last_not_of(' ') + 1);
    out += line + "\n";
  }
  std::cout << out;
  std::cout.flush();
  return 0;
}

std::optional<Key> keyOf(const ftxui::Event& event) {
  using ftxui::Event;
  const std::pair<Event, Key> keys[] = {
      {Event::ArrowUp, Key::Up},          {Event::Character('k'), Key::Up},
      {Event::ArrowDown, Key::Down},      {Event::Character('j'), Key::Down},
      {Event::PageUp, Key::PageUp},       {Event::PageDown, Key::PageDown},
      {Event::Home, Key::First},          {Event::End, Key::Last},
      {Event::Return, Key::Toggle},       {Event::Escape, Key::Close},
      {Event::ArrowLeft, Key::Previous},  {Event::ArrowRight, Key::Next},
      {Event::Character('s'), Key::Sort}, {Event::Character('p'), Key::FilterProject},
      {Event::Character('b'), Key::FilterBranch}, {Event::Character('r'), Key::FilterRole},
      {Event::Character('t'), Key::FilterState},  {Event::Character('x'), Key::ClearFilters},
      {Event::Character('?'), Key::Help},
  };
  for (const auto& [known, key] : keys) {
    if (event == known) {
      return key;
    }
  }
  return std::nullopt;
}

int runLive(const Options& options, const Snapshot& initial) {
  if ((::isatty(STDIN_FILENO) == 0) || (::isatty(STDOUT_FILENO) == 0)) {
    std::cerr << "workers-watch: the live view needs a terminal; use --once for one frame\n";
    return 2;
  }
  watch::StopSignal stop;
  if (!stop.valid()) {
    std::cerr << "workers-watch: the system gave no pipe to stop the reading thread with\n";
    return 2;
  }
  // NO_COLOR is the usual way to ask a program for no colour
  const char* noColour = std::getenv("NO_COLOR");
  const bool colour = (noColour == nullptr) || (noColour[0] == '\0');
  ftxui::ScreenInteractive screen = ftxui::ScreenInteractive::Fullscreen();
  // Without mouse tracking the terminal's own selection of text keeps working
  screen.TrackMouse(false);

  // Step 1. A second thread reads the document, so that a slow status command never blocks the keys.
  // It asks for a new frame only when there is something new to show
  std::mutex mutex;
  std::shared_ptr<const Snapshot> newest = std::make_shared<const Snapshot>(initial);
  std::thread loader([&] {
    std::shared_ptr<const Snapshot> last = newest;
    watch::Loaded previous;
    bool loadedOnce = false;
    bool overdueShown = false;
    while (true) {
      // A file that is still the same is not read again, and the same bytes are not parsed again
      const bool sameFile = loadedOnce && !options.file.empty() && (watch::markOf(options.file) == previous.mark);
      bool newFrame = false;
      if (!sameFile) {
        watch::Loaded loaded = load(options, stop.descriptor());
        const bool sameContent = loadedOnce && (loaded.ok == previous.ok) && (loaded.bytes == previous.bytes) &&
                                 (loaded.error == previous.error);
        previous = std::move(loaded);
        loadedOnce = true;
        if (!sameContent) {
          last = std::make_shared<const Snapshot>(toSnapshot(previous, *last));
          const std::lock_guard<std::mutex> lock(mutex);
          newest = last;
          newFrame = true;
        }
      }
      // A document that becomes overdue changes the frame without changing itself
      const bool overdue = watch::isOverdue(*last, nowSeconds());
      if (newFrame || (overdue != overdueShown)) {
        overdueShown = overdue;
        screen.PostEvent(ftxui::Event::Custom);
      }
      if (watch::stopRequested(stop.descriptor(), std::chrono::seconds(options.interval))) {
        return;
      }
    }
  });

  // Step 2. The screen thread draws the newest document and applies the keys; no key does anything else
  ViewState state;
  std::shared_ptr<const Snapshot> shown = newest;
  const auto takeNewest = [&] {
    const std::lock_guard<std::mutex> lock(mutex);
    shown = newest;
  };
  ftxui::Component view = ftxui::Renderer([&] {
    takeNewest();
    const ftxui::Dimensions size = ftxui::Terminal::Size();
    return watch::drawFrame(*shown, state, size.dimx, size.dimy, nowSeconds(), colour);
  });
  view = ftxui::CatchEvent(view, [&](const ftxui::Event& event) {
    if (event == ftxui::Event::Character('q')) {
      screen.Exit();
      return true;
    }
    const std::optional<Key> key = keyOf(event);
    if (!key) {
      return false;
    }
    takeNewest();
    watch::applyKey(state, *key, *shown, ftxui::Terminal::Size().dimy);
    return true;
  });
  screen.Loop(view);

  // Step 3. End the loader, and with it a status command that still runs, before the screen goes away
  stop.request();
  loader.join();
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  std::string error;
  const std::optional<Options> options = parseOptions(argc, argv, error);
  if (!options) {
    std::cerr << "workers-watch: " << error << "\n\n" << usage;
    return 2;
  }
  if (options->help) {
    std::cout << usage;
    return 0;
  }

  if (options->validate) {
    return runValidate(*options);
  }

  Snapshot initial;
  initial.origin = originOf(*options);
  if (options->once) {
    return runOnce(*options, initial);
  }
  // Three refreshes without a newer document, and it counts as outdated
  initial.staleAfter = 3.0 * options->interval + 1.0;
  return runLive(*options, initial);
}
