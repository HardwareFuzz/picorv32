    .section .text
    .globl _start

_start:
    li t0, 0x20000000
    li t1, 123456789
    sw t1, 0(t0)
    ebreak
