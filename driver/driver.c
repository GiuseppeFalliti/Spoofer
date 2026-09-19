#include "driver.h"

//
// This project deliberately DOES NOT install real kernel hooks.
// The three flags only model hook state so the user-mode application can
// exercise the same IOCTL control flow as the Python prototype.
//

static volatile LONG g_FirmwareHookEnabled = 0;
static volatile LONG g_HalHookEnabled = 0;
static volatile LONG g_SmbiosHookEnabled = 0;

static UCHAR g_SmbiosBlob[SMBIOS_BLOB_CAPACITY];
static ULONG g_SmbiosBlobSize = 0;

static
VOID
CompleteIrp(
    _Inout_ PIRP Irp,
    _In_ NTSTATUS Status,
    _In_ ULONG_PTR Information
    )
{
    Irp->IoStatus.Status = Status;
    Irp->IoStatus.Information = Information;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
}

static
UCHAR
ChecksumAdjustment(
    _In_reads_bytes_(Length) const UCHAR* Data,
    _In_ ULONG Length
    )
{
    ULONG sum = 0;
    ULONG i;

    for (i = 0; i < Length; ++i) {
        sum += Data[i];
    }

    return (UCHAR)(0u - (UCHAR)sum);
}

static
VOID
WriteU16Le(
    _Out_writes_bytes_(2) UCHAR* Destination,
    _In_ USHORT Value
    )
{
    Destination[0] = (UCHAR)(Value & 0xFF);
    Destination[1] = (UCHAR)((Value >> 8) & 0xFF);
}

static
VOID
WriteU32Le(
    _Out_writes_bytes_(4) UCHAR* Destination,
    _In_ ULONG Value
    )
{
    Destination[0] = (UCHAR)(Value & 0xFF);
    Destination[1] = (UCHAR)((Value >> 8) & 0xFF);
    Destination[2] = (UCHAR)((Value >> 16) & 0xFF);
    Destination[3] = (UCHAR)((Value >> 24) & 0xFF);
}

NTSTATUS
BuildFakeSmbiosBlob(
    VOID
    )
{
    //
    // SMBIOS 2.x 32-bit entry point, matching the layout used by the
    // Python build_raw_smbios_table() helper.
    //
    UCHAR entryPoint[31];
    SMBIOS_TYPE1_HEADER type1;

    //
    // Explicit trailing \0 + C string terminator = required double-NUL
    // termination for the SMBIOS structure string-set.
    //
    static const UCHAR strings[] =
        "SpooferMfg\0"
        "VirtualPro\0"
        "1.0\0"
        "SPOOFED-1234\0"
        "SKU001\0"
        "Virtual\0";

    static const UCHAR researchUuid[16] = {
        0x10, 0x32, 0x54, 0x76,
        0x98, 0xBA,
        0xDC, 0xFE,
        0x80, 0x11,
        0x22, 0x33, 0x44, 0x55, 0x66, 0x77
    };

    ULONG structureTableLength;
    ULONG requiredSize;
    ULONG offset;

    RtlZeroMemory(entryPoint, sizeof(entryPoint));
    RtlZeroMemory(&type1, sizeof(type1));
    RtlZeroMemory(g_SmbiosBlob, sizeof(g_SmbiosBlob));

    type1.Type = 0x01;
    type1.Length = (UCHAR)sizeof(type1);
    type1.Handle = 0x0001;
    type1.Manufacturer = 1;
    type1.ProductName = 2;
    type1.Version = 3;
    type1.SerialNumber = 4;
    RtlCopyMemory(type1.Uuid, researchUuid, sizeof(researchUuid));
    type1.WakeUpType = 0x06;
    type1.SkuNumber = 5;
    type1.Family = 6;

    structureTableLength = (ULONG)sizeof(type1) + (ULONG)sizeof(strings);
    requiredSize = (ULONG)sizeof(entryPoint) + structureTableLength;

    if (requiredSize > sizeof(g_SmbiosBlob)) {
        g_SmbiosBlobSize = 0;
        return STATUS_BUFFER_TOO_SMALL;
    }

    RtlCopyMemory(&entryPoint[0], "_SM_", 4);
    entryPoint[5] = 0x1F;
    entryPoint[6] = 3;      // SMBIOS major
    entryPoint[7] = 0;      // SMBIOS minor
    WriteU16Le(&entryPoint[8], (USHORT)structureTableLength);
    entryPoint[10] = 0x00;

    RtlCopyMemory(&entryPoint[16], "_DMI_", 5);
    WriteU16Le(&entryPoint[22], (USHORT)structureTableLength);
    WriteU32Le(&entryPoint[24], 0);   // no physical table address in simulation
    WriteU16Le(&entryPoint[28], 1);   // one SMBIOS structure
    entryPoint[30] = 0x30;            // BCD revision 3.0

    //
    // Intermediate DMI checksum covers bytes 16..30.
    //
    entryPoint[21] = ChecksumAdjustment(&entryPoint[16], 15);

    //
    // Main entry-point checksum covers all 31 bytes.
    //
    entryPoint[4] = ChecksumAdjustment(entryPoint, (ULONG)sizeof(entryPoint));

    offset = 0;
    RtlCopyMemory(&g_SmbiosBlob[offset], entryPoint, sizeof(entryPoint));
    offset += (ULONG)sizeof(entryPoint);

    RtlCopyMemory(&g_SmbiosBlob[offset], &type1, sizeof(type1));
    offset += (ULONG)sizeof(type1);

    RtlCopyMemory(&g_SmbiosBlob[offset], strings, sizeof(strings));
    offset += (ULONG)sizeof(strings);

    g_SmbiosBlobSize = offset;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer] Fake SMBIOS blob prepared: %lu bytes\n",
        g_SmbiosBlobSize
        );

    return STATUS_SUCCESS;
}

