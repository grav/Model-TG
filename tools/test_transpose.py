#!/usr/bin/env python3
"""Execute assembled transpose code on Unicorn ColdFire with mocked stock APIs.

Run `python3 build.py --assemble-only`, then run this with `unicorn` installed.
No Elektron firmware is needed. Stock UI event delivery/timers require hardware.
"""
import struct
import subprocess
from pathlib import Path
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn.m68k_const import *

ROOT = Path(__file__).resolve().parents[1]
symbols = {}
for line in subprocess.check_output(['m68k-elf-nm', str(ROOT/'build/_b.elf')], text=True).splitlines():
    parts = line.split()
    if len(parts) == 3:
        symbols[parts[2]] = int(parts[0], 16)
u = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
u.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
u.mem_map(0x40000000, 0x200000)
u.mem_map(0x100000, 0x200000)
u.mem_write(0x401ab750, (ROOT/'build/_b.bin').read_bytes())
KEY_EVENT = 0x117000
VIEW, EVENT, VTABLE, NODE = 0x110000, 0x111000, 0x112000, 0x150000
STACK, STOP, RAW_GET = 0x2ff000, 0x100000, 0x40001000
tracks = [0x120000 + i*0x1000 for i in range(6)]
lengths = [1, 8, 16, 32, 48, 64]
selected, all_tracks, delta = 3, False, 0
entries, next_nodes = {}, {}
writes = []

def put(addr, value):
    u.mem_write(addr, struct.pack('>I', value & 0xffffffff))

def get(addr):
    return struct.unpack('>I', u.mem_read(addr, 4))[0]

def arg(n):
    return get(u.reg_read(UC_M68K_REG_A7) + 4*n)

def tree():
    keys = sorted(entries)
    nodes = [NODE + key*24 for key in keys]
    sentinel = VIEW + 0x218
    put(VIEW+0x220, nodes[0] if nodes else sentinel)
    put(VIEW+0x228, len(keys))
    next_nodes.clear()
    for i, (key, node) in enumerate(zip(keys, nodes)):
        put(node+16, key)
        put(node+20, entries[key])
        next_nodes[node] = nodes[i+1] if i+1 < len(nodes) else sentinel

def clear():
    entries.clear()
    tree()

def insert():
    assert arg(1) == VIEW+0x214
    pair = arg(2)
    entries.setdefault(get(pair), get(pair+4))
    tree()
    return NODE+get(pair)*24

def setter():
    track, step, note = tracks.index(arg(1)), arg(2), arg(3)
    assert 0 <= step < 64 and (note == 0xffffffff or note <= 127)
    u.mem_write(tracks[track]+0x100+580+step, bytes([note & 255]))
    writes.append((track, step, note))

def cleanup():
    clear()
    put(VIEW+0x230, 0)

hooks = {
    symbols['gm_live']: lambda: 0,
    0x4006f73a: lambda: delta,
    0x400cf866: lambda: 0x113000,
    0x4000eb90: lambda: 0x114000,
    0x40012412: lambda: selected,
    0x4007faf4: lambda: 0,  # scan snapshot deliberately disagrees with key events
    0x400cf9a8: lambda: 0x115000,
    0x4006b71c: lambda: None,
    0x4001eecc: clear,
    0x4001ef0e: cleanup,
    0x4001ddb2: lambda: None,
    0x40077946: lambda: None,
    0x40076082: lambda: None,
    0x4000f208: lambda: 0x116000,
    0x4000cfcc: lambda: tracks[arg(2)],
    0x40016402: lambda: lengths[tracks.index(arg(1))],
    RAW_GET: lambda: arg(1)+0x100,
    0x400d8956: insert,
    0x40016642: setter,
    0x400f5c04: lambda: next_nodes[arg(1)],
    0x4001f4f0: lambda: None,
}

def intercept(uc, addr, size, data):
    if addr not in hooks:
        return
    result = hooks[addr]()
    sp = uc.reg_read(UC_M68K_REG_A7)
    uc.reg_write(UC_M68K_REG_D0, (result or 0) & 0xffffffff)
    for reg in (UC_M68K_REG_D1, UC_M68K_REG_A0, UC_M68K_REG_A1):
        uc.reg_write(reg, 0xdeadbeef)
    uc.reg_write(UC_M68K_REG_PC, get(sp))
    uc.reg_write(UC_M68K_REG_A7, sp+4)

