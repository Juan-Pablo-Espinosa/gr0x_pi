#!/bin/bash
# ============================================================
# Test 03: Try 500 kbps as fallback
# Run this only if test_01 found nothing at 1 Mbps
# ============================================================
echo "=== Switching to 500 kbps ==="
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 500000 restart-ms 100
sleep 0.2
ip -details link show can0

echo ""
echo "Now run: python3 test_01_scan.py"
echo "If found, update /etc/network/interfaces or systemd-networkd to use 500kbps"
echo "Then run MotorStudio to change back to 1 Mbps permanently."