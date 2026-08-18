from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import fcntl
except ImportError:
    fcntl = None

from services.competition_slurm import (
    _open_hashed_script,
    _snapshot_script_descriptor,
)


_HAS_LINUX_MEMFD_SEALING = (
    sys.platform.startswith("linux")
    and hasattr(os, "memfd_create")
    and fcntl is not None
    and hasattr(fcntl, "F_ADD_SEALS")
)


@unittest.skipUnless(_HAS_LINUX_MEMFD_SEALING, "Linux memfd sealing is required")
class LinuxSubmissionSnapshotProcessTests(unittest.TestCase):
    def test_child_process_consumes_sealed_snapshot_through_proc_fd(self):
        payload = b"#!/bin/bash\necho sealed-child-regression\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "runner.slurm"
            script_path.write_bytes(payload)
            source, source_digest = _open_hashed_script(script_path)
            try:
                snapshot, snapshot_digest = _snapshot_script_descriptor(source)
            finally:
                os.close(source)

        required_seals = (
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_SEAL
        )
        child_code = r"""
import fcntl
import json
import os
import sys

descriptor = int(sys.argv[1])
path = f"/proc/self/fd/{descriptor}"
with open(path, "rb", buffering=0) as handle:
    consumed = handle.read()
blocked = []
for name, operation in (
    ("write", lambda: os.write(descriptor, b"changed")),
    ("truncate", lambda: os.ftruncate(descriptor, 0)),
):
    try:
        operation()
    except OSError as exc:
        blocked.append([name, exc.errno])
print(json.dumps({
    "applied_seals": fcntl.fcntl(descriptor, fcntl.F_GET_SEALS),
    "blocked": blocked,
    "payload_hex": consumed.hex(),
}, sort_keys=True))
if len(blocked) != 2:
    raise SystemExit(12)
"""
        try:
            completed = subprocess.run(
                [sys.executable, "-c", child_code, str(snapshot)],
                pass_fds=(snapshot,),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        finally:
            os.close(snapshot)

        self.assertEqual(0, completed.returncode, completed.stderr)
        child_evidence = json.loads(completed.stdout)
        self.assertEqual(payload, bytes.fromhex(child_evidence["payload_hex"]))
        self.assertEqual(
            required_seals,
            child_evidence["applied_seals"] & required_seals,
        )
        self.assertEqual(
            [["write", errno.EPERM], ["truncate", errno.EPERM]],
            child_evidence["blocked"],
        )
        expected_digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(expected_digest, source_digest)
        self.assertEqual(expected_digest, snapshot_digest)


if __name__ == "__main__":
    unittest.main()
