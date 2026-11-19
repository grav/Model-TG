#!/usr/bin/env python3
"""Build an experimental standalone Model:Samples 1.13 .syx for DigiEmu.

Uses your stock .syx (or Elektron's .zip); never communicates with a device.
Not hardware-validated. Do not flash this experimental image to real hardware.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

from build_samples_fx import ROOT, HISTORY_BASE, build
from map_samples_fx import BASE, HASHES, CAPACITY_SITES, SAMPLE_POOL_CAPACITY, HISTORY_BYTES, audit_samples_pool

STOCK_END = 0x401A7640
BSS_START, BSS_END = 0x401A05A0, 0x4211F510
ZERO_BASE, CACHE_BASE, CACHE_ENTRY = 0x401AC760, 0x401B0760, 0x401F0760
CACHE_BLOCK = 0x4000
# Complete instruction windows; every replacement is checked before any write.
HOOKS = (
    (0x400004B2, '4feffff048d700f0', 'samples_boot_clear', 'jmp', 1),
    (0x40058892, '4eb94005575e', 'samples_audio', 'jsr', 0),
    (0x400555B4, '4fefffd848d73cfc', 'samples_mix', 'jmp', 1),
    (0x40055ADC, '4878000448798000c6904ebafa82', 'mfx_master', 'master', 3),
    (0x4007146C, '206f00042028000c4e75', 'samples_key', 'jmp', 2),
    (0x4001E8D8, '4e56ffbc48d73cfc', 'pad_hook', 'jmp', 1),
    (0x40001154, '2208d2804ab9404acb14', 'gate_tx_buffer', 'jmp', 2),
    (0x4000124E, '4ab9404acb14', 'gate_tx_byte', 'jmp', 0),
    (0x40001320, '1039ec074004', 'gate_flush_status', 'jmp', 0),
    (0x4003402A, '4cef7c7c0018', 'samples_gate_config', 'jmp', 0),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patches(report):
    result = []
    symbols = report['symbols']
    for address, old, label, kind, nops in HOOKS:
        target = symbols[label]
        if target & 1 or not CACHE_BASE <= target < CACHE_BASE + report['payload_bytes']:
            raise ValueError(f'invalid hook target: {label}')
        new = bytes.fromhex('4ef9' if kind == 'jmp' else '4eb9') + struct.pack('>I', target)
        if kind == 'master':
            new += bytes.fromhex('518f')  # original caller's addq #8 stack contract
        new += bytes.fromhex('4e71') * nops
        result.append((address, bytes.fromhex(old), new))
    capacity = SAMPLE_POOL_CAPACITY - HISTORY_BYTES
    for address, opcode, _ in CAPACITY_SITES:
        result.append((address, struct.pack('>HI', opcode, SAMPLE_POOL_CAPACITY),
                       struct.pack('>HI', opcode, capacity)))
    # Retire block zero from the LRU. All 16 valid flags are still cleared.
    # The forward-link loop is unchanged; entry 1's prev link remains NULL.
    result += [
        (0x4007831A, bytes.fromhex('203c401f0784'),
         bytes.fromhex('203c') + struct.pack('>I', CACHE_ENTRY + 20 * 2 + 16)),
        (0x40078350, bytes.fromhex('41f9401f0760'),
         bytes.fromhex('41f9') + struct.pack('>I', CACHE_ENTRY + 20)),
    ]
    return result


def validate_payload(report, payload):
    if (not report.get('cold_boot') or report['payload_base'] != CACHE_BASE or
            report['history_base'] != HISTORY_BASE or report['history_bytes'] != HISTORY_BYTES):
        raise ValueError('payload does not use the Samples cold-boot reservation')
    if (digest(payload) != report['payload_sha256'] or
            len(payload) != report['payload_bytes'] or len(payload) % 16 or
            not 0 < len(payload) <= CACHE_BLOCK):
        raise ValueError('payload digest, alignment or one-cache-block budget mismatch')
    if (report['symbols']['samples_payload_start'] != CACHE_BASE or
            report['symbols']['samples_payload_end'] != CACHE_BASE + len(payload)):
        raise ValueError('payload boundary symbols disagree with image')


def patch_main(stock, report, payload):
    if digest(stock) != HASHES['samples'] or BASE + len(stock) != STOCK_END:
        raise ValueError('requires the supported unmodified Samples 1.13 MAIN OS')
    audit_samples_pool(stock)
    validate_payload(report, payload)
    edits = patches(report)
    previous = BASE
    for address, old, new in sorted(edits):
        if len(old) != len(new) or address < previous or address + len(old) > STOCK_END:
            raise ValueError('overlapping or invalid firmware patch')
        if stock[address - BASE:address - BASE + len(old)] != old:
            raise ValueError(f'stock instruction mismatch at {address:08x}')
        previous = address + len(old)
    image = bytearray(stock) + bytearray(CACHE_BASE - STOCK_END) + payload
    for address, old, new in edits:
        image[address - BASE:address - BASE + len(old)] = new
    if any(image[ZERO_BASE - BASE:CACHE_BASE - BASE]):
        raise ValueError('filesystem chunk-blanking buffer must stay zero')
    return bytes(image), [dict(address=hex(a), old=o.hex(), new=n.hex()) for a, o, n in edits]


def build_firmware(stock_path, output, work, tool):
    stock_path, output, work = map(lambda p: Path(p).resolve(), (stock_path, output, work))
    if output.exists() or work.exists():
        raise ValueError('refusing to overwrite an output or work directory')
    work.mkdir(parents=True)
    if zipfile.is_zipfile(stock_path):
        with zipfile.ZipFile(stock_path) as archive:
            names = [n for n in archive.namelist() if Path(n).name == 'model-samples_OS1.13.syx']
            if len(names) != 1:
                raise ValueError('archive must contain exactly one stock Samples 1.13 .syx')
            source = work / 'stock.syx'
            with archive.open(names[0]) as src, source.open('xb') as dst:
                shutil.copyfileobj(src, dst)
    else:
        source = work / 'stock.syx'
        shutil.copyfile(stock_path, source)
    if not source.read_bytes().startswith(bytes.fromhex('f000203c0f')):
        raise ValueError('input is not a Model:Samples SysEx container (device 0x0f)')
    tool = str(Path(tool).resolve()) if Path(tool).exists() else tool
    def invoke(*args):
        subprocess.run([tool, *map(str, args)], check=True)
    invoke('-i', source, '-o', work / 'stock')
    stock = (work / 'stock/section_3_MAIN_OS.bin').read_bytes()
    # Fail before assembly if this is not the exact supported Samples release.
    if digest(stock) != HASHES['samples']:
        raise ValueError('not the supported unmodified Samples 1.13 MAIN OS')
    report = build(work / 'payload', payload_base=CACHE_BASE, cold_boot=True)
    payload = (work / 'payload/samples_fx.bin').read_bytes()
    image, edits = patch_main(stock, report, payload)
    main = work / 'Model-TG-Samples-MAIN.bin'
    main.write_bytes(image)
    candidate = work / 'candidate.syx'
    invoke('-i', source, '-c', 3, main, '-o', candidate)
    invoke('-i', candidate)  # validate all container/transport checksums
    invoke('-i', candidate, '-o', work / 'roundtrip')
    originals = {p.name: p.read_bytes() for p in (work / 'stock').glob('section_*') if p.is_file()}
    actual = {p.name: p.read_bytes() for p in (work / 'roundtrip').glob('section_*') if p.is_file()}
    expected = {**originals, 'section_3_MAIN_OS.bin': image}
    if actual != expected:
        raise ValueError('container round-trip differs or a non-MAIN section changed')
    if not candidate.read_bytes().startswith(bytes.fromhex('f000203c0f')):
        raise ValueError('output lost the Samples transport identity')
    summary = {
        'format': 'samples-firmware-experimental-v1', 'device': 'Model:Samples',
        'os': '1.13', 'hardware_validated': False, 'emulator_validated': False,
        'warning': 'Experimental. Validate in DigiEmu. Do not flash physical hardware.',
        'syx': str(output), 'syx_sha256': digest(candidate.read_bytes()),
        'main_sha256': digest(image), 'main_bytes': len(image),
        'payload_base': CACHE_BASE, 'payload_end': CACHE_BASE + len(payload),
        'retired_cache_blocks': 1, 'remaining_cache_blocks': 15,
        'bss_start': BSS_START, 'bss_end': BSS_END,
        'history_base': HISTORY_BASE, 'history_bytes': HISTORY_BYTES,
        'patches': edits, 'unchanged_sections': sorted(set(originals) - {'section_3_MAIN_OS.bin'}),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as dst, candidate.open('rb') as src:
        shutil.copyfileobj(src, dst)
    (work / 'firmware-build.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(f'Wrote EXPERIMENTAL Samples firmware: {output}\nSHA-256: {summary["syx_sha256"]}')
    print('Container round-trip passed. This is NOT a hardware-safety verdict.')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock', required=True, help='stock Samples 1.13 .syx or .zip')
    parser.add_argument('--out', default=str(ROOT / 'build/Model-TG-Samples-experimental.syx'))
    parser.add_argument('--work', default=str(ROOT / 'build' / ('samples-firmware-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))))
    parser.add_argument('--tool', default=os.environ.get('ELEKTRON_FIRMWARE_TOOL', 'elektron-firmware-tool'))
    args = parser.parse_args()
    build_firmware(args.stock, args.out, args.work, args.tool)


if __name__ == '__main__':
    main()
