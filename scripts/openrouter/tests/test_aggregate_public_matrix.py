import math
import pathlib
import sys
import unittest


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import aggregate_public_matrix as aggregate  # noqa: E402


def point(profile, concurrency, throughput, passed=True):
    return {
        "profile": profile,
        "concurrency": concurrency,
        "output_tokens_per_second": throughput,
        "performance_gate_passed": passed,
    }


class SelectionTests(unittest.TestCase):
    def test_selects_highest_shared_admissible_concurrency(self):
        points = []
        for profile, throughput in zip(aggregate.PRIMARY_PROFILES, (100, 80, 60, 40)):
            points.append(point(profile, 1, throughput))
            points.append(point(profile, 2, throughput * 1.5, passed=profile != "tool-use"))
        result = aggregate.select_candidate(points)
        self.assertTrue(result["performance_gate_passed"])
        self.assertEqual(result["admissible_concurrency"], 1)
        expected = math.prod((100, 80, 60, 40)) ** 0.25
        self.assertAlmostEqual(result["primary_throughput_geomean"], expected)

    def test_missing_primary_profile_fails_closed(self):
        points = [point(profile, 1, 10) for profile in aggregate.PRIMARY_PROFILES[:-1]]
        result = aggregate.select_candidate(points)
        self.assertFalse(result["performance_gate_passed"])
        self.assertIsNone(result["admissible_concurrency"])
        self.assertIn("long-prefill", result["evaluated_concurrencies"][0]["missing_profiles"])

    def test_geometric_mean_rejects_nonpositive_value(self):
        with self.assertRaises(ValueError):
            aggregate.geometric_mean([1.0, 0.0])


if __name__ == "__main__":
    unittest.main()
