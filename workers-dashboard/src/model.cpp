#include "model.hpp"

#include <algorithm>
#include <cmath>
#include <exception>
#include <set>
#include <tuple>
#include <utility>

#include <nlohmann/json.hpp>

#include "text.hpp"

namespace watch {

namespace {

using Json = nlohmann::json;

// The schema nests six levels; anything much deeper is not a status document
constexpr int deepestLevel = 32;
constexpr std::size_t problemsKept = 20;
constexpr double largestNumber = 1e18;

// The most entries read from each list; the schema allows 100 items and 20 runs
constexpr std::size_t mostWorkers = 2000;
constexpr std::size_t mostItems = 100;
constexpr std::size_t mostEntries = 20;

std::string article(const Json& value) {
  const std::string type = value.type_name();
  return (type == "null") ? type : ((type == "object") || (type == "array") ? "an " : "a ") + type;
}

void noteProblem(Document& document, const std::string& field, const std::string& what, bool keepAll) {
  ++document.problemCount;
  if (keepAll || (document.problems.size() < problemsKept)) {
    document.problems.push_back(cleanText(field + " " + what));
  }
}

// Reads the members of one JSON object, noting every member that is not what the schema says
class Reader {
 public:
  Reader(const Json* node, std::string path, Document& document, bool keepAll)
      : node_(node), path_(std::move(path)), document_(&document), keepAll_(keepAll) {}

  bool present() const { return node_ != nullptr; }

  Reader object(const char* key, bool required = false) const {
    const Json* value = find(key, required);
    if ((value != nullptr) && !value->is_object()) {
      problem(key, "is " + article(*value) + ", expected an object");
      value = nullptr;
    }
    return Reader(value, pathOf(key), *document_, keepAll_);
  }

  std::vector<Reader> list(const char* key, std::size_t most, bool required = false) const {
    std::vector<Reader> readers;
    const Json* value = find(key, required);
    if (value == nullptr) {
      return readers;
    }
    if (!value->is_array()) {
      problem(key, "is " + article(*value) + ", expected a list");
      return readers;
    }
    if (value->size() > most) {
      problem(key, "has " + std::to_string(value->size()) + " entries, only the first " + std::to_string(most) +
                       " are read");
    }
    const std::size_t count = std::min(value->size(), most);
    for (std::size_t index = 0; index < count; ++index) {
      const Json& entry = (*value)[index];
      const std::string entryPath = pathOf(key) + "[" + std::to_string(index) + "]";
      if (entry.is_object()) {
        readers.emplace_back(&entry, entryPath, *document_, keepAll_);
      } else {
        note(entryPath, "is " + article(entry) + ", expected an object");
      }
    }
    return readers;
  }

  std::vector<std::string> wordsList(const char* key, std::size_t most) const {
    std::vector<std::string> words;
    const Json* value = find(key, false);
    if (value == nullptr) {
      return words;
    }
    if (!value->is_array()) {
      problem(key, "is " + article(*value) + ", expected a list");
      return words;
    }
    if (value->size() > most) {
      problem(key, "has " + std::to_string(value->size()) + " entries, only the first " + std::to_string(most) +
                       " are read");
    }
    const std::size_t count = std::min(value->size(), most);
    for (std::size_t index = 0; index < count; ++index) {
      const Json& entry = (*value)[index];
      if (!entry.is_string()) {
        note(pathOf(key) + "[" + std::to_string(index) + "]", "is " + article(entry) + ", expected text");
        continue;
      }
      words.push_back(cleanText(entry.get_ref<const std::string&>(), nameLimit));
    }
    return words;
  }

  Number number(const char* key, bool negativeAllowed = false, bool required = false) const {
    const Json* value = find(key, required);
    if (value == nullptr) {
      return std::nullopt;
    }
    if (!value->is_number()) {
      problem(key, "is " + article(*value) + ", expected a number");
      return std::nullopt;
    }
    const double read = value->get<double>();
    if (!std::isfinite(read) || (std::abs(read) > largestNumber)) {
      problem(key, "is too large");
      return std::nullopt;
    }
    if ((read < 0.0) && !negativeAllowed) {
      problem(key, "is negative");
      return std::nullopt;
    }
    return read;
  }

  Flag flag(const char* key) const {
    const Json* value = find(key, false);
    if (value == nullptr) {
      return std::nullopt;
    }
    if (!value->is_boolean()) {
      problem(key, "is " + article(*value) + ", expected true or false");
      return std::nullopt;
    }
    return value->get<bool>();
  }

