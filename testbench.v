// This is free and unencumbered software released into the public domain.
//
// Anyone is free to copy, modify, publish, use, compile, sell, or
// distribute this software, either in source code form or as a compiled
// binary, for any purpose, commercial or non-commercial, and by any
// means.

`timescale 1 ns / 1 ps

`ifndef VERILATOR
module testbench #(
	parameter AXI_TEST = 0,
	parameter VERBOSE = 0
);
	reg clk = 1;
	reg resetn = 0;
	wire trap;

	always #5 clk = ~clk;

	initial begin
		repeat (100) @(posedge clk);
		resetn <= 1;
	end

	initial begin
		if ($test$plusargs("vcd")) begin
			$dumpfile("testbench.vcd");
			$dumpvars(0, testbench);
		end
		repeat (1000000) @(posedge clk);
		$display("TIMEOUT");
		$finish;
	end

	wire trace_valid;
	wire [35:0] trace_data;
	integer trace_file;

	initial begin
		if ($test$plusargs("trace")) begin
			trace_file = $fopen("testbench.trace", "w");
			repeat (10) @(posedge clk);
			while (!trap) begin
				@(posedge clk);
				if (trace_valid)
					$fwrite(trace_file, "%x\n", trace_data);
			end
			$fclose(trace_file);
			$display("Finished writing testbench.trace.");
		end
	end

	picorv32_wrapper #(
		.AXI_TEST (AXI_TEST),
		.VERBOSE  (VERBOSE)
	) top (
		.clk(clk),
		.resetn(resetn),
		.trap(trap),
		.trace_valid(trace_valid),
		.trace_data(trace_data)
	);
