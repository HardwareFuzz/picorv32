# picorv32 architecture pipeline

This tool generates config-specific elaborated RTL XML with Verilator and
extracts two graph views:

- hierarchy edges (parent instance -> child instance)
- connectivity edges (instance -> instance, grouped by shared signals)

## Usage

Run from `picorv32/`:

```bash
python3 tools/arch_graph/picorv32_arch_pipeline.py
```

Then generate overview/hierarchy/diff visualizations and AI summary JSON:

```bash
python3 tools/arch_graph/picorv32_arch_visualize.py
```

Then run semantic domain tagging and security clustering:

```bash
python3 tools/arch_graph/picorv32_arch_semantic.py
```

For deep extraction (hierarchy + module internals + source metadata paths):

```bash
python3 tools/arch_graph/picorv32_arch_deep_extract.py
```

Default matrix:

- `1:default`
- `2:default`
- `2:sb`
- `2:sb-bypass`
- `2:sb-fence-nop`

Custom matrix example:

```bash
python3 tools/arch_graph/picorv32_arch_pipeline.py \
  --matrix 2:default 2:sb 2:sb-fence-nop --force
```

## Outputs

All outputs are written to `build_result/arch/`:

- `<config_id>.xml` (Verilator elaborated XML)
- `<config_id>.verilator.log` (Verilator log)
- `<config_id>.arch.json` (nodes + hierarchy_edges + connection_edges)
- `matrix_manifest.json` (summary index)

Visualization outputs are written to `build_result/arch/visuals/`:

- `mermaid/<config_id>.overview.mmd`
- `mermaid/<config_id>.hierarchy.mmd`
- `diff/<baseline>__vs__<config>.diff.mmd`
- `diff/<baseline>__vs__<config>.diff.json`
- `matrix_diffs.json`
- `matrix_ai_summary.json`
- `matrix_semantic_annotations.json`
- `matrix_security_clusters.json`
- `architecture_security_report.md`

Deep extraction outputs are written to `build_result/arch/deep/`:

- `<config_id>.deep.json` (hierarchy + module internals + metadata)
- `deep_manifest.json` (summary index)

`config_id` uses:

`p32_c{NUM_CORES}_sb{STBUF_ENABLE}_bp{STBUF_ALLOW_LOAD_BYPASS}_cs{STBUF_CONFLICT_STALL}_fd{FENCE_DRAIN_STBUF}`
