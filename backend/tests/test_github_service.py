import os
import shutil
import unittest
from unittest.mock import patch, MagicMock, ANY
import subprocess
from pathlib import Path

from src.services.github import GitHubService, github_network_env

class TestGitHubService(unittest.TestCase):
    def setUp(self):
        self.service_no_token = GitHubService()
        self.service_with_token = GitHubService(token="test-token-123")

    @patch("os.makedirs")
    @patch("tempfile.mkdtemp")
    @patch("subprocess.run")
    def test_clone_repository_success(self, mock_run, mock_mkdtemp, mock_makedirs):
        # Setup mocks
        mock_mkdtemp.return_value = os.path.abspath("dummy_temp_dir")
        
        # Call the method
        repo_url = "https://github.com/user/repo"
        result_path = self.service_no_token.clone_repository(repo_url)
        
        # Verify makedirs called for base temp clones dir
        mock_makedirs.assert_called_once()
        # Verify subprocess.run called with correct arguments
        mock_run.assert_called_once_with(
            ["git", "clone", "--depth", "1", repo_url, os.path.abspath("dummy_temp_dir")],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=ANY,
        )
        self.assertEqual(result_path, os.path.abspath("dummy_temp_dir"))

    @patch("os.makedirs")
    @patch("tempfile.mkdtemp")
    @patch("subprocess.run")
    def test_clone_repository_token_injection(self, mock_run, mock_mkdtemp, mock_makedirs):
        mock_mkdtemp.return_value = os.path.abspath("dummy_temp_dir")
        
        repo_url = "https://github.com/user/repo"
        result_path = self.service_with_token.clone_repository(repo_url)
        
        expected_url = "https://x-access-token:test-token-123@github.com/user/repo"
        mock_run.assert_called_once_with(
            ["git", "clone", "--depth", "1", expected_url, os.path.abspath("dummy_temp_dir")],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=ANY,
        )

    @patch.dict(os.environ, {
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://localhost:9",
        "ALL_PROXY": "http://proxy.example.com:8080",
    }, clear=False)
    def test_github_network_env_removes_only_dead_local_proxy(self):
        env = github_network_env()

        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertEqual(env["ALL_PROXY"], "http://proxy.example.com:8080")

    def test_clone_repository_empty_url(self):
        with self.assertRaises(ValueError) as context:
            self.service_no_token.clone_repository("")
        self.assertIn("Repository URL cannot be empty", str(context.exception))
        
        with self.assertRaises(ValueError) as context:
            self.service_no_token.clone_repository("   ")
        self.assertIn("Repository URL cannot be empty", str(context.exception))

    @patch("os.makedirs")
    @patch("tempfile.mkdtemp")
    @patch("subprocess.run")
    @patch("os.path.exists")
    @patch("shutil.rmtree")
    def test_clone_repository_failure(self, mock_rmtree, mock_exists, mock_run, mock_mkdtemp, mock_makedirs):
        mock_mkdtemp.return_value = os.path.abspath("dummy_temp_dir")
        mock_exists.return_value = True
        
        # Simulate CalledProcessError
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="git clone",
            stderr="Could not resolve host"
        )
        
        repo_url = "https://github.com/user/repo"
        with self.assertRaises(RuntimeError) as context:
            self.service_no_token.clone_repository(repo_url)
            
        self.assertIn("Failed to clone repository: Could not resolve host", str(context.exception))
        # Ensure cleanup is called
        mock_rmtree.assert_called_once_with(os.path.abspath("dummy_temp_dir"))

    @patch.object(GitHubService, "clone_repository")
    @patch("os.walk")
    @patch("shutil.rmtree")
    @patch("os.path.exists")
    @patch.object(Path, "read_text")
    def test_fetch_repo_files_success(self, mock_read_text, mock_exists, mock_rmtree, mock_walk, mock_clone):
        # Mock clone dir
        dummy_dir = os.path.abspath("dummy_dir")
        mock_clone.return_value = dummy_dir
        mock_exists.return_value = True
        
        # Mock directory structure: files root/main.py, root/sub/test.js, root/sub/ignored.exe (ignored suffix)
        mock_walk.return_value = [
            (dummy_dir, ["sub"], ["main.py", "ignored.exe"]),
            (os.path.join(dummy_dir, "sub"), [], ["test.js"])
        ]
        
        mock_read_text.side_effect = ["print('hello')", "console.log('hello')"]
        
        repo_url = "https://github.com/user/repo"
        results = self.service_no_token.fetch_repo_files(repo_url)
        
        mock_clone.assert_called_once_with(repo_url)
        mock_rmtree.assert_called_once_with(dummy_dir)
        
        expected_results = [
            {"path": "main.py", "language": "Python", "content": "print('hello')"},
            {"path": "sub/test.js", "language": "JavaScript", "content": "console.log('hello')"}
        ]
        self.assertEqual(results, expected_results)

if __name__ == "__main__":
    unittest.main()
