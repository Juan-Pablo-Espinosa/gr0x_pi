#!/usr/bin/env python3
"""
Test 01: RobStride Motor ID Scanner (emoji-free version)
"""

import can
import time

INTERFACE = 'can0'

def make_enable_id(host_id, motor_id):
    return (0x3 << 24) | (host_id << 8) | (motor_id & 0xFF)

def scan_motor(bus, motor_id, host_id=0xFD, timeout=0.03):
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

    try:
        bus = can.interface.Bus(channel=INTERFACE, interface='socketcan')
    except Exception as e:
        print("ERROR: Cannot open %s: %s" % (INTERFACE, e))
        print("Run: sudo ip link set can0 up type can bitrate 1000000 restart-ms 100")
        return

    found = []

    # Pass 1: Just listen — motor may broadcast on power-up
    print("\nPass 1: Listening for spontaneous motor messages (2 seconds)...")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        msg = bus.recv(timeout=0.1)
        if msg is not None:
            comm_type = (msg.arbitration_id >> 24) & 0x1F
            src_id    = (msg.arbitration_id >> 8) & 0xFF
            dst_id    =  msg.arbitration_id & 0xFF
            print("  SPONTANEOUS: id=0x%08X  comm_type=0x%02X  src=%d  dst=%d  data=%s"
                  % (msg.arbitration_id, comm_type, src_id, dst_id, msg.data.hex()))

    # Pass 2: host_id = 0xFD (official default per RobStride manual)
    print("\nPass 2: Active scan with host_id=0xFD (official default)...")
    for mid in range(1, 128):
        ok, reply = scan_motor(bus, mid, host_id=0xFD)
        if ok:
            print("  FOUND motor at ID=%d (0x%02X)  reply_id=0x%08X  data=%s"
                  % (mid, mid, reply.arbitration_id, reply.data.hex()))
            found.append((mid, 0xFD))
        elif isinstance(reply, str):
            print("  BUS ERROR at ID=%d: %s" % (mid, reply))
            break
        time.sleep(0.002)

    # Pass 3: host_id = 0x00 (some implementations use this)
    print("\nPass 3: Active scan with host_id=0x00 (alternate)...")
    for mid in range(1, 128):
        ok, reply = scan_motor(bus, mid, host_id=0x00)
        if ok:
            print("  FOUND motor at ID=%d (0x%02X)  reply_id=0x%08X  data=%s"
                  % (mid, mid, reply.arbitration_id, reply.data.hex()))
            found.append((mid, 0x00))
        time.sleep(0.002)

    bus.shutdown()

    print("\n" + "=" * 60)
    if found:
        print("SCAN COMPLETE. Motors found: %s" % str(found))
        print("Update MOTOR_ID and HOST_ID in test_02_enable_hold.py with these values.")
    else:
        print("SCAN COMPLETE. No motors responded.")
        print("")
        print("Next steps to try:")
        print("  1. Power cycle the motor (48V off 10s, back on, wait 3s, re-run scan)")
        print("  2. Try 500 kbps: bash test_03_bitrate_fallback.sh then re-run scan")
        print("  3. Remove JP1 jumper on PiCAN (leave only motor's 120 ohm)")
    print("=" * 60)

if __name__ == '__main__':
    main()