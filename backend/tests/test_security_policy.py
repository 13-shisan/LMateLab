import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from schemas import load_policy


class SecurityPolicyTests(unittest.TestCase):
    def test_load_policy_uses_configured_runtime_path(self):
        expected = {"password": {"minLength": 12}}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "security_policy.json"
            policy_path.write_text(
                json.dumps(expected),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"SECURITY_POLICY_PATH": str(policy_path)},
            ):
                self.assertEqual(expected, load_policy())


if __name__ == "__main__":
    unittest.main()
