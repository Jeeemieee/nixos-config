#!/usr/bin/env python3
"""Measures what the live workers-watch costs: processor time, wake-ups, bytes written, memory, and one frame.

  measure.py --binary BIN idle     [--workers 12] [--seconds 300]   the document does not change
  measure.py --binary BIN changing [--workers 12] [--seconds 60]    one value changes, then every row changes
  measure.py --binary BIN memory   [--workers 300] [--seconds 600]  the document changes at every refresh
  measure.py --binary BIN frame                                     one `--once` frame, as T6, and its parts

It reports; it judges nothing. The interval is 2 s, the window 160 by 50.
"""

import argparse
import json
import os
import re
import select
import statistics
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402  (the pseudo-terminal and the generator of the tests)

INTERVAL = 2


def threads(pid):
    """Processor time in ms and voluntary switches of every thread, which are its wake-ups."""
    result = {}
    for thread in os.listdir(f"/proc/{pid}/task"):
        base = f"/proc/{pid}/task/{thread}/"
        try:
            ran = int(open(base + "schedstat").read().split()[0]) / 1e6
            woke = int(re.search(r"voluntary_ctxt_switches:\s+(\d+)", open(base + "status").read()).group(1))
        except (OSError, AttributeError):
            continue
        result[thread] = (ran, woke)
    return result


def resident(pid):
    return int(re.search(r"VmRSS:\s+(\d+)", open(f"/proc/{pid}/status").read()).group(1)) / 1024


def write(path, document):
    """As SCHEMA.md asks of a producer: a new file, renamed into place."""
    with open(path + ".new", "w") as file:
        json.dump(document, file)
    os.replace(path + ".new", path)


def watch(terminal, seconds, everyInterval=None):
    """Reads what the program writes for some seconds; returns the bytes of every refresh, by the pauses between."""
    bursts = []
    last = None
    begin = time.monotonic()
    nextCall = begin + INTERVAL
    while True:
        now = time.monotonic()
        if now - begin >= seconds:
            return bursts
        if everyInterval and now >= nextCall:
            everyInterval()
            nextCall += INTERVAL
        ready, _, _ = select.select([terminal.controller], [], [], min(0.25, begin + seconds - now))
        if ready:
            data = os.read(terminal.controller, 65536)
            moment = time.monotonic()
            if last is None or moment - last > 0.5:
                bursts.append(0)
            bursts[-1] += len(data)
            last = moment


def start(binary, path):
    terminal = run.Terminal([binary, "--file", path, "--interval", str(INTERVAL)], 160, 50)
    terminal.read(3.0)
    return terminal


def cost(terminal, seconds, everyInterval=None):
    """One measured stretch: what every thread did, and what was written."""
    before = threads(terminal.process.pid)
    begin = time.monotonic()
    bursts = watch(terminal, seconds, everyInterval)
    elapsed = time.monotonic() - begin
    after = threads(terminal.process.pid)
    perThread = sorted(
        ((after[t][0] - before.get(t, (0, 0))[0], after[t][1] - before.get(t, (0, 0))[1]) for t in after),
        key=lambda pair: pair[1],
    )
    ran = sum(pair[0] for pair in perThread)
    woke = sum(pair[1] for pair in perThread)
    print(f"  measured for {elapsed:.0f} s")
    print(f"  processor time     {ran:.0f} ms, {ran / elapsed / 10:.3f} % of one processor")
    print(f"  wake-ups           {woke * 60 / elapsed:.0f} per minute")
    for milliseconds, switches in perThread:
        print(f"    one thread       {milliseconds:7.1f} ms  {switches * 60 / elapsed:7.0f} wake-ups per minute")
    print(f"  refreshes written  {len(bursts)}, {sum(bursts)} bytes in all" +
          (f", {statistics.median(bursts):.0f} bytes each (median), {max(bursts)} at most" if bursts else ""))
    print(f"  resident memory    {resident(terminal.process.pid):.1f} MiB")


