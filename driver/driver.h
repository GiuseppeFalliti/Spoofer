#pragma once

#include <ntddk.h>

//
// Device names
//
#define HWID_DEVICE_NAME      L"\\Device\\HwidSpoofer"
#define HWID_DOS_DEVICE_NAME  L"\\DosDevices\\HwidSpoofer"

//
// IOCTL values kept identical to the Python simulation.
//
#define IOCTL_SET_FIRMWARE_HOOK    ((ULONG)0x80002000)
#define IOCTL_CLEAR_FIRMWARE_HOOK  ((ULONG)0x80002004)
#define IOCTL_SET_HAL_HOOK         ((ULONG)0x80002008)
#define IOCTL_CLEAR_HAL_HOOK       ((ULONG)0x8000200C)
#define IOCTL_SET_SMBIOS_HOOK      ((ULONG)0x80002010)
#define IOCTL_CLEAR_SMBIOS_HOOK    ((ULONG)0x80002014)

// Safe, METHOD_BUFFERED test path for retrieving the generated SMBIOS blob.
#define IOCTL_QUERY_FAKE_SMBIOS \
    CTL_CODE(FILE_DEVICE_UNKNOWN, 0x801, METHOD_BUFFERED, FILE_ANY_ACCESS)

// Safe, METHOD_BUFFERED test path for retrieving the generated firmware blob.
#define IOCTL_QUERY_FAKE_FIRMWARE \
    CTL_CODE(FILE_DEVICE_UNKNOWN, 0x802, METHOD_BUFFERED, FILE_ANY_ACCESS)

// Safe, METHOD_BUFFERED test path for retrieving the generated HAL/PCI blob.
#define IOCTL_QUERY_FAKE_HAL \
    CTL_CODE(FILE_DEVICE_UNKNOWN, 0x803, METHOD_BUFFERED, FILE_ANY_ACCESS)

#define SMBIOS_BLOB_CAPACITY 512
#define FIRMWARE_BLOB_CAPACITY 128
#define HAL_BLOB_CAPACITY 64

#pragma pack(push, 1)

typedef struct _SMBIOS_TYPE1_HEADER {
    UCHAR Type;
    UCHAR Length;
    USHORT Handle;
    UCHAR Manufacturer;
    UCHAR ProductName;
    UCHAR Version;
    UCHAR SerialNumber;
    UCHAR Uuid[16];
    UCHAR WakeUpType;
    UCHAR SkuNumber;
    UCHAR Family;
} SMBIOS_TYPE1_HEADER, *PSMBIOS_TYPE1_HEADER;

#pragma pack(pop)

C_ASSERT(sizeof(SMBIOS_TYPE1_HEADER) == 27);

DRIVER_INITIALIZE DriverEntry;

_Dispatch_type_(IRP_MJ_CREATE)
DRIVER_DISPATCH HwidCreateClose;

_Dispatch_type_(IRP_MJ_CLOSE)
DRIVER_DISPATCH HwidCreateClose;

_Dispatch_type_(IRP_MJ_DEVICE_CONTROL)
DRIVER_DISPATCH HwidDeviceControl;

DRIVER_UNLOAD HwidUnload;

NTSTATUS
Hooked_NtQuerySystemInformation(
    _In_ ULONG SystemInformationClass,
    _Out_writes_bytes_opt_(SystemInformationLength) PVOID SystemInformation,
    _In_ ULONG SystemInformationLength,
    _Out_opt_ PULONG ReturnLength
    );

NTSTATUS
BuildFakeSmbiosBlob(
    VOID
    );

NTSTATUS
BuildFakeFirmwareBlob(
    VOID
    );

NTSTATUS
BuildFakeHalBlob(
    VOID
    );
