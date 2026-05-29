#!/usr/bin/env python3
"""
Test 01: RobStride Motor ID Scanner
Tries every possible motor ID from 1 to 127 using the Private Protocol.
Uses BOTH host_id=0x00 and host_id=0xFD (the two variants seen in the wild).

IMPORTANT: Motor MUST be powered on and CAN interface up before running.
Run: sudo ip link set can0 up type can bitrate 1000000 restart-ms 100

Expected output: "FOUND motor at ID=X" when the motor responds.
"""

import can
import time
import struct

INTERFACE = 'can0'

def float_to_uint(x, x_min, x_max, bits=16):
    x = max(min(x, x_max), x_min)
    return int((x - x_min) * ((1 << bits) - 1) / (x_max - x_min))

def make_enable_id(host_id, motor_id):
    """Type 0x03: Enable Motor — CAN ID = (0x3 << 24) | (host_id << 8) | motor_id"""
    return (0x3 << 24) | (host_id << 8) | (motor_id & 0xFF)

def make_get_id_cmd(motor_id):
    """Type 0x00: Get Motor ID — used as a ping"""
    return (0x00 << 24) | (0x00 << 8) | (motor_id & 0xFF)

def scan_motor(bus, motor_id, host_id=0xFD, timeout=0.03):
    """
    Send enable command to a motor ID and listen for any response.
    Returns True if motor replies.
    """
    can_id = make_enable_id(host_id, motor_id)
    msg = can.Message(
        arbitration_id=can_id,
        data=bytes(8),
        is_extended_id=True,
    )
    try:
        bus.send(msg)
    except can.CanError as e:
        return False, str(e)

    # Listen for any incoming frame (the motor echoes back feedback Type 0x02)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = bus.recv(timeout=0.005)
        if reply is not None:
            return True, reply
    return False, None

def main():
    print("=" * 60)
    print("RobStride Motor ID Scanner")
    print("Scanning IDs 1-127 with host_id=0xFD and host_id=0x00")
    print("=" * 60)
    print()

    try:
        bus = can.interface.Bus(channel=INTERFACE, interface='socketcan')
    except Exception as e:
        print(f"ERROR: Cannot open {INTERFACE}: {e}")
        print("Did you run: sudo ip link set can0 up type can bitrate 1000000 restart-ms 100")
        return

    found = []

    # --- Pass 1: Quick broadcast — just listen for spontaneous motor messages ---
    print("Pass 1: Listening for spontaneous motor messages (2 seconds)...")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        msg = bus.recv(timeout=0.1)
        if msg is not None:
            comm_type = (msg.arbitration_id >> 24) & 0x1F
            src_id    = (msg.arbitration_id >> 8) & 0xFF
            dst_id    =  msg.arbitration_id & 0xFF
            print(f"  SPONTANEOUS FRAME: id=0x{msg.arbitration_id:08X}  "
                  f"comm_type=0x{comm_type:02X}  src={src_id}  dst={dst_id}  "
                  f"data={msg.data.hex()}")

    print()
    print("Pass 2: Active scan with host_id=0xFD (official default)...")
    for mid in range(1, 128):
        ok, reply = scan_motor(bus, mid, host_id=0xFD)
        if ok:
            print(f"  ✅ FOUND motor at ID={mid} (0x{mid:02X})  "
                  f"reply_id=0x{reply.arbitration_id:08X}  data={reply.data.hex()}")
            found.append((mid, 0xFD))
        elif isinstance(reply, str):
            print(f"  ERROR at ID={mid}: {reply}")
            break
        time.sleep(0.002)

    print()
    print("Pass 3: Active scan with host_id=0x00 (alternate)...")
    for mid in range(1, 128):
        ok, reply = scan_motor(bus, mid, host_id=0x00)
        if ok:
            print(f"  ✅ FOUND motor at ID={mid} (0x{mid:02X})  "
                  f"reply_id=0x{reply.arbitration_id:08X}  data={reply.data.hex()}")
            found.append((mid, 0x00))
        time.sleep(0.002)

    bus.shutdown()
    print()
    print("=" * 60)
    if found:
        print(f"SCAN COMPLETE. Found motors: {found}")
        print("Use the motor_id and host_id from above in test_02.")
    else:
        print("SCAN COMPLETE. No motors responded.")
        print("Possible causes:")
        print("  - Motor ID was set to 0 or >127 (unlikely but possible)")
        print("  - Bitrate mismatch: try running at 500kbps and re-scan")
        print("  - ADM3055E transceiver issue: see test_03 for fallback")
    print("=" * 60)

if __name__ == '__main__':
    main()