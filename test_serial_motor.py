#!/usr/bin/env python3
"""
RobStride RS-03 via official USB-CAN adapter.
Protocol from RobStride official manual:
  Frame header: 0x41 0x54  (ASCII "AT")
  Frame tail:   0x0D 0x0A  (CR LF)
  Full frame:   AT + [4 byte CAN ID little-endian] + [1 byte DLC] + [8 bytes data] + CRLF
  Total:        15 bytes per frame

DIP switches on adapter: SW1=OFF, SW2=ON (termination enabled)
Baud rate: 921600
"""

import serial
import struct
import time
import sys

PORT     = "/dev/ttyUSB0"
BAUD     = 921600
HOST_ID  = 0xFD

def float_to_uint(x, x_min, x_max, bits=16):
    x = max(min(x, x_max), x_min)
    return int((x - x_min) * ((1 << bits) - 1) / (x_max - x_min))

def uint_to_float(x, x_min, x_max, bits=16):
    return float(x) * (x_max - x_min) / ((1 << bits) - 1) + x_min

def make_frame(can_id_29bit, data8):
    """Build 15-byte serial frame."""
    assert len(data8) == 8
    eff_id = can_id_29bit | 0x80000000
    return (bytes([0x41, 0x54])
            + struct.pack('<I', eff_id)
            + bytes([8])
            + bytes(data8)
            + bytes([0x0D, 0x0A]))

def parse_frame(buf15):
    """Parse 15-byte frame. Returns (can_id_29bit, data_bytes) or None."""
    if len(buf15) < 15:
        return None
    if buf15[0] != 0x41 or buf15[1] != 0x54:
        return None
    raw_id = struct.unpack_from('<I', buf15, 2)[0]
    can_id = raw_id & 0x1FFFFFFF
    dlc    = buf15[6]
    data   = buf15[7:7 + min(dlc, 8)]
    return can_id, bytes(data)

def read_reply(ser, timeout=0.08):
    """Read for up to timeout seconds, return first valid parsed frame."""
    buf = b''
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        waiting = ser.in_waiting
        if waiting:
            buf += ser.read(waiting)
        else:
            time.sleep(0.002)
        while len(buf) >= 15:
            idx = -1
            for i in range(len(buf) - 1):
                if buf[i] == 0x41 and buf[i+1] == 0x54:
                    idx = i
                    break
            if idx < 0:
                buf = b''
                break
            if idx > 0:
                buf = buf[idx:]
            if len(buf) >= 15:
                result = parse_frame(buf[:15])
                buf = buf[15:]
                if result:
                    return result
    return None

def decode_feedback(can_id, data):
    ct = (can_id >> 24) & 0x1F
    if ct != 0x02 or len(data) < 8:
        return None
    pos_u, vel_u, trq_u = struct.unpack_from('>HHH', data, 0)
    temp_raw            = struct.unpack_from('>H',   data, 6)[0]
    return {
        'pos':    uint_to_float(pos_u, -12.566, 12.566),
        'vel':    uint_to_float(vel_u, -50.0,   50.0),
        'torque': uint_to_float(trq_u, -60.0,   60.0),
        'temp_c': temp_raw / 10.0,
    }

def send(ser, can_id, data=None):
    if data is None:
        data = bytes(8)
    frame = make_frame(can_id, data)
    ser.write(frame)
    ser.flush()
    return read_reply(ser)

def make_id(comm_type, area2, motor_id):
    return ((comm_type & 0x1F) << 24) | ((area2 & 0xFFFF) << 8) | (motor_id & 0xFF)

