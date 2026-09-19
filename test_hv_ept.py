import struct
import win32con
import win32file

DEVICE = r"\\.\HwidSpoofer"

IOCTL_START_HYPERVISOR = 0x80002020
IOCTL_STOP_HYPERVISOR = 0x80002024
IOCTL_TEST_SMBIOS_EPT_HOOK = 0x8000202C

HEADER_FORMAT = "<iBBBBII9Q"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
RESULT_SIZE = 248
SNAPSHOT_CAPACITY = 160


def ntstatus_hex(value: int) -> str:
    return f"0x{value & 0xFFFFFFFF:08X}"


def fixed_string(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", errors="replace")


handle = win32file.CreateFile(
    DEVICE,
    win32con.GENERIC_READ | win32con.GENERIC_WRITE,
    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
    None,
    win32con.OPEN_EXISTING,
    win32con.FILE_ATTRIBUTE_NORMAL,
    None,
)

started = False

try:
    win32file.DeviceIoControl(
        handle,
        IOCTL_START_HYPERVISOR,
        b"",
        0,
        None,
    )
    started = True

    data = win32file.DeviceIoControl(
        handle,
        IOCTL_TEST_SMBIOS_EPT_HOOK,
        b"",
        RESULT_SIZE,
        None,
    )

    if len(data) < RESULT_SIZE:
        raise RuntimeError(
            f"short EPT result: got {len(data)} bytes, expected {RESULT_SIZE}"
        )

    (
        status,
        vmcs_valid,
        shadow_installed,
        violation_observed,
        snapshot_matches,
        processor_count,
        snapshot_size,
        synthetic_gpa,
        shadow_physical,
        vmexit_count,
        ept_violation_count,
        cpuid_exit_count,
        vmcall_exit_count,
        invept_count,
        vmresume_failure_count,
        vmexit_cycles,
    ) = struct.unpack_from(HEADER_FORMAT, data, 0)

    if snapshot_size > SNAPSHOT_CAPACITY:
        raise RuntimeError(
            f"invalid snapshot size returned by driver: {snapshot_size}"
        )

    snapshot = data[
        HEADER_SIZE : HEADER_SIZE + snapshot_size
    ]

    print("=== VT-x / EPT synthetic lab test ===")
    print(f"Status                  : {ntstatus_hex(status)}")
    print(f"VMCS valid              : {bool(vmcs_valid)}")
    print(f"EPT violation observed  : {bool(violation_observed)}")
    print(f"Shadow installed        : {bool(shadow_installed)}")
    print(f"Snapshot matches shadow : {bool(snapshot_matches)}")
    print(f"Processor count         : {processor_count}")
    print(f"Synthetic GPA           : 0x{synthetic_gpa:016X}")
    print(f"Shadow physical         : 0x{shadow_physical:016X}")
    print()
    print("=== VM-exit statistics ===")
    print(f"VM exits                : {vmexit_count}")
    print(f"EPT violations          : {ept_violation_count}")
    print(f"CPUID exits             : {cpuid_exit_count}")
    print(f"VMCALL exits            : {vmcall_exit_count}")
    print(f"INVEPT operations       : {invept_count}")
    print(f"VMRESUME failures       : {vmresume_failure_count}")
    print(f"VM-exit cycles          : {vmexit_cycles}")

    if snapshot_size >= 140:
        signature = fixed_string(snapshot[0:8])
        type_id = snapshot[8]
        length = snapshot[9]
        handle_id = struct.unpack_from("<H", snapshot, 10)[0]
        manufacturer = fixed_string(snapshot[12:44])
        product = fixed_string(snapshot[44:76])
        version = fixed_string(snapshot[76:92])
        serial = fixed_string(snapshot[92:124])
        uuid = snapshot[124:140].hex("-")

        print()
        print("=== Synthetic Type 1 snapshot ===")
        print(f"Signature    : {signature}")
        print(f"Type         : {type_id}")
        print(f"Length       : {length}")
        print(f"Handle       : 0x{handle_id:04X}")
        print(f"Manufacturer : {manufacturer}")
        print(f"Product      : {product}")
        print(f"Version      : {version}")
        print(f"Serial       : {serial}")
        print(f"UUID bytes   : {uuid}")

finally:
    if started:
        try:
            win32file.DeviceIoControl(
                handle,
                IOCTL_STOP_HYPERVISOR,
                b"",
                0,
                None,
            )
        except Exception as exc:
            print(f"WARNING: stop IOCTL failed: {exc}")

    win32file.CloseHandle(handle)