endmodule
`endif

// Minimal 2x1 AXI-lite arbiter for PicoRV32 testbench
module axi4_arbiter_2x1 (
	input             clk,
	input             resetn,

	// Master 0
	input             m0_awvalid,
	output            m0_awready,
	input      [31:0] m0_awaddr,
	input      [ 2:0] m0_awprot,
	input             m0_wvalid,
	output            m0_wready,
	input      [31:0] m0_wdata,
	input      [ 3:0] m0_wstrb,
	output            m0_bvalid,
	input             m0_bready,
	input             m0_arvalid,
	output            m0_arready,
	input      [31:0] m0_araddr,
	input      [ 2:0] m0_arprot,
	output            m0_rvalid,
	input             m0_rready,
	output     [31:0] m0_rdata,

	// Master 1
	input             m1_awvalid,
	output            m1_awready,
	input      [31:0] m1_awaddr,
	input      [ 2:0] m1_awprot,
	input             m1_wvalid,
	output            m1_wready,
	input      [31:0] m1_wdata,
	input      [ 3:0] m1_wstrb,
	output            m1_bvalid,
	input             m1_bready,
	input             m1_arvalid,
	output            m1_arready,
	input      [31:0] m1_araddr,
	input      [ 2:0] m1_arprot,
	output            m1_rvalid,
	input             m1_rready,
	output     [31:0] m1_rdata,

	// Slave (memory)
	output            s_awvalid,
	input             s_awready,
	output     [31:0] s_awaddr,
	output     [ 2:0] s_awprot,
	output            s_wvalid,
	input             s_wready,
	output     [31:0] s_wdata,
	output     [ 3:0] s_wstrb,
	input             s_bvalid,
	output            s_bready,
	output            s_arvalid,
	input             s_arready,
	output     [31:0] s_araddr,
	output     [ 2:0] s_arprot,
	input             s_rvalid,
	output            s_rready,
	input      [31:0] s_rdata
);

	localparam ST_IDLE = 3'd0;
	localparam ST_R0   = 3'd1;
	localparam ST_R1   = 3'd2;
	localparam ST_W0   = 3'd3;
	localparam ST_W1   = 3'd4;

	reg [2:0] state, state_n;

	wire m0_write_req = m0_awvalid || m0_wvalid;
	wire m1_write_req = m1_awvalid || m1_wvalid;

	always @* begin
		state_n = state;
		case (state)
			ST_IDLE: begin
				if (m0_write_req)
					state_n = ST_W0;
				else if (m1_write_req)
					state_n = ST_W1;
				else if (m0_arvalid)
					state_n = ST_R0;
				else if (m1_arvalid)
					state_n = ST_R1;
			end
			ST_R0: if (s_rvalid && m0_rready) state_n = ST_IDLE;
			ST_R1: if (s_rvalid && m1_rready) state_n = ST_IDLE;
			ST_W0: if (s_bvalid && m0_bready) state_n = ST_IDLE;
			ST_W1: if (s_bvalid && m1_bready) state_n = ST_IDLE;
			default: state_n = ST_IDLE;
		endcase
	end

	always @(posedge clk or negedge resetn) begin
		if (!resetn)
			state <= ST_IDLE;
		else
			state <= state_n;
	end

	// Default outputs
	assign m0_awready = (state == ST_W0) ? s_awready : 1'b0;
	assign m0_wready  = (state == ST_W0) ? s_wready  : 1'b0;
	assign m0_bvalid  = (state == ST_W0) ? s_bvalid  : 1'b0;
	assign m0_arready = (state == ST_R0) ? s_arready : 1'b0;
	assign m0_rvalid  = (state == ST_R0) ? s_rvalid  : 1'b0;
	assign m0_rdata   = (state == ST_R0) ? s_rdata   : 32'b0;

	assign m1_awready = (state == ST_W1) ? s_awready : 1'b0;
	assign m1_wready  = (state == ST_W1) ? s_wready  : 1'b0;
	assign m1_bvalid  = (state == ST_W1) ? s_bvalid  : 1'b0;
	assign m1_arready = (state == ST_R1) ? s_arready : 1'b0;
	assign m1_rvalid  = (state == ST_R1) ? s_rvalid  : 1'b0;
	assign m1_rdata   = (state == ST_R1) ? s_rdata   : 32'b0;

	assign s_awvalid = (state == ST_W0) ? m0_awvalid :
	                   (state == ST_W1) ? m1_awvalid : 1'b0;
	assign s_awaddr  = (state == ST_W0) ? m0_awaddr  :
	                   (state == ST_W1) ? m1_awaddr  : 32'b0;
	assign s_awprot  = (state == ST_W0) ? m0_awprot  :
	                   (state == ST_W1) ? m1_awprot  : 3'b0;

	assign s_wvalid  = (state == ST_W0) ? m0_wvalid  :
	                   (state == ST_W1) ? m1_wvalid  : 1'b0;
	assign s_wdata   = (state == ST_W0) ? m0_wdata   :
	                   (state == ST_W1) ? m1_wdata   : 32'b0;
	assign s_wstrb   = (state == ST_W0) ? m0_wstrb   :
	                   (state == ST_W1) ? m1_wstrb   : 4'b0;

	assign s_bready  = (state == ST_W0) ? m0_bready  :
	                   (state == ST_W1) ? m1_bready  : 1'b0;

	assign s_arvalid = (state == ST_R0) ? m0_arvalid :
	                   (state == ST_R1) ? m1_arvalid : 1'b0;
	assign s_araddr  = (state == ST_R0) ? m0_araddr  :
	                   (state == ST_R1) ? m1_araddr  : 32'b0;
	assign s_arprot  = (state == ST_R0) ? m0_arprot  :
	                   (state == ST_R1) ? m1_arprot  : 3'b0;

	assign s_rready  = (state == ST_R0) ? m0_rready  :
	                   (state == ST_R1) ? m1_rready  : 1'b0;
endmodule

module picorv32_wrapper #(
	parameter AXI_TEST = 0,
	parameter VERBOSE = 0,
	parameter integer NUM_CORES = 2
) (
	input clk,
	input resetn,
	output trap,
	output trace_valid,
	output [35:0] trace_data
);
	wire tests_passed;
	reg [31:0] irq = 0;

	reg [15:0] count_cycle = 0;
	always @(posedge clk) count_cycle <= resetn ? count_cycle + 1 : 0;

	always @* begin
		irq = 0;
		irq[4] = &count_cycle[12:0];
		irq[5] = &count_cycle[15:0];
	end

	wire        trap0;
	wire        trap1;
	wire        trace_valid0;
	wire        trace_valid1;
	wire [35:0] trace_data0;
	wire [35:0] trace_data1;

	//
	// Dual-core exit policy
	//
	// By default (NUM_CORES > 1), require BOTH cores to reach trap and PASS before
	// finishing. This avoids false positives where one core exits early.
	// Use +any_hart_exit to restore the old behavior (OR trap / single PASS).
	reg require_all_harts;
	initial begin
		require_all_harts = (NUM_CORES > 1);
		if ($test$plusargs("any_hart_exit"))
			require_all_harts = 0;
	end

	wire trap_any = trap0 | trap1;
	wire trap_all = (NUM_CORES > 1) ? (trap0 & trap1) : trap0;
	assign trap = require_all_harts ? trap_all : trap_any;
	assign trace_valid = trace_valid0;
	assign trace_data = trace_data0;

	// Track PASS writes per core so we can require both cores to pass.
	// We attribute a PASS to a core when it completes a write transaction to
	// 0x2000_0000 with magic value 123456789.
	reg core0_passed, core1_passed;
	reg core0_aw_seen, core0_w_seen;
	reg core1_aw_seen, core1_w_seen;
	reg [31:0] core0_awaddr, core0_wdata;
	reg [31:0] core1_awaddr, core1_wdata;

	always @(posedge clk) begin
		if (!resetn) begin
			core0_passed <= 0;
			core1_passed <= 0;
			core0_aw_seen <= 0;
			core0_w_seen <= 0;
			core1_aw_seen <= 0;
			core1_w_seen <= 0;
			core0_awaddr <= 0;
			core0_wdata  <= 0;
			core1_awaddr <= 0;
			core1_wdata  <= 0;
		end else begin
			// Core 0
			if (core0_axi_awvalid && core0_axi_awready) begin
				core0_aw_seen <= 1;
				core0_awaddr <= core0_axi_awaddr;
			end
			if (core0_axi_wvalid && core0_axi_wready) begin
				core0_w_seen <= 1;
				core0_wdata <= core0_axi_wdata;
			end
			// picoRV32 may not wait for AXI B responses (posted writes). Attribute PASS
			// as soon as we have both AW and W handshakes for a transaction.
			if (core0_aw_seen && core0_w_seen) begin
				if (core0_awaddr == 32'h2000_0000 && core0_wdata == 32'd123456789)
					core0_passed <= 1;
				core0_aw_seen <= 0;
				core0_w_seen <= 0;
			end

			// Core 1
			if (core1_axi_awvalid && core1_axi_awready) begin
				core1_aw_seen <= 1;
				core1_awaddr <= core1_axi_awaddr;
			end
			if (core1_axi_wvalid && core1_axi_wready) begin
				core1_w_seen <= 1;
				core1_wdata <= core1_axi_wdata;
			end
			if (core1_aw_seen && core1_w_seen) begin
				if (core1_awaddr == 32'h2000_0000 && core1_wdata == 32'd123456789)
					core1_passed <= 1;
				core1_aw_seen <= 0;
				core1_w_seen <= 0;
			end
		end
	end

	wire        mem_axi_awvalid;
	wire        mem_axi_awready;
	wire [31:0] mem_axi_awaddr;
	wire [ 2:0] mem_axi_awprot;

	wire        mem_axi_wvalid;
	wire        mem_axi_wready;
	wire [31:0] mem_axi_wdata;
	wire [ 3:0] mem_axi_wstrb;

	wire        mem_axi_bvalid;
	wire        mem_axi_bready;

	wire        mem_axi_arvalid;
	wire        mem_axi_arready;
	wire [31:0] mem_axi_araddr;
	wire [ 2:0] mem_axi_arprot;

	wire        mem_axi_rvalid;
	wire        mem_axi_rready;
	wire [31:0] mem_axi_rdata;

	// Core 0 AXI signals
	wire        core0_axi_awvalid;
	wire        core0_axi_awready;
	wire [31:0] core0_axi_awaddr;
	wire [ 2:0] core0_axi_awprot;

	wire        core0_axi_wvalid;
	wire        core0_axi_wready;
	wire [31:0] core0_axi_wdata;
	wire [ 3:0] core0_axi_wstrb;

	wire        core0_axi_bvalid;
	wire        core0_axi_bready;

	wire        core0_axi_arvalid;
	wire        core0_axi_arready;
	wire [31:0] core0_axi_araddr;
	wire [ 2:0] core0_axi_arprot;

	wire        core0_axi_rvalid;
	wire        core0_axi_rready;
	wire [31:0] core0_axi_rdata;

	// Core 1 AXI signals
	wire        core1_axi_awvalid;
	wire        core1_axi_awready;
	wire [31:0] core1_axi_awaddr;
	wire [ 2:0] core1_axi_awprot;

	wire        core1_axi_wvalid;
	wire        core1_axi_wready;
	wire [31:0] core1_axi_wdata;
	wire [ 3:0] core1_axi_wstrb;

	wire        core1_axi_bvalid;
	wire        core1_axi_bready;

	wire        core1_axi_arvalid;
	wire        core1_axi_arready;
	wire [31:0] core1_axi_araddr;
	wire [ 2:0] core1_axi_arprot;

	wire        core1_axi_rvalid;
	wire        core1_axi_rready;
	wire [31:0] core1_axi_rdata;

	axi4_memory #(
		.AXI_TEST (AXI_TEST),
		.VERBOSE  (VERBOSE)
	) mem (
		.clk             (clk             ),
		.mem_axi_awvalid (mem_axi_awvalid ),
		.mem_axi_awready (mem_axi_awready ),
		.mem_axi_awaddr  (mem_axi_awaddr  ),
		.mem_axi_awprot  (mem_axi_awprot  ),

		.mem_axi_wvalid  (mem_axi_wvalid  ),
		.mem_axi_wready  (mem_axi_wready  ),
		.mem_axi_wdata   (mem_axi_wdata   ),
		.mem_axi_wstrb   (mem_axi_wstrb   ),

		.mem_axi_bvalid  (mem_axi_bvalid  ),
		.mem_axi_bready  (mem_axi_bready  ),

		.mem_axi_arvalid (mem_axi_arvalid ),
		.mem_axi_arready (mem_axi_arready ),
		.mem_axi_araddr  (mem_axi_araddr  ),
		.mem_axi_arprot  (mem_axi_arprot  ),

		.mem_axi_rvalid  (mem_axi_rvalid  ),
		.mem_axi_rready  (mem_axi_rready  ),
		.mem_axi_rdata   (mem_axi_rdata   ),

		.tests_passed    (tests_passed    )
	);

	axi4_arbiter_2x1 axi_arb (
		.clk(clk),
		.resetn(resetn),

		.m0_awvalid(core0_axi_awvalid),
		.m0_awready(core0_axi_awready),
		.m0_awaddr (core0_axi_awaddr ),
		.m0_awprot (core0_axi_awprot ),
		.m0_wvalid (core0_axi_wvalid ),
		.m0_wready (core0_axi_wready ),
		.m0_wdata  (core0_axi_wdata  ),
		.m0_wstrb  (core0_axi_wstrb  ),
		.m0_bvalid (core0_axi_bvalid ),
		.m0_bready (core0_axi_bready ),
		.m0_arvalid(core0_axi_arvalid),
		.m0_arready(core0_axi_arready),
		.m0_araddr (core0_axi_araddr ),
		.m0_arprot (core0_axi_arprot ),
		.m0_rvalid (core0_axi_rvalid ),
		.m0_rready (core0_axi_rready ),
		.m0_rdata  (core0_axi_rdata  ),

		.m1_awvalid(core1_axi_awvalid),
		.m1_awready(core1_axi_awready),
		.m1_awaddr (core1_axi_awaddr ),
		.m1_awprot (core1_axi_awprot ),
		.m1_wvalid (core1_axi_wvalid ),
		.m1_wready (core1_axi_wready ),
		.m1_wdata  (core1_axi_wdata  ),
		.m1_wstrb  (core1_axi_wstrb  ),
		.m1_bvalid (core1_axi_bvalid ),
		.m1_bready (core1_axi_bready ),
		.m1_arvalid(core1_axi_arvalid),
		.m1_arready(core1_axi_arready),
		.m1_araddr (core1_axi_araddr ),
		.m1_arprot (core1_axi_arprot ),
		.m1_rvalid (core1_axi_rvalid ),
		.m1_rready (core1_axi_rready ),
		.m1_rdata  (core1_axi_rdata  ),

		.s_awvalid(mem_axi_awvalid),
		.s_awready(mem_axi_awready),
		.s_awaddr (mem_axi_awaddr ),
		.s_awprot (mem_axi_awprot ),
		.s_wvalid (mem_axi_wvalid ),
		.s_wready (mem_axi_wready ),
		.s_wdata  (mem_axi_wdata  ),
		.s_wstrb  (mem_axi_wstrb  ),
		.s_bvalid (mem_axi_bvalid ),
		.s_bready (mem_axi_bready ),
		.s_arvalid(mem_axi_arvalid),
		.s_arready(mem_axi_arready),
		.s_araddr (mem_axi_araddr ),
		.s_arprot (mem_axi_arprot ),
		.s_rvalid (mem_axi_rvalid ),
		.s_rready (mem_axi_rready ),
		.s_rdata  (mem_axi_rdata  )
	);

`ifdef RISCV_FORMAL
	wire        rvfi_valid;
	wire [63:0] rvfi_order;
	wire [31:0] rvfi_insn;
	wire        rvfi_trap;
	wire        rvfi_halt;
	wire        rvfi_intr;
	wire [4:0]  rvfi_rs1_addr;
	wire [4:0]  rvfi_rs2_addr;
	wire [31:0] rvfi_rs1_rdata;
	wire [31:0] rvfi_rs2_rdata;
	wire [4:0]  rvfi_rd_addr;
	wire [31:0] rvfi_rd_wdata;
	wire [31:0] rvfi_pc_rdata;
	wire [31:0] rvfi_pc_wdata;
	wire [31:0] rvfi_mem_addr;
	wire [3:0]  rvfi_mem_rmask;
	wire [3:0]  rvfi_mem_wmask;
	wire [31:0] rvfi_mem_rdata;
	wire [31:0] rvfi_mem_wdata;
