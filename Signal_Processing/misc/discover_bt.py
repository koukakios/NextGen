import asyncio
from bleak import BleakScanner

async def discover_devices():
    print("Scanning for Bluetooth devices...")
    devices = await BleakScanner.discover()
    for d in devices:
        if d.name:  # Filters out unnamed devices to keep the list clean
            print(f"Name: {d.name} | Address: {d.address}")

asyncio.run(discover_devices())