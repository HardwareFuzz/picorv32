// PicoRV32 CLI Testbench - Similar to Spike/Rocket
// Usage: ./testbench_cli [options] <elf_file>
// Options:
//   +vcd           - Generate VCD waveform
//   +trace         - Generate instruction trace
//   +verbose       - Verbose output
//   --timeout=N    - Set timeout in cycles (default: 1000000)

#include "Vpicorv32_wrapper.h"
#include "Vpicorv32_wrapper_picorv32_wrapper.h"
#include "Vpicorv32_wrapper_axi4_memory.h"
#include "verilated_vcd_c.h"
#include "verilated_cov.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <elf.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/mman.h>

// Memory access functions for Verilator model
// Note: memory array is declared as "public" in testbench.v
#define MEM_SIZE (128 * 1024)
#define MEM_WORDS (MEM_SIZE / 4)

class ElfLoader {
private:
    void *mapped_file;
    size_t file_size;
    int fd;

public:
    ElfLoader() : mapped_file(nullptr), file_size(0), fd(-1) {}
    
    ~ElfLoader() {
        if (mapped_file) {
            munmap(mapped_file, file_size);
        }
        if (fd >= 0) {
            close(fd);
        }
    }

    bool load(const char* filename, uint32_t* memory) {
        // Open ELF file
        fd = open(filename, O_RDONLY);
        if (fd < 0) {
            fprintf(stderr, "Error: Cannot open file '%s'\n", filename);
            return false;
        }

        // Get file size
        struct stat st;
        if (fstat(fd, &st) < 0) {
            fprintf(stderr, "Error: Cannot stat file '%s'\n", filename);
            return false;
        }
        file_size = st.st_size;

        // Memory map the file
        mapped_file = mmap(nullptr, file_size, PROT_READ, MAP_PRIVATE, fd, 0);
        if (mapped_file == MAP_FAILED) {
            fprintf(stderr, "Error: Cannot mmap file '%s'\n", filename);
            return false;
        }

        // Check ELF magic
        Elf32_Ehdr* ehdr = (Elf32_Ehdr*)mapped_file;
        if (memcmp(ehdr->e_ident, ELFMAG, SELFMAG) != 0) {
            fprintf(stderr, "Error: '%s' is not a valid ELF file\n", filename);
            return false;
        }

        // Check for 32-bit RISC-V
        if (ehdr->e_ident[EI_CLASS] != ELFCLASS32) {
            fprintf(stderr, "Error: Only 32-bit ELF files are supported\n");
            return false;
        }

        if (ehdr->e_machine != EM_RISCV) {
            fprintf(stderr, "Warning: ELF file is not for RISC-V (machine type: %d)\n", ehdr->e_machine);
        }

        // Initialize memory to zero
        memset(memory, 0, MEM_SIZE);

        printf("Loading ELF file: %s\n", filename);
        printf("Entry point: 0x%08x\n", ehdr->e_entry);

        // Load program headers
        Elf32_Phdr* phdr = (Elf32_Phdr*)((char*)mapped_file + ehdr->e_phoff);
        for (int i = 0; i < ehdr->e_phnum; i++) {
            if (phdr[i].p_type == PT_LOAD) {
                uint32_t paddr = phdr[i].p_paddr;
                uint32_t vaddr = phdr[i].p_vaddr;
                uint32_t filesz = phdr[i].p_filesz;
                uint32_t memsz = phdr[i].p_memsz;
                uint32_t offset = phdr[i].p_offset;

                // Use physical address if available, otherwise virtual address
                uint32_t load_addr = (paddr != 0) ? paddr : vaddr;

                printf("  Segment %d: addr=0x%08x size=0x%08x (file=0x%08x)\n", 
                       i, load_addr, memsz, filesz);

                // Check bounds
                if (load_addr >= MEM_SIZE || load_addr + memsz > MEM_SIZE) {
                    fprintf(stderr, "Error: Segment %d exceeds memory bounds (0x%08x + 0x%08x > 0x%08x)\n",
                            i, load_addr, memsz, MEM_SIZE);
                    return false;
                }

                // Copy file data
                if (filesz > 0) {
                    uint8_t* src = (uint8_t*)mapped_file + offset;
                    uint8_t* dst = (uint8_t*)memory + load_addr;
                    memcpy(dst, src, filesz);
                }

                // Zero out BSS (memsz > filesz)
                if (memsz > filesz) {
                    uint8_t* dst = (uint8_t*)memory + load_addr + filesz;
                    memset(dst, 0, memsz - filesz);
                }
            }
        }

        printf("ELF loaded successfully\n\n");
        return true;
    }
};

void print_usage(const char* prog) {
    fprintf(stderr, "PicoRV32 CLI Simulator - Usage:\n");
    fprintf(stderr, "  %s [options] <elf_file>\n\n", prog);
    fprintf(stderr, "Options:\n");
    fprintf(stderr, "  +vcd              Generate VCD waveform (testbench.vcd)\n");
    fprintf(stderr, "  +trace            Generate instruction trace (testbench.trace)\n");
    fprintf(stderr, "  +verbose          Enable verbose output\n");
    fprintf(stderr, "  --timeout=N       Set simulation timeout in cycles (default: 1000000)\n");
    fprintf(stderr, "  -h, --help        Show this help message\n\n");
    fprintf(stderr, "Examples:\n");
    fprintf(stderr, "  %s firmware/firmware.elf\n", prog);
    fprintf(stderr, "  %s +vcd +trace program.elf\n", prog);
    fprintf(stderr, "  %s --timeout=5000000 dhrystone.elf\n", prog);
}

