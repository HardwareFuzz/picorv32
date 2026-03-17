// PicoRV32: Skip Exception Handler (Standalone Version)
// No external dependencies - all macros defined inline

// ============================================
// PicoRV32 Custom Instruction Macros
// ============================================
#define regnum_q0   0
#define regnum_q2   2
#define regnum_q3   3

#define regnum_zero 0
#define regnum_t0   5
#define regnum_t1   6
#define regnum_t2   7

#define r_type_insn(_f7, _rs2, _rs1, _f3, _rd, _opc) \
.word (((_f7) << 25) | ((_rs2) << 20) | ((_rs1) << 15) | ((_f3) << 12) | ((_rd) << 7) | ((_opc) << 0))

#define picorv32_getq_insn(_rd, _qs) \
r_type_insn(0b0000000, 0, regnum_ ## _qs, 0b100, regnum_ ## _rd, 0b0001011)

#define picorv32_setq_insn(_qd, _rs) \
r_type_insn(0b0000001, 0, regnum_ ## _rs, 0b010, regnum_ ## _qd, 0b0001011)

#define picorv32_retirq_insn() \
r_type_insn(0b0000010, 0, 0, 0b000, 0, 0b0001011)

#define picorv32_maskirq_insn(_rd, _rs) \
r_type_insn(0b0000011, 0, regnum_ ## _rs, 0b110, regnum_ ## _rd, 0b0001011)

// ============================================
// Code Section
// ============================================
    .section .text
    .globl _start

// ============================================
// Reset Vector (0x00)
// ============================================
_start:
    j start_code
    .balign 16

// ============================================
// IRQ Vector (0x10) - Exception Handler
// ============================================
irq_vec:
    // Save t0, t1 to Q registers
    picorv32_setq_insn(q2, t0)
    picorv32_setq_insn(q3, t1)
    
    // Get exception info from Q registers
    picorv32_getq_insn(t0, q0)      // t0 = return_addr | compressed_flag
    
    // Calculate faulting instruction PC
    andi t1, t0, 1                   // Extract compressed flag
    bnez t1, 1f
    addi t0, t0, -4                  // Standard instruction: PC - 4
    j 2f
1:  addi t0, t0, -3                  // Compressed instruction: PC - 3
2:
    // Read faulting instruction to determine its length
    lhu t1, 0(t0)                    // Load first 16 bits
    andi t1, t1, 0x3                 // Check bits [1:0]
    li t2, 0x3
    bne t1, t2, 3f
    // Faulting instruction is 32-bit: skip 4 bytes
    addi t0, t0, 4
    j 4f
3:  // Faulting instruction is 16-bit: skip 2 bytes
    addi t0, t0, 2
4:
    // Check if next instruction is compressed
    lhu t1, 0(t0)
    andi t1, t1, 0x3
    li t2, 0x3
    bne t1, t2, 5f
    ori t0, t0, 0                    // Next is standard: flag = 0
    j 6f
5:  ori t0, t0, 1                    // Next is compressed: flag = 1
6:
    // Update return address in q0
    picorv32_setq_insn(q0, t0)
    
    // Restore t0, t1
    picorv32_getq_insn(t0, q2)
    picorv32_getq_insn(t1, q3)
    
    // Return from exception
    picorv32_retirq_insn()

// ============================================
// System Initialization (uses t registers only)
// ============================================
start_code:
    // Enable exception handling
    picorv32_maskirq_insn(zero, zero)
    j user_code

// ============================================
// User Code Area (uses s registers only)
// ============================================
user_code:
    // Test 1: Illegal instruction
    li s0, 0x12345678
    .word 0xFFFFFFFF                 // Will be skipped
    li s1, 0x11111111                // Should execute
    
    // Test 2: Unaligned access
    li s2, 0x00000001
    lw s3, 0(s2)                     // Will be skipped
    li s4, 0x22222222                // Should execute
    
    // Test 3: EBREAK
    li s5, 0x33333333
    ebreak                           // Will be skipped
    li s6, 0x44444444                // Should execute
    
    j exit

// ============================================
// System Exit (uses t registers only)
// ============================================
exit:
    // Report success to testbench
    li t0, 123456789
    li t1, 0x20000000
    sw t0, 0(t1)
    
    // Disable IRQ handling before final trap
    li t0, -1
    picorv32_maskirq_insn(t0, t0)
    
    // Trigger trap for clean exit
    ebreak
