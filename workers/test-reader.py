import json
import os
import pathlib
import sys
import tempfile
import unittest
from typing import Annotated

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from broker import Broker, Refused


class ReaderTest(unittest.TestCase):
    def setUp(self):
        ## Step 1. Build two project trees and one trusted alpha manager identity
        self._temporary_ = tempfile.TemporaryDirectory()
        self._home_ = pathlib.Path(self._temporary_.name)
        self._workers_ = self._home_ / "workers" / "alpha"
        self._roles_ = self._home_ / "state" / "alpha" / "roles"
        self._scratch_ = self._home_ / "scratch" / "workers" / "alpha"
        self._worker_ = self._workers_ / "b1" / "i1"
        for _path_ in [
            self._worker_ / "reports",
            self._worker_ / "records",
            self._worker_ / "repo",
            self._worker_ / "sessions",
            self._roles_ / "b1",
            self._scratch_ / "b1" / "i1",
            self._scratch_ / "manager" / "manager",
        ]:
            _path_.mkdir(parents=True, exist_ok=True)
        (self._roles_ / "b1" / "i1").write_text("implementer\n")
        (self._worker_ / "reports" / "report").write_bytes(b"legacy-report\n")
        (self._worker_ / "repo" / "uncommitted").write_bytes(b"working-copy\n")
        (self._worker_ / "sessions" / "session.jsonl").write_bytes(b"session\n")
        (self._scratch_ / "b1" / "i1" / "run.log").write_bytes(b"scratch\n")

        ## Step 2. Construct only the broker state used by the closed reader
        self._broker_ = Broker.__new__(Broker)
        self._broker_.identity = {"project": "alpha", "branch": "manager", "name": "manager", "role": "manager"}
        self._broker_.workersRoot = str(self._workers_)
        self._broker_.rolesRoot = str(self._roles_)
        self._broker_.scratch = str(self._scratch_ / "manager" / "manager")
        self._broker_.config = {"maxReadBytes": 64}

    def tearDown(self):
        self._temporary_.cleanup()

    def _read(
        self,
        command: Annotated[list[str], "The closed worker-read command"],
    ):
        _request_ = {
            "mode": "worker-read",
            "command": command,
            "folder": "/",
            "environment": {},
        }
        with tempfile.TemporaryFile() as _output_:
            _result_ = self._broker_._workerRead(_request_, _output_.fileno())
            _output_.seek(0)
            return _result_, _output_.read()

    def testLegacyAndManagedRoots(self):
        ## Step 1. Preserve the legacy report bytes
        _result_, _data_ = self._read(["b1", "i1", "reports", "report", "0", "read"])
        self.assertEqual(_data_, b"legacy-report\n")
        self.assertEqual(_result_["bytes"], len(_data_))

        ## Step 2. Reach every managed file root through the trusted alpha paths
        for _root_, _path_, _expected_ in [
            ("repo", "uncommitted", b"working-copy\n"),
            ("sessions", "session.jsonl", b"session\n"),
            ("scratch", "run.log", b"scratch\n"),
        ]:
            _, _data_ = self._read(["b1", "i1", _root_, _path_, "0", "read"])
            self.assertEqual(_data_, _expected_)
        _, _data_ = self._read(["b1", "i1", "folder", "", "0", "read"])
        self.assertEqual(set(json.loads(_line_) for _line_ in _data_.splitlines()), {"records", "repo", "reports", "sessions"})

    def testDynamicWorkerList(self):
        _, _data_ = self._read(["workers"])
        self.assertEqual(_data_, b'"b1/i1"\n')
        (self._roles_ / "b2").mkdir()
        (self._roles_ / "b2" / "later").write_text("reviewer\n")
        _, _data_ = self._read(["workers"])
        self.assertEqual(_data_, b'"b1/i1"\n"b2/later"\n')

    def testCheckedGitBindSurvivesExchange(self):
        ## Step 1. Prepare a link target outside the trusted project and stand-ins for systemd-run and bwrap
        _repo_ = self._worker_ / "repo"
        _original_ = self._worker_ / "repo-original"
        _target_ = self._home_ / "workers" / "beta" / "b1" / "foreign" / "repo"
        _target_.mkdir(parents=True)
        (_repo_ / "marker").write_text("CHECKED\n")
        (_target_ / "marker").write_text("LINK-TARGET\n")
        _runner_ = self._home_ / "systemd-run"
        _runner_.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "_arguments_ = sys.argv[1:]\n"
            "_command_ = _arguments_[_arguments_.index('--') + 1:]\n"
            "os.execv(_command_[0], _command_)\n"
        )
        _bwrap_ = self._home_ / "bwrap"
        _bwrap_.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            f"_repo_ = pathlib.Path({str(_repo_)!r})\n"
            f"_original_ = pathlib.Path({str(_original_)!r})\n"
            f"_target_ = pathlib.Path({str(_target_)!r})\n"
            "_repo_.rename(_original_)\n"
            "_repo_.symlink_to(_target_, target_is_directory=True)\n"
            "_arguments_ = sys.argv[1:]\n"
            "if ('--ro-bind-fd' in _arguments_):\n"
            "    _index_ = _arguments_.index('--ro-bind-fd')\n"
            "    _source_ = pathlib.Path('/proc/self/fd') / _arguments_[_index_ + 1]\n"
            "else:\n"
            "    _sources_ = [_arguments_[_index_ + 1] for _index_ in range(len(_arguments_) - 2) if (_arguments_[_index_] == '--ro-bind') and (_arguments_[_index_ + 2] == str(_repo_))]\n"
            "    _source_ = pathlib.Path(_sources_[0])\n"
            "sys.stdout.write((_source_ / 'marker').read_text())\n"
        )
        _runner_.chmod(0o755)
        _bwrap_.chmod(0o755)
        self._broker_.config.update(
            {
                "bwrap": str(_bwrap_),
                "git": "/unused/git",
                "openChecked": [sys.executable, "-I", str(pathlib.Path(__file__).parent / "open-checked.py")],
                "requestSeconds": 2,
                "systemctl": "/unused/systemctl",
                "systemdRun": str(_runner_),
            }
        )

        ## Step 2. Exchange the path after the broker check and require the already-opened repository
        try:
            _, _data_ = self._read(["b1", "i1", "refs", "", "0", "read"])
            self.assertEqual(_data_, b"CHECKED\n")
        finally:
            if _repo_.is_symlink():
                _repo_.unlink()
            if _original_.exists():
                _original_.rename(_repo_)

    def testRefusals(self):
        ## Step 1. Authority comes from the launcher's identity
        self._broker_.identity = {"project": "alpha", "branch": "b1", "name": "reviewer", "role": "reviewer"}
        with self.assertRaisesRegex(Refused, "only a manager"):
            self._read(["b1", "i1", "reports", "report", "0", "read"])
        self._broker_.identity = {"project": "alpha", "branch": "manager", "name": "manager", "role": "manager"}

        ## Step 2. No request can select another project or a write mode
        _betaRole_ = self._home_ / "state" / "beta" / "roles" / "b1"
        _betaRole_.mkdir(parents=True)
        (_betaRole_ / "foreign").write_text("implementer\n")
        with self.assertRaisesRegex(Refused, "no worker alpha"):
            self._read(["b1", "foreign", "reports", "report", "0", "read"])
        with self.assertRaisesRegex(Refused, "never write"):
            self._read(["b1", "i1", "repo", "uncommitted", "0", "write"])

        ## Step 3. Traversal, links, special files and oversized listings disclose no data
        (self._worker_ / "repo" / "link").symlink_to(self._home_ / "secret")
        os.mkfifo(self._worker_ / "repo" / "pipe")
        for _command_, _reason_ in [
            (["b1", "i1", "repo", "../reports/report", "0", "read"], "path stays below repo"),
            (["b1", "i1", "repo", "link", "0", "read"], "without a link"),
            (["b1", "i1", "repo", "pipe", "0", "read"], "not a regular file or directory"),
        ]:
            with self.assertRaisesRegex(Refused, _reason_):
                self._read(_command_)
        for _index_ in range(20):
            (self._worker_ / "repo" / f"long-entry-{_index_:02d}").touch()
        with self.assertRaisesRegex(Refused, "listing is larger"):
            self._read(["b1", "i1", "repo", "", "0", "read"])


if (__name__ == "__main__"):
    unittest.main()
