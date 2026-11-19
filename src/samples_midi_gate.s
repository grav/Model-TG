| Samples 1.13 adapters for PR #27. UART code is shared in midi_gate.inc;
| framework helpers are extracted by build_samples_fx.py from model_tg.s.
| DeviceSettingsMenuView ("Device Config") constructor: 0x40033c62.
samples_gate_config:
    lea.l   %sp@(-16),%sp
    moveml  %d0-%d1/%a0-%a1,%sp@
    pea     gate_row
    movel   %a2,%sp@-
    jsr     lm_add_row
    addql   #8,%sp
    moveml  %sp@,%d0-%d1/%a0-%a1
    lea.l   %sp@(16),%sp
    moveml  %sp@(24),%d2-%d6/%a2-%fp
    jmp     0x40034030

| The stock Device Config uses a right-hand icon pane, not the granular
| list page expected by upstream gm_val. Draw a compact 5x9 mode name inside
| that pane, keeping 24PPQN within the screen and away from the row label.
samples_gate_value:
    movel   %d2,%sp@-
    movel   %sp@(16),%d2          | drawing context (third callback argument)
    movel   gate_mode,%d0
    lea.l   gate_names,%a0
    movea.l %a0@(0,%d0:l:4),%a0
    moveq   #15,%d0              | top-relative y
    moveq   #80,%d1              | right pane, six chars fit through x=109
    bsr     sys_atl
    movel   %sp@+,%d2
    rts

| Press selects editing without changing the value (stock list-menu ABI).
id_press:
    movel   %sp@(8),%sp@-
    movel   %sp@(8),%sp@-
    jsr     new_slot2_invoker
    addql   #8,%sp
    rts

    .equ ALLOC,            0x4007f0c4
    .equ FREE_CLOSURE,     0x400cacca
    .equ MENUITEM_CTOR,    0x40072510
    .equ MENUVIEW_ADDITEM, 0x40071d46
    .equ FORMAT_STRING,    0x400f4bd0
    .equ SLOT2_MANAGER,    0x400306c4
    .equ GENERIC_MANAGER,  0x40030672
