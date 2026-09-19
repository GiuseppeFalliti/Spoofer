import struct
import win32con
import win32file

DEVICE = r"\\.\HwidSpoofer"

IOCTL_CHECK_VTX_SUPPORT = 0x80002018
IOCTL_CHECK_HYPERVISOR  = 0x8000201C

handle = win32file.CreateFile(
    DEVICE,
    win32con.GENERIC_READ | win32con.GENERIC_WRITE,
    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
    None,
    win32con.OPEN_EXISTING,
    win32con.FILE_ATTRIBUTE_NORMAL,
    None,
)

try:
    data = win32file.DeviceIoControl(
        handle,
        IOCTL_CHECK_VTX_SUPPORT,
        b"",
        8,
        None,
    )

    vtx, ept, vmx_locked, hypervisor, processor_count = struct.unpack(
        "<BBBBI",
        data
    )

    print("=== VT-x / EPT capabilities ===")
    print(f"VT-x supported     : {bool(vtx)}")
    print(f"EPT supported      : {bool(ept)}")
    print(f"VMX blocked        : {bool(vmx_locked)}")
    print(f"Hypervisor present : {bool(hypervisor)}")
    print(f"Processor count    : {processor_count}")

    hv_data = win32file.DeviceIoControl(
        handle,
        IOCTL_CHECK_HYPERVISOR,
        b"",
        1,
        None,
    )

    print()
    print(f"Hypervisor IOCTL   : {bool(hv_data[0])}")

finally:
    win32file.CloseHandle(handle)