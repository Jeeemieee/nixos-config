#include "source.hpp"

#include <array>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <iterator>

#include <fcntl.h>
#include <poll.h>
#include <sys/stat.h>
#include <unistd.h>

#include "statusCommand.hpp"
#include "text.hpp"

#if WORKERS_WATCH_STATUS_COMMAND
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>

extern char** environ;
#endif

namespace watch {

namespace {

#if WORKERS_WATCH_STATUS_COMMAND
// A status command that takes longer than this is ended
constexpr std::chrono::seconds commandTimeout{10};
// Enough of the command's own complaint to show one line of it
constexpr std::size_t largestComplaint = 4096;
#endif

std::string errorText(int error) {
  return cleanText(std::strerror(error));
}

// Closes a descriptor when it goes out of scope, so that no early return leaks one
class Descriptor {
 public:
  explicit Descriptor(int number = -1) : number_(number) {}
  Descriptor(const Descriptor&) = delete;
  Descriptor& operator=(const Descriptor&) = delete;
  ~Descriptor() { reset(); }

  int get() const { return number_; }
  void reset(int number = -1) {
    if (number_ >= 0) {
      ::close(number_);
    }
    number_ = number;
  }

 private:
  int number_;
};

// Appends what can be read now; false at the end of the input or on an error
bool readSome(int descriptor, std::string& into, std::size_t most) {
  std::array<char, 65536> buffer{};
  const ssize_t count = ::read(descriptor, buffer.data(), buffer.size());
  if (count < 0) {
    return (errno == EINTR) || (errno == EAGAIN);
  }
  if (count == 0) {
    return false;
  }
  // Beyond the limit the bytes are read and dropped, so that the writer is not blocked
  if (into.size() <= most) {
    into.append(buffer.data(), static_cast<std::size_t>(count));
  }
  return true;
}

FileMark markFrom(const struct stat& status) {
  return {true,
          static_cast<std::uint64_t>(status.st_dev),
          static_cast<std::uint64_t>(status.st_ino),
          static_cast<std::int64_t>(status.st_size),
          static_cast<std::int64_t>(status.st_mtim.tv_sec),
          static_cast<std::int64_t>(status.st_mtim.tv_nsec)};
}

}  // namespace

StopSignal::StopSignal() {
  std::array<int, 2> ends{};
  if (::pipe2(ends.data(), O_CLOEXEC) == 0) {
    watched_ = ends[0];
    held_ = ends[1];
  }
}

StopSignal::~StopSignal() {
  request();
  if (watched_ >= 0) {
    ::close(watched_);
  }
}

void StopSignal::request() {
  if (held_ >= 0) {
    ::close(held_);
    held_ = -1;
  }
}

FileMark markOf(const std::string& path) {
  struct stat status {};
  return (::stat(path.c_str(), &status) == 0) ? markFrom(status) : FileMark{};
}

bool stopRequested(int stopDescriptor, std::chrono::milliseconds wait) {
  pollfd stop = {stopDescriptor, 0, 0};
  // A closed other end is reported without being asked for
  return (::poll(&stop, 1, static_cast<int>(wait.count())) > 0) && ((stop.revents & (POLLHUP | POLLERR)) != 0);
}

Loaded loadFile(const std::string& path) {
  Loaded loaded;
  const std::string shown = cleanText(path);

  // Step 1. Open for reading only; not blocking, so that a pipe given as the file cannot hang the program
  const Descriptor file(::open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOCTTY));
  if (file.get() < 0) {
    loaded.error = "cannot read " + shown + ": " + errorText(errno);
    return loaded;
  }
  struct stat status {};
  if (::fstat(file.get(), &status) != 0) {
    loaded.error = "cannot read " + shown + ": " + errorText(errno);
    return loaded;
  }
  if (!S_ISREG(status.st_mode)) {
    loaded.error = "cannot read " + shown + ": not a regular file";
    return loaded;
  }
  loaded.mark = markFrom(status);

  // Step 2. Read to the end, or to one byte past the limit
  while ((loaded.bytes.size() <= largestDocument) && readSome(file.get(), loaded.bytes, largestDocument)) {
  }
  if (loaded.bytes.size() > largestDocument) {
    loaded.bytes.clear();
    loaded.error = shown + " is larger than 16 MiB, which is not a status document";
    return loaded;
  }
  loaded.ok = true;
  return loaded;
}

bool hasCommand() {
  return WORKERS_WATCH_STATUS_COMMAND != 0;
}

#if !WORKERS_WATCH_STATUS_COMMAND

