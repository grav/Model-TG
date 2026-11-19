# Experimental Model:Samples MIDI OUT gate clock (OS 1.13)

Standalone port of [Model-TG PR #27](https://github.com/TinyGregAudio/Model-TG/pull/27),
head `5161f21ac5a03ff9e4c7d3dbfc06f7553654e3a5`, on the `model-samples` base.
This branch does **not** include PR #22 / FUNC FX snapping. The unchanged UART
core lives in `src/midi_gate.inc`; the Samples builder relocates its runtime
addresses and extracts existing menu closures. It does not alter the Cycles
builder or turn on the feature for Cycles.

Controllable TXD does not establish a usable voltage at the jack. Electrical
levels, polarity, loading and suitability for CV remain unmeasured.

UART9 is at `0xEC074000`. Byte commands to UCR9 (`+8`) enable TX (`0x04`),
start BREAK (`0x60`) and stop BREAK (`0x70`). Start requires TX enabled and
can wait one bit time on an empty transmitter; stop releases TXD within two
bit times. At MIDI baud, these bounds are 32 and 64 microseconds. See
[NXP MCF54418RM, §41.3.5, table 41-8](https://www.nxp.com/docs/en/reference-manual/MCF54418RM.pdf).

Gate clock uses the Samples stock MIDI clock sender, requiring CLK OUT on,
OUT TO MID/M+U and OUT/THRU OUT. No extra tempo oscillator is introduced. The
stock polarity GPIO (PF3) is left alone.

## Ownership and hooks

| Address | Role |
|---|---|
| `0x40001154` | Buffered TX, after saving SR and raising IPL7: suppress new data while requested/active |
| `0x4000124E` | Byte TX, also inside IPL7: consume real-time clock/transport and suppress physical MIDI |
| `0x40001320` | Flush's UART-status read: report empty while gate owns an already drained transmitter |
| `0x404ACB14` | Stock transmit state (idle/DMA/byte queue) |
| `0x404ACB30` / `0x404ACB40` | Pending buffer/byte counts |
| `0xFC0454BE` | TX DMA37 CSR; ACTIVE bit 6 |
| `0xEC074004` | UART status; TXEMP bit 3 includes FIFO and shift register |

`gate_mode` is the menu request; `gate_active` is the mode that owns TX.
Checks in the producer critical sections prevent a task preempted before
enqueue from writing after the mode changes. Both software queues keep
draining through the unmodified UART/DMA interrupts. Once the driver and
queues are idle, DMA is inactive and the UART is empty, `gate_service`
claims TX under IPL7. It disables DMA37 requests, acknowledges any stale
DMA37 completion, and masks UART interrupt source 53 (as stock does at idle).
RX DMA36 is untouched. There is no busy-wait in the audio path.

Restoring MIDI stops BREAK before clearing ownership. Nothing has entered
the FIFO while gate owns it. The next stock send can directly write a byte
or start DMA as usual; byte-queue interrupts are unmasked by the stock writer
when necessary. Buffered messages and non-clock real-time bytes are discarded
during gate mode, not queued for playback later. USB routing occurs above
these physical-port hooks and is unchanged.

Clock mode holds BREAK between pulses and releases it at the clock tick.
This puts the TXD rising edge at pulse start instead of about 5 ms later.
Start (FA) emits pulse zero immediately while playback is active and reloads
the divider. The next edge is on the divisor-th F8. Previously Start only
reset the counter, waiting for the next F8 and potentially adding one tick
(83.3 ms at 30 BPM, 20.8 ms at 120 BPM). The local Samples Start path sets
playing at `0x40054034` before sending FA at `0x40054042`. Actual alignment
with audio still needs a hardware timing comparison; this is a test fix for
the reported tempo-dependent delay.
The audio output wrapper restores BREAK after eight 32-sample blocks
(roughly 4.7–5.3 ms, plus UART command latency). It also restores BREAK
when the stock playing flag clears, even without a transmitted Stop byte.
The default disabled path is one call, two flag reads, an OR/branch and return
per block, plus the producer checks. Actual CPU and timing must be measured.

## Samples menu and memory

`DeviceSettingsMenuView` at `0x40033c62` references the stock "Device Config"
and class-name strings. Its epilogue at `0x4003402a` adds the Gate Clock row,
replays the saved-register restore, then resumes at `0x40034030`. The framework
closures use the Samples mappings in `scalelock_address_map.md`. The row label
is shortened to **Gate Clk**; values use the existing 5x9 font inside the right
icon pane. Upstream's generic list-page renderer clips its large text in this
menu, so the Samples value callback uses the native `sys_atl` helper instead.
The row is constructed during boot: adding the constructor hook to a previously
settled stock snapshot does **not** retroactively add it to that snapshot's menu.
Use a cold-built gate firmware profile for the menu integration test.

The standalone payload occupies 15,840 bytes of the existing 16,384-byte cache
block reservation (544 bytes spare). No second cache block or additional sample
RAM is taken. History reservation and DSP processing are unchanged; the audio
wrapper additionally services UART ownership and pulse expiry once per block.

## Validation

Run `python3 tools/test_samples_midi_gate.py` with Unicorn and ColdFire binutils
installed; it builds its own payload at the standalone Samples address. The tests execute
the assembled CFV4E routines and check all clock divisions, expiry, transport,
fixed test states, deferred claims for each busy condition, command widths,
MIDI suppression during transitions, register preservation, flush and the
disabled stock continuation paths. Full builds also assert all replaced
stock bytes before patching.

Local validation of this Samples port:

- 56 stock-free Samples tests pass, including the relocated gate routines,
  compact renderer arguments, injection rejection and cold-boot reservation.
- Standalone container round-trip and unchanged non-MAIN sections pass.
- DigiEmu bootloader, cold boot and runtime checks pass. Six named screens
  match stock and 6.3 seconds of bypass audio are identical; a transient frame
  first differs at 1410 ms. The checker lacks bundled SysEx checksum support;
  the separate firmware packer validates those checksums. The stock comparison
  reports its two known ISA_C violations at `0x400a3c42` and `0x400a3c54`.
- A locked disposable copy of the standalone profile passes real-panel menu
  editing across all six modes, clamping, IDLE/BREAK states, OFF restoration
  and reopening. Screens were inspected for text clipping.
- Existing factory-enabled DSP and retrig-panel regressions pass. All twelve
  effects change audio; bypass remains identical and histories record dry.

These are emulator checks, not scope measurements. The firmware checker was
run with `--no-timing`; CPU headroom is not established by these results.

The test MMIO model does not establish DMA arbitration, whole-firmware
scheduling, real UART latency, or electrical behavior. Before calling the
feature hardware-validated, measure IDLE/BREAK voltages on a TRS breakout,
check pulse polarity/width and all rates on a scope, and verify stop/start,
mode switching under TX load, restored normal MIDI, MIDI input and USB.