NTSTATUS
HwidCreateClose(
    _In_ PDEVICE_OBJECT DeviceObject,
    _Inout_ PIRP Irp
    )
{
    UNREFERENCED_PARAMETER(DeviceObject);

    CompleteIrp(Irp, STATUS_SUCCESS, 0);
    return STATUS_SUCCESS;
}

NTSTATUS
HwidDeviceControl(
    _In_ PDEVICE_OBJECT DeviceObject,
    _Inout_ PIRP Irp
    )
{
    PIO_STACK_LOCATION stack;
    ULONG ioctlCode;
    NTSTATUS status = STATUS_SUCCESS;

    UNREFERENCED_PARAMETER(DeviceObject);

    stack = IoGetCurrentIrpStackLocation(Irp);
    ioctlCode = stack->Parameters.DeviceIoControl.IoControlCode;

    switch (ioctlCode) {
    case IOCTL_SET_FIRMWARE_HOOK:
        InterlockedExchange(&g_FirmwareHookEnabled, 1);
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] Firmware hook simulation ENABLED\n"
            );
        break;

    case IOCTL_CLEAR_FIRMWARE_HOOK:
        InterlockedExchange(&g_FirmwareHookEnabled, 0);
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] Firmware hook simulation DISABLED\n"
            );
        break;

    case IOCTL_SET_HAL_HOOK:
        InterlockedExchange(&g_HalHookEnabled, 1);
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] HAL hook simulation ENABLED\n"
            );
        break;

    case IOCTL_CLEAR_HAL_HOOK:
        InterlockedExchange(&g_HalHookEnabled, 0);
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] HAL hook simulation DISABLED\n"
            );
        break;

    case IOCTL_SET_SMBIOS_HOOK:
        InterlockedExchange(&g_SmbiosHookEnabled, 1);
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] SMBIOS hook simulation ENABLED; blob size=%lu\n",
            g_SmbiosBlobSize
            );
        break;

    case IOCTL_CLEAR_SMBIOS_HOOK:
        InterlockedExchange(&g_SmbiosHookEnabled, 0);
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] SMBIOS hook simulation DISABLED\n"
            );
        break;

    default:
        status = STATUS_INVALID_DEVICE_REQUEST;
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_WARNING_LEVEL,
            "[HwidSpoofer] Unknown IOCTL: 0x%08lX\n",
            ioctlCode
            );
        break;
    }

    CompleteIrp(Irp, status, 0);
    return status;
}

VOID
HwidUnload(
    _In_ PDRIVER_OBJECT DriverObject
    )
{
    UNICODE_STRING dosDeviceName;

    InterlockedExchange(&g_FirmwareHookEnabled, 0);
    InterlockedExchange(&g_HalHookEnabled, 0);
    InterlockedExchange(&g_SmbiosHookEnabled, 0);

    RtlInitUnicodeString(&dosDeviceName, HWID_DOS_DEVICE_NAME);
    IoDeleteSymbolicLink(&dosDeviceName);

    if (DriverObject->DeviceObject != NULL) {
        IoDeleteDevice(DriverObject->DeviceObject);
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer] Driver unloaded\n"
        );
}

NTSTATUS
DriverEntry(
    _In_ PDRIVER_OBJECT DriverObject,
    _In_ PUNICODE_STRING RegistryPath
    )
{
    NTSTATUS status;
    PDEVICE_OBJECT deviceObject = NULL;
    UNICODE_STRING deviceName;
    UNICODE_STRING dosDeviceName;

    UNREFERENCED_PARAMETER(RegistryPath);

    RtlInitUnicodeString(&deviceName, HWID_DEVICE_NAME);
    RtlInitUnicodeString(&dosDeviceName, HWID_DOS_DEVICE_NAME);

    status = BuildFakeSmbiosBlob();
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = IoCreateDevice(
        DriverObject,
        0,
        &deviceName,
        FILE_DEVICE_UNKNOWN,
        FILE_DEVICE_SECURE_OPEN,
        FALSE,
        &deviceObject
        );

    if (!NT_SUCCESS(status)) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidSpoofer] IoCreateDevice failed: 0x%08X\n",
            status
            );
        return status;
    }

    deviceObject->Flags |= DO_BUFFERED_IO;

    status = IoCreateSymbolicLink(
        &dosDeviceName,
        &deviceName
        );

    if (!NT_SUCCESS(status)) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidSpoofer] IoCreateSymbolicLink failed: 0x%08X\n",
            status
            );
        IoDeleteDevice(deviceObject);
        return status;
    }

    DriverObject->MajorFunction[IRP_MJ_CREATE] = HwidCreateClose;
    DriverObject->MajorFunction[IRP_MJ_CLOSE] = HwidCreateClose;
    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = HwidDeviceControl;
    DriverObject->DriverUnload = HwidUnload;

    deviceObject->Flags &= ~DO_DEVICE_INITIALIZING;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer] Driver loaded. Device: \\.\\HwidSpoofer\n"
        );

    return STATUS_SUCCESS;
}
