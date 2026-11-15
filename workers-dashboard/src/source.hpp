#pragma once

#include <chrono>
#include <cstdint>
#include <string>

namespace watch {

// What tells that a file is still the one that was read, without reading it again
struct FileMark {
  bool exists = false;
  std::uint64_t device = 0;
  std::uint64_t node = 0;
  std::int64_t size = 0;
  std::int64_t changedSeconds = 0;
  std::int64_t changedNanoseconds = 0;

  bool operator==(const FileMark&) const = default;
};

struct Loaded {
  bool ok = false;
  // The document's bytes, or why there are none
  std::string bytes;
  std::string error;
  // Of the file as it was when it was opened
  FileMark mark;
};

// Larger than any status document: 2000 workers take about 4 MiB
inline constexpr std::size_t largestDocument = 16U * 1024U * 1024U;

// Reads a regular file, only for reading
Loaded loadFile(const std::string& path);

// The mark of the file as it is now
FileMark markOf(const std::string& path);

// Whether this build was given a status command
bool hasCommand();

// Runs the status command of the build, without a shell, and returns what it printed;
// the command is ended at once when the stop descriptor is closed at its other end
Loaded loadCommand(int stopDescriptor);

// Waits for a time; true as soon as the stop descriptor is closed at its other end (never for a descriptor of -1)
bool stopRequested(int stopDescriptor, std::chrono::milliseconds wait);

// Tells a thread that waits, or that runs the status command, to end at once: closing one end of a pipe wakes
// whoever watches the other. Nothing is ever sent through it
class StopSignal {
 public:
  StopSignal();
  StopSignal(const StopSignal&) = delete;
  StopSignal& operator=(const StopSignal&) = delete;
  ~StopSignal();

  // False when the system gave no pipe
  bool valid() const { return watched_ >= 0; }
  // What the thread to be stopped watches
  int descriptor() const { return watched_; }
  // Called once, by the thread that wants the other to end
  void request();

 private:
  int watched_ = -1;
  int held_ = -1;
};

}  // namespace watch
