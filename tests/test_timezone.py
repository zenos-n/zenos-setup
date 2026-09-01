import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.views.timezone.runtime import apply_runtime_timezone


class RuntimeTimezoneTests(unittest.TestCase):
    def test_updates_live_timezone_without_marker(self):
        run = mock.Mock(return_value=mock.Mock(returncode=0, stderr=""))
        marker = apply_runtime_timezone(
            "Europe/Warsaw",
            run=run,
            environ={"ZENOS_INSTALLER": "1"},
        )
        run.assert_called_once_with(
            ["sudo", "-n", "timedatectl", "set-timezone", "Europe/Warsaw"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertIsNone(marker)

    def test_oobe_writes_clock_ready_marker_after_success(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            marker = apply_runtime_timezone(
                "America/New_York",
                run=mock.Mock(return_value=mock.Mock(returncode=0, stderr="")),
                environ={"ZENOS_OOBE": "1", "XDG_RUNTIME_DIR": runtime_dir},
            )
            self.assertEqual(marker, Path(runtime_dir) / "zenos-oobe-timezone-ready")
            self.assertTrue(marker.is_file())

    def test_invalid_timezone_never_invokes_timedatectl(self):
        run = mock.Mock()
        with self.assertRaises(Exception):
            apply_runtime_timezone("Not/A_Timezone", run=run, environ={})
        run.assert_not_called()

    def test_nixos_fallback_repoints_localtime(self):
        run = mock.Mock(
            side_effect=[
                mock.Mock(returncode=1, stderr="read-only timezone configuration"),
                mock.Mock(returncode=0, stderr=""),
            ]
        )
        apply_runtime_timezone("Europe/Warsaw", run=run, environ={})
        self.assertEqual(
            run.call_args_list[1].args[0],
            [
                "sudo",
                "-n",
                "ln",
                "-sfn",
                "/etc/zoneinfo/Europe/Warsaw",
                "/etc/localtime",
            ],
        )


if __name__ == "__main__":
    unittest.main()
