#!/usr/bin/env python3
"""Build an emulator-only Samples 1.13 retrig/master-FX payload and native UI.

No vendor firmware is patched, packaged, or transmitted. Shared DSP and UI
helpers are extracted from their existing source rather than forked. Cold boot
is not implemented. See docs/SAMPLES_EMULATOR.md for the interactive launcher.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Development scratch address ONLY. It is not reserved by any hardware builder.
PAYLOAD_BASE = 0x47000000
HISTORY_BASE = 0x4DEDD4E0
ADDRESS_MAP = {
    0x40A78840: 0x40968150,  # sequencer step
    0x40A7883C: 0x4096814C,  # playing
    0x40A78628: 0x40967F38,  # sequencer time at step start
    0x40149310: 0x4014555C,  # tempo, 1/120 BPM
    0x8000184C: 0x80001B3C,  # audio clock
    0x80001858: 0x80001B48,  # six track channels, 128 bytes each
    0x8000B990: 0x8000C690,  # interleaved mixed stereo bus
    0x400565C6: 0x4005556A,  # output x4
}


def section(text, start, end):
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"shared-source boundary changed: {start!r} / {end!r}")
    return text.split(start, 1)[1].split(end, 1)[0]


def shared_source(text):
    # This part is DSP-only; native UI helpers are extracted separately below.
    dsp = "rtg_want:\n" + section(text, "\nrtg_want:\n", "\nrtg_render:\n")
    # End at the actual final state field; don't depend on surrounding sections.
    start = text.index("\nrtg_names:")
    end = text.index("\nrtg_env:", start)
    state = text[start:end] + "\n" + text[end + 1:].split("\n", 1)[0] + "\n"
    # Names referenced by rtg_names, but no text renderer.
    names = section(text, "\nrtg_s_mode:", "\nrtg_names:")
    state = "rtg_s_mode:" + names + state
    decimal = "sys_dec:\n" + section(text, "\nsys_dec:\n", "\n| sys_tick:")
    # The real UI uses the stock knob-event acceleration function. In this
    # development payload d0 already carries a signed delta from the mailbox.
    entry = """mfx_knob:
    pea     4                     | clicks: 1 each slowly, 4 turned fast
    pea     1
    movel   %d2,%sp@-
    jsr     0x4006f73a
    lea.l   %sp@(12),%sp
"""
    if dsp.count(entry) != 1:
        raise ValueError("shared knob entry changed")
    dsp = dsp.replace(entry, "mfx_knob:\n")
    combined = dsp + '\n' + state + '\n' + decimal
    # Only executable statements are rewritten; preserve original comments as
    # provenance, and reject unknown absolute runtime dependencies below.
    lines = []
    for line in combined.splitlines():
        code, sep, comment = line.partition("|")
        def relocate(match):
            value = int(match.group(), 16)
            return f"0x{ADDRESS_MAP[value]:08x}" if value in ADDRESS_MAP else match.group()
        code = re.sub(r"0x[0-9a-fA-F]{8}\b", relocate, code)
        for match in re.finditer(r"0x[0-9a-fA-F]{8}\b", code):
            value = int(match.group(), 16)
            if (0x40000000 <= value < 0x48000000 or
                    0x80000000 <= value < 0x80010000):
                if value not in ADDRESS_MAP.values():
                    raise ValueError(f"unmapped runtime dependency: {match.group()}")
        lines.append(code + (sep + comment if sep else ""))
    return "\n".join(lines) + "\n"


def ui_source(text):
    """Reuse renderer, momentary/latch key state machine and pad selection."""
    render = 'rtg_render:\n' + section(text, '\nrtg_render:\n', '\nrtg_s_mode:')
    helpers = 'sys_left:\n' + section(text, '\nsys_left:\n', '\n| sys_bar')
    zero = 'rtg_zero:\n' + section(text, '\nrtg_zero:\n', '\n| rtg_topnow')
    pads = 'pad_hook:\n' + section(text, '\npad_hook:\n', '\n| rtg_zero')
    pads = pads.replace('movel   %d1,rtg_sel', 'movel   %d1,rtg_sel\n    bsr     sp_redraw')
    keys = 'kh_rtg:\n' + section(text, '\nkh_rtg:\n', '\n    | ---- Settings + a trig key:')
    keys = keys.replace('krn_out:\n    rts', 'krn_out:\n    bra     sp_page_other')
    # Redraw after step press/release, not merely after an FX knob turn.
    keys = keys.replace('    moveq   #0,%d0\n    rts',
                        '    bsr     sp_redraw\n    moveq   #0,%d0\n    rts')
    relocations = {0x40070DEA: 0x4006FE4A, 0x40071A04: 0x40070A64,
                   0x401001D0: 0x400FBB74, 0x4001D188: 0x4001E8E0}
    result = []
    for line in (render + helpers + zero + pads + keys).splitlines():
        code, sep, comment = line.partition('|')
        code = code.replace('0x40124b58', 'sp_fmt_s')
        for old, new in relocations.items():
            code = code.replace(f'0x{old:08x}', f'0x{new:08x}')
        result.append(code + (sep + comment if sep else ''))
    return ('SYS_FONT = 0x40c70c18\nKEY_SETTINGS = 13\nKEY_PATTERN = 3\n'
            'KEY_RETRIG = 4\n' + '\n'.join(result) + '\n')


def build(output, cross=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cross = cross or os.environ.get("CROSS") or next(
        (c for c in ("m68k-elf-", "m68k-linux-gnu-") if shutil.which(c + "as")),
        "m68k-elf-")
    shared = (ROOT / "src/model_tg.s").read_text()
    glue = (ROOT / "src/samples_fx_glue.s").read_text()
    ui = (ROOT / "src/samples_fx_ui.s").read_text()
    constants = f"""
RTG_N = 131072
RTG_MASK = RTG_N-1
RTG_NS = 16
RTG_R = 32
RTG_REDRAW = 150
RTG_STEP = 1024
RTG_QN = 21600000
RTG_BASE = 0x{HISTORY_BASE:08x}
"""
    assembly = output / "samples_fx.s"
    assembly.write_text(glue + ui + constants + shared_source(shared) + ui_source(shared))
    obj, elf, binary = (output / f"samples_fx.{ext}" for ext in ("o", "elf", "bin"))
    subprocess.run([cross + "as", "-march=cfv4e", "-o", str(obj), str(assembly)], check=True)
    subprocess.run([cross + "ld", f"-Ttext=0x{PAYLOAD_BASE:x}", "-e", "samples_audio",
                    "-o", str(elf), str(obj)], check=True)
    subprocess.run([cross + "objcopy", "-O", "binary", str(elf), str(binary)], check=True)
    syms = {}
    for line in subprocess.check_output([cross + "nm", "-n", str(elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1].lower() in ("t", "d", "b"):
            syms[fields[2]] = int(fields[0], 16)
    payload = binary.read_bytes()
    if len(payload) >= 0x10000:
        raise ValueError("development payload exceeds scratch budget")
    report = {
        "format": "samples-fx-emulator-v1", "hardware_installable": False,
        "native_panel_ui": True,
        "payload_base": PAYLOAD_BASE, "history_base": HISTORY_BASE,
        "history_bytes": 0x400000, "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "shared_source_sha256": hashlib.sha256(shared.encode()).hexdigest(),
        "symbols": syms,
    }
    (output / "samples_fx.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Emulator-only DSP/UI: {len(payload):,} bytes at 0x{PAYLOAD_BASE:08x}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(ROOT / "build/samples-fx"))
    args = ap.parse_args()
    build(args.out_dir)