`endif

	picorv32_axi #(
`ifndef SYNTH_TEST
`ifdef SP_TEST
		.ENABLE_REGS_DUALPORT(0),
`endif
`ifdef COMPRESSED_ISA
		.COMPRESSED_ISA(1),
`endif
		.ENABLE_MUL(1),
		.ENABLE_DIV(1),
		.ENABLE_IRQ(1),
		.ENABLE_TRACE(1)
`endif
	) uut0 (
		.clk            (clk               ),
		.resetn         (resetn            ),
		.trap           (trap0             ),
		.mem_axi_awvalid(core0_axi_awvalid),
		.mem_axi_awready(core0_axi_awready),
		.mem_axi_awaddr (core0_axi_awaddr ),
		.mem_axi_awprot (core0_axi_awprot ),
		.mem_axi_wvalid (core0_axi_wvalid ),
		.mem_axi_wready (core0_axi_wready ),
		.mem_axi_wdata  (core0_axi_wdata  ),
		.mem_axi_wstrb  (core0_axi_wstrb  ),
		.mem_axi_bvalid (core0_axi_bvalid ),
		.mem_axi_bready (core0_axi_bready ),
		.mem_axi_arvalid(core0_axi_arvalid),
		.mem_axi_arready(core0_axi_arready),
		.mem_axi_araddr (core0_axi_araddr ),
		.mem_axi_arprot (core0_axi_arprot ),
		.mem_axi_rvalid (core0_axi_rvalid ),
		.mem_axi_rready (core0_axi_rready ),
		.mem_axi_rdata  (core0_axi_rdata  ),
		.irq            (irq            ),
`ifdef RISCV_FORMAL
		.rvfi_valid     (rvfi_valid     ),
		.rvfi_order     (rvfi_order     ),
		.rvfi_insn      (rvfi_insn      ),
		.rvfi_trap      (rvfi_trap      ),
		.rvfi_halt      (rvfi_halt      ),
		.rvfi_intr      (rvfi_intr      ),
		.rvfi_rs1_addr  (rvfi_rs1_addr  ),
		.rvfi_rs2_addr  (rvfi_rs2_addr  ),
		.rvfi_rs1_rdata (rvfi_rs1_rdata ),
		.rvfi_rs2_rdata (rvfi_rs2_rdata ),
		.rvfi_rd_addr   (rvfi_rd_addr   ),
		.rvfi_rd_wdata  (rvfi_rd_wdata  ),
		.rvfi_pc_rdata  (rvfi_pc_rdata  ),
		.rvfi_pc_wdata  (rvfi_pc_wdata  ),
		.rvfi_mem_addr  (rvfi_mem_addr  ),
		.rvfi_mem_rmask (rvfi_mem_rmask ),
		.rvfi_mem_wmask (rvfi_mem_wmask ),
		.rvfi_mem_rdata (rvfi_mem_rdata ),
		.rvfi_mem_wdata (rvfi_mem_wdata ),
