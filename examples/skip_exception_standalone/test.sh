#!/bin/bash
# Test script for PicoRV32 Skip Exception Handler (Standalone Version)

set -e

TESTBENCH="../../testbench_cli"
ELF="skip_exception_standalone.elf"

echo "========================================"
echo "PicoRV32 Skip Exception Test"
echo "Standalone Version"
echo "========================================"
echo ""

# Check if testbench exists
if [ ! -f "$TESTBENCH" ]; then
    echo "❌ Error: testbench_cli not found at $TESTBENCH"
    echo "   Please build it first: cd ../.. && make testbench_cli"
    exit 1
fi

# Build if needed
if [ ! -f "$ELF" ]; then
    echo "Building..."
    make
    echo ""
fi

# Run test
echo "Running test..."
echo "----------------------------------------"
if $TESTBENCH "$ELF" 2>&1 | tee test_output.log | grep -q "ALL TESTS PASSED"; then
    echo ""
    echo "✅ TEST PASSED"
    
    # Extract stats
    CYCLES=$(grep "Cycles:" test_output.log | awk '{print $2}')
    TIME=$(grep "Time:" test_output.log | awk '{print $2}')
    
    echo "   Cycles: $CYCLES"
    echo "   Time: $TIME"
    echo ""
    
    rm -f test_output.log
    exit 0
else
    echo ""
    echo "❌ TEST FAILED"
    echo ""
    echo "Output saved to: test_output.log"
    exit 1
fi
