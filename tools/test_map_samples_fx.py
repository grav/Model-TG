#!/usr/bin/env python3
"""Tests use synthetic bytes only; no vendor firmware is needed."""
import tempfile
import unittest
from pathlib import Path

import struct

from map_samples_fx import (
    BASE, CAPACITY_SITES, POOL_BASE_SITES, SAMPLE_POOL_BASE,
    SAMPLE_POOL_CAPACITY, HISTORY_BYTES, audit_samples_pool,
    candidates, load_stock, signature,
)


class SignatureTests(unittest.TestCase):
    def test_exact_and_overlapping_matches(self):
        self.assertEqual(candidates(b"ababab", b"abab", b"\xff" * 4),
                         [BASE, BASE + 2])

    def test_unaligned_matches_are_excluded(self):
        self.assertEqual(candidates(b"xabab", b"abab", b"\xff" * 4), [])

    def test_relocated_pointer_and_pc_call(self):
        original = bytes.fromhex("4879401000004ebaff804e75")
        relocated = bytes.fromhex("4879402000004eba12344e75")
        window, mask = signature(original, BASE, len(original))
        self.assertEqual(candidates(relocated, window, mask), [BASE])
        # The opcode and non-address instruction bytes must still agree.
        self.assertEqual(candidates(relocated[:-1] + b"x", window, mask), [])

    def test_register_and_stack_offsets_are_preserved(self):
        original = bytes.fromhex("206f00042028000c4e75")
        window, mask = signature(original, BASE, len(original))
        self.assertEqual(mask, b"\xff" * len(original))
        self.assertEqual(candidates(bytes.fromhex("206f00082028000c4e75"),
                                    window, mask), [])

    def test_wildcard_includes_newline(self):
        self.assertEqual(candidates(b"a\nbc", b"axbc", b"\xff\0\xff\xff"), [BASE])

    def test_out_of_bounds_signature_is_rejected(self):
        for address, size in ((BASE - 2, 4), (BASE, 6)):
            with self.assertRaises(ValueError):
                signature(b"abcd", address, size)

    def test_unknown_firmware_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unknown.bin"
            path.write_bytes(b"not stock firmware")
            with self.assertRaisesRegex(ValueError, "not the supported unmodified"):
                load_stock(path, "samples")


class PoolAuditTests(unittest.TestCase):
    def setUp(self):
        self.image = bytearray(0xA1800)
        for address, opcode, _ in CAPACITY_SITES:
            struct.pack_into(">HI", self.image, address - BASE,
                             opcode, SAMPLE_POOL_CAPACITY)
        for address, opcode in POOL_BASE_SITES:
            struct.pack_into(">HI", self.image, address - BASE,
                             opcode, SAMPLE_POOL_BASE)

    def test_expected_sites(self):
        audit_samples_pool(self.image)

    def test_changed_capacity_or_opcode(self):
        for address, _, _ in CAPACITY_SITES:
            for delta in (0, 5):
                with self.subTest(address=address, delta=delta):
                    damaged = self.image.copy()
                    damaged[address - BASE + delta] ^= 1
                    with self.assertRaisesRegex(ValueError, "capacity instruction changed"):
                        audit_samples_pool(damaged)

    def test_changed_base(self):
        self.image[POOL_BASE_SITES[0][0] - BASE + 5] ^= 1
        with self.assertRaisesRegex(ValueError, "base instruction changed"):
            audit_samples_pool(self.image)

    def test_additional_capacity_literal(self):
        struct.pack_into(">I", self.image, 0, SAMPLE_POOL_CAPACITY)
        with self.assertRaisesRegex(ValueError, "unaccounted"):
            audit_samples_pool(self.image)

    def test_truncated_image(self):
        with self.assertRaises(ValueError):
            audit_samples_pool(self.image[:100])

    def test_reservation_arithmetic(self):
        end = SAMPLE_POOL_BASE + SAMPLE_POOL_CAPACITY
        start = end - HISTORY_BYTES
        self.assertEqual(end, 0x4E2DD4E0)
        self.assertEqual(start, 0x4DEDD4E0)
        self.assertEqual(SAMPLE_POOL_CAPACITY - HISTORY_BYTES, 0x03C00050)
        self.assertEqual(start % 16, 0)
        self.assertLess(SAMPLE_POOL_BASE, start)
        self.assertLess(end, 0x4E400000)  # stock delay-ring base


if __name__ == "__main__":
    unittest.main()
