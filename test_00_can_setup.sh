#!/bin/bash
# ============================================================
# Test 0: Bring up CAN interface correctly
# Run this before ANY other test
# ============================================================
echo "=== Bringing up can0 at 1 Mbps ==="
sudo ip link set can0 down 2>/dev/null
sudo ip link set can0 up type can bitrate 1000000 restart-ms 100
sleep 0.2
echo ""
echo "=== Interface status ==="
ip -details -statistics link show can0
echo ""
echo "If state shows ERROR-ACTIVE with berr-counter tx 0 rx 0 → ready"
echo "If state shows STOPPED → driver issue, check dmesg"
