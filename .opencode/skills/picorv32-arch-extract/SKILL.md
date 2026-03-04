---
name: picorv32-arch-extract
description: Extract full picorv32 config inventory, hierarchy, and inter-module connectivity across configuration matrices
compatibility: opencode
metadata:
  repo: picorv32
  domain: rtl-architecture
---

## What I do

- Build a complete configuration inventory for `picorv32` family modules.
- Extract elaborated module hierarchy (parent -> child) from HDL elaboration output.
- Extract inter-instance connectivity (instance -> instance, grouped by shared signals).
- Generate machine-readable JSON and human-readable graph/report artifacts.
- Explain which parameters change structure vs behavior-only logic.

## When to use me

Use this skill when you need a reproducible architecture extraction pipeline for:

- `picorv32` core only
- `picorv32_axi` / `picorv32_wb` shell views
- `testbench.v` `picorv32_wrapper` system view

Use this skill before security review, differential fuzzing, or migration to another RISC-V core.

## Preconditions

- Work from repo root: `/home/canxin/Git/riscv_research/picorv32`
- Required: `python3`, `verilator`
- Optional: `yosys` (for cross-check netlist hierarchy; not mandatory)

Current environment note: `verilator` is available, `yosys` may be absent.

## Phase 1: Build config inventory (static)

1. Enumerate parameterized modules from RTL:
   - `picorv32.v` modules: `picorv32`, `picorv32_axi`, `picorv32_wb`, `picorv32_pcpi_mul`, `picorv32_pcpi_fast_mul`.
   - `testbench.v` modules: `picorv32_wrapper`, `testbench`, `axi4_memory`.
2. Record each parameter with:
   - `module`
   - `name`
   - `default`
   - `type/width`
   - `doc_text` (from `README.md` if present)
3. Produce `param_inventory.json`.

Recommended output item format:

```json
{
  "module": "picorv32",
  "name": "ENABLE_DIV",
  "default": "1'h0",
  "width": "[0:0]",
  "doc": "Enables internal picorv32_pcpi_div for DIV/REM instructions."
}
```

## Phase 2: Build parameter influence map (static)

For every parameter, classify each use-site as:

- `structural`: used in `generate if`, module existence, or macro-based module replacement.
- `interface`: changes ports/protocol shape or wrapper behavior.
- `behavioral`: changes datapath/control logic but not module tree.
- `derived`: used only in localparams/derived expressions.

Required picorv32-specific rules:

- `ENABLE_MUL`, `ENABLE_FAST_MUL`, `ENABLE_DIV` -> structural (`pcpi_*` module instantiation).
- `PICORV32_REGS` macro path -> structural alternate register-file module.
- `STBUF_*`, `FENCE_DRAIN_STBUF` -> primarily behavioral (store-buffer policy), usually no module count delta.
- `LATCHED_MEM_RDATA` exists in `picorv32` only (not exposed by `picorv32_axi` / `picorv32_wb`).

Produce `param_influence_map.json`.

## Phase 3: Define config matrix

Create two matrix tiers:

1. **Structure matrix** (small, must toggle hierarchy-affecting options):
   - Baseline
   - `ENABLE_MUL=1`
   - `ENABLE_FAST_MUL=1`
   - `ENABLE_DIV=1`
   - `ENABLE_MUL=1,ENABLE_DIV=1`
   - `PICORV32_REGS` macro-enabled run (if custom regfile module is provided)

2. **Behavior matrix** (focus on ordering/control options):
   - Existing store-buffer set (`default`, `sb`, `sb-bypass`, `sb-fence-nop`)
   - Optionally include `COMPRESSED_ISA`, `TWO_CYCLE_ALU`, `TWO_CYCLE_COMPARE`, IRQ combinations

Keep matrix metadata in `matrix_manifest.json`.

## Phase 4: Elaborate with Verilator

Use Verilator elaboration artifacts as ground truth for instantiated hierarchy.

Example commands:

```bash
verilator --xml-only --xml-output build_result/arch/core_default.xml --top-module picorv32 picorv32.v -Wno-fatal
verilator --xml-only --xml-output build_result/arch/core_mul_div.xml --top-module picorv32 picorv32.v -GENABLE_MUL=1 -GENABLE_DIV=1 -Wno-fatal
verilator --xml-only --xml-output build_result/arch/wrapper_sb.xml --top-module picorv32_wrapper testbench.v picorv32.v -GSTBUF_ENABLE=1 -Wno-fatal
```

Notes:

- New Verilator versions warn that `--xml-only` is deprecated in favor of `--json-only`; keep parser compatibility in mind.
- If elaboration fails for one matrix point, record the failure in manifest and continue remaining points.

## Phase 5: Parse hierarchy + connectivity

From each elaboration artifact extract:

- `nodes`: instance path, instance name, resolved module variant, parent path.
- `hierarchy_edges`: parent-path -> child-path.
- `connection_edges`: instance-level directed/undirected links inferred from shared signal endpoints.
- `params_all_modules`: parameter values for every elaborated module variant (not only top module).

Minimum JSON schema:

```json
{
  "config_id": "core_mul_div",
  "top_path": "picorv32",
  "params": {
    "top_module": {"ENABLE_MUL": {"raw": "1'h1", "int": 1}},
    "modules": {
      "picorv32": {"ENABLE_DIV": {"raw": "1'h1", "int": 1}},
      "picorv32_pcpi_mul": {"STEPS_AT_ONCE": {"raw": "32'sh1", "int": 1}}
    }
  },
  "nodes": [],
  "hierarchy_edges": [],
  "connection_edges": []
}
```

## Phase 6: Generate deliverables

Produce these artifacts per run:

- `*.arch.json`: full machine-readable architecture graph.
- `matrix_manifest.json`: config index and summary counts.
- `visuals/mermaid/*.hierarchy.mmd`: full hierarchy diagrams.
- `visuals/mermaid/*.overview.mmd`: top-level interaction diagrams.
- `visuals/diff/*.diff.json`: baseline-vs-target structural + param deltas.
- `architecture_report.md`: concise explanation of stable vs changing architecture.

## Phase 7: Quality gates

A run is complete only if all checks pass:

1. Parameter coverage: every declared parameter appears in inventory.
2. Parsing coverage: every matrix point produces parseable elaboration output.
3. Graph sanity: no dangling node references in edges.
4. Diff sanity: changed params must be reflected in either structural or behavioral delta notes.
5. Reproducibility: re-run same matrix and verify unchanged counts/checksums.

## Existing implementation in this repo

Use these scripts as the current baseline pipeline:

- `tools/arch_graph/picorv32_arch_pipeline.py`
- `tools/arch_graph/picorv32_arch_visualize.py`
- `tools/arch_graph/picorv32_arch_semantic.py`

These scripts already produce hierarchy/connectivity/diff outputs under:

- `build_result/arch/`
- `build_result/arch/visuals/`

## Expected final AI response format

When reporting results, include:

1. Config matrix and rationale.
2. Module tree (top 2-3 levels) with parent-child edges.
3. Parameter delta table per compared config.
4. Connectivity summary (top links + key signals).
5. Structural vs behavioral impact summary.
6. Paths to generated JSON/diagram/report artifacts.

Do not claim complete extraction if only one matrix point was elaborated.