Loaded loadCommand(int) {
  Loaded loaded;
  loaded.error = "this build has no status command; give --file";
  return loaded;
}

#else

Loaded loadCommand(int stopDescriptor) {
  Loaded loaded;

  // Step 1. Two pipes: what the command prints, and what it complains about
  std::array<int, 2> outEnds{};
  std::array<int, 2> complaintEnds{};
  if (::pipe2(outEnds.data(), O_CLOEXEC) != 0) {
    loaded.error = "cannot run the status command: " + errorText(errno);
    return loaded;
  }
  Descriptor outRead(outEnds[0]);
  Descriptor outWrite(outEnds[1]);
  if (::pipe2(complaintEnds.data(), O_CLOEXEC) != 0) {
    loaded.error = "cannot run the status command: " + errorText(errno);
    return loaded;
  }
  Descriptor complaintRead(complaintEnds[0]);
  Descriptor complaintWrite(complaintEnds[1]);

  // Step 2. Start the command itself: a fixed list of arguments, no shell, nothing from a document
  posix_spawn_file_actions_t actions;
  posix_spawn_file_actions_init(&actions);
  posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
  posix_spawn_file_actions_adddup2(&actions, outWrite.get(), STDOUT_FILENO);
  posix_spawn_file_actions_adddup2(&actions, complaintWrite.get(), STDERR_FILENO);
  // A group of its own, so that the command can be ended together with whatever it started
  posix_spawnattr_t attributes;
  posix_spawnattr_init(&attributes);
  posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP);
  posix_spawnattr_setpgroup(&attributes, 0);
  pid_t child = -1;
  // The interface wants pointers to characters that it does not change
  char* const* arguments = const_cast<char* const*>(statusCommand);
  const int spawned = ::posix_spawn(&child, statusCommand[0], &actions, &attributes, arguments, environ);
  posix_spawnattr_destroy(&attributes);
  posix_spawn_file_actions_destroy(&actions);
  outWrite.reset();
  complaintWrite.reset();
  if (spawned != 0) {
    loaded.error = "cannot run the status command: " + errorText(spawned);
    return loaded;
  }

  // Step 3. Read both pipes until they close, the time is up, or the program is asked to end
  const auto deadline = std::chrono::steady_clock::now() + commandTimeout;
  std::string complaint;
  bool timedOut = false;
  bool stopped = false;
  while ((outRead.get() >= 0) || (complaintRead.get() >= 0)) {
    const auto left =
        std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now());
    if (left.count() <= 0) {
      timedOut = true;
      break;
    }
    std::array<pollfd, 3> waits = {
        {{outRead.get(), POLLIN, 0}, {complaintRead.get(), POLLIN, 0}, {stopDescriptor, 0, 0}}};
    const int ready = ::poll(waits.data(), waits.size(), static_cast<int>(left.count()));
    if ((ready < 0) && (errno != EINTR)) {
      break;
    }
    if ((waits[2].revents & (POLLHUP | POLLERR)) != 0) {
      stopped = true;
      break;
    }
    if ((waits[0].revents != 0) && !readSome(outRead.get(), loaded.bytes, largestDocument)) {
      outRead.reset();
    }
    if ((waits[1].revents != 0) && !readSome(complaintRead.get(), complaint, largestComplaint)) {
      complaintRead.reset();
    }
  }

  // Step 4. End it if it still runs, and collect it so that no dead process stays behind
  if (timedOut || stopped) {
    ::kill(-child, SIGKILL);
  }
  int status = 0;
  while ((::waitpid(child, &status, 0) < 0) && (errno == EINTR)) {
  }

  // Step 5. Only a command that ended well has printed a document
  const std::string firstLine = cleanText(complaint.substr(0, complaint.find('\n')));
  if (stopped) {
    loaded.error = "the status command was ended with the program";
  } else if (timedOut) {
    loaded.error = "the status command did not end within 10 s";
  } else if (!WIFEXITED(status) || (WEXITSTATUS(status) != 0)) {
    loaded.error = "the status command failed" +
                   (WIFEXITED(status) ? (" with status " + std::to_string(WEXITSTATUS(status))) : std::string()) +
                   (firstLine.empty() ? "" : (": " + firstLine));
  } else if (loaded.bytes.size() > largestDocument) {
    loaded.error = "the status command printed more than 16 MiB, which is not a status document";
  } else {
    loaded.ok = true;
  }
  if (!loaded.ok) {
    loaded.bytes.clear();
  }
  return loaded;
}

#endif

}  // namespace watch
