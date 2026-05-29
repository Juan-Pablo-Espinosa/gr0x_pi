#!/usr/bin/env python3
import can
import math
import time

# ---------- CONFIG ----------
CAN_CHANNEL = 'can0'
MOTOR_ID    = 0x02      # Default motor ID. If you changed it with the USB debugger, update this.
HOST_ID     = 0xFE      # Master host ID
# --------------------------

bus = can.interface.Bus(channel=CAN_CHANNEL, bustype='socketcan', fd=False)

def float_to_uint(x, x_min, x_max, bits=16):
    span = x_max - x_min
    x = max(min(x, x_max), x_min)
    return int((x - x_min) * ((1 << bits) - 1) / span)

def uint_to_float(x, x_min, x_max, bits=16):
    span = x_max - x_min
    return float(x) * span / ((1 << bits) - 1) + x_min

def pack_type1(motor_id, angle, velocity, kp, kd, torque):
    """Private Protocol Type 1 — Operation Control"""
    a = float_to_uint(angle,    -4*math.pi, 4*math.pi)
    v = float_to_uint(velocity, -33.0,      33.0)
    p = float_to_uint(kp,        0.0,       500.0)
    d = float_to_uint(kd,        0.0,         5.0)
    t = float_to_uint(torque,   -60.0,       60.0)  # RS-03 safe range

    data = [
        (a >> 8) & 0xFF, a & 0xFF,
        (v >> 8) & 0xFF, v & 0xFF,
        (p >> 8) & 0xFF, p & 0xFF,
        (d >> 8) & 0xFF, d & 0xFF,
    ]
    can_id = (0x1 << 24) | ((t & 0xFFFF) << 8) | (motor_id & 0xFF)
    return can.Message(arbitration_id=can_id, data=data, is_extended_id=True)

def pack_type3(motor_id, host_id=0xFE):
    """Private Protocol Type 3 — Enable Motor"""
    can_id = (0x3 << 24) | ((host_id & 0xFF) << 8) | (motor_id & 0xFF)
    return can.Message(arbitration_id=can_id, data=[0,0,0,0,0,0,0,0], is_extended_id=True)

def pack_type4(motor_id, host_id=0xFE, clear_error=False):
    """Private Protocol Type 4 — Stop Motor"""
    can_id = (0x4 << 24) | ((host_id & 0xFF) << 8) | (motor_id & 0xFF)
    data = [1,0,0,0,0,0,0,0] if clear_error else [0,0,0,0,0,0,0,0]
    return can.Message(arbitration_id=can_id, data=data, is_extended_id=True)

def unpack_feedback(msg):
    """Unpack Type 0x2 feedback frame from motor"""
    if msg.is_extended_id and ((msg.arbitration_id >> 24) & 0x1F) == 0x2:
        d = msg.data
        angle    = uint_to_float((d[0]<<8)|d[1], -4*math.pi, 4*math.pi)
        velocity = uint_to_float((d[2]<<8)|d[3], -33.0, 33.0)
        torque   = uint_to_float((d[4]<<8)|d[5], -60.0, 60.0)
        temp     = ((d[6]<<8)|d[7]) / 10.0
        return {
            'angle': angle,
            'velocity': velocity,
            'torque': torque,
            'temperature': temp,
        }
    return None

# ---------- TEST SEQUENCE ----------
print("[1] Enabling motor...")
bus.send(pack_type3(MOTOR_ID, HOST_ID))
time.sleep(0.1)

print("[2] Holding position gently (kp=30, kd=0.5, torque=0)...")
print("    Press Ctrl+C to stop safely.\n")

try:
    for _ in range(200):  # 2 seconds @ 100 Hz
        msg = pack_type1(MOTOR_ID, angle=0.0, velocity=0.0, kp=30.0, kd=0.5, torque=0.0)
        bus.send(msg)

        rx = bus.recv(timeout=0.005)
        if rx:
            fb = unpack_feedback(rx)
            if fb:
                print(f"  Pos: {fb['angle']:+.3f} rad | Vel: {fb['velocity']:+.3f} | "
                      f"Torque: {fb['torque']:+.3f} Nm | Temp: {fb['temperature']:.1f}°C")
        time.sleep(0.01)

    print("\n[3] Slow sine wave (±0.3 rad) for 3 seconds...")
    start = time.time()
    while time.time() - start < 3.0:
        t = time.time() - start
        target = math.sin(t) * 0.3
        msg = pack_type1(MOTOR_ID, angle=target, velocity=0.0, kp=30.0, kd=0.5, torque=0.0)
        bus.send(msg)

        rx = bus.recv(timeout=0.005)
        if rx:
            fb = unpack_feedback(rx)
            if fb:
                print(f"  Target: {target:+.3f} | Actual: {fb['angle']:+.3f}")
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nInterrupted by user.")

finally:
    print("\n[4] Stopping motor...")
    bus.send(pack_type4(MOTOR_ID, HOST_ID, clear_error=False))
    bus.shutdown()
    print("Done.")