import pathlib
import sys
import unittest


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import check_early_429 as overload  # noqa: E402


class Early429Tests(unittest.TestCase):
    def test_valid_early_rejection(self):
        results = [
            {"status_code": 200, "headers_ms": 20.0, "retry_after_present": False},
            {"status_code": 429, "headers_ms": 25.0, "retry_after_present": True},
            {"status_code": 429, "headers_ms": 30.0, "retry_after_present": True},
        ]
        passed, failures, summary = overload.evaluate(results, 100.0, 1)
        self.assertTrue(passed, failures)
        self.assertEqual(summary["rejected_429"], 2)

    def test_queue_or_bad_error_fails(self):
        results = [
            {"status_code": 200, "headers_ms": 20.0, "retry_after_present": False},
            {"status_code": 500, "headers_ms": 30.0, "retry_after_present": False},
        ]
        passed, failures, _ = overload.evaluate(results, 100.0, 1)
        self.assertFalse(passed)
        self.assertTrue(any("no overload" in item for item in failures))
        self.assertTrue(any("unexpected" in item for item in failures))

    def test_slow_or_headerless_429_fails(self):
        results = [
            {"status_code": 200, "headers_ms": 20.0, "retry_after_present": False},
            {"status_code": 429, "headers_ms": 1500.0, "retry_after_present": False},
        ]
        passed, failures, _ = overload.evaluate(results, 1000.0, 1)
        self.assertFalse(passed)
        self.assertTrue(any("Retry-After" in item for item in failures))
        self.assertTrue(any("exceeds" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