u.hook_add(UC_HOOK_CODE, intercept)

def call(name, *args):
    preserved = [UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4,
                 UC_M68K_REG_D5, UC_M68K_REG_D6, UC_M68K_REG_D7,
                 UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4,
                 UC_M68K_REG_A5, UC_M68K_REG_A6]
    for i, reg in enumerate(preserved):
        u.reg_write(reg, 0x123400+i)
    u.reg_write(UC_M68K_REG_A7, STACK)
    put(STACK, STOP)
    for i, value in enumerate(args, 1):
        put(STACK+4*i, value)
    u.emu_start(symbols[name], STOP, count=1000000)
    assert u.reg_read(UC_M68K_REG_PC) == STOP, name
    assert u.reg_read(UC_M68K_REG_A7) == STACK+4, 'stack imbalance'
    for i, reg in enumerate(preserved):
        assert u.reg_read(reg) == 0x123400+i, ('callee-saved register', reg)

put(VTABLE+40, RAW_GET)
for i, track in enumerate(tracks):
    put(track, VTABLE)
    raw = bytearray(722)
    raw[712] = 50+i
    for step in range(64):
        raw[2*step+1] = int(step % 3 != 1)  # empty steps interspersed
        raw[580+step] = [255, 60, 0, 127, 120, 3][step % 6]
    u.mem_write(track+0x100, bytes(raw))
original = [bytes(u.mem_read(t+0x100, 722)) for t in tracks]
expected = [bytearray(b) for b in original]
clear()
put(EVENT+12, 2)
def key(code, flags):
    put(KEY_EVENT+12, code)
    put(KEY_EVENT+16, flags)
    call('key_hook', KEY_EVENT)
    assert u.reg_read(UC_M68K_REG_D0) == code

# Both press orders, repeated accessor reads, repeat events, independent releases.
for first, second in [(2, 4), (4, 2)]:
    key(first, 1)
    key(first, 1)
    key(second, 1)
    key(second, 9)
    assert get(symbols['transpose_held']) == 1
    assert get(symbols['transpose_track_held']) == 1
    key(2, 16)
    assert get(symbols['transpose_held']) == 1
    assert get(symbols['transpose_track_held']) == 0
    key(4, 16)
    assert get(symbols['transpose_held']) == 0
key(4, 1)

def turn(amount, scope):
    global delta, all_tracks
    delta, all_tracks = amount, scope
    key(2, 1 if scope else 16)
    for i in range(6) if scope else [selected]:
        for step in range(lengths[i]):
            if expected[i][step*2+1] & 1:
                old = expected[i][580+step]
                value = expected[i][712] if old == 255 else old
                new = max(0, min(127, value+amount))
                if new != value:
                    expected[i][580+step] = new
    call('transpose_enc', VIEW, EVENT)
    assert [bytes(u.mem_read(t+0x100, 722)) for t in tracks] == expected
    assert get(VIEW+0x238) == 60

turn(12, False)
turn(12, True)
turn(-5, True)
turn(-120, False)
assert get(symbols['transpose_all']) == 0
assert get(symbols['transpose_delta']) == ((-120) & 0xffffffff)
assert {k//64 for k in entries} == set(range(6))
call('transpose_restore', VIEW)
assert [bytes(u.mem_read(t+0x100, 722)) for t in tracks] == original
# Stock BACK clears changed flag; another turn retains the first baseline.
u.mem_write(VIEW+0x23d, b'\0')
expected = [bytearray(b) for b in original]
turn(-12, True)
call('transpose_restore', VIEW)
assert [bytes(u.mem_read(t+0x100, 722)) for t in tracks] == original
# A non-transpose dial must discard encoded keys before stock sees the view.
put(EVENT+12, 3)
call('transpose_enc_th', VIEW+4, EVENT)
assert not entries and get(symbols['transpose_view']) == 0
assert get(VIEW+0x230) == 0
print('PASS: assembled ColdFire single/all/mixed transpose, per-track lengths,')
print('empty steps, clipping, inherited notes, exact repeated restore, ABI and stack')
print('PASS: both modifier press orders, repeats/releases, stale scan snapshot')
