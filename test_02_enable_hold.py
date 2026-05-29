#!/usr/bin/env python3
"""
Test 02: Enable motor and hold at current position.
EDIT motor_id and host_id based on test_01 scan results.

RS-03 parameter ranges:
  position: -4π to +4π rad
  velocity: -50 to +50 rad/s
  Kp:       0 to 5000
  Kd:       0 to 100
  torque:   -60 to +60 Nm
"""

import can
import struct
import time
import sys

# ── EDIT THESE after running test_01_scan.py ────────────────────────────────
MOTOR_ID  = 127    # Default factory ID — change if scan found a different one
HOST_ID   = 0xFD   # Official default; change to 0x00 if that worked in scan
INTERFACE = 'can0'
# ────────────────────────────────────────────────────────────────────────────

def float_to_uint(x, x_min, x_max, bits=16):
    x = max(min(x, x_max), x_min)
    return int((x - x_min) * ((1 << bits) - 1) / (x_max - x_min))

def uint_to_float(x, x_min, x_max, bits=16):
    return float(x) * (x_max - x_min) / ((1 << bits) - 1) + x_min

def enable_id():
    return (0x3 << 24) | (HOST_ID << 8) | MOTOR_ID

def stop_id():
    return (0x4 << 24) | (HOST_ID << 8) | MOTOR_ID

def control_id(torque_nm=0.0):
    t = float_to_uint(torque_nm, -60.0, 60.0)
    return (0x1 << 24) | (t << 8) | MOTOR_ID

def control_data(pos=0.0, vel=0.0, kp=10.0, kd=1.0):
    return struct.pack('>HHHH',
        float_to_uint(pos,  -12.566, 12.566),
        float_to_uint(vel,  -50.0,   50.0),
        float_to_uint(kp,     0.0, 5000.0),
        float_to_uint(kd,     0.0,  100.0),
    )

def decode_feedback(msg):
    if len(msg.data) < 8:
        return None
    ct = (msg.arbitration_id >> 24) & 0x1F
    if ct != 0x02:
        return None
    p, v, t = struct.unpack_from('>HHH', msg.data, 0)
    temp_raw = struct.unpack_from('>H', msg.data, 6)[0]
    return {
        'pos':  uint_to_float(p, -12.566, 12.566),
        'vel':  uint_to_float(v, -50.0,   50.0),
        'torque': uint_to_float(t, -60.0, 60.0),
        'temp_c': temp_raw / 10.0,
    }

def send(bus, arb_id, data=bytes(8)):
    msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=True)
    bus.send(msg)

def main():
    print(f"Connecting to {INTERFACE} | motor_id={MOTOR_ID} (0x{MOTOR_ID:02X}) | host_id=0x{HOST_ID:02X}")
    bus = can.interface.Bus(channel=INTERFACE, interface='socketcan')

    print(f"Sending ENABLE → CAN ID 0x{enable_id():08X}")
    send(bus, enable_id())
    time.sleep(0.1)

    # Flush any reply
    reply = bus.recv(timeout=0.05)
    if reply:
        fb = decode_feedback(reply)
        if fb:
            print(f"  Enable ACK: pos={fb['pos']:+.3f} rad  vel={fb['vel']:+.3f}  "
                  f"torque={fb['torque']:+.2f}Nm  temp={fb['temp_c']:.1f}°C")
        else:
            print(f"  Got frame: id=0x{reply.arbitration_id:08X}  data={reply.data.hex()}")
    else:
        print("  No reply to enable. Motor may not be at this ID — run test_01 first.")

    print("Holding zero position. Press Ctrl+C to stop.")
    t = 0
    try:
        while True:
            send(bus, control_id(0.0), control_data(0.0, 0.0, 10.0, 0.5))

            reply = bus.recv(timeout=0.002)
            if reply and t % 50 == 0:
                fb = decode_feedback(reply)
                if fb:
                    print(f"  pos={fb['pos']:+.3f} rad  vel={fb['vel']:+.3f}  "
                          f"torque={fb['torque']:+.2f}Nm  temp={fb['temp_c']:.1f}°C")
            t += 1
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nSending STOP...")
        send(bus, stop_id())
        time.sleep(0.05)

    bus.shutdown()
    print("Done. Motor stopped.")

if __name__ == '__main__':
    main()