`endif
		.trace_valid    (trace_valid0   ),
		.trace_data     (trace_data0    )
	);

	picorv32_axi #(
`ifndef SYNTH_TEST
`ifdef SP_TEST
		.ENABLE_REGS_DUALPORT(0),
`endif
`ifdef COMPRESSED_ISA
		.COMPRESSED_ISA(1),
`endif
		.ENABLE_MUL(1),
		.ENABLE_DIV(1),
		.ENABLE_IRQ(1),
		.ENABLE_TRACE(1)
`endif
	) uut1 (
		.clk            (clk               ),
		.resetn         (resetn            ),
		.trap           (trap1             ),
		.mem_axi_awvalid(core1_axi_awvalid),
		.mem_axi_awready(core1_axi_awready),
		.mem_axi_awaddr (core1_axi_awaddr ),
		.mem_axi_awprot (core1_axi_awprot ),
		.mem_axi_wvalid (core1_axi_wvalid ),
		.mem_axi_wready (core1_axi_wready ),
		.mem_axi_wdata  (core1_axi_wdata  ),
		.mem_axi_wstrb  (core1_axi_wstrb  ),
		.mem_axi_bvalid (core1_axi_bvalid ),
		.mem_axi_bready (core1_axi_bready ),
		.mem_axi_arvalid(core1_axi_arvalid),
		.mem_axi_arready(core1_axi_arready),
		.mem_axi_araddr (core1_axi_araddr ),
		.mem_axi_arprot (core1_axi_arprot ),
		.mem_axi_rvalid (core1_axi_rvalid ),
		.mem_axi_rready (core1_axi_rready ),
		.mem_axi_rdata  (core1_axi_rdata  ),
		.irq            (irq            ),
`ifdef RISCV_FORMAL
		.rvfi_valid     (/* unused */   ),
		.rvfi_order     (/* unused */   ),
		.rvfi_insn      (/* unused */   ),
		.rvfi_trap      (/* unused */   ),
		.rvfi_halt      (/* unused */   ),
		.rvfi_intr      (/* unused */   ),
		.rvfi_rs1_addr  (/* unused */   ),
		.rvfi_rs2_addr  (/* unused */   ),
		.rvfi_rs1_rdata (/* unused */   ),
		.rvfi_rs2_rdata (/* unused */   ),
		.rvfi_rd_addr   (/* unused */   ),
		.rvfi_rd_wdata  (/* unused */   ),
		.rvfi_pc_rdata  (/* unused */   ),
		.rvfi_pc_wdata  (/* unused */   ),
		.rvfi_mem_addr  (/* unused */   ),
		.rvfi_mem_rmask (/* unused */   ),
		.rvfi_mem_wmask (/* unused */   ),
		.rvfi_mem_rdata (/* unused */   ),
		.rvfi_mem_wdata (/* unused */   ),
