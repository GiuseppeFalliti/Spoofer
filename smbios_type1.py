import struct
import uuid
from dataclasses import dataclass

@dataclass
class SMBIOSType1:
    """SMBIOS Type 1 (System Information) - struttura completa fino a SMBIOS 2.4+"""
    type_id: int = 0x01
    length: int = 27          # 0x1B, dimensione area formattata
    handle: int = 0x0001
    manufacturer: int = 1     # indice stringa
    product_name: int = 2
    version: int = 3
    serial_number: int = 4
    uuid_bytes: bytes = b"\x00" * 16
    wake_up_type: int = 0x06  # Power Switch
    sku_number: int = 5
    family: int = 6

    def pack(self) -> bytes:
        """Serializza la struttura nel formato binario SMBIOS (little-endian, packed)."""
        fmt = "<BBHBBBB16sBBB"
        return struct.pack(
            fmt,
            self.type_id,
            self.length,
            self.handle,
            self.manufacturer,
            self.product_name,
            self.version,
            self.serial_number,
            self.uuid_bytes,
            self.wake_up_type,
            self.sku_number,
            self.family,
        )

def generate_fake_smbios_type1() -> SMBIOSType1:
    info = SMBIOSType1()
    info.uuid_bytes = uuid.uuid4().bytes_le  # bytes_le rispetta il mixed-endian SMBIOS
    return info

def generate_random_uuid() -> str:
    """Genera un UUID casuale in formato stringa.

    Alias usato dalla GUI (gui/main_window.py) per generare un UUID
    casuale da usare come nuovo identificatore SMBIOS/BIOS.
    """
    return str(uuid.uuid4())


def build_raw_smbios_table() -> bytes:
    """
    Costruisce un blob SMBIOS completo contenente solo la struttura Type 1,
    nel formato atteso da GetSystemFirmwareTable('RSMB').
    Layout: Entry Point 32-bit (31 byte) + Type 1 formattata + string table.
    """
    type1 = generate_fake_smbios_type1()
    formatted_area = type1.pack()

    strings = [b"SpooferMfg", b"VirtualPro", b"1.0", b"SPOOFED-1234", b"SKU001", b"Virtual"]
    string_table = b""
    for s in strings:
        string_table += s + b"\x00"
    string_table += b"\x00"

    structure_table = formatted_area + string_table
    structure_table_length = len(structure_table)

    entry_point = bytearray(31)
    entry_point[0:4] = b"_SM_"
    entry_point[5] = 0x1F
    entry_point[6] = 3
    entry_point[7] = 0
    struct.pack_into("<H", entry_point, 8, len(formatted_area) + len(string_table))
    entry_point[10] = 0x00
    entry_point[11:16] = b"\x00" * 5
    entry_point[16:21] = b"_DMI_"
    struct.pack_into("<H", entry_point, 22, structure_table_length)
    struct.pack_into("<I", entry_point, 24, 0)
    struct.pack_into("<H", entry_point, 28, 1)
    entry_point[30] = 0x30

    intermediate_sum = sum(entry_point[16:31]) & 0xFF
    entry_point[21] = (256 - intermediate_sum) & 0xFF
    ep_sum = sum(entry_point[0:31]) & 0xFF
    entry_point[4] = (256 - ep_sum) & 0xFF

    return bytes(entry_point) + structure_table

if __name__ == "__main__":
    fake = generate_fake_smbios_type1()
    blob = fake.pack()

    print("=== Fake SMBIOS Type 1 Structure ===")
    print(f"Type:          0x{fake.type_id:02X}")
    print(f"Length:        {fake.length} bytes")
    print(f"Handle:        0x{fake.handle:04X}")
    print(f"Manufacturer:  String Index {fake.manufacturer}")
    print(f"Product Name:  String Index {fake.product_name}")
    print(f"Version:       String Index {fake.version}")
    print(f"Serial Number: String Index {fake.serial_number}")
    print(f"UUID:          {uuid.UUID(bytes_le=fake.uuid_bytes)}")
    print(f"Wake-up Type:  0x{fake.wake_up_type:02X}")
    print(f"SKU Number:    String Index {fake.sku_number}")
    print(f"Family:        String Index {fake.family}")
    print(f"Raw size:      {len(blob)} bytes")
    print(f"Raw hex:       {blob.hex()}")
    print("====================================")

