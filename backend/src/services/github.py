import logging
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from itertools import islice
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlparse

from github import Github, GithubException

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: Dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".html": "HTML",
    ".css": "CSS",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".sh": "Shell",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".txt": "Text"
}

IGNORE_DIRS = {
    ".git", 
    "node_modules", 
    "build", 
    "dist", 
    "venv", 
    ".venv", 
    "pycache", 
    "__pycache__"
}

PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def is_dead_local_proxy(value: Optional[str]) -> bool:
    """Return True for the blocked proxy value inherited by some local/sandbox shells."""
    if not value:
        return False

    parsed = urlparse(value)
    return parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 9


def github_network_env() -> Dict[str, str]:
    """Build an environment for GitHub network calls without inherited dead local proxies."""
    env = os.environ.copy()
    for key in PROXY_ENV_VARS:
        if is_dead_local_proxy(env.get(key)):
            env.pop(key, None)
    return env


@contextmanager
def without_dead_local_proxy() -> Iterator[None]:
    """Temporarily remove dead local proxy variables for libraries that read os.environ."""
    removed: Dict[str, str] = {}
    for key in PROXY_ENV_VARS:
        value = os.environ.get(key)
        if is_dead_local_proxy(value):
            removed[key] = value
            os.environ.pop(key, None)

    try:
        yield
    finally:
        os.environ.update(removed)

def safe_rmtree(path: str) -> None:
    """
    Safely remove directory tree, handling Windows read-only file permission issues (e.g. from .git).
    """
    try:
        shutil.rmtree(path)
    except Exception:
        try:
            import stat
            def _handle_readonly(func, p, exc_info):
                try:
                    os.chmod(p, stat.S_IWRITE)
                    func(p)
                except Exception:
                    pass
            shutil.rmtree(path, onerror=_handle_readonly)
        except Exception as e:
            logger.warning("Failed to safely remove directory %s: %s", path, e)

