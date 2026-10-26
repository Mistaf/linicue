import unittest

from linicue.pollrate import peak_rate


class PeakRateTests(unittest.TestCase):
    def test_counts_the_busiest_second(self):
        slow = [i / 125 for i in range(125 * 2)]  # 125 Hz for two seconds
        self.assertAlmostEqual(peak_rate(slow), 125, delta=2)
        burst = [0.0, 0.1, 0.2, 5.0] + [10 + i / 1000 for i in range(1000)]  # a 1000 Hz burst somewhere
        self.assertAlmostEqual(peak_rate(burst), 1000, delta=2)

    def test_a_full_second_of_reports_is_not_counted_one_too_many(self):
        reports = [i / 1000 for i in range(1001)]  # 1001 timestamps spanning exactly one second at 1 kHz
        self.assertEqual(peak_rate(reports), 1000)  # half-open window: [t, t + 1s)

    def test_empty_and_single(self):
        self.assertEqual(peak_rate([]), 0)
        self.assertEqual(peak_rate([3.0]), 1)


if __name__ == "__main__":
    unittest.main()
