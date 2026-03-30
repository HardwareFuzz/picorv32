#!/usr/bin/env bash
set -euo pipefail

usage() {
	cat <<'EOF'
Usage:
	./build.sh --isa <rv32|rv32f|rv32fd|rv64|rv64f|rv64fd> --cores N \
	          [--out-dir DIR] [--coverage|--coverage-light|--no-coverage] [--clean] [--help] \
	          [-- extra_verilator_args...]

Notes:
	- PicoRV32 build supports only --isa rv32 (others error).
	- Extra arguments after "--" are forwarded to Verilator.
	- Use --out-dir (or env CX_OUT_DIR / OUT_DIR) to place the final binary in a
	  shared artifacts folder. Intermediate Verilator files stay under build_result/.

Output naming:
	<out-dir>/picorv32_<isa>_<N>c[_cov|_cov_light]
EOF
}

ISA=""
CORES="1"
OUT_DIR_OPT=""
COVERAGE_MODE="none"   # none|full|light
CLEAN=0
EXTRA_VERILATOR_ARGS=()

while [[ $# -gt 0 ]]; do
	case "$1" in
		--isa)
			ISA="$2"; shift
			;;
		--cores)
			CORES="$2"; shift
			;;
		--out-dir)
			OUT_DIR_OPT="$2"; shift
			;;
		--out-dir=*)
			OUT_DIR_OPT="${1#*=}"
			;;
		--coverage|-c) COVERAGE_MODE="full" ;;
		--coverage-light) COVERAGE_MODE="light" ;;
		--no-coverage|--no-cov|-n) COVERAGE_MODE="none" ;;
		--clean) CLEAN=1 ;;
		--help|-h) usage; exit 0 ;;
		--)
			shift
			EXTRA_VERILATOR_ARGS+=("$@")
			break
			;;
		*)
			echo "Unknown option: $1" >&2
			usage >&2
			exit 2
			;;
	esac
	shift || true
done

if [[ -z "$ISA" ]]; then
	echo "Missing required --isa" >&2
	usage >&2
	exit 2
fi

case "$ISA" in
	rv32) ;;
	*)
		echo "Unsupported --isa for PicoRV32: $ISA (supported: rv32)" >&2
		exit 1
		;;
esac

if [[ ! "$CORES" =~ ^[0-9]+$ ]] || [[ "$CORES" -lt 1 ]]; then
	echo "Invalid --cores: $CORES" >&2
	exit 2
fi

if [[ "$CORES" -ne 1 ]]; then
	echo "This branch supports --cores 1 only (requested: $CORES)." >&2
	echo "Use cx-2hart-build for --cores 2." >&2
	exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VERILATOR="${VERILATOR:-verilator}"
BUILD_ROOT="${BUILD_ROOT:-${ROOT_DIR}/build_result}"
TOP_MODULE="picorv32_wrapper"
SOURCES=(testbench.v picorv32.v testbench_cli.cc)

OUT_DIR="${OUT_DIR_OPT:-${CX_OUT_DIR:-${OUT_DIR:-${BUILD_ROOT}}}}"
mkdir -p "$BUILD_ROOT" "$OUT_DIR"

COV_SUFFIX=""
case "$COVERAGE_MODE" in
	full) COV_SUFFIX="_cov" ;;
	light) COV_SUFFIX="_cov_light" ;;
	none) ;;
	*) echo "Internal error: unknown COVERAGE_MODE=$COVERAGE_MODE" >&2; exit 2 ;;
esac

ARTIFACT_NAME="picorv32_${ISA}_${CORES}c${COV_SUFFIX}"
MDIR="${BUILD_ROOT}/${ARTIFACT_NAME}_dir"
OUT_BIN="${OUT_BIN:-${OUT_DIR}/${ARTIFACT_NAME}}"

if (( CLEAN )); then
	rm -rf "$MDIR" "$OUT_BIN"
fi

VERILATOR_CMD=(
	"$VERILATOR" --cc --exe -Wno-lint --trace
	--top-module "$TOP_MODULE"
	"${SOURCES[@]}"
	-DVERBOSE_DEBUG -DREGS_INIT_ZERO=1 -DRISCV_FORMAL
	--Mdir "$MDIR"
)

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
make -C "$MDIR" -f "V${TOP_MODULE}.mk"
cp "$MDIR/V${TOP_MODULE}" "$OUT_BIN"
chmod +x "$OUT_BIN"

echo "Built binary: $OUT_BIN (work dir: $MDIR)"
