#!/usr/bin/env python3
"""Check factory-bank RAM size and walk STOCK patterns in an offline DigiEmu copy.

No physical-device access. Runtime test uses stock Samples 1.13 with only the
same five capacity operands reduced to the port's 60 MiB pool. Source cards,
snapshots, projects and the running panel are not modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import zlib

from map_samples_fx import CAPACITY_SITES, HISTORY_BYTES, SAMPLE_POOL_CAPACITY, load_stock
from test_samples_fx_emulator import clone_file, put

FACTORY_SHA256 = 'f4565d6549deb19d395bb7794062af8ccb8ce2fd10a406b8f1e90ae18c0900e9'
REDUCED_CAPACITY = SAMPLE_POOL_CAPACITY - HISTORY_BYTES


def allocation_bytes(sizes):
    sizes = tuple(sizes)
    if any(size < 0 for size in sizes):
        raise ValueError('negative file size')
    return sum((size + 15) & ~15 for size in sizes)


def bank_usage(bank):
    if hashlib.sha256(bank).hexdigest() != FACTORY_SHA256:
        raise ValueError('not the verified reconstructed Samples 1.13 factory bank')
    header, version, table, count = struct.unpack_from('>HHII', bank, 8)
    if bank[:4] != b'MaGj' or (header, version, table, count) != (20, 2, 20 + 396 * 12, 396):
        raise ValueError('unexpected factory-bank header')
    if zlib.crc32(bank[8:table] + bank[4:8]) ^ 0xffffffff != 0xdebb20e3:
        raise ValueError('factory-bank CRC mismatch')
    sizes = []
    for i in range(count):
        _hash, size, block = struct.unpack_from('>III', bank, 20 + 12 * i)
        if block * 0x4000 + size > len(bank):
            raise ValueError('factory sample exceeds bank')
        sizes.append(size)
    total = allocation_bytes(sizes)
    return {'sample_count': count, 'bank_storage_bytes': len(bank),
            'sample_file_bytes': sum(sizes), 'aligned_sample_file_bytes': total,
            'reduced_pool_bytes': REDUCED_CAPACITY,
            'headroom_if_all_factory_files_loaded': REDUCED_CAPACITY - total,
            'all_factory_files_fit': total <= REDUCED_CAPACITY}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank', required=True, type=Path)
    parser.add_argument('--digiemu', required=True, type=Path)
    parser.add_argument('--firmware-dir', required=True, type=Path,
                        help='offline factory-enabled stock Samples 1.13 profile')
    parser.add_argument('--syx-name', default='model-samples_OS1.13.syx')
    parser.add_argument('--work', required=True, type=Path, help='new disposable directory')
    args = parser.parse_args()
    bank_data = args.bank.read_bytes()
    summary = bank_usage(bank_data)
    work = args.work.resolve()
    if work.exists():
        raise ValueError('refusing to overwrite a work directory')
    work.mkdir(parents=True)
    sys.path.insert(0, str(args.digiemu.resolve()))
    from emu.bootstrap import FirmwarePaths
    from emu.portable import FolderLock
    from emu.session import Session
    from emu import panel
    target = work / 'firmware'
    with FolderLock(str(args.firmware_dir.resolve()), 'factory-memory-copy').acquire(0):
        shutil.copytree(args.firmware_dir, target, copy_function=clone_file,
                        ignore=shutil.ignore_patterns('.lock', 'logs'))
    paths = FirmwarePaths(str(target), args.syx_name, str(args.digiemu.resolve() / 'devices'))
    os.environ.update(paths.env())
    with open(paths.card, 'rb') as card:
        card.seek(0x30000000)
        if hashlib.sha256(card.read(len(bank_data))).hexdigest() != FACTORY_SHA256:
            raise ValueError('copied card does not contain the verified factory bank')
    stock = load_stock(paths.main_img, 'samples')
    result = {'mode': 'stock snapshot, reduced sample-pool operands, no FX injection; stopped pattern selection',
              'transport': 'stopped', 'factory_bank': summary, 'patterns': []}
    with FolderLock(str(target), 'factory-memory-audit').acquire(0):
        s = Session(paths.gui, paths.syx, audio=False)
        def counters():
            freed, high_water = struct.unpack('>II', s.m.uc.mem_read(0x40DBF264, 8))
            return {'high_water_bytes': high_water, 'freed_bytes': freed,
                    'live_bytes': high_water - freed}
        peak = counters()['high_water_bytes']
        try:
            if peak > REDUCED_CAPACITY:
                raise ValueError('initial stock snapshot already exceeds reduced capacity')
            # Check all sites before changing any guest code.
            for address, opcode, _ in CAPACITY_SITES:
                expected = struct.pack('>HI', opcode, SAMPLE_POOL_CAPACITY)
                if bytes(s.m.uc.mem_read(address, 6)) != expected or stock[address-0x40000400:address-0x40000400+6] != expected:
                    raise ValueError('snapshot capacity site differs from stock')
            for address, _, _ in CAPACITY_SITES:
                put(s.m, address + 2, struct.pack('>I', REDUCED_CAPACITY))
            result['initial'] = counters()
            def run(ms):
                nonlocal peak
                for _ in range(ms // 5):
                    s.run_ms(5)
                    if s.halted:
                        raise RuntimeError(s.halted)
                    peak = max(peak, counters()['high_water_bytes'])
                    if peak > REDUCED_CAPACITY:
                        raise RuntimeError('sample pool exceeded reduced capacity')
            def tap(code, hold=80, after=80):
                s.press(code); run(hold)
                s.release(code); run(after)
            tap(s.code('STOP'))
            for bank in range(6):
                for pattern in range(16):
                    label = f'{chr(65 + bank)}{pattern + 1:02d}'
                    s.press(s.code('PATTERN')); run(80)
                    tap(s.code(f'T{bank + 1}'))
                    tap(s.code(str(pattern + 1)))
                    s.release(s.code('PATTERN')); run(800)
                    item = {'requested_pattern': label, **counters(), 'peak_so_far': peak}
                    result['patterns'].append(item)
                    panel.write_png(s.screen_at(s.ms), str(work / f'{label}.png'))
                    print(json.dumps(item), flush=True)
            result['peak_high_water_bytes'] = peak
            result['headroom_bytes'] = REDUCED_CAPACITY - peak
            result['completed_selections'] = len(result['patterns'])
        finally:
            (work / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
            (work / 'panel-inputs.json').write_text(json.dumps(s.inputs, indent=2) + '\n')
            s.close()
    print(json.dumps({k: v for k, v in result.items() if k != 'patterns'}, indent=2))


if __name__ == '__main__':
    main()
