| Samples OS 1.13 cold-boot clear, replacing the complete stock clear function.
| Payload resides in retired filesystem cache block(s), not 0x47000000 scratch.
| Keep stock cache configuration; this hook adds no ACR/CACR optimizations.
| samples_payload_end is 16-aligned by the payload builder.
    .globl samples_boot_clear
    .text
samples_boot_clear:
    lea.l   %sp@(-16),%sp
    moveml  %d4-%d7,%sp@
    moveq   #0,%d4
    moveq   #0,%d5
    moveq   #0,%d6
    moveq   #0,%d7
    movea.l #0x401a05a0,%a0
sbc_bss:
    cmpal   #samples_payload_start,%a0
    bnes    sbc_store
    movea.l #samples_payload_end,%a0
sbc_store:
    cmpal   #0x4211f510,%a0
    bccs    sbc_histories
    moveml  %d4-%d7,%a0@
    lea.l   %a0@(16),%a0
    bras    sbc_bss
sbc_histories:
    movea.l #RTG_BASE,%a0
sbc_history_loop:
    moveml  %d4-%d7,%a0@
    lea.l   %a0@(16),%a0
    cmpal   #RTG_BASE+0x400000,%a0
    bcss    sbc_history_loop
    | Match the original clear's return registers and stack contract.
    movea.l #0x4211f510,%a0
    moveq   #0,%d1
    moveml  %sp@,%d4-%d7
    lea.l   %sp@(16),%sp
    rts
