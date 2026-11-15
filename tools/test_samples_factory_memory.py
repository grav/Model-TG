"""Stock-free arithmetic/identity checks for the factory-memory audit."""
import unittest

from check_samples_factory_memory import allocation_bytes, bank_usage, REDUCED_CAPACITY


class FactoryMemoryTests(unittest.TestCase):
    def test_every_file_is_rounded_to_sixteen_bytes(self):
        self.assertEqual(allocation_bytes([0, 1, 15, 16, 17, 80]), 160)

    def test_iterators_are_supported(self):
        self.assertEqual(allocation_bytes(n for n in (15, 16, 17)), 64)

    def test_negative_sizes_are_rejected(self):
        with self.assertRaises(ValueError):
            allocation_bytes([16, -1])

    def test_unverified_bank_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'verified reconstructed'):
            bank_usage(b'not a factory bank')

    def test_pool_reduction_is_exactly_four_mib(self):
        self.assertEqual(REDUCED_CAPACITY, 60 * 1024 * 1024 + 80)


if __name__ == '__main__':
    unittest.main()