`endif
		.trace_valid    (trace_valid1   ),
		.trace_data     (trace_data1    )
	);

`ifdef RISCV_FORMAL
	picorv32_rvfimon rvfi_monitor (
		.clock          (clk           ),
		.reset          (!resetn       ),
		.rvfi_valid     (rvfi_valid    ),
		.rvfi_order     (rvfi_order    ),
		.rvfi_insn      (rvfi_insn     ),
		.rvfi_trap      (rvfi_trap     ),
		.rvfi_halt      (rvfi_halt     ),
		.rvfi_intr      (rvfi_intr     ),
		.rvfi_rs1_addr  (rvfi_rs1_addr ),
		.rvfi_rs2_addr  (rvfi_rs2_addr ),
		.rvfi_rs1_rdata (rvfi_rs1_rdata),
		.rvfi_rs2_rdata (rvfi_rs2_rdata),
		.rvfi_rd_addr   (rvfi_rd_addr  ),
		.rvfi_rd_wdata  (rvfi_rd_wdata ),
		.rvfi_pc_rdata  (rvfi_pc_rdata ),
		.rvfi_pc_wdata  (rvfi_pc_wdata ),
		.rvfi_mem_addr  (rvfi_mem_addr ),
		.rvfi_mem_rmask (rvfi_mem_rmask),
		.rvfi_mem_wmask (rvfi_mem_wmask),
		.rvfi_mem_rdata (rvfi_mem_rdata),
		.rvfi_mem_wdata (rvfi_mem_wdata)
	);
