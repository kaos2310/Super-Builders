// Return false for config lookups. Emit a marker for prop-watch, then exit.
.text
.global _start
_start:
    ldr x1, [sp, #16]
    ldrb w2, [x1]
    cmp w2, #112
    b.ne exit
    mov x0, #1
    adr x1, marker
    mov x2, #18
    mov x8, #64
    svc #0
exit:
    mov x0, #0
    mov x8, #93
    svc #0
marker:
    .ascii "native prop-watch\n"
