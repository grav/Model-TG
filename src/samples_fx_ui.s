| Model:Samples OS 1.13 native View subclass for emulator development.
| No Python input interception: real firmware events call these handlers.
    .balign 4
samples_key:
    movea.l %sp@(4),%a0
    movel   %a0@(12),%d0
    tstl    rtg_on
    bnew    kh_rtg
sk_normal:
    cmpil   #13,%d0
    beqw    kh_mod
    cmpil   #4,%d0
    beqw    sk_retrig
    cmpil   #12,%d0
    bnew    sk_out
    tstl    set_held
    bnew    sk_reset
    tstl    return_eaten
    bnew    sk_reset
sk_out:
    rts
kh_mod:
    movel   %a0@(16),%d1
    btst    #5,%d1
    bnew    kh_eat
    btst    #0,%d1
    beqs    sk_settings_up
    btst    #3,%d1
    bnes    sk_settings_down
    clrl    mod_used
sk_settings_down:
    moveq   #1,%d1
    movel   %d1,set_held
    rts
sk_settings_up:
    clrl    set_held
    tstl    mod_used
    bnew    kh_eat
    rts
sk_retrig:
    movel   %a0@(16),%d1
    btst    #0,%d1
    bnes    sk_retrig_down
    tstl    kh_eaten4
    beqs    sk_out
    clrl    kh_eaten4
    braw    kh_eat
sk_retrig_down:
    tstl    kh_eaten4
    bnew    kh_eat
    btst    #3,%d1
    bnes    sk_out
    tstl    set_held
    beqs    sk_out
    movel   %a0,%sp@-
    bsr     sp_open
    movea.l %sp@+,%a0
    tstl    page_obj
    beqs    sk_failed
    moveq   #1,%d1
    movel   %d1,kh_eaten4
    movel   %d1,mod_used
    movel   %a0@(16),%d1
    oril    #8,%d1
    movel   %d1,%a0@(16)
    braw    kh_eat
sk_failed:
    moveq   #4,%d0
    rts
sk_reset:
    btst    #0,%a0@(19)
    bnes    sk_reset_down
    clrl    return_eaten
    braw    kh_eat
sk_reset_down:
    tstl    return_eaten
    bnew    kh_eat
    moveq   #1,%d1
    movel   %d1,return_eaten
    movel   %d1,mod_used
    movel   %a0,%sp@-
    bsr     mfx_reset
    bsr     sp_redraw
    movea.l %sp@+,%a0
    movel   %a0@(16),%d1
    oril    #8,%d1
    movel   %d1,%a0@(16)
kh_eat:
    moveq   #0,%d0
    rts

| Reached by the shared retrig-key handler for unrelated page keys.
| Settings is handled by kh_mod; return-reset chords by this bridge.
sp_page_other:
    braw    sk_normal

sp_open:
    lea.l   %sp@(-16),%sp
    moveml  %d2/%a2-%a4,%sp@
    tstl    page_obj
    bnew    spo_out
    pea     76
    jsr     0x4007f340            | operator new
    addql   #4,%sp
    tstl    %d0
    beqw    spo_out
    movea.l %d0,%a4
    pea     rtg_s_mode
    movel   %a4,%sp@-
    jsr     0x4007502a            | View(this, caption), no machine UI in Samples
    addql   #8,%sp
    lea.l   0x4010cf30,%a0        | complete stock View vtable group
    lea.l   page_vt,%a1
    moveq   #38,%d0              | 0x9c bytes, including RTTI/subobject tables