`endif

	reg [1023:0] firmware_file;
	reg skip_firmware_load;
	initial begin
		skip_firmware_load = $test$plusargs("nohex");
		if (!skip_firmware_load) begin
			if (!$value$plusargs("firmware=%s", firmware_file))
				firmware_file = "firmware/firmware.hex";
			$readmemh(firmware_file, mem.memory);
		end
	end

	integer cycle_counter;
	wire tests_passed_any = tests_passed;
	wire tests_passed_all = (NUM_CORES > 1) ? (core0_passed & core1_passed) : core0_passed;
	wire tests_passed_effective = require_all_harts ? tests_passed_all : tests_passed_any;

	always @(posedge clk) begin
		cycle_counter <= resetn ? cycle_counter + 1 : 0;
		if (resetn && trap) begin
`ifndef VERILATOR
			repeat (10) @(posedge clk);
`endif
			$display("TRAP after %1d clock cycles", cycle_counter);
			if (tests_passed_effective) begin
				$display("ALL TESTS PASSED.");
				$finish;
			end else begin
				$display("ERROR!");
				if ($test$plusargs("noerror"))
					$finish;
				$stop;
			end
		end
	end
endmodule

module axi4_memory #(
	parameter AXI_TEST = 0,
	parameter VERBOSE = 0
) (
	/* verilator lint_off MULTIDRIVEN */

	input             clk,
	input             mem_axi_awvalid,
	output reg        mem_axi_awready,
	input      [31:0] mem_axi_awaddr,
	input      [ 2:0] mem_axi_awprot,

	input             mem_axi_wvalid,
	output reg        mem_axi_wready,
	input      [31:0] mem_axi_wdata,
	input      [ 3:0] mem_axi_wstrb,

	output reg        mem_axi_bvalid,
	input             mem_axi_bready,

	input             mem_axi_arvalid,
	output reg        mem_axi_arready,
	input      [31:0] mem_axi_araddr,
	input      [ 2:0] mem_axi_arprot,

	output reg        mem_axi_rvalid,
	input             mem_axi_rready,
	output reg [31:0] mem_axi_rdata,

	output reg        tests_passed
);
	reg [31:0]   memory [0:128*1024/4-1] /* verilator public */;
	reg [31:0]   pass_reg;
	reg verbose;
	initial verbose = $test$plusargs("verbose") || VERBOSE;

	reg axi_test;
	initial axi_test = $test$plusargs("axi_test") || AXI_TEST;

	initial begin
		mem_axi_awready = 0;
		mem_axi_wready = 0;
		mem_axi_bvalid = 0;
		mem_axi_arready = 0;
		mem_axi_rvalid = 0;
		tests_passed = 0;
		pass_reg = 0;
	end

	reg [63:0] xorshift64_state = 64'd88172645463325252;

	task xorshift64_next;
		begin
			// see page 4 of Marsaglia, George (July 2003). "Xorshift RNGs". Journal of Statistical Software 8 (14).
			xorshift64_state = xorshift64_state ^ (xorshift64_state << 13);
			xorshift64_state = xorshift64_state ^ (xorshift64_state >>  7);
			xorshift64_state = xorshift64_state ^ (xorshift64_state << 17);
		end
	endtask

	reg [2:0] fast_axi_transaction = ~0;
	reg [4:0] async_axi_transaction = ~0;
	reg [4:0] delay_axi_transaction = 0;

	always @(posedge clk) begin
		if (axi_test) begin
				xorshift64_next;
				{fast_axi_transaction, async_axi_transaction, delay_axi_transaction} <= xorshift64_state;
		end
	end

	reg latched_raddr_en = 0;
	reg latched_waddr_en = 0;
	reg latched_wdata_en = 0;

	reg fast_raddr = 0;
	reg fast_waddr = 0;
	reg fast_wdata = 0;

	reg [31:0] latched_raddr;
	reg [31:0] latched_waddr;
	reg [31:0] latched_wdata;
	reg [ 3:0] latched_wstrb;
	reg        latched_rinsn;

	task handle_axi_arvalid; begin
		mem_axi_arready <= 1;
		latched_raddr = mem_axi_araddr;
		latched_rinsn = mem_axi_arprot[2];
		latched_raddr_en = 1;
		fast_raddr <= 1;
	end endtask

	task handle_axi_awvalid; begin
		mem_axi_awready <= 1;
		latched_waddr = mem_axi_awaddr;
		latched_waddr_en = 1;
		fast_waddr <= 1;
	end endtask

	task handle_axi_wvalid; begin
		mem_axi_wready <= 1;
		latched_wdata = mem_axi_wdata;
		latched_wstrb = mem_axi_wstrb;
		latched_wdata_en = 1;
		fast_wdata <= 1;
	end endtask

	task handle_axi_rvalid; begin
		if (verbose)
			$display("RD: ADDR=%08x DATA=%08x%s", latched_raddr, memory[latched_raddr >> 2], latched_rinsn ? " INSN" : "");
		if (latched_raddr < 128*1024) begin
			mem_axi_rdata <= memory[latched_raddr >> 2];
			mem_axi_rvalid <= 1;
			latched_raddr_en = 0;
		end else if (latched_raddr == 32'h2000_0000) begin
			mem_axi_rdata <= pass_reg;
			mem_axi_rvalid <= 1;
			latched_raddr_en = 0;
		end else begin
			$display("OUT-OF-BOUNDS MEMORY READ FROM %08x", latched_raddr);
			$finish;
		end
	end endtask

	task handle_axi_bvalid; begin
		if (verbose)
			$display("WR: ADDR=%08x DATA=%08x STRB=%04b", latched_waddr, latched_wdata, latched_wstrb);
		if (latched_waddr < 128*1024) begin
			if (latched_wstrb[0]) memory[latched_waddr >> 2][ 7: 0] <= latched_wdata[ 7: 0];
			if (latched_wstrb[1]) memory[latched_waddr >> 2][15: 8] <= latched_wdata[15: 8];
			if (latched_wstrb[2]) memory[latched_waddr >> 2][23:16] <= latched_wdata[23:16];
			if (latched_wstrb[3]) memory[latched_waddr >> 2][31:24] <= latched_wdata[31:24];
		end else
		if (latched_waddr == 32'h1000_0000) begin
			if (verbose) begin
				if (32 <= latched_wdata && latched_wdata < 128)
					$display("OUT: '%c'", latched_wdata[7:0]);
				else
					$display("OUT: %3d", latched_wdata);
			end else begin
				$write("%c", latched_wdata[7:0]);
`ifndef VERILATOR
				$fflush();
