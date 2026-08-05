import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from routers import server_monitor


class ServerMonitorHistoryTests(unittest.TestCase):
    def setUp(self):
        self.original_base_dir = server_monitor.SERVER_MONITOR_BASE_DIR

    def tearDown(self):
        server_monitor.SERVER_MONITOR_BASE_DIR = self.original_base_dir

    @staticmethod
    def write_snapshot(history_dir: Path, day: str, name: str, updated_at: str):
        target = history_dir / day / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"updated_at": updated_at, "scheduler": {"jobs": []}}),
            encoding="utf-8",
        )
        return target

    def test_history_scan_prunes_old_date_directories_before_reading_json(self):
        now = datetime.now(timezone.utc).astimezone()
        today = now.date().isoformat()

        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            history_dir = base_dir / "Dell" / "history"
            expected = self.write_snapshot(
                history_dir,
                today,
                "12-00-00.json",
                now.isoformat(),
            )
            self.write_snapshot(
                history_dir,
                "2000-01-01",
                "12-00-00.json",
                now.isoformat(),
            )
            server_monitor.SERVER_MONITOR_BASE_DIR = base_dir

            snapshots = server_monitor.iter_history_files_in_range("Dell", 7)

            self.assertEqual([expected], [item[1] for item in snapshots])

    def test_stale_users_overview_cache_is_returned_while_refresh_is_scheduled(self):
        self.assertTrue(
            hasattr(server_monitor, "get_users_overview_response"),
            "get_users_overview_response is missing",
        )

        payload = {"range": "30d", "realtime": {}, "history": {}}
        scheduled = []
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            cache_path = server_monitor.get_users_overview_cache_path(30, cache_dir)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            os.utime(cache_path, (time.time() - 86400, time.time() - 86400))

            result = server_monitor.get_users_overview_response(
                30,
                lambda function, *args: scheduled.append((function, args)),
                cache_dir=cache_dir,
                builder=lambda _days: self.fail("stale cache must be returned"),
            )

        self.assertEqual(payload, result)
        self.assertEqual(1, len(scheduled))
        self.assertIs(
            server_monitor.refresh_users_overview_cache,
            scheduled[0][0],
        )

    def test_cache_refresh_builds_and_persists_missing_range(self):
        self.assertTrue(
            hasattr(server_monitor, "refresh_users_overview_cache"),
            "refresh_users_overview_cache is missing",
        )

        payload = {"range": "7d", "realtime": {"users": []}, "history": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = server_monitor.refresh_users_overview_cache(
                7,
                cache_dir=cache_dir,
                builder=lambda _days: payload,
            )
            cache_path = server_monitor.get_users_overview_cache_path(7, cache_dir)

            self.assertEqual(payload, result)
            self.assertEqual(payload, json.loads(cache_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