spo_copy:
    movel   %a0@+,%a1@+
    subql   #1,%d0
    bpls    spo_copy
    lea.l   page_vt,%a1
    movel   #sp_dtor,%d0
    movel   %d0,%a1@(8)
    movel   #sp_delete,%d0
    movel   %d0,%a1@(12)
    movel   #sp_key,%d0
    movel   %d0,%a1@(16)
    movel   #sp_render,%d0
    movel   %d0,%a1@(24)
    movel   #sp_encoder_th,%d0
    movel   %d0,%a1@(0x5c)
    lea.l   %a1@(8),%a0
    movel   %a0,%a4@
    lea.l   %a1@(0x54),%a0
    movel   %a0,%a4@(4)
    pea     16
    jsr     0x4007f340
    addql   #4,%sp
    tstl    %d0
    beqw    spo_noholder
    movea.l %d0,%a0
    movel   #0x400f786c,%a0@      | stock shared_ptr<View> holder from 0x4000e102
    moveq   #1,%d0
    movel   %d0,%a0@(4)
    movel   %d0,%a0@(8)
    movel   %a4,%a0@(12)
    movel   %a4,page_obj
    clrl    rtg_on
    clrl    rtg_func              | match PR #22: no stale FUNC gesture on open
    clrl    mfx_fwait
    clrl    mfx_fsteps
    movea.l %a0,%a2              | retain holder while clearing stale histories
    moveq   #0,%d2
spo_histories:
    movel   %d2,%d0
    bsr     rtg_zero
    addql   #1,%d2
    cmpil   #16,%d2
    bcss    spo_histories
    movea.l %a2,%a0
    lea.l   rtg_held,%a1
    moveq   #15,%d0
spo_held:
    clrl    %a1@+
    subql   #1,%d0
    bpls    spo_held
    moveq   #-1,%d0
    movel   %d0,rtg_lstep
    clrl    rtg_pat
    clrl    rtg_row
    clrl    rtg_edit
    movel   blk_clk,%d0
    subil   #1500,%d0
    movel   %d0,mfx_mt
    | Clear histories on each open, as the original Cycles page does.
    movel   %a0,%sp@-
    movel   %a4,%sp@-
    jsr     0x400cc642            | UI context; stock root-view callers use this
    movel   %d0,%sp@-
    jsr     0x40006358            | context's root ViewController (+64)
    addql   #4,%sp
    movea.l %sp,%a0
    clrl    %sp@-
    movel   %a0,%sp@-
    movel   %d0,%sp@-
    jsr     0x4007606e            | present(controller, {page, holder}, false)
    lea.l   %sp@(12),%sp
    pea     %sp@(4)
    jsr     0x400caec2            | release local holder reference
    lea.l   %sp@(12),%sp
    moveq   #1,%d0
    movel   %d0,rtg_on
    bsr     sp_redraw
    bras    spo_out
spo_noholder:
    movel   %a4,%sp@-
    jsr     0x40075360            | stock View deleting destructor
    addql   #4,%sp
spo_out:
    moveml  %sp@,%d2/%a2-%a4
    lea.l   %sp@(16),%sp
    rts

sp_dtor:
    clrl    page_obj
    clrl    rtg_on
    jmp     0x400752a8
sp_delete:
    clrl    page_obj
    clrl    rtg_on
    jmp     0x40075360

sp_redraw:
    movel   page_obj,%d0
    beqs    spr_out
    movel   %d0,%sp@-
    jsr     0x400750e2
    addql   #4,%sp
spr_out:
    rts

sp_render:
    movel   %d2,%sp@-
    movel   %sp@(12),%d2          | ctx, second argument after saved d2
    bsr     rtg_render
    movel   %sp@+,%d2
    rts

sp_key:
    lea.l   %sp@(-12),%sp
    moveml  %d2-%d3/%a2,%sp@
    movea.l %sp@(16),%a2
    movea.l %sp@(20),%a0
    movel   %a0,%d2
    movel   %a0,%sp@-
    jsr     0x4007146c            | hooked key-code accessor
    addql   #4,%sp
    movel   %d0,%d3
    tstl    %d0
    beqw    spk_used
    cmpil   #12,%d0
    beqs    spk_reset
    cmpil   #32,%d0
    beqs    spk_data
    cmpil   #13,%d0
    beqs    spk_close
    cmpil   #4,%d0
    beqs    spk_close
    cmpil   #5,%d0
    beqs    spk_close
    cmpil   #3,%d0
    beqs    spk_close
