#!/usr/bin/env python3
"""Stock-free builder tests; optionally execute cold-boot clearing in Unicorn."""
import hashlib
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from build_samples_fx import build, HISTORY_BASE
from build_samples_firmware import (BSS_START, BSS_END, CACHE_BASE, CACHE_BLOCK,
                                    CACHE_ENTRY, HOOKS, patch_main, patches, validate_payload)
from map_samples_fx import CAPACITY_SITES, SAMPLE_POOL_CAPACITY, HISTORY_BYTES

CROSS = next((c for c in ('m68k-elf-', 'm68k-linux-gnu-') if shutil.which(c + 'as')), None)


class FirmwarePatchTests(unittest.TestCase):
    def report(self):
        return {'payload_bytes': 1600, 'symbols': {
            label: CACHE_BASE + i * 16 for i, (_, _, label, _, _) in enumerate(HOOKS)}}

    def test_patches_are_disjoint_complete_instructions(self):
        edits = sorted(patches(self.report()))
        self.assertEqual(len(edits), len(HOOKS) + len(CAPACITY_SITES) + 2)
        previous = 0
        for address, old, new in edits:
            self.assertGreaterEqual(address, previous)
            self.assertEqual(len(old), len(new))
            self.assertEqual(len(new) % 2, 0)
            previous = address + len(new)

    def test_all_capacity_operands_and_cache_links_are_reserved(self):
        edits = {a: new for a, old, new in patches(self.report())}
        for address, opcode, _ in CAPACITY_SITES:
            self.assertEqual(edits[address], struct.pack('>HI', opcode, SAMPLE_POOL_CAPACITY - HISTORY_BYTES))
        self.assertEqual(edits[0x4007831A][2:], struct.pack('>I', CACHE_ENTRY + 56))
        self.assertEqual(edits[0x40078350][2:], struct.pack('>I', CACHE_ENTRY + 20))

    def test_invalid_hook_targets_are_rejected(self):
        for invalid in (CACHE_BASE - 2, CACHE_BASE + 1, CACHE_BASE + 1600):
            report = self.report()
            report['symbols']['samples_key'] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'invalid hook target'):
                patches(report)

    def test_wrong_stock_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unmodified Samples'):
            patch_main(b'not firmware', {}, b'payload')