def main():
    motor_id = int(sys.argv[1]) if len(sys.argv) > 1 else 127

    print("=" * 55)
    print("RobStride USB-CAN Serial Test")
    print("Port=%s  Baud=%d  Motor ID=%d" % (PORT, BAUD, motor_id))
    print("=" * 55)
    print("")
    print("PHYSICAL CHECKLIST:")
    print("  USB adapter DIP SW1 = OFF  (not in boot mode)")
    print("  USB adapter DIP SW2 = ON   (120 ohm termination)")
    print("  CAN_H + CAN_L wired from adapter to motor")
    print("  48V supply is ON and motor powered")
    print("")
    input("Press ENTER when above is confirmed...")
    print("")

    try:
        ser = serial.Serial(PORT, baudrate=BAUD, timeout=0.1,
                            bytesize=8, parity='N', stopbits=1)
    except Exception as e:
        print("ERROR: Cannot open %s: %s" % (PORT, e))
        return

    time.sleep(0.3)
    ser.reset_input_buffer()
    print("Port open OK")
    print("")

    # ── Step 1: Passive listen ────────────────────────────────────────────
    print("[1] Passive listen 3 seconds (motor may broadcast on power-up)...")
    buf = b''
    end = time.monotonic() + 3.0
    heard_bytes = 0
    while time.monotonic() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            heard_bytes += n
        while len(buf) >= 15:
            found = False
            for i in range(len(buf) - 1):
                if buf[i] == 0x41 and buf[i+1] == 0x54:
                    if len(buf) >= i + 15:
                        r = parse_frame(buf[i:i+15])
                        buf = buf[i+15:]
                        if r:
                            fb = decode_feedback(r[0], r[1])
                            if fb:
                                print("  BROADCAST: pos=%.3f vel=%.3f torque=%.2f temp=%.1fC"
                                      % (fb['pos'], fb['vel'], fb['torque'], fb['temp_c']))
                            else:
                                print("  RAW frame: id=0x%08X data=%s" % (r[0], r[1].hex()))
                        found = True
                    break
            if not found:
                buf = b''
                break
        time.sleep(0.01)

    print("  Bytes received passively: %d" % heard_bytes)
    if heard_bytes == 0:
        print("  WARNING: No bytes from adapter at all.")
        print("  Check: sudo chmod 666 /dev/ttyUSB0")
        print("  Check: USB cable is data cable (not charge-only)")
        print("  Check: sudo stty -F /dev/ttyUSB0 921600")

    # ── Step 2: Active scan IDs 127, then 1, 2 ───────────────────────────
    ids_to_try = list(dict.fromkeys([motor_id, 127, 1, 2]))
    for mid in ids_to_try:
        enable_id = make_id(0x03, HOST_ID, mid)
        print("")
        print("[2] Sending ENABLE  motor_id=%d  CAN_ID=0x%08X" % (mid, enable_id))
        print("    Frame bytes: %s" % make_frame(enable_id, bytes(8)).hex())

        reply = send(ser, enable_id)
        if reply:
            can_id, data = reply
            fb = decode_feedback(can_id, data)
            if fb:
                print("    SUCCESS! Motor ID=%d is alive:" % mid)
                print("    pos=%.3f rad  vel=%.3f rad/s  torque=%.2f Nm  temp=%.1fC"
                      % (fb['pos'], fb['vel'], fb['torque'], fb['temp_c']))

                print("")
                print("[3] Holding position 3 seconds (low gains, safe)...")
                ctrl_id = make_id(0x01, float_to_uint(0.0, -60.0, 60.0), mid)
                ctrl_d  = struct.pack('>HHHH',
                    float_to_uint(0.0,  -12.566, 12.566),
                    float_to_uint(0.0,  -50.0,   50.0),
                    float_to_uint(10.0,   0.0, 5000.0),
                    float_to_uint(0.5,    0.0,  100.0))
                for i in range(300):
                    r2 = send(ser, ctrl_id, ctrl_d)
                    if r2 and i % 100 == 0:
                        fb2 = decode_feedback(r2[0], r2[1])
                        if fb2:
                            print("    pos=%.3f vel=%.3f torque=%.2f temp=%.1fC"
                                  % (fb2['pos'], fb2['vel'], fb2['torque'], fb2['temp_c']))
                    time.sleep(0.01)

                stop_id = make_id(0x04, HOST_ID, mid)
                send(ser, stop_id)
                print("    Motor stopped safely.")
                ser.close()
                return
            else:
                print("    Got reply (unexpected type): id=0x%08X data=%s" % (can_id, data.hex()))
        else:
            print("    No reply at ID=%d" % mid)

    print("")
    print("=" * 55)
    print("No motor responded.")
    print("")
    print("Troubleshooting:")
    print("  1. DIP SW2 must be ON (look for tiny switch on USB adapter)")
    print("  2. Try swapping CAN_H and CAN_L wires")
    print("  3. Make sure ONLY the USB adapter is on the CAN bus,")
    print("     NOT the PiCAN HAT at the same time")
    print("  4. Try: python3 test_serial_motor.py 127")
    print("=" * 55)
    ser.close()

if __name__ == "__main__":
    main()