spk_stock:
    movel   %d2,%sp@-
    movel   %a2,%sp@-
    jsr     0x40074f9c
    addql   #8,%sp
    bras    spk_out
spk_data:
    movel   %d2,%sp@-
    jsr     0x40071494            | click, not press/repeat/release noise
    addql   #4,%sp
    tstb    %d0
    beqs    spk_used
    moveq   #1,%d0
    eorl    %d0,rtg_edit
    bras    spk_draw
spk_reset:
    movel   %d2,%sp@-
    jsr     0x40071494
    addql   #4,%sp
    tstb    %d0
    beqs    spk_used
    bsr     mfx_reset
spk_draw:
    bsr     sp_redraw
    bras    spk_used
spk_close:
    movel   %d2,%sp@-
    jsr     0x40071500            | fresh down, not an auto-repeat
    addql   #4,%sp
    tstb    %d0
    beqs    spk_stock
    moveq   #1,%d0
    movel   %d0,mod_used
    movel   %a2,%sp@-
    jsr     0x40075186            | deferred View.close()
    addql   #4,%sp
    cmpil   #3,%d3
    beqs    spk_stock            | Pattern press must reach stock picker
spk_used:
    moveq   #1,%d0
spk_out:
    moveml  %sp@,%d2-%d3/%a2
    lea.l   %sp@(12),%sp
    rts

sp_encoder_th:
    subql   #4,%sp@(4)
sp_encoder:
    lea.l   %sp@(-16),%sp
    moveml  %d2-%d4/%a2,%sp@
    movea.l %sp@(24),%a2         | event
    movel   %a2@(12),%d3         | logical parameter knob index
    movel   %d3,sp_last_encoder
    moveq   #4,%d0
    cmpil   #1,%d3
    beqs    spe_slow
    tstl    rtg_func
    beqs    spe_accel
    cmpil   #6,%d3               | FUNC + Filter counts unaccelerated clicks
    bnes    spe_accel
spe_slow:
    moveq   #1,%d0
spe_accel:
    movel   %d0,%sp@-
    pea     1
    movel   %a2,%sp@-
    jsr     0x4006e79a
    lea.l   %sp@(12),%sp
    tstl    %d0
    beqw    spe_done
    cmpil   #1,%d3
    beqs    spe_data
    bsr     mfx_knob              | same direct-delta entry as DSP mailbox
    braw    spe_draw
spe_data:
    moveq   #0,%d4
    tstl    %d0
    bmis    spe_dir
    moveq   #1,%d4
spe_dir:
    tstl    rtg_edit
    bnes    spe_value
    movel   %d4,rtg_row
    bras    spe_draw
spe_value:
    tstl    rtg_row
    bnes    spe_returns
    movel   %d4,rtg_latch
    moveq   #-1,%d0
    movel   %d0,rtg_lstep
    bras    spe_draw
spe_returns:
    tstl    %d4
    beqs    spe_setfx
    tstl    rtg_fx
    bnes    spe_setfx
    moveq   #12,%d2
spe_clear:
    movel   %d2,%d0
    bsr     rtg_zero
    addql   #1,%d2
    cmpil   #16,%d2
    bcss    spe_clear
spe_setfx:
    movel   %d4,rtg_fx
spe_draw:
    bsr     sp_redraw
spe_done:
    moveq   #1,%d0
    moveml  %sp@,%d2-%d4/%a2
    lea.l   %sp@(16),%sp
    rts

    .balign 4
page_obj:      .long 0
page_vt:       .space 0x9c
set_held:      .long 0
mod_used:      .long 0
kh_eaten4:     .long 0
return_eaten:  .long 0
sp_last_encoder: .long 0          | input diagnostics, not a control mailbox
sp_fmt_s:      .asciz "%s"
    .balign 4
