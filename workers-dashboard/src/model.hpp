#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace watch {

// Where a value comes from; the last two are shown apart from the others
enum class Source { Measured, Recorded, Derived, SelfReported, Claimed };

// Every value may be missing: "not known"
using Number = std::optional<double>;
using Flag = std::optional<bool>;
// Text is cleaned and cut when it is read, so that no other code sees a document's raw string
using Words = std::optional<std::string>;

struct Amount {
  Number used;
  Number limit;
  Number peak;
};

struct Taken {
  Number taken;
  Number total;
};

struct MemoryStop {
  Number time;
  Words worker;
  Words what;
};

struct Machine {
  Amount memory;
  Amount agentsMemory;
  Number agentsCpuShare;
  Number agentsCpuLimit;
  Number stopCount;
  std::vector<MemoryStop> stops;
  Number cpuCount;
  Words timingCores;
  Flag timingReserved;
  Taken slots;
  Taken parallel;
  Taken timing;
  Flag exclusive;
  Number waiting;
  Amount diskWorkers;
  Amount diskScratch;
};

struct Job {
  Words mode;
  Words state;
  Words command;
  Number since;
  Number memoryUsed;
  Number memoryPeak;
  Number cpuShare;
};

struct StepItem {
  Words text;
  Words state;
};

struct Steps {
  Number done;
  Number total;
  Number changed;
  Words current;
  Source source = Source::Claimed;
  std::vector<StepItem> items;
};

struct Intent {
  Flag approved;
  Flag changedSinceApproval;
  Number approach;
  Number approvedAt;
  Source source = Source::Recorded;
};

struct Run {
  Words mode;
  Words command;
  Number time;
  Number exit;
  Number duration;
  Flag onCurrentCommit;
  Source source = Source::Recorded;
  bool known = false;
};

struct Acceptance {
  Words value;
  Flag onCurrentCommit;
  Number time;
  Source source = Source::Recorded;
};

struct Commits {
  Number ahead;
  Number behind;
  Flag pending;
  Flag uncommitted;
  Source uncommittedSource = Source::SelfReported;
  Source source = Source::Derived;
};

struct Verdict {
  Words by;
  Words value;
  Source source = Source::Claimed;
};

struct Reviews {
  Number count;
  Number outdated;
  std::vector<Verdict> verdicts;
  Source source = Source::Derived;
};

struct Places {
  Words copy;
  Words reports;
  Words records;
  Words task;
  Words scratch;
};

struct NextStep {
  Words command;
  Source source = Source::Derived;
};

struct ReviewRelation {
  std::vector<std::string> implementers;
  Flag removableWithMerged;
  Source source = Source::Derived;
};

struct Removal {
  Words value;
  Source source = Source::Derived;
};

struct Worker {
  std::string project = "–";
  std::string branch = "–";
  std::string name = "–";
  std::string role = "–";
  std::string state = "–";
  Source stateSource = Source::Derived;
  Flag running;
  Number runningSince;
  Number lastRun;
  Amount memory;
  Amount folder;
  Amount scratch;
  Number cpuShare;
  Number cpuSeconds;
  Number gpuMemory;
  // How often the agent or one of its jobs was stopped for memory
  Number memoryStops;
  std::vector<Job> jobs;
  Steps steps;
  Intent intent;
  Run lastQueuedRun;
  std::vector<Run> runs;
  Acceptance acceptance;
  Commits commits;
  Reviews reviews;
  Places places;
  NextStep nextStep;
  ReviewRelation reviewRelation;
  Removal removal;
  Words claim;
  Source claimSource = Source::Claimed;
  Flag removable;
  Source removableSource = Source::Derived;
};

struct Document {
  Number generated;
  Machine machine;
  std::vector<Worker> workers;
  // What is wrong with the document, each naming its field; only the first few are kept, all are counted
  std::vector<std::string> problems;
  std::size_t problemCount = 0;
};

struct Parsed {
  // False when nothing could be read; the reason then says why
  bool readable = false;
  std::string reason;
  Document document;
};

// The version of SCHEMA.md this program reads
inline constexpr double schemaVersion = 1;

// Never throws and never ends the program, whatever the bytes are
Parsed parseDocument(std::string_view bytes);

// The same reader, retaining every problem and applying the schema's checks that a tolerant live view need not use
Parsed validateDocument(std::string_view bytes);

std::string sourceName(Source source);

}  // namespace watch
