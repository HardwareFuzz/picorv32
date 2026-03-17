# Makefile for PicoRV32 Skip Exception (Standalone Version)

TOOLCHAIN_PREFIX ?= /mnt/disk1/linux/programs/riscv/bin/riscv64-unknown-elf-

CC = $(TOOLCHAIN_PREFIX)gcc
OBJCOPY = $(TOOLCHAIN_PREFIX)objcopy
OBJDUMP = $(TOOLCHAIN_PREFIX)objdump

CFLAGS = -mabi=ilp32 -march=rv32imc -Os -ffreestanding -nostdlib
ASFLAGS = -mabi=ilp32 -march=rv32imc
LDFLAGS = -nostdlib -Wl,--build-id=none,-Bstatic,-T,linker.ld

# Target files
TARGET = skip_exception_standalone
ELF = $(TARGET).elf
HEX = $(TARGET).hex
BIN = $(TARGET).bin
DIS = $(TARGET).dis
OBJ = $(TARGET).o

# Paths
TESTBENCH = ../../testbench_cli

.PHONY: all clean test test-vcd test-verbose disassemble

all: $(ELF) $(HEX) $(BIN)

$(ELF): $(OBJ) linker.ld
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJ)
	@echo "✓ Built: $@"
	@echo "  Entry point: 0x00000000"
	@echo "  IRQ vector: 0x00000010"

$(OBJ): $(TARGET).S
	$(CC) $(ASFLAGS) -c -o $@ $<

$(HEX): $(ELF)
	$(OBJCOPY) -O verilog $< $@

$(BIN): $(ELF)
	$(OBJCOPY) -O binary $< $@

$(DIS): $(ELF)
	$(OBJDUMP) -d $< > $@

# Create linker script
linker.ld:
	@echo "Creating linker script..."
	@echo "SECTIONS" > $@
	@echo "{" >> $@
	@echo "    . = 0x00000000;" >> $@
	@echo "    .text : {" >> $@
	@echo "        *(.text)" >> $@
	@echo "    }" >> $@
	@echo "    .data : {" >> $@
	@echo "        *(.data)" >> $@
	@echo "        *(.data.*)" >> $@
	@echo "    }" >> $@
	@echo "    .bss : {" >> $@
	@echo "        *(.bss)" >> $@
	@echo "        *(.bss.*)" >> $@
	@echo "    }" >> $@
	@echo "    .tohost : {" >> $@
	@echo "        *(.tohost)" >> $@
	@echo "    }" >> $@
	@echo "}" >> $@

clean:
	rm -f *.o *.elf *.hex *.bin *.dis linker.ld

# Test with CLI simulator
test: $(ELF)
	@echo "Running exception skip test..."
	@$(TESTBENCH) $<

# Test with VCD output
test-vcd: $(ELF)
	@echo "Generating VCD waveform..."
	@$(TESTBENCH) +vcd $<
	@echo "View with: gtkwave testbench.vcd"

# Test with verbose output
test-verbose: $(ELF)
	@echo "Running with verbose output..."
	@$(TESTBENCH) +verbose --timeout=5000 $<

# Generate disassembly
disassemble: $(DIS)
	@cat $(DIS)

# Quick check - compile only
check:
	@$(CC) $(ASFLAGS) -c -o /dev/null $(TARGET).S && echo "✓ Syntax OK"
