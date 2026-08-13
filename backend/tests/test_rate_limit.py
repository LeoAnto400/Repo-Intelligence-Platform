import unittest
from unittest.mock import patch

from src.core.rate_limit import InMemoryRateLimiter


class TestInMemoryRateLimiter(unittest.TestCase):
    def test_allows_up_to_max_requests_then_blocks(self):
        limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60.0)

        self.assertTrue(limiter.allow("client-a"))
        self.assertTrue(limiter.allow("client-a"))
        self.assertTrue(limiter.allow("client-a"))
        self.assertFalse(limiter.allow("client-a"))

    def test_tracks_keys_independently(self):
        limiter = InMemoryRateLimiter(max_requests=1, window_seconds=60.0)

        self.assertTrue(limiter.allow("client-a"))
        self.assertFalse(limiter.allow("client-a"))
        self.assertTrue(limiter.allow("client-b"))

    def test_allows_again_once_window_elapses(self):
        limiter = InMemoryRateLimiter(max_requests=1, window_seconds=60.0)

        with patch("src.core.rate_limit.time.time", return_value=1000.0):
            self.assertTrue(limiter.allow("client-a"))
            self.assertFalse(limiter.allow("client-a"))

        with patch("src.core.rate_limit.time.time", return_value=1061.0):
            self.assertTrue(limiter.allow("client-a"))

    def test_reset_clears_all_tracked_keys(self):
        limiter = InMemoryRateLimiter(max_requests=1, window_seconds=60.0)
        limiter.allow("client-a")
        self.assertFalse(limiter.allow("client-a"))

        limiter.reset()

        self.assertTrue(limiter.allow("client-a"))


if __name__ == "__main__":
    unittest.main()
