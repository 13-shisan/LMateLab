import json
import os
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.prod.yml"
CANONICAL_ROOT = Path(
    os.getenv("LMATELAB_PROJECT_DIR", "/home/software/LMateLab")
).resolve()


def rendered_compose():
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class ComposeIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rendered_compose()

    def db_directory_source(self, service_name):
        volumes = self.config["services"][service_name].get("volumes", [])
        matches = [
            volume
            for volume in volumes
            if volume.get("target") == "/app/var/db"
        ]
        self.assertEqual(1, len(matches), service_name)
        self.assertEqual("bind", matches[0].get("type"), service_name)
        return Path(matches[0]["source"]).resolve()

    def test_database_directory_mount_is_shared(self):
        sources = {
            service: self.db_directory_source(service)
            for service in ("backend", "worker", "beat")
        }

        self.assertEqual(sources["backend"], sources["worker"])
        self.assertEqual(sources["backend"], sources["beat"])
        self.assertEqual(Path("var/db"), Path(*sources["backend"].parts[-2:]))

        if PROJECT_ROOT.resolve() == CANONICAL_ROOT:
            self.assertEqual(CANONICAL_ROOT / "var/db", sources["backend"])
            self.assertTrue(sources["backend"].is_dir())

    def test_backend_specific_var_mounts_are_not_shadowed_by_parent_mount(self):
        targets = {
            volume.get("target")
            for volume in self.config["services"]["backend"].get("volumes", [])
        }

        self.assertNotIn("/app/var", targets)
        for expected in (
            "/app/var/artifacts",
            "/app/var/config",
            "/app/var/data",
            "/app/var/db",
            "/app/var/issues",
            "/app/var/tmp",
        ):
            self.assertIn(expected, targets)

    def test_backend_healthcheck_uses_script_baked_into_image(self):
        healthcheck = self.config["services"]["backend"].get("healthcheck")

        self.assertIsNotNone(healthcheck)
        command = " ".join(healthcheck["test"])
        self.assertIn("/app/healthcheck.py", command)

        script_mounts = [
            volume
            for volume in self.config["services"]["backend"].get("volumes", [])
            if volume.get("target") == "/app/healthcheck.py"
        ]
        self.assertEqual([], script_mounts)

    def test_worker_mounts_complete_data_directory_read_only(self):
        data_mounts = [
            volume
            for volume in self.config["services"]["worker"].get("volumes", [])
            if volume.get("target") in (
                "/app/var/data",
                "/app/var/data/allowed_users.json",
            )
        ]

        self.assertEqual(1, len(data_mounts))
        self.assertEqual("/app/var/data", data_mounts[0].get("target"))
        self.assertEqual("bind", data_mounts[0].get("type"))
        self.assertTrue(data_mounts[0].get("read_only"))
        self.assertEqual(
            Path("var/data"),
            Path(*Path(data_mounts[0]["source"]).parts[-2:]),
        )


if __name__ == "__main__":
    unittest.main()
