# Model:Samples 1.13: retrig and master FX port investigation

## Status: not installable

This is groundwork for porting **only** the output retrig and master FX in
[the user guide](../USER_GUIDE.md#retrig-and-master-fx), keeping the stock
Model:Samples sampler and project format. There is no Samples payload or
firmware builder yet. The existing `build.py` and `Model-TG.syx` target
**Cycles only**. Do not install them on Samples or bypass their stock hash
checks. No device communication is needed for this investigation.

## Images examined

Both are unmodified, decompressed section 3, loaded at `0x40000400`:

| OS 1.13 | MAIN OS bytes | End (exclusive) | SHA-256 |
|---|---:|---|---|
| Cycles | 1,744,192 | `0x401aa140` | `cc99d4f0175d34d1e91d046e6ec85a5e8ab58ab9edbb3c24406acd48cb99ee98` |
| Samples | 1,733,184 | `0x401a7640` | `a351392c62ec1c6c3324a807baf46934690d54edfc76029a4b4882541cad1ab2` |

Samples was extracted from the supplied `model-samples_OS1.13.zip`. No
vendor firmware bytes are included in this note or the mapping tool.

## Findings

The firmware framework is shared, but there is **no single relocation
offset**. A masked byte comparison finds these candidates:

| Dependency | Cycles | Samples candidate |
|---|---|---|
| Pad event handler | `0x4001d180` | `0x4001e8d8` |
| Knob acceleration | `0x4006f73a` | `0x4006e79a` |
| Text drawing | `0x40071a04` | `0x40070a64` |
| Output scaling | `0x400565c6` | `0x4005556a` |
| Channel mixer | `0x40056610` | `0x400555b4` |
| Post-mix FX insertion | `0x40056b38` | `0x40055adc` |
| Filesystem cache initialization window | `0x400792bc` | `0x4007831c` |

Disassembly provides additional evidence for two of these paths:

- At Samples `0x40055a88..0x40055aea`, the output routine calls the mixer
  for L and R, then scales the mixed bus by four through `0x4005556a`.
  The track-channel base passed to the mixer is **`0x80001b48`**, not the
  Cycles address `0x80001858`. The interleaved stereo bus is
  **`0x8000c690`**, not `0x8000b990`. The return buffers passed through this
  path are `0x80001e48` and `0x80001ec8`. Confirm their delay/reverb identities
  and layout before adapting `rtg_fxpass`.
- Samples `0x4001e8d8` starts with the same stack-frame/save instructions
  as the Cycles pad handler. Its instruction at `0x4001e8f8` loads the pad
  map at **`0x400fbb74`**. Matching that small table alone was ambiguous;
  checking its actual caller disambiguates it.

The short key accessor, rectangle drawing function, and UI context getter
all have multiple signature matches. The root-view manager and the pre-mix
gain call window have no match with the present signatures. None of these
results authorizes a patch: a unique byte match is not a verified ABI.

The Samples boot-clear routine at `0x400004b2` clears from `0x401a05a0` to
`0x4211f510`. That is **not** Cycles' BSS layout. Simply appending the Cycles
blob, or using its boot-clear exception and filesystem-cache reservation,
is unsafe.

## Stock sample RAM allocator (follow-up investigation)

The external `model-samples-analysis/` directory provides a full disassembly
and a factory-sample backup. Its `FINDINGS.md` primarily describes **MMC
storage**, not the playback RAM allocator; the factory-content sector is not
a suitable retrig-buffer address. The following RAM findings were traced in
`main-disassembly-coldfire.txt` and checked against this note's hashed MAIN OS.

| Item | Samples 1.13 |
|---|---|
| Sample-file allocation base | `0x4a2dd490` |
| Allocation capacity constant | `0x04000050` (64 MiB + 80 bytes) |
| Allocation end, exclusive | `0x4e2dd4e0` |
| Allocation high-water counter | `0x40dbf268` |
| Freed-byte accounting | `0x40dbf264` |
| Most recent load's allocation size | `0x40dbf260` |
| Most recent load's slot ID | `0x4014f398` |

Evidence and capacity-immediate sites (addresses are **instructions**, not
immediate operands):

| Instruction | Role inferred from data flow |
|---|---|
| `0x400a12a6` | Returns capacity minus high-water counter |
| `0x400a12b4` | Returns total capacity |
| `0x400a156e` | Admission/space check using high-water and freed-byte counters |
| `0x400a15ae` | Bump allocator: checks remaining space, rounds size to 16 bytes, increments high-water, returns base + old high-water |
| `0x400a17a8` | File-load capacity check, before reading into base + high-water |

All five embed the same `0x04000050` immediate at instruction +2. These are
all word-aligned occurrences of that value in the entire MAIN OS image.
The two base-address immediates occur at instructions `0x400a15d8` and
`0x400a17de`. The file loader at `0x400a1660` reads a sample file into that
pool, then passes payload at file +64 to `0x400a637e`. Consequently this is
an allocation budget for sample **files/headers/alignment**, not just PCM.
The pool reset at `0x400a18b4` clears all three accounting counters.

A candidate full-size history reservation is:

```text
stock pool:       [0x4a2dd490, 0x4e2dd4e0)   0x04000050 bytes
reduced pool:     [0x4a2dd490, 0x4dedd4e0)   0x03c00050 bytes
retrig histories: [0x4dedd4e0, 0x4e2dd4e0)   0x00400000 bytes
```

Reducing all five capacity immediates by 4 MiB would keep those reporting and
allocation paths consistent. This is a proposed reservation, **not an applied
patch or a proof that all writers have been found**. Audit compaction, preview,
project reload, failure/rollback paths, and allocator alignment bounds before
using it. No capacity or base-address change was made to firmware.

The end is significant: stock code clears/uses a scratch buffer starting at
`0x4e2dd4e0` (`0x400a6526..0x400a6536`, 0x160 bytes), and the word staging
ring at `0x4e2dd640` is accessed by `0x400025ba`. The stock delay ring uses
`0x4e400000..0x4e800000`: `0x400561a4` clears 4 MiB there, and
`0x4005633e`/`0x4005711e` calculate masked ring positions and configure DMA.
**Do not reuse Cycles' `RTG_BASE` calculation on Samples**: its reservation
near `0x4e800000` overlaps this stock delay ring.

## What still needs implementing/verifying

1. **Memory ownership first.** Audit the allocator paths above and locate the
   filesystem cache layout. Reserve history space by reducing the allocator's
   usable range, not merely choosing an apparently empty address. Cycles uses
   16 histories of 131,072 signed 16-bit samples (4 MiB), including its custom
   stereo side streams. Samples needs its own stream-layout decision. Reserve
   payload/state memory and adapt startup clearing and cache handling too.
2. **Audio hooks and timing.** Find a once-per-block, pre-mixer hook for the
   six stock tracks; confirm 32-frame format, gain/send ordering, EMAC state,
   tempo units, audio clock, play flag, and bar-start timestamp. The existing
   `rtg_audio` directly reads Cycles globals and depends on `blk_clk`.
3. **Separate the feature from the Cycles sampler.** The retrig engine and
   master effects are mostly in `src/model_tg.s:11954..14215`, but are not a
   standalone module. `sx_gain`/`sx_mix` integrate them into the audio path;
   they also use the machine-menu view, key/knob/pad handlers, LEDs, pattern
   state, and shared helpers. Do not pull in the added sampler machines,
   transfer-identity spoofing, or Cycles-specific optimizations.
4. **UI integration.** Resolve the ambiguous signatures from callers; port
   the Settings+Retrig chord, momentary/latch keys, track pads/LEDs, the two
   DATA rows, all twelve FX knobs, page lifecycle, and Settings+Return reset.
   Preserve stock Samples behavior outside this page.
5. **Samples-only builder.** Require the Samples hash above, assert every
   replaced stock byte, retain the Samples update container/identity, validate
   branch/stack/memory bounds, and round-trip unpack/repack. Do not add a
   force option to the Cycles builder.
6. **Hardware validation, after explicit installation approval and backups.**
   Start with a feature-disabled boot, then bypassed audio, UI, histories,
   repeat, and individual FX. Check maximum sample occupancy, sample loading
   while playing, all six tracks, sends, tempo changes, transport, pattern
   changes, USB/Transfer, and worst-case CPU load. An assembly or signature
   check cannot establish that an image is safe to install.

## Reproduce the candidate map offline

Use `elektron-firmware-tool` as documented in [BUILD.md](../BUILD.md).
Unpack into **separate directories** so Samples cannot overwrite the Cycles
stock file used by `build.py`:

```sh
mkdir -p build/model-samples/stock
unzip -p /path/to/model-samples_OS1.13.zip model-samples_OS1.13.syx \
  > build/model-samples/model-samples_OS1.13.syx
elektron-firmware-tool -i build/model-samples/model-samples_OS1.13.syx \
  -d 3 -o build/model-samples/stock
# Assuming the unmodified Cycles image is already unpacked in build/stock:
python3 tools/map_samples_fx.py \
  --cycles build/stock/section_3_MAIN_OS.bin \
  --samples build/model-samples/stock/section_3_MAIN_OS.bin
python3 -m unittest discover -s tools -p 'test_map_samples_fx.py'
```

The tool checks both input hashes and prints candidates only. It heuristically
masks word-aligned image/RAM pointers and PC-relative jsr/jmp operands;
it is not an instruction decoder. It can miss counterparts or match unrelated
code. It never writes firmware, generates patches, accesses MIDI, or sends
anything to a device.
