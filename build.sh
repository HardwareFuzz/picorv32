#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./build.sh [--coverage] [--no-coverage] [--clean] [--help] [-- extra_verilator_args...]

Build the Verilator CLI testbench (testbench_cli). Pass --coverage to build a
coverage-instrumented binary (testbench_cli_cov). Extra arguments after "--"
are forwarded to the Verilator command.
EOF
}

COVERAGE=0
CLEAN=0
EXTRA_VERILATOR_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --coverage|-c) COVERAGE=1 ;;
        --no-coverage|-n) COVERAGE=0 ;;
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

if (( COVERAGE )); then
    OUT_DIR="${OUT_DIR:-$BUILD_ROOT/picorv32_cov_dir}"
    OUT_BIN="${OUT_BIN:-$BUILD_ROOT/picorv32_cov}"
else
    OUT_DIR="${OUT_DIR:-$BUILD_ROOT/picorv32_dir}"
    OUT_BIN="${OUT_BIN:-$BUILD_ROOT/picorv32}"
fi

if (( CLEAN )); then
    rm -rf "$OUT_DIR" "$OUT_BIN"
fi

VERILATOR_CMD=(
    "$VERILATOR" --cc --exe -Wno-lint --trace
    --top-module "$TOP_MODULE"
    "${SOURCES[@]}"
    -DVERBOSE_DEBUG -DREGS_INIT_ZERO=1
    --Mdir "$OUT_DIR"
)

if [[ -n "$COMPRESSED_FLAG" ]]; then
    VERILATOR_CMD+=("$COMPRESSED_FLAG")
fi

if (( COVERAGE )); then
    VERILATOR_CMD+=(--coverage)
fi

VERILATOR_CMD+=("${EXTRA_VERILATOR_ARGS[@]}")

echo "Running Verilator:"
printf '  %q' "${VERILATOR_CMD[@]}"
echo

"${VERILATOR_CMD[@]}"

make -C "$OUT_DIR" -f "V${TOP_MODULE}.mk"
cp "$OUT_DIR/V${TOP_MODULE}" "$OUT_BIN"

if (( COVERAGE )); then
    echo "Built coverage-enabled binary: $OUT_BIN (output dir: $OUT_DIR)"
else
    echo "Built binary: $OUT_BIN (output dir: $OUT_DIR)"
fi
