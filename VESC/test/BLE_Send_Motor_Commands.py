import asyncio
import time
from bleak import BleakScanner, BleakClient

DEVICE_NAME = "GIGA Data Sender"
CHARACTERISTIC_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"

SEND_INTERVAL = 0.20   # Must be less than Arduino timeout: 500 ms

COMMAND_NAMES = {
    0: "STOP",
    1: "FORWARD SLOW",
    2: "FORWARD MEDIUM",
    3: "FORWARD FAST",
    4: "RIGHT",
    5: "LEFT",
}


def notification_handler(sender, data):
    try:
        print(f"\nReply from Arduino: {data.decode('utf-8')}")
    except UnicodeDecodeError:
        print(f"\nRaw reply from Arduino: {data.hex()}")


async def send_command(client, command):
    # Send ASCII text because the Arduino code uses BLEStringCharacteristic.
    # Example: command 1 is sent as b"1", not as raw byte b"\x01".
    await client.write_gatt_char(
        CHARACTERISTIC_UUID,
        str(command).encode("utf-8"),
        response=True,
    )
    print(f"Sent {command}: {COMMAND_NAMES[command]}")


async def hold_command(client, command, seconds):
    if command not in COMMAND_NAMES:
        print("Invalid command. Use 0 to 5.")
        return

    if command == 0:
        await send_command(client, 0)
        return

    end_time = time.time() + seconds
    print(f"Holding {COMMAND_NAMES[command]} for {seconds} seconds")

    while time.time() < end_time:
        await send_command(client, command)
        await asyncio.sleep(SEND_INTERVAL)

    await send_command(client, 0)
    print("Auto stop")


async def async_input(prompt):
    return await asyncio.to_thread(input, prompt)


async def main():
    print(f"Scanning for '{DEVICE_NAME}'...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=8.0)

    if not device:
        print(f"Device {DEVICE_NAME} not found")
        return

    print(f"Device found: {device.name} [{device.address}]")

    async with BleakClient(device, timeout=10.0) as client:
        print("Connected successfully")

        await client.start_notify(CHARACTERISTIC_UUID, notification_handler)
        print("Subscribed to Arduino replies")

        await send_command(client, 0)

        print()
        print("Commands:")
        print("0 = stop")
        print("1 = forward slow")
        print("2 = forward medium")
        print("3 = forward fast")
        print("4 = right")
        print("5 = left")
        print()
        print("Examples:")
        print("1 1     = forward slow for 1 second")
        print("4 0.5   = turn right for 0.5 seconds")
        print("0       = stop")
        print("q       = quit")
        print()

        try:
            while True:
                user_input = (await async_input("command> ")).strip().lower()

                if user_input in ["q", "quit", "exit"]:
                    await send_command(client, 0)
                    print("Stopped and closed.")
                    break

                if not user_input:
                    continue

                parts = user_input.split()

                try:
                    command = int(parts[0])
                except ValueError:
                    print("Invalid command.")
                    continue

                if command not in COMMAND_NAMES:
                    print("Use command 0 to 5.")
                    continue

                seconds = 1.0

                if len(parts) > 1:
                    try:
                        seconds = float(parts[1])
                    except ValueError:
                        print("Invalid time value.")
                        continue

                await hold_command(client, command, seconds)

        except KeyboardInterrupt:
            await send_command(client, 0)
            print("\nStopped and closed.")

        await client.stop_notify(CHARACTERISTIC_UUID)


if __name__ == "__main__":
    asyncio.run(main())