int main(int argc, char **argv, char **env)
{
    printf("PicoRV32 CLI Simulator\n");
    printf("Built with %s %s\n\n", Verilated::productName(), Verilated::productVersion());

    // Parse command line arguments
    const char* elf_file = nullptr;
    int timeout_cycles = 1000000;
    
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else if (strncmp(argv[i], "--timeout=", 10) == 0) {
            timeout_cycles = atoi(argv[i] + 10);
            if (timeout_cycles <= 0) {
                fprintf(stderr, "Error: Invalid timeout value\n");
                return 1;
            }
        } else if (argv[i][0] == '+') {
            // Verilator plusargs - will be handled by Verilated::commandArgs
            continue;
        } else if (argv[i][0] == '-') {
            fprintf(stderr, "Error: Unknown option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        } else {
            // This should be the ELF file
            if (elf_file != nullptr) {
                fprintf(stderr, "Error: Multiple ELF files specified\n");
                return 1;
            }
            elf_file = argv[i];
        }
    }

    if (elf_file == nullptr) {
        fprintf(stderr, "Error: No ELF file specified\n\n");
        print_usage(argv[0]);
        return 1;
    }

    // Initialize Verilator
    Verilated::commandArgs(argc, argv);
    Vpicorv32_wrapper* top = new Vpicorv32_wrapper;

    // Load ELF file into memory
    printf("Loading ELF: %s\n", elf_file);
    ElfLoader loader;
    if (!loader.load(elf_file, top->picorv32_wrapper->mem->memory.data())) {
        fprintf(stderr, "Failed to load ELF file\n");
        delete top;
        return 1;
    }

    // Setup VCD tracing
    VerilatedVcdC* tfp = NULL;
    const char* flag_vcd = Verilated::commandArgsPlusMatch("vcd");
    if (flag_vcd && 0==strcmp(flag_vcd, "+vcd")) {
        Verilated::traceEverOn(true);
        tfp = new VerilatedVcdC;
        top->trace(tfp, 99);
        tfp->open("testbench.vcd");
        printf("VCD tracing enabled -> testbench.vcd\n");
    }

    // Setup instruction trace
    FILE *trace_fd = NULL;
    const char* flag_trace = Verilated::commandArgsPlusMatch("trace");
    if (flag_trace && 0==strcmp(flag_trace, "+trace")) {
        trace_fd = fopen("testbench.trace", "w");
        if (trace_fd) {
            printf("Instruction tracing enabled -> testbench.trace\n");
        }
    }

    const char* flag_verbose = Verilated::commandArgsPlusMatch("verbose");
    bool verbose = (flag_verbose && 0==strcmp(flag_verbose, "+verbose"));

    printf("\nStarting simulation (timeout: %d cycles)...\n", timeout_cycles);
    printf("---------------------------------------------------\n\n");

#if VM_COVERAGE
    // Decide coverage output path; default to logs/coverage.dat, override with +covfile=<path>
    std::string cov_path = "logs/coverage.dat";
    if (const char* cov_arg = Verilated::commandArgsPlusMatch("covfile=")) {
        const char* val = cov_arg + std::strlen("+covfile=");
        if (*val) cov_path = val;
    }
    const auto slash_pos = cov_path.find_last_of('/');
    if (slash_pos != std::string::npos && slash_pos != 0) {
        Verilated::mkdir(cov_path.substr(0, slash_pos).c_str());
    } else {
        Verilated::mkdir("logs");
    }
    Verilated::threadContextp()->coveragep()->zero();
#endif

    // Run simulation
    top->clk = 0;
    top->resetn = 0;
    int t = 0;
    int cycle = 0;
    bool timed_out = false;

    while (!Verilated::gotFinish() && cycle < timeout_cycles) {
        // Release reset after 200 time units
        if (t > 200)
            top->resetn = 1;
        
        // Toggle clock
        top->clk = !top->clk;
        top->eval();
        
        // Dump waveform
        if (tfp) tfp->dump(t);
        
        // Log instruction trace
        if (trace_fd && top->clk && top->resetn && top->trace_valid) {
            fprintf(trace_fd, "%9.9lx\n", (unsigned long)top->trace_data);
        }
        
        // Count cycles (on positive edge)
        if (top->clk && top->resetn) {
            cycle++;
            if (verbose && (cycle % 10000 == 0)) {
                printf("Cycle: %d\r", cycle);
                fflush(stdout);
            }
        }
        
        t += 5;
    }

    if (cycle >= timeout_cycles) {
        timed_out = true;
    }

    // Cleanup
    if (tfp) {
        tfp->close();
        delete tfp;
    }
    if (trace_fd) {
        fclose(trace_fd);
    }

    printf("\n---------------------------------------------------\n");
    printf("Simulation finished:\n");
    printf("  Cycles: %d\n", cycle);
    printf("  Time: %d ns\n", t);
    if (timed_out) {
        printf("  Status: TIMEOUT\n");
    } else {
        printf("  Status: FINISHED\n");
    }

#if VM_COVERAGE
    Verilated::threadContextp()->coveragep()->write(cov_path.c_str());
    printf("  Coverage: %s\n", cov_path.c_str());
#endif

    delete top;
    return timed_out ? 2 : 0;
}