  Words words(const char* key, std::size_t limit = textLimit, bool required = false) const {
    const Json* value = find(key, required);
    if (value == nullptr) {
      return std::nullopt;
    }
    if (!value->is_string()) {
      problem(key, "is " + article(*value) + ", expected text");
      return std::nullopt;
    }
    return cleanText(value->get_ref<const std::string&>(), limit);
  }

  // A name that every row needs; a dash stands for one that is missing
  std::string name(const char* key) const {
    if (!present()) {
      return "–";
    }
    const Words read = words(key, nameLimit, true);
    return (read && !read->empty()) ? *read : "–";
  }

  // A source that is not one of the five is treated as the least trusted one
  Source source(Source fallback) const {
    const Words read = words("source", nameLimit);
    if (!read) {
      return (present() && (node_->find("source") != node_->end())) ? Source::Claimed : fallback;
    }
    for (const Source known :
         {Source::Measured, Source::Recorded, Source::Derived, Source::SelfReported, Source::Claimed}) {
      if (*read == sourceName(known)) {
        return known;
      }
    }
    problem("source", "is '" + *read + "', which is not a known source; shown as claimed");
    return Source::Claimed;
  }

  void problem(const char* key, const std::string& what) const { note(pathOf(key), what); }

 private:
  const Json* find(const char* key, bool required) const {
    if (node_ == nullptr) {
      return nullptr;
    }
    const auto member = node_->find(key);
    if (member == node_->end()) {
      if (required) {
        problem(key, "is missing");
      }
      return nullptr;
    }
    return &*member;
  }

  std::string pathOf(const char* key) const { return path_.empty() ? std::string(key) : (path_ + "." + key); }

  void note(const std::string& field, const std::string& what) const {
    noteProblem(*document_, field, what, keepAll_);
  }

