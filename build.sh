#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./build.sh [--coverage|--coverage-light|--no-coverage] [--cores N] [--clean] [--help] [-- extra_verilator_args...]

Build the Verilator CLI testbench (testbench_cli).
  --cores N          : set core count (default: 2)
  --coverage        : 全覆盖（Verilator --coverage，产物 picorv32_cov）
  --coverage-light  : 轻覆盖（只行/用户覆盖，禁 toggle，产物 picorv32_cov_light）
  --no-coverage     : 不启用覆盖（默认，产物 picorv32）
Extra arguments after "--" are forwarded to the Verilator command.
EOF
}

COVERAGE_MODE="none"   # none|full|light
CORES="${CORES:-2}"
CLEAN=0
EXTRA_VERILATOR_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --coverage|-c) COVERAGE_MODE="full" ;;
        --coverage-light) COVERAGE_MODE="light" ;;
        --no-coverage|-n) COVERAGE_MODE="none" ;;
        --cores) CORES="$2"; shift ;;
        --clean) CLEAN=1 ;;
        --help|-h) usage; exit 0 ;;
        --) shift; EXTRA_VERILATOR_ARGS+=("$@"); break ;;
        *) EXTRA_VERILATOR_ARGS+=("$1") ;;
    esac
    shift || true
done

VERILATOR="${VERILATOR:-verilator}"
BUILD_ROOT="${BUILD_ROOT:-build_result}"
TOP_MODULE="picorv32_wrapper"
SOURCES=(testbench.v picorv32.v testbench_cli.cc)

COMPRESSED_ISA="${COMPRESSED_ISA:-C}"
COMPRESSED_FLAG="${COMPRESSED_ISA/C/-DCOMPRESSED_ISA}"

mkdir -p "$BUILD_ROOT"

case "$COVERAGE_MODE" in
    full)
        OUT_DIR="${OUT_DIR:-$BUILD_ROOT/picorv32_${CORES}c_cov_dir}"
        OUT_BIN="${OUT_BIN:-$BUILD_ROOT/picorv32_${CORES}c_cov}"
        ;;
    light)
        OUT_DIR="${OUT_DIR:-$BUILD_ROOT/picorv32_${CORES}c_cov_light_dir}"
        OUT_BIN="${OUT_BIN:-$BUILD_ROOT/picorv32_${CORES}c_cov_light}"
        ;;
    none)
        OUT_DIR="${OUT_DIR:-$BUILD_ROOT/picorv32_${CORES}c_dir}"
        OUT_BIN="${OUT_BIN:-$BUILD_ROOT/picorv32_${CORES}c}"
        ;;
esac

if (( CLEAN )); then
    rm -rf "$OUT_DIR" "$OUT_BIN"
fi

VERILATOR_CMD=(
    "$VERILATOR" --cc --exe -Wno-lint --trace
    --top-module "$TOP_MODULE"
    "${SOURCES[@]}"
    -DVERBOSE_DEBUG -DREGS_INIT_ZERO=1
    -GNUM_CORES="$CORES"
    --Mdir "$OUT_DIR"
)

if [[ -n "$COMPRESSED_FLAG" ]]; then
    VERILATOR_CMD+=("$COMPRESSED_FLAG")
fi

case "$COVERAGE_MODE" in
    full) VERILATOR_CMD+=(--coverage) ;;
    light) VERILATOR_CMD+=(--coverage-line --coverage-user --coverage-max-width 0) ;;
    none) ;;
esac

VERILATOR_CMD+=("${EXTRA_VERILATOR_ARGS[@]}")

echo "Running Verilator:"
printf '  %q' "${VERILATOR_CMD[@]}"
echo

"${VERILATOR_CMD[@]}"

make -C "$OUT_DIR" -f "V${TOP_MODULE}.mk"
cp "$OUT_DIR/V${TOP_MODULE}" "$OUT_BIN"

echo "Built binary: $OUT_BIN (output dir: $OUT_DIR)"

# Also copy to fuzz bin directory if present
FUZZ_BIN_DIR="/home/canxin/Git/riscv_fuzz_test/riscv_impls_bins"
if [[ -d "$FUZZ_BIN_DIR" ]]; then
    cp -f "$OUT_BIN" "$FUZZ_BIN_DIR/$(basename "$OUT_BIN")"
    echo "Copied to $FUZZ_BIN_DIR/$(basename "$OUT_BIN")"
fi
