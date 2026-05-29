#!/usr/bin/env python3
"""
RobStride RS-03 direct serial control via USB-CAN adapter.
Zero Rust/cargo dependencies. Pure pyserial only.

The RobStride USB-CAN adapter is a CH341 USB-serial bridge.
It wraps CAN frames in a simple serial packet:
  Header:  0x41 0x54  ("AT")
  Data:    CAN ID (4 bytes LE) + DLC (1 byte) + Data (8 bytes)
  Footer:  0x0D 0x0A  (CR LF)

Total packet = 15 bytes per frame.

Motor default ID = 127 (0x7F). Change MOTOR_ID below if yours differs.
"""

import serial
import struct
import time
import sys

# ── CONFIGURATION ────────────────────────────────────────────────────────────
PORT      = "/dev/ttyUSB0"
BAUD      = 921600
MOTOR_ID  = 127    # Factory default. Change to 2 if you already set it.
HOST_ID   = 0xFD   # Standard host ID per RobStride protocol docs
# ─────────────────────────────────────────────────────────────────────────────

def float_to_uint(x, x_min, x_max, bits=16):
    x = max(min(x, x_max), x_min)
    return int((x - x_min) * ((1 << bits) - 1) / (x_max - x_min))

def uint_to_float(x, x_min, x_max, bits=16):
    return float(x) * (x_max - x_min) / ((1 << bits) - 1) + x_min

def build_can_id(comm_type, data_area_2, motor_id):
    """Build 29-bit CAN ID: [28:24]=comm_type [23:8]=data_area_2 [7:0]=motor_id"""
    return ((comm_type & 0x1F) << 24) | ((data_area_2 & 0xFFFF) << 8) | (motor_id & 0xFF)

def pack_serial_frame(can_id_29bit, data_8bytes):
    """
    Pack a CAN frame into the RobStride USB serial protocol.
    Format: 0x41 0x54 [can_id 4B LE] [dlc 1B] [data 8B] 0x0D 0x0A
    The CAN ID has the EFF flag set (bit 31) to indicate extended frame.
    """
    eff_id = can_id_29bit | 0x80000000  # Set EFF (extended frame) flag
    header = bytes([0x41, 0x54])
    id_bytes = struct.pack('<I', eff_id)   # Little-endian 4 bytes
    dlc = bytes([8])
    footer = bytes([0x0D, 0x0A])
    return header + id_bytes + dlc + data_8bytes + footer

def parse_serial_frame(raw_15bytes):
    """Parse a 15-byte response frame from the motor."""
    if len(raw_15bytes) < 15:
        return None
    if raw_15bytes[0] != 0x41 or raw_15bytes[1] != 0x54:
        return None
    eff_id = struct.unpack_from('<I', raw_15bytes, 2)[0]
    can_id = eff_id & 0x1FFFFFFF
    dlc    = raw_15bytes[6]
    data   = raw_15bytes[7:7+dlc]
    return can_id, dlc, data

def decode_feedback(can_id, data):
    """Decode Type 0x02 motor feedback frame."""
    comm_type = (can_id >> 24) & 0x1F
    if comm_type != 0x02:
        return None
    if len(data) < 8:
        return None
    pos_u, vel_u, trq_u = struct.unpack_from('>HHH', data, 0)
    temp_raw            = struct.unpack_from('>H',   data, 6)[0]
    return {
        'pos':    uint_to_float(pos_u, -12.566, 12.566),
        'vel':    uint_to_float(vel_u, -50.0,   50.0),
        'torque': uint_to_float(trq_u, -60.0,   60.0),
        'temp_c': temp_raw / 10.0,
    }

def send_and_recv(ser, can_id, data=bytes(8), timeout=0.05):
    """Send a frame and wait for any reply."""
    frame = pack_serial_frame(can_id, data)
    ser.reset_input_buffer()
    ser.write(frame)
    ser.flush()

    deadline = time.monotonic() + timeout
    buf = b''
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
        # Look for complete 15-byte frame
        while len(buf) >= 15:
            # Find header
            idx = buf.find(b'\x41\x54')
            if idx < 0:
                buf = b''
                break
            if idx > 0:
                buf = buf[idx:]
            if len(buf) >= 15:
                frame_bytes = buf[:15]
                buf = buf[15:]
                result = parse_serial_frame(frame_bytes)
                if result:
                    return result
    return None