`endif
			end
		end else
		if (latched_waddr == 32'h2000_0000) begin
			pass_reg <= latched_wdata;
			if (latched_wdata == 123456789)
				tests_passed = 1;
		end else begin
			$display("OUT-OF-BOUNDS MEMORY WRITE TO %08x", latched_waddr);
			$finish;
		end
		mem_axi_bvalid <= 1;
		latched_waddr_en = 0;
		latched_wdata_en = 0;
	end endtask

	always @(negedge clk) begin
		if (mem_axi_arvalid && !(latched_raddr_en || fast_raddr) && async_axi_transaction[0]) handle_axi_arvalid;
		if (mem_axi_awvalid && !(latched_waddr_en || fast_waddr) && async_axi_transaction[1]) handle_axi_awvalid;
		if (mem_axi_wvalid  && !(latched_wdata_en || fast_wdata) && async_axi_transaction[2]) handle_axi_wvalid;
		if (!mem_axi_rvalid && latched_raddr_en && async_axi_transaction[3]) handle_axi_rvalid;
		if (!mem_axi_bvalid && latched_waddr_en && latched_wdata_en && async_axi_transaction[4]) handle_axi_bvalid;
	end

	always @(posedge clk) begin
		mem_axi_arready <= 0;
		mem_axi_awready <= 0;
		mem_axi_wready <= 0;

		fast_raddr <= 0;
		fast_waddr <= 0;
		fast_wdata <= 0;

		if (mem_axi_rvalid && mem_axi_rready) begin
			mem_axi_rvalid <= 0;
		end

		if (mem_axi_bvalid && mem_axi_bready) begin
			mem_axi_bvalid <= 0;
		end

		if (mem_axi_arvalid && mem_axi_arready && !fast_raddr) begin
			latched_raddr = mem_axi_araddr;
			latched_rinsn = mem_axi_arprot[2];
			latched_raddr_en = 1;
		end

		if (mem_axi_awvalid && mem_axi_awready && !fast_waddr) begin
			latched_waddr = mem_axi_awaddr;
			latched_waddr_en = 1;
		end

		if (mem_axi_wvalid && mem_axi_wready && !fast_wdata) begin
			latched_wdata = mem_axi_wdata;
			latched_wstrb = mem_axi_wstrb;
			latched_wdata_en = 1;
		end

		if (mem_axi_arvalid && !(latched_raddr_en || fast_raddr) && !delay_axi_transaction[0]) handle_axi_arvalid;
		if (mem_axi_awvalid && !(latched_waddr_en || fast_waddr) && !delay_axi_transaction[1]) handle_axi_awvalid;
		if (mem_axi_wvalid  && !(latched_wdata_en || fast_wdata) && !delay_axi_transaction[2]) handle_axi_wvalid;

		if (!mem_axi_rvalid && latched_raddr_en && !delay_axi_transaction[3]) handle_axi_rvalid;
		if (!mem_axi_bvalid && latched_waddr_en && latched_wdata_en && !delay_axi_transaction[4]) handle_axi_bvalid;
	end
endmodule