@unittest.skipUnless(CROSS, 'ColdFire binutils not installed')
class FirmwarePayloadTests(unittest.TestCase):
    def test_bad_reservations_and_boundaries_are_rejected(self):
        import copy
        with tempfile.TemporaryDirectory() as folder:
            report = build(folder, payload_base=CACHE_BASE, cold_boot=True)
            payload = (Path(folder) / 'samples_fx.bin').read_bytes()
            validate_payload(report, payload)
            for field, value in (('cold_boot', False), ('payload_base', 0x47000000),
                                 ('history_base', 0x4E400000), ('history_bytes', 0),
                                 ('payload_bytes', len(payload) + 16),
                                 ('payload_sha256', 'incorrect')):
                bad = copy.deepcopy(report)
                bad[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate_payload(bad, payload)
            bad = copy.deepcopy(report)
            bad['symbols']['samples_payload_end'] += 16
            with self.assertRaisesRegex(ValueError, 'boundary symbols'):
                validate_payload(bad, payload)

    def test_corrupt_unaligned_and_oversized_payloads_are_rejected(self):
        import copy
        with tempfile.TemporaryDirectory() as folder:
            report = build(folder, payload_base=CACHE_BASE, cold_boot=True)
            payload = (Path(folder) / 'samples_fx.bin').read_bytes()
            with self.assertRaisesRegex(ValueError, 'digest'):
                validate_payload(report, b'bad' + payload[3:])
            for data in (payload + b'xx', bytes(CACHE_BLOCK + 16)):
                bad = copy.deepcopy(report)
                bad['payload_bytes'] = len(data)
                bad['payload_sha256'] = hashlib.sha256(data).hexdigest()
                bad['symbols']['samples_payload_end'] = CACHE_BASE + len(data)
                with self.assertRaisesRegex(ValueError, 'alignment or one-cache-block'):
                    validate_payload(bad, data)

    def test_relocated_payload_fits_one_cache_block(self):
        with tempfile.TemporaryDirectory() as folder:
            report = build(folder, payload_base=CACHE_BASE, cold_boot=True)
            payload = (Path(folder) / 'samples_fx.bin').read_bytes()
            self.assertTrue(report['cold_boot'])
            self.assertFalse(report['hardware_installable'])
            self.assertEqual(report['payload_base'], CACHE_BASE)
            self.assertLessEqual(len(payload), CACHE_BLOCK)
            self.assertEqual(len(payload) % 16, 0)
            self.assertEqual(report['symbols']['samples_payload_end'], CACHE_BASE + len(payload))
            self.assertEqual(hashlib.sha256(payload).hexdigest(), report['payload_sha256'])
            # Boot routine must skip exactly this blob, not the BSS before it.
            boot = payload[report['symbols']['samples_boot_clear'] - CACHE_BASE:]
            for immediate in (BSS_START, BSS_END, CACHE_BASE, CACHE_BASE + len(payload), HISTORY_BASE):
                self.assertIn(struct.pack('>I', immediate), boot)

    def test_boot_clear_preserves_payload_and_clears_all_owned_memory(self):
        try:
            from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
            from unicorn.m68k_const import (UC_CPU_M68K_CFV4E, UC_M68K_REG_A0,
                UC_M68K_REG_A7, UC_M68K_REG_PC, UC_M68K_REG_SR, UC_M68K_REG_D1,
                UC_M68K_REG_D4, UC_M68K_REG_D5, UC_M68K_REG_D6, UC_M68K_REG_D7)
        except ImportError:
            self.skipTest('Unicorn not installed; run with DigiEmu Python to execute boot clear')
        with tempfile.TemporaryDirectory() as folder:
            report = build(folder, payload_base=CACHE_BASE, cold_boot=True)
            payload = (Path(folder) / 'samples_fx.bin').read_bytes()
            uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
            uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
            low, size = 0x40000000, 0x02200000
            uc.mem_map(low, size)
            uc.mem_write(low, b'\xa5' * size)
            history_page = HISTORY_BASE & ~0xfff
            history_size = ((HISTORY_BASE + HISTORY_BYTES + 16 - history_page + 0xfff) // 0x1000) * 0x1000
            uc.mem_map(history_page, history_size)
            uc.mem_write(history_page, b'\xa5' * history_size)
            stack_page, stop = 0x47ff0000, 0x47000000
            uc.mem_map(stack_page, 0x1000)
            uc.mem_map(stop, 0x1000)
            stack = stack_page + 0x800
            uc.mem_write(stack, struct.pack('>I', stop))
            uc.mem_write(CACHE_BASE, payload)
            uc.mem_write(0x400004B2, bytes.fromhex('4ef9') + struct.pack('>I', report['symbols']['samples_boot_clear']))
            uc.reg_write(UC_M68K_REG_SR, 0x2700)
            uc.reg_write(UC_M68K_REG_A7, stack)
            saved = (UC_M68K_REG_D4, UC_M68K_REG_D5, UC_M68K_REG_D6, UC_M68K_REG_D7)
            for i, register in enumerate(saved):
                uc.reg_write(register, 0x11223300 + i)
            uc.emu_start(0x400004B2, stop, count=20_000_000)
            self.assertEqual(uc.reg_read(UC_M68K_REG_PC), stop)
            self.assertEqual(uc.reg_read(UC_M68K_REG_A7), stack + 4)
            self.assertEqual(uc.reg_read(UC_M68K_REG_A0), BSS_END)
            self.assertEqual(uc.reg_read(UC_M68K_REG_D1), 0)
            for i, register in enumerate(saved):
                self.assertEqual(uc.reg_read(register), 0x11223300 + i)
            self.assertEqual(bytes(uc.mem_read(CACHE_BASE, len(payload))), payload)
            self.assertFalse(any(uc.mem_read(BSS_START, CACHE_BASE - BSS_START)))
            end = CACHE_BASE + len(payload)
            self.assertFalse(any(uc.mem_read(end, BSS_END - end)))
            self.assertFalse(any(uc.mem_read(HISTORY_BASE, HISTORY_BYTES)))
            for address in (BSS_START - 16, BSS_END, HISTORY_BASE - 16, HISTORY_BASE + HISTORY_BYTES):
                self.assertEqual(bytes(uc.mem_read(address, 16)), b'\xa5' * 16)


if __name__ == '__main__':
    unittest.main()
