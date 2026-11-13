#!/usr/bin/env python3
"""Offline porting aid, NOT a firmware builder or a verified relocation map.

Compare unpacked, unmodified Cycles/Samples 1.13 MAIN OS sections. Only
candidate addresses and hashes are printed; nothing is patched or transmitted.
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct

BASE = 0x40000400
HASHES = {
    "cycles": "cc99d4f0175d34d1e91d046e6ec85a5e8ab58ab9edbb3c24406acd48cb99ee98",
    "samples": "a351392c62ec1c6c3324a807baf46934690d54edfc76029a4b4882541cad1ab2",
}
# Samples allocator facts traced from the stock loader, not signature matches.
SAMPLE_POOL_BASE = 0x4A2DD490
SAMPLE_POOL_CAPACITY = 0x04000050
HISTORY_BYTES = 16 * 131072 * 2
CAPACITY_SITES = (
    (0x400A12A6, 0x203C, "remaining capacity"),
    (0x400A12B4, 0x203C, "total capacity"),
    (0x400A156E, 0x223C, "admission check"),
    (0x400A15AE, 0x207C, "bump allocator"),
    (0x400A17A8, 0x247C, "sample-file load check"),
)
POOL_BASE_SITES = ((0x400A15D8, 0x0680), (0x400A17DE, 0xD5FC))

# Cycles addresses, from build.py and src/model_tg.s. Deliberately keep the
# audio entry points separate from the short UI accessor (which is not unique).
ANCHORS = (
    ("boot BSS clear", 0x400004B2, 48),
    ("key-code accessor", 0x4007240C, 10),
    ("pad-event method", 0x4001D180, 64),
    ("pad-to-track map (data)", 0x401001D0, 28),
    ("knob acceleration", 0x4006F73A, 64),
    ("rectangle drawing", 0x40070DEA, 64),
    ("text drawing", 0x40071A04, 64),
    ("root view manager", 0x400060D8, 64),
    ("UI context getter", 0x400D0974, 48),
    ("output scaling", 0x400565C6, 64),
    ("channel mixer", 0x40056610, 64),
    ("mixed-bus FX hook site", 0x40056B38, 32),
    ("pre-mix gain hook site", 0x4005982A, 48),
    ("filesystem cache init", 0x400792BC, 64),
)


def signature(data, address, size):
    """Heuristic byte signature with likely relocations masked.

    This is deliberately NOT a decoder. Word-aligned RAM/image pointers and
    PC-relative jsr/jmp operands are ignored. Branch offsets, register usage,
    stack offsets and non-address constants remain significant. Consequently
    both false negatives and false positives are possible. A unique hit is
    still only a candidate, never permission to patch firmware.
    """
    start = address - BASE
    if start < 0 or start + size > len(data):
        raise ValueError("signature is outside the image")
    window = data[start:start + size]
    mask = bytearray(b"\xff" * size)
    for i in range(0, size - 3, 2):
        value = struct.unpack_from(">I", window, i)[0]
        if (0x40000000 <= value < 0x48000000 or
                0x80000000 <= value < 0x80010000):
            mask[i:i + 4] = b"\0" * 4
        if window[i:i + 2] in (b"\x4e\xba", b"\x4e\xfa"):
            mask[i + 2:i + 4] = b"\0" * 2
    return window, bytes(mask)


def candidates(data, window, mask):
    pattern = b"".join(re.escape(bytes([b])) if m else b"."
                       for b, m in zip(window, mask))
    # Lookahead includes overlapping matches; firmware instructions are aligned.
    return [BASE + m.start() for m in re.finditer(b"(?=" + pattern + b")", data,
                                                re.DOTALL) if m.start() % 2 == 0]


def load_stock(path, model):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != HASHES[model]:
        raise ValueError(f"{path}: not the supported unmodified {model} 1.13 "
                         f"MAIN OS (sha256 {digest})")
    return data


def audit_samples_pool(data):
    """Check known allocator instructions and account for capacity literals.

    These checks establish reproducible static facts, not memory safety of a
    future reservation. In particular, they do not find computed addresses or
    prove that compaction/preview/rollback respect a reduced capacity.
    """
    for address, opcode, _ in CAPACITY_SITES:
        expected = struct.pack(">HI", opcode, SAMPLE_POOL_CAPACITY)
        if data[address - BASE:address - BASE + 6] != expected:
            raise ValueError(f"sample capacity instruction changed at 0x{address:08x}")
    for address, opcode in POOL_BASE_SITES:
        expected = struct.pack(">HI", opcode, SAMPLE_POOL_BASE)
        if data[address - BASE:address - BASE + 6] != expected:
            raise ValueError(f"sample base instruction changed at 0x{address:08x}")
    literal = struct.pack(">I", SAMPLE_POOL_CAPACITY)
    found = {BASE + match.start() for match in
             re.finditer(b"(?=" + re.escape(literal) + b")", data)
             if match.start() % 2 == 0}
    if found != {address + 2 for address, _, _ in CAPACITY_SITES}:
        raise ValueError("unaccounted sample capacity literal(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", required=True, help="unpacked Cycles MAIN OS .bin")
    parser.add_argument("--samples", required=True, help="unpacked Samples MAIN OS .bin")
    args = parser.parse_args()
    try:
        cycles = load_stock(args.cycles, "cycles")
        samples = load_stock(args.samples, "samples")
        audit_samples_pool(samples)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("# Samples 1.13 retrig/FX port: candidate address report\n")
    print("NOT a verified map. No image generated; no device access.\n")
    for model, data in (("cycles", cycles), ("samples", samples)):
        print(f"{model}: {len(data)} bytes, end 0x{BASE + len(data):08x}, "
              f"sha256 {hashlib.sha256(data).hexdigest()}")
    print("\n| Dependency | Cycles | Samples candidates | Fixed bytes |")
    print("|---|---|---|---|")
    for name, address, size in ANCHORS:
        window, mask = signature(cycles, address, size)
        hits = candidates(samples, window, mask)
        result = ", ".join(f"0x{hit:08x}" for hit in hits[:8]) or "no match"
        if len(hits) > 8:
            result += f", … ({len(hits)} total)"
        print(f"| {name} | 0x{address:08x} | {result} | {sum(bool(m) for m in mask)}/{size} |")
    print("\n## Stock Samples RAM allocator (instruction/literal checks passed)\n")
    end = SAMPLE_POOL_BASE + SAMPLE_POOL_CAPACITY
    print(f"Sample-file pool: [0x{SAMPLE_POOL_BASE:08x}, 0x{end:08x})")
    print(f"Capacity: 0x{SAMPLE_POOL_CAPACITY:08x} bytes; five immediate sites:")
    for address, _, role in CAPACITY_SITES:
        print(f"- 0x{address:08x}: {role}")
    print(f"Proposed {HISTORY_BYTES // (1024 * 1024)} MiB history reservation: "
          f"[0x{end - HISTORY_BYTES:08x}, 0x{end:08x})")
    print(f"Proposed reduced capacity: 0x{SAMPLE_POOL_CAPACITY - HISTORY_BYTES:08x}")
    print("NOT applied or safety-verified; compaction and other writers need auditing.")
    print("\nVerify candidates by disassembly and independent caller/data-flow checks.")
    print("No match does not mean the counterpart is absent. Do not relocate by offset.")


if __name__ == "__main__":
    main()