def idle(binary, workers, seconds, scratch):
    generate = run.generator()
    path = os.path.join(scratch, "status.json")
    write(path, generate.document(generate.newWorld(3, workers, int(time.time()))))
    terminal = start(binary, path)
    print(f"idle: {workers} workers, the document does not change")
    cost(terminal, seconds)
    print(f"  exit status        {terminal.close()}")


def changing(binary, workers, seconds, scratch):
    generate = run.generator()
    world = generate.newWorld(3, workers, int(time.time()))
    path = os.path.join(scratch, "status.json")
    document = generate.document(world)
    write(path, document)
    terminal = start(binary, path)

    def oneValue():
        document["machine"]["queue"]["waiting"] = (document["machine"]["queue"]["waiting"] + 1) % 9
        write(path, document)

    def everyRow():
        generate.advance(world, INTERVAL)
        write(path, generate.document(world))

    print(f"changing: {workers} workers, one value of the header changes at every refresh")
    cost(terminal, seconds, oneValue)
    print(f"changing: {workers} workers, the whole document moves on at every refresh")
    cost(terminal, seconds, everyRow)
    print(f"  exit status        {terminal.close()}")


def memory(binary, workers, seconds, scratch):
    generate = run.generator()
    world = generate.newWorld(3, workers, int(time.time()))
    path = os.path.join(scratch, "status.json")
    write(path, generate.document(world))
    terminal = start(binary, path)

    def moveOn():
        generate.advance(world, INTERVAL)
        write(path, generate.document(world))

    print(f"memory: {workers} workers, the whole document moves on every {INTERVAL} s; resident memory in MiB")
    samples = []
    for step in range(seconds // 10):
        watch(terminal, 10, moveOn)
        samples.append(resident(terminal.process.pid))
        if (step + 1) % 6 == 0:
            print(f"  after {(step + 1) // 6:2d} min  {samples[-1]:.1f}", flush=True)
    if len(samples) > 12:
        print(f"  growth from minute 2 to the end: {samples[-1] - samples[11]:+.2f} MiB; highest {max(samples):.1f} MiB")
    print(f"  exit status        {terminal.close()}")


def frame(binary, scratch):
    generate = run.generator()
    large = generate.document(generate.newWorld(3, 300, 1794650000))
    paths = {}
    for name, document in (("300 workers", large), ("no workers", dict(large, workers=[]))):
        paths[name] = os.path.join(scratch, name.replace(" ", "-") + ".json")
        write(paths[name], document)

    def median(command):
        times = []
        for _ in range(30):
            begin = time.perf_counter()
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True)
            times.append((time.perf_counter() - begin) * 1000)
        return statistics.median(times)

    whole = median([binary, "--once", "--file", paths["300 workers"], "--width", "160", "--height", "50"])
    empty = median([binary, "--once", "--file", paths["no workers"], "--width", "160", "--height", "50"])
    begin = median([binary, "--help"])
    print(f"frame: one whole `--once` process, median of 30, the document has {os.path.getsize(paths['300 workers'])} bytes")
    print(f"  300 workers        {whole:.1f} ms")
    print(f"  of which: starting the process {begin:.1f} ms (a run of --help)")
    print(f"            drawing and printing {empty - begin:.1f} ms (the same document without its workers, less the start)")
    print(f"            reading 300 workers  {whole - empty:.1f} ms (the rest: parsing, and the rows in sight)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--binary", required=True)
    parser.add_argument("what", choices=["idle", "changing", "memory", "frame"])
    parser.add_argument("--workers", type=int)
    parser.add_argument("--seconds", type=int)
    arguments = parser.parse_args()
    binary = os.path.abspath(arguments.binary)
    print(f"# {binary}")
    with tempfile.TemporaryDirectory() as scratch:
        if arguments.what == "idle":
            idle(binary, arguments.workers or 12, arguments.seconds or 300, scratch)
        elif arguments.what == "changing":
            changing(binary, arguments.workers or 12, arguments.seconds or 60, scratch)
        elif arguments.what == "memory":
            memory(binary, arguments.workers or 300, arguments.seconds or 600, scratch)
        else:
            frame(binary, scratch)


if __name__ == "__main__":
    main()
