###################################################################
# Receive.py
# Receive and print data from Arduino Giga
# Make sure you enter correct 'address'. Use ScanDevices to find it
####################################################################
import asyncio
from bleak import BleakClient

address = "2C90DFF4-98C3-F0A2-0658-4EA1151DE327" # Address of Arduino Giga BT module
UUID = "0001" # ID of characteristic (kind of port)

data =""

# Connect to Giga, write a byte 1 to characteristic UUID
async def main(address):
    async with BleakClient(address) as client:
        data = await client.read_gatt_char(UUID)
        print(data)

asyncio.run(main(address))
