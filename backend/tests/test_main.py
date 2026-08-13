import os
import tempfile
import unittest
from unittest.mock import patch

from src.api.main import _clear_stale_temp_clones


class TestClearStaleTempClones(unittest.TestCase):
    def test_removes_leftover_directories(self):
        with tempfile.TemporaryDirectory() as workspace:
            temp_clones_dir = os.path.join(workspace, ".temp_clones")
            stale_dir = os.path.join(temp_clones_dir, "tmpabc123")
            os.makedirs(stale_dir)
            with open(os.path.join(stale_dir, "testing.txt"), "w") as f:
                f.write("leftover clone")

            with patch("src.api.main.os.getcwd", return_value=workspace):
                _clear_stale_temp_clones()

            self.assertTrue(os.path.isdir(temp_clones_dir))
            self.assertEqual(os.listdir(temp_clones_dir), [])

    def test_noop_when_temp_clones_dir_does_not_exist(self):
        with tempfile.TemporaryDirectory() as workspace:
            with patch("src.api.main.os.getcwd", return_value=workspace):
                _clear_stale_temp_clones()  # should not raise

            self.assertFalse(os.path.isdir(os.path.join(workspace, ".temp_clones")))


if __name__ == "__main__":
    unittest.main()
