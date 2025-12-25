#!/usr/bin/env python3
"""
K+DCAN Cable Diagnostic Tool

Tests different DTR/RTS combinations to find what makes the green LED light up.
Run with your cable plugged into the car (ignition ON).
"""

import serial
import time
import sys

def test_cable(port: str = "/dev/ttyUSB0"):
    """Test different DTR/RTS combinations."""

    print(f"\n=== K+DCAN Cable Diagnostic ===")
    print(f"Port: {port}")
    print(f"Make sure cable is plugged into car and ignition is ON\n")

    try:
        ser = serial.Serial(
            port=port,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
        )
    except Exception as e:
        print(f"ERROR: Could not open {port}: {e}")
        return

    # Test different combinations
    combinations = [
        (True, True, "DTR=1, RTS=1 (HX D-CAN common)"),
        (True, False, "DTR=1, RTS=0 (Standard D-CAN)"),
        (False, True, "DTR=0, RTS=1 (K-line mode)"),
        (False, False, "DTR=0, RTS=0 (Both off)"),
    ]

    for dtr, rts, desc in combinations:
        print(f"\nTesting: {desc}")
        print("-" * 40)

        ser.dtr = dtr
        ser.rts = rts
        time.sleep(0.2)

        # Flush buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Send a TesterPresent to DME (address 0x12)
        # ISO 14230 format: [0x82 (format: 2 bytes), 0x12 (target), 0xF1 (source), 0x3E, 0x00, checksum]
        msg = bytes([0x82, 0x12, 0xF1, 0x3E, 0x00])
        checksum = 0
        for b in msg:
            checksum ^= b
        msg += bytes([checksum])

        print(f"  Sending: {msg.hex()}")
        ser.write(msg)
        ser.flush()

        # Wait for echo + response
        time.sleep(0.1)

        # Read everything available
        response = ser.read(100)

        if response:
            print(f"  Received ({len(response)} bytes): {response.hex()}")

            # Check if we got more than just our echo
            if len(response) > len(msg):
                print(f"  >>> GOT RESPONSE! This setting works! <<<")
            elif response == msg:
                print(f"  (Echo only - no ECU response)")
            else:
                print(f"  (Partial/different data)")
        else:
            print(f"  No response")

        input("  Check green LED now. Press Enter to try next setting...")

    ser.close()
    print("\n=== Diagnostic Complete ===")
    print("Use the setting where green LED lit up AND you got a response.")


if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
    test_cable(port)