def main():
    print("=" * 55)
    print("RobStride RS-03 Serial Motor Test")
    print("Port: %s  Baud: %d  Motor ID: %d" % (PORT, BAUD, MOTOR_ID))
    print("=" * 55)

    # Override motor ID from command line
    mid = int(sys.argv[1]) if len(sys.argv) > 1 else MOTOR_ID

    try:
        ser = serial.Serial(PORT, baudrate=BAUD, timeout=0.1)
        print("Serial port open: OK")
    except Exception as e:
        print("ERROR opening serial port: %s" % e)
        print("Try: sudo chmod 666 /dev/ttyUSB0")
        return

    time.sleep(0.2)
    ser.reset_input_buffer()

    # ── TEST 1: Listen for any spontaneous motor message ──────────────────
    print("\n[1] Listening for spontaneous motor broadcast (2s)...")
    deadline = time.monotonic() + 2.0
    buf = b''
    got_anything = False
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
            got_anything = True
        while len(buf) >= 15:
            idx = buf.find(b'\x41\x54')
            if idx < 0:
                buf = b''
                break
            if idx > 0:
                buf = buf[idx:]
            if len(buf) >= 15:
                parsed = parse_serial_frame(buf[:15])
                buf = buf[15:]
                if parsed:
                    can_id, dlc, data = parsed
                    fb = decode_feedback(can_id, bytes(data))
                    if fb:
                        print("  MOTOR BROADCAST: pos=%.3f vel=%.3f torque=%.2f temp=%.1fC"
                              % (fb['pos'], fb['vel'], fb['torque'], fb['temp_c']))
                    else:
                        print("  RAW FRAME: id=0x%08X  data=%s"
                              % (can_id, bytes(data).hex()))
    if not got_anything:
        print("  No bytes received (motor may not be auto-reporting, that's OK)")

    # ── TEST 2: Send enable command ────────────────────────────────────────
    print("\n[2] Sending ENABLE to motor ID %d ..." % mid)
    enable_id = build_can_id(0x03, HOST_ID, mid)
    print("    CAN ID = 0x%08X" % enable_id)
    reply = send_and_recv(ser, enable_id, bytes(8), timeout=0.1)
    if reply:
        can_id, dlc, data = reply
        fb = decode_feedback(can_id, bytes(data))
        if fb:
            print("  REPLY: pos=%.3f rad  vel=%.3f  torque=%.2f Nm  temp=%.1fC"
                  % (fb['pos'], fb['vel'], fb['torque'], fb['temp_c']))
        else:
            print("  REPLY (raw): id=0x%08X  data=%s" % (can_id, bytes(data).hex()))
    else:
        print("  No reply. Trying motor ID 127 (factory default)...")
        mid = 127
        enable_id = build_can_id(0x03, HOST_ID, mid)
        reply = send_and_recv(ser, enable_id, bytes(8), timeout=0.1)
        if reply:
            can_id, dlc, data = reply
            fb = decode_feedback(can_id, bytes(data))
            if fb:
                print("  FOUND at ID=127: pos=%.3f  vel=%.3f  torque=%.2f  temp=%.1fC"
                      % (fb['pos'], fb['vel'], fb['torque'], fb['temp_c']))
                print("  --> Update MOTOR_ID=127 at top of this script")
            else:
                print("  FOUND at ID=127 (raw): id=0x%08X  data=%s"
                      % (can_id, bytes(data).hex()))
        else:
            print("  No reply at ID=127 either.")
            print("  Check: Is 48V supply ON? Are CAN_H/CAN_L wired to USB adapter?")
            ser.close()
            return

    # ── TEST 3: Hold position ─────────────────────────────────────────────
    print("\n[3] Holding zero position for 5 seconds (Ctrl+C to stop early)...")
    t = 0
    try:
        while t < 500:
            ctrl_id = build_can_id(0x01, float_to_uint(0.0, -60.0, 60.0), mid)
            ctrl_data = struct.pack('>HHHH',
                float_to_uint(0.0,  -12.566, 12.566),
                float_to_uint(0.0,  -50.0,   50.0),
                float_to_uint(10.0,   0.0, 5000.0),
                float_to_uint(0.5,    0.0,  100.0),
            )
            reply = send_and_recv(ser, ctrl_id, ctrl_data, timeout=0.015)
            if reply and t % 50 == 0:
                can_id, dlc, data = reply
                fb = decode_feedback(can_id, bytes(data))
                if fb:
                    print("  t=%ds  pos=%.3f  vel=%.3f  torque=%.2f  temp=%.1fC"
                          % (t//100, fb['pos'], fb['vel'], fb['torque'], fb['temp_c']))
            t += 1
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("  Interrupted.")

    # ── TEST 4: Stop motor ────────────────────────────────────────────────
    print("\n[4] Sending STOP...")
    stop_id = build_can_id(0x04, HOST_ID, mid)
    reply = send_and_recv(ser, stop_id, bytes(8), timeout=0.1)
    if reply:
        print("  Stop ACK received.")
    else:
        print("  No stop reply (motor may have already stopped).")

    ser.close()
    print("\nDone. Motor stopped safely.")

if __name__ == "__main__":
    main()