class GitHubService:
    """
    Handles cloning GitHub repositories locally, scanning their directories,
    filtering for supported source files, and extracting file contents and metadata.
    """
    
    def __init__(self, token: Optional[str] = None):
        """
        Initialize the GitHub service with an optional access token for auth/rate limits.
        
        Args:
            token: GitHub personal access token (optional).
        """
        self.token = token

    def parse_repo_url(self, repo_url: str) -> tuple[str, str]:
        """Extract GitHub owner and repository name from an HTTPS repo URL."""
        parsed = urlparse(repo_url.strip())
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if parsed.netloc.lower() not in {"github.com", "www.github.com"} or len(path_parts) < 2:
            raise ValueError("Expected a GitHub repository URL like https://github.com/owner/repo.")

        owner = path_parts[0]
        repo_name = path_parts[1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        return owner, repo_name

    def fetch_repository_context(
        self,
        repo_url: str,
        files: Optional[List[Dict[str, Any]]] = None,
        commit_limit: int = 50,
        pull_limit: int = 50,
        contributor_limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Fetch repository metadata, commits, pull requests, and the current source snapshot.
        The file list can be supplied from ingestion to avoid cloning the repository twice.
        Pass an empty list (rather than omitting the argument) to skip the source
        snapshot entirely without triggering a clone.
        """
        owner, repo_name = self.parse_repo_url(repo_url)
        try:
            with without_dead_local_proxy():
                github_client = Github(self.token) if self.token else Github()
                repo = github_client.get_repo(f"{owner}/{repo_name}")
                license_name = repo.license.name if repo.license else None
                contributors = [
                    {"login": contributor.login, "contributions": contributor.contributions}
                    for contributor in islice(repo.get_contributors(), contributor_limit)
                ]
                commits = [
                    self._commit_to_dict(commit, repo.default_branch)
                    for commit in islice(repo.get_commits(), commit_limit)
                ]
                try:
                    pull_requests = [
                        self._pull_request_to_dict(pr)
                        for pr in islice(repo.get_pulls(state="all", sort="updated", direction="desc"), pull_limit)
                    ]
                except GithubException as pr_exc:
                    logger.warning(
                        "Could not fetch pull requests for %s/%s (status %s): %s. Skipping PRs.",
                        owner,
                        repo_name,
                        getattr(pr_exc, "status", "?"),
                        pr_exc.data.get("message", str(pr_exc)) if pr_exc.data else str(pr_exc),
                    )
                    pull_requests = []

                return {
                    "metadata": {
                        "name": repo.name,
                        "full_name": repo.full_name,
                        "description": repo.description,
                        "owner": repo.owner.login,
                        "stars": repo.stargazers_count,
                        "forks": repo.forks_count,
                        "primary_language": repo.language,
                        "license": license_name,
                        "default_branch": repo.default_branch,
                        "latest_commit": commits[0]["message"] if commits else None,
                        "size_kb": repo.size,
                        "visibility": "private" if repo.private else "public",
                        "open_issues": repo.open_issues_count,
                        "contributors": contributors,
                        "html_url": repo.html_url,
                    },
                    "files": files if files is not None else self.fetch_repo_files(repo_url),
                    "commits": commits,
                    "pull_requests": pull_requests,
                }
        except GithubException as e:
            logger.exception("GitHub API request failed for %s/%s", owner, repo_name)
            raise RuntimeError(f"GitHub API request failed: {e.data.get('message', str(e)) if e.data else e}") from e

    def _commit_to_dict(self, commit: Any, default_branch: str) -> Dict[str, Any]:
        stats = getattr(commit, "stats", None)
        raw_files = getattr(commit, "files", None)
        files = list(raw_files) if raw_files is not None else []
        diff_lines: List[str] = []
        for changed_file in files[:5]:
            patch = getattr(changed_file, "patch", None)
            if patch:
                diff_lines.append(f"--- {changed_file.filename}\n{patch}")

        return {
            "hash": commit.sha,
            "author": (
                commit.author.login
                if commit.author
                else commit.commit.author.name
                if commit.commit and commit.commit.author
                else "unknown"
            ),
            "message": commit.commit.message if commit.commit else "",
            "time": commit.commit.author.date.isoformat() if commit.commit and commit.commit.author else "",
            "branch": default_branch,
            "filesChanged": len(files),
            "additions": stats.additions if stats else 0,
            "deletions": stats.deletions if stats else 0,
            "diff": "\n\n".join(diff_lines),
        }

    def _pull_request_to_dict(self, pr: Any) -> Dict[str, Any]:
        status = "merged" if pr.merged else pr.state
        return {
            "id": pr.id,
            "number": pr.number,
            "title": pr.title,
            "author": pr.user.login if pr.user else "unknown",
            "status": status,
            "labels": [label.name for label in pr.labels],
            "merge_date": pr.merged_at.isoformat() if pr.merged_at else None,
            "reviewers": [reviewer.login for reviewer in pr.requested_reviewers],
            "created_at": pr.created_at.isoformat() if pr.created_at else "",
            "updated_at": pr.updated_at.isoformat() if pr.updated_at else "",
            "body": pr.body or "",
        }

    def clone_repository(self, repo_url: str, depth: int = 1) -> str:
        """
        Clones a GitHub repository from a URL into a temporary workspace within the project.

        Args:
            repo_url: Full HTTP URL to the GitHub repository.
            depth: How many commits of history to fetch (``git clone --depth``).
                Defaults to 1 (just the latest commit); callers that need local
                commit history (see ``get_local_commit_history``) should pass a
                larger value.

        Returns:
            The absolute local path to the cloned repository.

        Raises:
            ValueError: If the repository URL is empty or invalid.
            RuntimeError: If cloning fails.
        """
        if not repo_url or not repo_url.strip():
            logger.error("Repository URL is empty or invalid.")
            raise ValueError("Repository URL cannot be empty.")

        # Ensure temp directory exists inside workspace root to adhere to constraints
        workspace_root = os.getcwd()
        temp_base_dir = os.path.join(workspace_root, ".temp_clones")
        try:
            os.makedirs(temp_base_dir, exist_ok=True)
        except Exception as e:
            logger.exception("Failed to create temporary base directory %s", temp_base_dir)
            raise RuntimeError(f"Failed to initialize temporary workspace directory: {e}") from e

        # Build authenticated clone URL if token is present
        clone_url = repo_url.strip()
        if self.token:
            # Handle token injection for HTTP clone URLs
            if clone_url.startswith("https://github.com/"):
                clone_url = clone_url.replace("https://github.com/", f"https://x-access-token:{self.token}@github.com/")
            elif clone_url.startswith("http://github.com/"):
                clone_url = clone_url.replace("http://github.com/", f"http://x-access-token:{self.token}@github.com/")

        # Create a unique temporary directory inside the temp base directory
        try:
            temp_dir = tempfile.mkdtemp(dir=temp_base_dir)
            logger.info("Created temporary workspace directory for cloning: %s", temp_dir)
        except Exception as e:
            logger.exception("Failed to create temporary directory for clone")
            raise RuntimeError(f"Failed to create temporary directory for clone: {e}") from e

        try:
            logger.info("Cloning repository from %s to %s", repo_url, temp_dir)
            # Execute git clone
            # Use --depth 1 to minimize download size and speed up ingestion
            subprocess.run(
                ["git", "clone", "--depth", str(max(depth, 1)), clone_url, temp_dir],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=github_network_env(),
            )
            logger.info("Successfully cloned repository to %s", temp_dir)
            return os.path.abspath(temp_dir)
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.strip() if e.stderr else (e.stdout.strip() if e.stdout else str(e))
            logger.error("Git clone failed: %s", err_msg)
            if os.path.exists(temp_dir):
                try:
                    safe_rmtree(temp_dir)
                    logger.info("Cleaned up temporary directory %s after clone failure", temp_dir)
                except Exception as cleanup_err:
                    logger.exception("Failed to clean up directory %s after clone failure", temp_dir)
            raise RuntimeError(f"Failed to clone repository: {err_msg}") from e
        except Exception as e:
            logger.exception("An unexpected error occurred during repository clone")
            if os.path.exists(temp_dir):
                try:
                    safe_rmtree(temp_dir)
                    logger.info("Cleaned up temporary directory %s after clone failure", temp_dir)
                except Exception as cleanup_err:
                    logger.exception("Failed to clean up directory %s after clone failure", temp_dir)
            raise RuntimeError(f"An unexpected error occurred during repository clone: {e}") from e

    def fetch_repo_files(self, repo_url: str) -> List[Dict[str, Any]]:
        """
        Clones a GitHub repository into a temporary workspace within the project,
        scans the files, and extracts path, language, and content metadata.
        
        Args:
            repo_url: Full HTTP URL to the GitHub repository.
            
        Returns:
            List of dicts, each containing:
                - "path": Relative path from the repository root
                - "language": Inferred language based on file extension
                - "content": Decoded UTF-8 content of the file
                
        Raises:
            ValueError: If the repository URL is empty or invalid.
            RuntimeError: If cloning or reading files fails.
        """
        temp_dir = self.clone_repository(repo_url)
        try:
            return self._scan_files(temp_dir)
        finally:
            if os.path.exists(temp_dir):
                try:
                    safe_rmtree(temp_dir)
                    logger.info("Cleaned up temporary directory %s after file scanning", temp_dir)
                except Exception as cleanup_err:
                    logger.exception("Failed to clean up temporary directory %s after scanning", temp_dir)

    def fetch_repo_files_and_commits(
        self, repo_url: str, commit_limit: int = 50
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Clones the repository once and returns both its scanned source files
        and its recent commit history, extracted locally via ``git log``
        (see ``get_local_commit_history``). Used by ingestion so the commits
        tab has real data without depending on a live GitHub API call, which
        needs a github.com URL, a good rate limit, and network access.
        """
        temp_dir = self.clone_repository(repo_url, depth=max(commit_limit, 1))
        try:
            files = self._scan_files(temp_dir)
            try:
                commits = self.get_local_commit_history(temp_dir, limit=commit_limit)
            except Exception as e:
                logger.warning("Failed to read local commit history for %s: %s", repo_url, e)
                commits = []
            return files, commits
        finally:
            if os.path.exists(temp_dir):
                try:
                    safe_rmtree(temp_dir)
                    logger.info("Cleaned up temporary directory %s after file scanning", temp_dir)
                except Exception:
                    logger.exception("Failed to clean up temporary directory %s after scanning", temp_dir)

    def _scan_files(self, temp_dir: str) -> List[Dict[str, Any]]:
        """Walks a cloned repository directory and extracts supported source files."""
        results: List[Dict[str, Any]] = []
        temp_path = Path(temp_dir)
        for root, dirs, files in os.walk(temp_dir):
            # Filter out ignore directories in place to prevent visiting
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                file_path = Path(root) / file
                ext = file_path.suffix.lower()

                if ext in SUPPORTED_EXTENSIONS:
                    lang = SUPPORTED_EXTENSIONS[ext]
                    # Calculate path relative to the clone directory root
                    rel_path = file_path.relative_to(temp_path).as_posix()

                    try:
                        # Read content; ignore decoding errors for non-UTF8/binary edge cases
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        results.append({
                            "path": rel_path,
                            "language": lang,
                            "content": content
                        })
                    except Exception as e:
                        logger.warning("Failed to read file %s: %s", file_path, e)
                        continue
        return results

    def get_local_commit_history(
        self, repo_path: str, limit: int = 50, max_diff_chars: int = 6000
    ) -> List[Dict[str, Any]]:
        """
        Extracts recent commit history (hash, author, date, message, diff
        stats, and a truncated diff) directly from a local git clone via
        ``git log``, instead of the GitHub API. Works for any git host and
        needs no network access, GitHub token, or known ``repo_url``.
        """
        try:
            branch_result = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
                check=True, capture_output=True, text=True,
            )
            branch = branch_result.stdout.strip() or "HEAD"
        except Exception:
            branch = "HEAD"

        record_start, field_sep, header_end = "\x02", "\x1f", "\x03"
        fmt = f"{record_start}%H{field_sep}%an{field_sep}%aI{field_sep}%B{header_end}"
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "log", f"-n{max(limit, 1)}", "-p", "--shortstat", f"--pretty=format:{fmt}"],
                check=True, capture_output=True, text=True, errors="ignore",
            )
        except subprocess.CalledProcessError as e:
            logger.warning("`git log` failed for %s: %s", repo_path, e.stderr)
            return []

        stat_pattern = re.compile(
            r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?"
        )

        commits: List[Dict[str, Any]] = []
        for record in result.stdout.split(record_start):
            if header_end not in record:
                continue
            header, _, rest = record.partition(header_end)
            fields = header.split(field_sep)
            if len(fields) < 4:
                continue
            commit_hash, author, date, message = fields[0], fields[1], fields[2], fields[3]

            # git emits the `--shortstat` summary line right after the commit
            # message and *before* the `-p` patch body, e.g.:
            #   <message>\n 1 file changed, 1 insertion(+), 1 deletion(-)\n\ndiff --git ...
            stat_match = stat_pattern.search(rest)
            if stat_match:
                files_changed = int(stat_match.group(1) or 0)
                additions = int(stat_match.group(2) or 0)
                deletions = int(stat_match.group(3) or 0)
                diff_text = rest[stat_match.end():]
            else:
                files_changed = additions = deletions = 0
                diff_text = rest

            diff_text = diff_text.strip()
            if len(diff_text) > max_diff_chars:
                diff_text = diff_text[:max_diff_chars] + "\n... (diff truncated)"

            commits.append({
                "hash": commit_hash,
                "author": author.strip() or "unknown",
                "message": message.strip(),
                "time": date.strip(),
                "branch": branch,
                "filesChanged": files_changed,
                "additions": additions,
                "deletions": deletions,
                "diff": diff_text,
            })

        return commits

    def chunk_file_content(self, file_content: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
        """
        Splits source code/file contents into smaller overlapping chunks suitable for embedding.
        
        Args:
            file_content: Raw contents of a code file.
            chunk_size: Target character size of chunks.
            chunk_overlap: Overlapping size between subsequent chunks.
            
        Returns:
            List of chunked substrings.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive.")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative.")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size.")

        chunks = []
        start = 0
        content_len = len(file_content)

        if content_len == 0:
            return []

        while start < content_len:
            end = start + chunk_size
            chunks.append(file_content[start:end])
            start += chunk_size - chunk_overlap

        return chunks
