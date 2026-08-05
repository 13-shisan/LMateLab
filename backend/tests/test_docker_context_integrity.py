import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DOCKERIGNORE = BACKEND_ROOT / ".dockerignore"


def dockerignore_patterns():
    if not DOCKERIGNORE.is_file():
        return set()

    return {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


class DockerContextIntegrityTests(unittest.TestCase):
    def test_backend_image_excludes_environment_secrets(self):
        patterns = dockerignore_patterns()

        self.assertIn(".env", patterns)
        self.assertIn(".env.*", patterns)

    def test_backend_image_excludes_runtime_data(self):
        patterns = dockerignore_patterns()

        for expected in (
            "__pycache__/",
            "*.py[cod]",
            "*.db",
            "uploads/",
            "Customized_database/",
            "data/",
        ):
            self.assertIn(expected, patterns)


if __name__ == "__main__":
    unittest.main()
