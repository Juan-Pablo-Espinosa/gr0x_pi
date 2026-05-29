#!/bin/bash
# CAN setup with SPI-safe settings and generous TX queue
echo "=== Bringing up can0 ==="
sudo ip link set can0 down 2>/dev/null
sleep 0.2
sudo ip link set can0 up type can bitrate 1000000 restart-ms 100
sudo ip link set can0 txqueuelen 1000
sleep 0.3
echo ""
echo "=== Interface status ==="
ip -details -statistics link show can0
echo ""
echo "=== Recent kernel messages for mcp251xfd ==="
dmesg | tail -20 | grep -i "mcp\|can\|spi" || echo "(no recent CAN kernel messages)"