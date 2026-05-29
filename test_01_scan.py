#!/usr/bin/env python3
"""
Test 01: RobStride Motor ID Scanner with BUS-OFF auto-recovery
Works around mcp251xfd driver lockup bug by resetting interface after each error.
"""

import can
import time
import subprocess
import os

INTERFACE = 'can0'
BITRATE   = 1000000

def reset_interface():
    """Bring CAN interface down and back up to clear BUS-OFF state."""
    subprocess.run(['sudo', 'ip', 'link', 'set', INTERFACE, 'down'],
                   capture_output=True)
    time.sleep(0.15)
    subprocess.run(['sudo', 'ip', 'link', 'set', INTERFACE, 'up',
                    'type', 'can', 'bitrate', str(BITRATE), 'restart-ms', '100'],
                   capture_output=True)
    subprocess.run(['sudo', 'ip', 'link', 'set', INTERFACE, 'txqueuelen', '1000'],
                   capture_output=True)
    time.sleep(0.2)

def open_bus():
    return can.interface.Bus(channel=INTERFACE, interface='socketcan')

def make_enable_id(host_id, motor_id):
    return (0x3 << 24) | (host_id << 8) | (motor_id & 0xFF)

def scan_one(motor_id, host_id):
    """
    Open a fresh bus, send one enable frame, listen for reply, close.
    Returns (True, reply_msg) or (False, None).
    Handles BUS-OFF by resetting and returning False.
    """
    try:
        bus = open_bus()
    except Exception as e:
        print("  Cannot open bus: %s" % e)
        return False, None

    can_id = make_enable_id(host_id, motor_id)
    msg = can.Message(arbitration_id=can_id, data=bytes(8), is_extended_id=True)

    try:
        bus.send(msg)
    except can.CanError:
        bus.shutdown()
        reset_interface()
        return False, None

    # Listen for any reply
    deadline = time.monotonic() + 0.025
    reply = None
    while time.monotonic() < deadline:
        r = bus.recv(timeout=0.005)
        if r is not None:
            reply = r
            break

    bus.shutdown()

    if reply:
        return True, reply

    # Check if BUS-OFF happened
    result = subprocess.run(
        ['ip', '-details', 'link', 'show', INTERFACE],
        capture_output=True, text=True
    )
    if 'BUS-OFF' in result.stdout or 'ERROR-PASSIVE' in result.stdout:
        reset_interface()

    return False, None

def main():
    print("=" * 60)
    print("RobStride Motor ID Scanner (BUS-OFF safe)")
    print("=" * 60)

    # Check we can run sudo without password (needed for reset)
    r = subprocess.run(['sudo', '-n', 'ip', 'link', 'show'],
                       capture_output=True)
    if r.returncode != 0:
        print("WARNING: sudo requires password. Interface resets may ask for it.")
        print("To fix: run 'sudo visudo' and add NOPASSWD for ip command,")
        print("or run this script with: sudo python3 test_01_scan.py")
        print()

    reset_interface()
    found = []

    # ── Pass 1: Just listen passively ────────────────────────────────────────
    print("\nPass 1: Listening for spontaneous motor messages (3 seconds)...")
    try:
        bus = open_bus()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            msg = bus.recv(timeout=0.1)
            if msg is not None:
                ct  = (msg.arbitration_id >> 24) & 0x1F
                src = (msg.arbitration_id >> 8)  & 0xFF
                dst =  msg.arbitration_id         & 0xFF
                print("  SPONTANEOUS: id=0x%08X  type=0x%02X  src=%d  dst=%d  data=%s"
                      % (msg.arbitration_id, ct, src, dst, msg.data.hex()))
        bus.shutdown()
    except Exception as e:
        print("  Listen error: %s" % e)

    # ── Pass 2: Active scan, host_id=0xFD ────────────────────────────────────
    print("\nPass 2: Scanning IDs 1-127 with host_id=0xFD ...")
    for mid in range(1, 128):
        ok, reply = scan_one(mid, 0xFD)
        if ok:
            print("  FOUND ID=%d (0x%02X)  host_id=0xFD  reply=0x%08X  data=%s"
                  % (mid, mid, reply.arbitration_id, reply.data.hex()))
            found.append((mid, 0xFD))
        if mid % 20 == 0:
            print("  ... scanned up to ID %d" % mid)
        time.sleep(0.005)

    # ── Pass 3: Active scan, host_id=0x00 ────────────────────────────────────
    print("\nPass 3: Scanning IDs 1-127 with host_id=0x00 ...")
    for mid in range(1, 128):
        ok, reply = scan_one(mid, 0x00)
        if ok:
            print("  FOUND ID=%d (0x%02X)  host_id=0x00  reply=0x%08X  data=%s"
                  % (mid, mid, reply.arbitration_id, reply.data.hex()))
            found.append((mid, 0x00))
        if mid % 20 == 0:
            print("  ... scanned up to ID %d" % mid)
        time.sleep(0.005)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if found:
        print("SUCCESS. Motors found: %s" % str(found))
        print("Edit MOTOR_ID and HOST_ID in test_02_enable_hold.py")
    else:
        print("No motors responded on either pass.")
        print()
        print("NEXT: Try 500 kbps (motor may have been left there by USB debugger)")
        print("  sudo ip link set can0 down")
        print("  sudo ip link set can0 up type can bitrate 500000 restart-ms 100")
        print("  sudo ip link set can0 txqueuelen 1000")
        print("  python3 test_01_scan.py")
        print()
        print("If still nothing: remove JP1 jumper on PiCAN, then retry.")
    print("=" * 60)

if __name__ == '__main__':
    main()