| Model:Samples OS 1.13 DSP port, emulator-only development payload.
| Not a hardware memory reservation or a bootable firmware image.
| The builder extracts the shared DSP from model_tg.s, without its sampler/UI.
    .text
    .balign 4
    .globl samples_audio, samples_mix
samples_audio:
    lea.l   %sp@(-60),%sp
    moveml  %d0-%d7/%a0-%a6,%sp@
    addql   #1,blk_clk
    tstl    command_reset
    beqs    sa_knob
    clrl    command_reset
    bsr     mfx_reset
sa_knob:
    movel   command_delta,%d0
    beqs    sa_run
    clrl    command_delta
    movel   command_knob,%d3
    bsr     mfx_knob              | port entry: d0 delta, d3 panel index + 1
sa_run:
    bsr     rtg_audio
    moveml  %sp@,%d0-%d7/%a0-%a6
    lea.l   %sp@(60),%sp
    jmp     0x4005575e            | stock output/sends function; args untouched

samples_mix:
    movel   %d0,%sp@-
    movel   %sp@(8),%d0           | bus, behind saved d0 and return address
    cmpil   #0x8000c690,%d0
    beqs    sm_left
    cmpil   #0x8000c694,%d0
    bnes    sm_stock
    moveq   #1,%d0
    bras    sm_returns
sm_left:
    moveq   #0,%d0
sm_returns:
    bsr     rtg_fxpass
sm_stock:
    movel   %sp@+,%d0
    lea.l   %sp@(-40),%sp         | replay stock mixer's overwritten prologue
    moveml  %d2-%d7/%a2-%a5,%sp@
    jmp     0x400555bc

    .balign 4
command_knob:  .long 0
command_delta: .long 0
command_reset: .long 0
blk_clk:       .long 0
| Stock Samples tracks are mono. No Model-TG stereo sampler side streams.
sx_on:         .space 24
sx_side:       .space 6*128