  const Json* node_;
  std::string path_;
  Document* document_;
  bool keepAll_;
};

Amount readAmount(const Reader& parent, const char* key) {
  const Reader reader = parent.object(key);
  return {reader.number("used"), reader.number("limit"), reader.number("peak")};
}

Taken readTaken(const Reader& parent, const char* key) {
  const Reader reader = parent.object(key);
  return {reader.number("taken"), reader.number("total")};
}

Run readRun(const Reader& reader) {
  Run run;
  run.known = reader.present();
  run.mode = reader.words("mode", nameLimit);
  run.command = reader.words("command");
  run.time = reader.number("time");
  // A process ended by a signal may be recorded with a negative status
  run.exit = reader.number("exit", true);
  run.duration = reader.number("duration");
  run.onCurrentCommit = reader.flag("onCurrentCommit");
  run.source = reader.source(Source::Recorded);
  return run;
}

Machine readMachine(const Reader& reader) {
  Machine machine;
  machine.memory = readAmount(reader, "memory");
  machine.agentsMemory = readAmount(reader, "agentsMemory");

  const Reader agentsCpu = reader.object("agentsCpu");
  machine.agentsCpuShare = agentsCpu.number("share");
  machine.agentsCpuLimit = agentsCpu.number("limit");

  const Reader stops = reader.object("memoryStops");
  machine.stopCount = stops.number("count");
  for (const Reader& stop : stops.list("last", mostEntries)) {
    machine.stops.push_back({stop.number("time"), stop.words("worker", 3 * nameLimit), stop.words("what", nameLimit)});
  }

  const Reader cpus = reader.object("cpus");
  machine.cpuCount = cpus.number("count");
  machine.timingCores = cpus.words("timing", nameLimit);
  machine.timingReserved = cpus.flag("timingReserved");

  const Reader queue = reader.object("queue");
  machine.slots = readTaken(queue, "slots");
  machine.parallel = readTaken(queue, "parallel");
  machine.timing = readTaken(queue, "timing");
  machine.exclusive = queue.flag("exclusive");
  machine.waiting = queue.number("waiting");

  const Reader disk = reader.object("disk");
  machine.diskWorkers = readAmount(disk, "workers");
  machine.diskScratch = readAmount(disk, "scratch");
  return machine;
}

Worker readWorker(const Reader& reader) {
  Worker worker;

  // Step 1. Who it is and what it uses
  worker.project = reader.name("project");
  worker.branch = reader.name("branch");
  worker.name = reader.name("name");
  worker.role = reader.name("role");
  const Reader state = reader.object("state", true);
  worker.state = state.name("value");
  worker.stateSource = state.source(Source::Derived);

  const Reader running = reader.object("running");
  worker.running = running.flag("value");
  worker.runningSince = running.number("since");
  worker.lastRun = reader.number("lastRun");

  worker.memory = readAmount(reader, "memory");
  worker.folder = readAmount(reader, "folder");
  worker.scratch = readAmount(reader, "scratch");
  const Reader cpu = reader.object("cpu");
  worker.cpuShare = cpu.number("share");
  worker.cpuSeconds = cpu.number("seconds");
  worker.gpuMemory = reader.object("gpuMemory").number("used");
  worker.memoryStops = reader.object("memoryStops").number("count");

  for (const Reader& entry : reader.list("jobs", mostEntries)) {
    Job job;
    job.mode = entry.words("mode", nameLimit);
    job.state = entry.words("state", nameLimit);
    job.command = entry.words("command");
    job.since = entry.number("since");
    const Reader memory = entry.object("memory");
    job.memoryUsed = memory.number("used");
    job.memoryPeak = memory.number("peak");
    job.cpuShare = entry.object("cpu").number("share");
    worker.jobs.push_back(std::move(job));
  }

  // Step 2. What it says about its progress
  const Reader steps = reader.object("steps");
  worker.steps.done = steps.number("done");
  worker.steps.total = steps.number("total");
  worker.steps.changed = steps.number("changed");
  worker.steps.current = steps.words("current");
  worker.steps.source = steps.source(Source::Claimed);
  for (const Reader& item : steps.list("items", mostItems)) {
    worker.steps.items.push_back({item.words("text"), item.words("state", nameLimit)});
  }

  const Reader claim = reader.object("claim");
  worker.claim = claim.words("value");
  worker.claimSource = claim.source(Source::Claimed);

  // Step 3. What the tools recorded about it
  const Reader intent = reader.object("intent");
  worker.intent.approved = intent.flag("approved");
  worker.intent.changedSinceApproval = intent.flag("changedSinceApproval");
  worker.intent.approach = intent.number("approach");
  worker.intent.approvedAt = intent.number("approvedAt");
  worker.intent.source = intent.source(Source::Recorded);

  worker.lastQueuedRun = readRun(reader.object("lastQueuedRun"));
  for (const Reader& entry : reader.list("runs", mostEntries)) {
    worker.runs.push_back(readRun(entry));
  }

  const Reader acceptance = reader.object("acceptance");
  worker.acceptance.value = acceptance.words("value", nameLimit);
  worker.acceptance.onCurrentCommit = acceptance.flag("onCurrentCommit");
  worker.acceptance.time = acceptance.number("time");
  worker.acceptance.source = acceptance.source(Source::Recorded);

  const Reader commits = reader.object("commits");
  worker.commits.ahead = commits.number("ahead");
  worker.commits.behind = commits.number("behind");
  worker.commits.pending = commits.flag("pending");
  const Reader uncommitted = commits.object("uncommitted");
  worker.commits.uncommitted = uncommitted.flag("value");
  worker.commits.uncommittedSource = uncommitted.source(Source::SelfReported);
  worker.commits.source = commits.source(Source::Derived);

  const Reader reviews = reader.object("reviews");
  worker.reviews.count = reviews.number("count");
  worker.reviews.outdated = reviews.number("outdated");
  worker.reviews.source = reviews.source(Source::Derived);
  for (const Reader& entry : reviews.list("verdicts", mostEntries)) {
    worker.reviews.verdicts.push_back(
        {entry.words("by", nameLimit), entry.words("value"), entry.source(Source::Claimed)});
  }

  const Reader places = reader.object("places");
  worker.places.copy = places.words("copy");
  worker.places.reports = places.words("reports");
  worker.places.records = places.words("records");
  worker.places.task = places.words("task");
  worker.places.scratch = places.words("scratch");

  const Reader nextStep = reader.object("nextStep");
  worker.nextStep.command = nextStep.words("command");
  worker.nextStep.source = nextStep.source(Source::Derived);

  const Reader review = reader.object("review");
  worker.reviewRelation.implementers = review.wordsList("implementers", mostEntries);
  worker.reviewRelation.removableWithMerged = review.flag("removableWithMerged");
  worker.reviewRelation.source = review.source(Source::Derived);

  const Reader removal = reader.object("removal");
  worker.removal.value = removal.words("value");
  worker.removal.source = removal.source(Source::Derived);

  const Reader removable = reader.object("removable");
  worker.removable = removable.flag("value");
  worker.removableSource = removable.source(Source::Derived);
  return worker;
}

Parsed readDocument(std::string_view bytes, bool validation) {
  Parsed parsed;

  // Step 1. Parse with the library, leaving out what is nested too deep
  const bool blank = std::all_of(bytes.begin(), bytes.end(), [](char byte) {
    return (byte == ' ') || (byte == '\t') || (byte == '\n') || (byte == '\r');
  });
  if (blank) {
    parsed.reason = "the document is empty";
    return parsed;
  }
  bool tooDeep = false;
  const auto withinDepth = [&tooDeep](int depth, Json::parse_event_t, Json&) {
    if (depth > deepestLevel) {
      tooDeep = true;
      return false;
    }
    return true;
  };
  Json root;
  try {
    root = Json::parse(bytes.begin(), bytes.end(), withinDepth);
  } catch (const Json::exception& error) {
    // The library's message starts with its own error number in brackets, and may quote bytes of the document
    const std::string_view message = error.what();
    const std::size_t numberEnd = message.find("] ");
    parsed.reason = "the document is not valid JSON: " +
                    cleanText(message.substr((numberEnd == std::string_view::npos) ? 0 : (numberEnd + 2)));
    return parsed;
  }

  // Step 2. The top level
  if (!root.is_object()) {
    parsed.reason = "the document is " + article(root) + ", expected an object";
    return parsed;
  }
  parsed.readable = true;
  Document& document = parsed.document;
  const Reader top(&root, "", document, validation);
  if (tooDeep) {
    top.problem("document", "has values nested deeper than " + std::to_string(deepestLevel) +
                                " levels, which are left out");
  }
  const Number version = top.number("version", false, true);
  if (version && (*version != schemaVersion)) {
    const bool whole = (std::floor(*version) == *version);
    top.problem("version", "is " + (whole ? formatCount(*version) : formatShare(*version)) +
                               ", this program reads version " +
                               formatCount(schemaVersion) + "; what follows may be wrong");
  }
  document.generated = top.number("generated");

  // Step 3. The machine and the workers
  document.machine = readMachine(top.object("machine", true));
  const std::vector<Reader> workers = top.list("workers", mostWorkers, true);
  document.workers.reserve(workers.size());
  for (const Reader& worker : workers) {
    document.workers.push_back(readWorker(worker));
  }

  // Validation compares the complete original names, not the shortened names that the screen keeps
  if (validation) {
    const auto member = root.find("workers");
    if ((member != root.end()) && member->is_array()) {
      std::set<std::tuple<std::string, std::string, std::string>> identities;
      for (std::size_t index = 0; index < member->size(); ++index) {
        const Json& worker = (*member)[index];
        if (!worker.is_object()) {
          continue;
        }
        const auto project = worker.find("project");
        const auto branch = worker.find("branch");
        const auto name = worker.find("name");
        if ((project == worker.end()) || !project->is_string() || (branch == worker.end()) || !branch->is_string() ||
            (name == worker.end()) || !name->is_string()) {
          continue;
        }
        const auto identity = std::make_tuple(project->get<std::string>(), branch->get<std::string>(),
                                              name->get<std::string>());
        if (!identities.insert(identity).second) {
          noteProblem(document, "workers[" + std::to_string(index) + "]",
                      "has the same project, branch and name as an earlier worker", true);
        }
      }
    }
  }
  return parsed;
}

}  // namespace

std::string sourceName(Source source) {
  switch (source) {
    case Source::Measured:
      return "measured";
    case Source::Recorded:
      return "recorded";
    case Source::Derived:
      return "derived";
    case Source::SelfReported:
      return "self-reported";
    case Source::Claimed:
      return "claimed";
  }
  return "claimed";
}

namespace {

Parsed readSafely(std::string_view bytes, bool validation) {
  try {
    return readDocument(bytes, validation);
  } catch (const std::exception& error) {
    // Out of memory, or a fault of the library: say so instead of ending
    Parsed parsed;
    parsed.reason = "the document could not be read: " + cleanText(error.what());
    return parsed;
  }
}

}  // namespace

Parsed parseDocument(std::string_view bytes) {
  return readSafely(bytes, false);
}

Parsed validateDocument(std::string_view bytes) {
  return readSafely(bytes, true);
}

}  // namespace watch
