###################################################################
# SendOne.py
# Send byte 1 to Arduino Giga BT port
# Make sure you enter correct 'address'. Use ScanDevices to find it
####################################################################
import asyncio
from bleak import BleakClient

address = "2C90DFF4-98C3-F0A2-0658-4EA1151DE327" # Address of Arduino Giga BT module
UUID = "0001" # ID of characteristic (kind of port)

# Connect to Giga, write a byte 1 to characteristic UUID
async def main(address):
    async with BleakClient(address) as client:
        await client.write_gatt_char(UUID,b'\x01')

asyncio.run(main(address))
