#!/bin/sh
# Stands in for `workers status --json` in the tests: prints the document given as its argument,
# fails with a complaint that carries an escape sequence, or takes 12 s, when the test asks for it
if [ -n "$WORKERS_WATCH_TEST_FAIL" ]; then
  printf 'the stand-in was told to fail \033[2J\nits second line is not shown\n' >&2
  exit 3
fi
if [ -n "$WORKERS_WATCH_TEST_SLOW" ]; then
  sleep 12
fi
exec cat "$1"
