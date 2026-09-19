#include "driver.h"
#include <intrin.h>

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

static UCHAR g_FirmwareBlob[FIRMWARE_BLOB_CAPACITY];
static ULONG g_FirmwareBlobSize = 0;

static UCHAR g_HalBlob[HAL_BLOB_CAPACITY];
static ULONG g_HalBlobSize = 0;

#pragma pack(push, 1)

typedef struct _FAKE_PCI_DATA {
    USHORT VendorID;
    USHORT DeviceID;
    USHORT Command;
    USHORT Status;
    UCHAR RevisionID;
    UCHAR ProgIf;
    UCHAR SubClass;
    UCHAR BaseClass;
    UCHAR CacheLineSize;
    UCHAR LatencyTimer;
    UCHAR HeaderType;
    UCHAR BIST;
} FAKE_PCI_DATA, *PFAKE_PCI_DATA;

#pragma pack(pop)

C_ASSERT(sizeof(FAKE_PCI_DATA) == 16);

typedef NTSTATUS (NTAPI *PFN_NT_QUERY_SYSTEM_INFORMATION)(
    _In_ ULONG SystemInformationClass,
    _Inout_updates_bytes_(SystemInformationLength) PVOID SystemInformation,
    _In_ ULONG SystemInformationLength,
    _Out_opt_ PULONG ReturnLength
    );

static PFN_NT_QUERY_SYSTEM_INFORMATION g_OriginalNtQuerySystemInformation = NULL;

#define IA32_FEATURE_CONTROL_MSR          0x0000003A
#define IA32_VMX_BASIC_MSR                0x00000480
#define IA32_VMX_PROCBASED_CTLS_MSR       0x00000482
#define IA32_VMX_PROCBASED_CTLS2_MSR      0x0000048B
#define IA32_VMX_EPT_VPID_CAP_MSR         0x0000048C

#define CPUID_ECX_VMX                     (1UL << 5)
#define CPUID_ECX_HYPERVISOR_PRESENT      (1UL << 31)

#define FEATURE_CONTROL_LOCK              (1ULL << 0)
#define FEATURE_CONTROL_VMX_OUTSIDE_SMX   (1ULL << 2)

#define VMX_PRIMARY_ACTIVATE_SECONDARY    (1UL << 31)
#define VMX_SECONDARY_ENABLE_EPT          (1UL << 1)

#define EPT_CAP_PAGE_WALK_LENGTH_4        (1ULL << 6)
#define EPT_CAP_WRITE_BACK                (1ULL << 14)

static
NTSTATUS
HvReadMsrSafe(
    _In_ ULONG Msr,
    _Out_ PULONGLONG Value
    )
{
    NTSTATUS exceptionCode;

    if (Value == NULL) {
        return STATUS_INVALID_PARAMETER;
    }

    *Value = 0;

    __try {
        *Value = __readmsr(Msr);
        return STATUS_SUCCESS;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        exceptionCode = (NTSTATUS)GetExceptionCode();

        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_WARNING_LEVEL,
            "[HwidSpoofer][HV] RDMSR 0x%08lX failed: 0x%08X\n",
            Msr,
            exceptionCode
            );

        return exceptionCode;
    }
}

BOOLEAN
HvCheckHypervisorPresence(
    VOID
    )
{
    int cpuInfo[4] = { 0 };
    int hvInfo[4] = { 0 };
    CHAR vendorId[13];

    RtlZeroMemory(vendorId, sizeof(vendorId));

    __cpuid(cpuInfo, 1);

    if ((((ULONG)cpuInfo[2]) & CPUID_ECX_HYPERVISOR_PRESENT) == 0) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer][HV] CPUID hypervisor-present bit: 0\n"
            );

        return FALSE;
    }

    __cpuid(hvInfo, 0x40000000);

    //
    // Hypervisor vendor strings use EBX, ECX, EDX order.
    //
    RtlCopyMemory(&vendorId[0], &hvInfo[1], sizeof(ULONG));
    RtlCopyMemory(&vendorId[4], &hvInfo[2], sizeof(ULONG));
    RtlCopyMemory(&vendorId[8], &hvInfo[3], sizeof(ULONG));
    vendorId[12] = '\0';

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer][HV] Hypervisor present: vendor='%s', "
        "Microsoft Hyper-V=%u, max leaf=0x%08X\n",
        vendorId,
        (ULONG)(RtlCompareMemory(vendorId, "Microsoft Hv", 12) == 12),
        (ULONG)hvInfo[0]
        );

    return TRUE;
}

NTSTATUS
HvCheckVtxSupport(
    _Out_ PVTX_CAPABILITIES Capabilities
    )
{
    int cpuInfo[4] = { 0 };
    CHAR cpuVendor[13];

    ULONGLONG featureControl = 0;
    ULONGLONG vmxBasic = 0;
    ULONGLONG procBasedControls = 0;
    ULONGLONG procBasedControls2 = 0;
    ULONGLONG eptVpidCapabilities = 0;

    BOOLEAN featureControlLocked;
    BOOLEAN vmxOutsideSmxEnabled;
    BOOLEAN secondaryControlsAllowed;
    BOOLEAN eptControlAllowed;
    BOOLEAN eptFourLevelWalk;
    BOOLEAN eptWriteBack;

    NTSTATUS status;

    if (Capabilities == NULL) {
        return STATUS_INVALID_PARAMETER;
    }

    RtlZeroMemory(Capabilities, sizeof(*Capabilities));
    RtlZeroMemory(cpuVendor, sizeof(cpuVendor));

    Capabilities->ProcessorCount =
        KeQueryActiveProcessorCountEx(ALL_PROCESSOR_GROUPS);

    Capabilities->HypervisorPresent =
        HvCheckHypervisorPresence();

    __cpuid(cpuInfo, 0);

    //
    // Normal CPU vendor strings use EBX, EDX, ECX order.
    //
    RtlCopyMemory(&cpuVendor[0], &cpuInfo[1], sizeof(ULONG));
    RtlCopyMemory(&cpuVendor[4], &cpuInfo[3], sizeof(ULONG));
    RtlCopyMemory(&cpuVendor[8], &cpuInfo[2], sizeof(ULONG));
    cpuVendor[12] = '\0';

    if (RtlCompareMemory(cpuVendor, "GenuineIntel", 12) != 12) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_WARNING_LEVEL,
            "[HwidSpoofer][HV] CPU vendor '%s' is not GenuineIntel; "
            "Intel VT-x probe skipped\n",
            cpuVendor
            );

        return STATUS_SUCCESS;
    }

    __cpuid(cpuInfo, 1);

    Capabilities->VtxSupported =
        ((((ULONG)cpuInfo[2]) & CPUID_ECX_VMX) != 0) ? TRUE : FALSE;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer][HV] CPUID.01H:ECX.VMX=%u, hypervisor=%u, CPUs=%lu\n",
        (ULONG)Capabilities->VtxSupported,
        (ULONG)Capabilities->HypervisorPresent,
        Capabilities->ProcessorCount
        );

    if (!Capabilities->VtxSupported) {
        return STATUS_SUCCESS;
    }

    status = HvReadMsrSafe(
        IA32_FEATURE_CONTROL_MSR,
        &featureControl
        );

    if (!NT_SUCCESS(status)) {
        Capabilities->VmxLocked = TRUE;
        return STATUS_SUCCESS;
    }

    featureControlLocked =
        ((featureControl & FEATURE_CONTROL_LOCK) != 0) ? TRUE : FALSE;

    vmxOutsideSmxEnabled =
        ((featureControl & FEATURE_CONTROL_VMX_OUTSIDE_SMX) != 0)
            ? TRUE
            : FALSE;

    //
    // For this diagnostic structure, VmxLocked means "VMXON outside SMX
    // is not currently permitted by IA32_FEATURE_CONTROL".  Intel requires
    // both the lock bit and Enable VMX Outside SMX for VMXON to be legal.
    //
    Capabilities->VmxLocked =
        (!featureControlLocked || !vmxOutsideSmxEnabled) ? TRUE : FALSE;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer][HV] IA32_FEATURE_CONTROL=0x%I64X "
        "(Lock=%u, VMX outside SMX=%u, blocked=%u)\n",
        featureControl,
        (ULONG)featureControlLocked,
        (ULONG)vmxOutsideSmxEnabled,
        (ULONG)Capabilities->VmxLocked
        );

    status = HvReadMsrSafe(
        IA32_VMX_BASIC_MSR,
        &vmxBasic
        );

    if (!NT_SUCCESS(status)) {
        return STATUS_SUCCESS;
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer][HV] IA32_VMX_BASIC=0x%I64X "
        "(RevisionId=0x%08lX, RegionSize=%lu, TrueControls=%u)\n",
        vmxBasic,
        (ULONG)(vmxBasic & 0x7FFFFFFFULL),
        (ULONG)((vmxBasic >> 32) & 0x1FFFULL),
        (ULONG)((vmxBasic >> 55) & 0x1ULL)
        );

    //
    // Before reading IA32_VMX_EPT_VPID_CAP, verify that secondary
    // processor-based controls exist and that their allowed-1 settings
    // permit Enable EPT. This avoids treating the capability MSR as an
    // unconditional indication that EPT can actually be enabled.
    //
    status = HvReadMsrSafe(
        IA32_VMX_PROCBASED_CTLS_MSR,
        &procBasedControls
        );

    if (!NT_SUCCESS(status)) {
        return STATUS_SUCCESS;
    }

    secondaryControlsAllowed =
        ((((ULONG)(procBasedControls >> 32)) &
          VMX_PRIMARY_ACTIVATE_SECONDARY) != 0)
            ? TRUE
            : FALSE;

    if (!secondaryControlsAllowed) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer][HV] Secondary VM-execution controls are not available\n"
            );

        return STATUS_SUCCESS;
    }

    status = HvReadMsrSafe(
        IA32_VMX_PROCBASED_CTLS2_MSR,
        &procBasedControls2
        );

    if (!NT_SUCCESS(status)) {
        return STATUS_SUCCESS;
    }

    eptControlAllowed =
        ((((ULONG)(procBasedControls2 >> 32)) &
          VMX_SECONDARY_ENABLE_EPT) != 0)
            ? TRUE
            : FALSE;

    if (!eptControlAllowed) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer][HV] Secondary controls do not allow Enable EPT\n"
            );

        return STATUS_SUCCESS;
    }

    status = HvReadMsrSafe(
        IA32_VMX_EPT_VPID_CAP_MSR,
        &eptVpidCapabilities
        );

    if (!NT_SUCCESS(status)) {
        return STATUS_SUCCESS;
    }

    eptFourLevelWalk =
        ((eptVpidCapabilities & EPT_CAP_PAGE_WALK_LENGTH_4) != 0)
            ? TRUE
            : FALSE;

    eptWriteBack =
        ((eptVpidCapabilities & EPT_CAP_WRITE_BACK) != 0)
            ? TRUE
            : FALSE;

    Capabilities->EptSupported =
        (eptControlAllowed && eptFourLevelWalk) ? TRUE : FALSE;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer][HV] IA32_VMX_EPT_VPID_CAP=0x%I64X "
        "(EPT control=%u, 4-level walk=%u, WB=%u, EPT supported=%u)\n",
        eptVpidCapabilities,
        (ULONG)eptControlAllowed,
        (ULONG)eptFourLevelWalk,
        (ULONG)eptWriteBack,
        (ULONG)Capabilities->EptSupported
        );

    return STATUS_SUCCESS;
}

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
BuildFakeFirmwareBlob(
    VOID
    )
{
    static const CHAR fakeVariable[] = "SecureBootEnabled";
    static const CHAR fakeValue[] = "0x0";
    ULONG requiredSize;
    ULONG offset = 0;

    //
    // Test-wire format used by the user-mode application:
    //
    //   SecureBootEnabled\0x0\0
    //
    // The first NUL terminates the variable name and separates it from the
    // value; the second terminates the value.
    //
    requiredSize = (ULONG)sizeof(fakeVariable) + (ULONG)sizeof(fakeValue);

    if (requiredSize > sizeof(g_FirmwareBlob)) {
        g_FirmwareBlobSize = 0;
        return STATUS_BUFFER_TOO_SMALL;
    }

    RtlZeroMemory(g_FirmwareBlob, sizeof(g_FirmwareBlob));

    RtlCopyMemory(
        &g_FirmwareBlob[offset],
        fakeVariable,
        sizeof(fakeVariable)
        );
    offset += (ULONG)sizeof(fakeVariable);

    RtlCopyMemory(
        &g_FirmwareBlob[offset],
        fakeValue,
        sizeof(fakeValue)
        );
    offset += (ULONG)sizeof(fakeValue);

    g_FirmwareBlobSize = offset;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer] Fake firmware blob prepared: %lu bytes\n",
        g_FirmwareBlobSize
        );

    return STATUS_SUCCESS;
}

NTSTATUS
BuildFakeHalBlob(
    VOID
    )
{
    FAKE_PCI_DATA pciData;
    ULONG requiredSize = (ULONG)sizeof(pciData);

    if (requiredSize > sizeof(g_HalBlob)) {
        g_HalBlobSize = 0;
        return STATUS_BUFFER_TOO_SMALL;
    }

    RtlZeroMemory(&pciData, sizeof(pciData));
    RtlZeroMemory(g_HalBlob, sizeof(g_HalBlob));

    //
    // Compact PCI configuration-header test payload.  The first fields and
    // RevisionID use the same offsets as the standard PCI common header, so
    // user mode can validate the HAL spoofing logic without touching real
    // hardware or installing a kernel hook.
    //
    pciData.VendorID = 0x1234;
    pciData.DeviceID = 0x5678;
    pciData.Command = 0x0007;
    pciData.Status = 0x0010;
    pciData.RevisionID = 0x01;
    pciData.ProgIf = 0x00;
    pciData.SubClass = 0x00;
    pciData.BaseClass = 0x02;
    pciData.CacheLineSize = 0x10;
    pciData.LatencyTimer = 0x00;
    pciData.HeaderType = 0x00;
    pciData.BIST = 0x00;

    RtlCopyMemory(
        g_HalBlob,
        &pciData,
        sizeof(pciData)
        );

    g_HalBlobSize = requiredSize;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidSpoofer] Fake HAL/PCI blob prepared: %lu bytes "
        "(VID=%04X DID=%04X REV=%02X)\n",
        g_HalBlobSize,
        pciData.VendorID,
        pciData.DeviceID,
        pciData.RevisionID
        );

    return STATUS_SUCCESS;
}

NTSTATUS
Hooked_NtQuerySystemInformation(
    _In_ ULONG SystemInformationClass,
    _Out_writes_bytes_opt_(SystemInformationLength) PVOID SystemInformation,
    _In_ ULONG SystemInformationLength,
    _Out_opt_ PULONG ReturnLength
    )
{
    NTSTATUS status;

    //
    // This is not installed as a global hook.  The original routine pointer
    // is kept only so this proxy preserves NtQuerySystemInformation semantics
    // when the SMBIOS test path is disabled.
    //
    if (InterlockedCompareExchange(&g_SmbiosHookEnabled, 0, 0) == 0) {
        if (g_OriginalNtQuerySystemInformation == NULL) {
            return STATUS_NOT_SUPPORTED;
        }

        return g_OriginalNtQuerySystemInformation(
            SystemInformationClass,
            SystemInformation,
            SystemInformationLength,
            ReturnLength
            );
    }

    status = BuildFakeSmbiosBlob();
    if (!NT_SUCCESS(status)) {
        return status;
    }

    if (ReturnLength != NULL) {
        *ReturnLength = g_SmbiosBlobSize;
    }

    if (SystemInformation == NULL ||
        SystemInformationLength < g_SmbiosBlobSize) {
        return STATUS_BUFFER_TOO_SMALL;
    }

    //
    // Hooked_NtQuerySystemInformation is invoked only by our METHOD_BUFFERED
    // IOCTL path, so SystemInformation is a kernel SystemBuffer here.
    //
    RtlCopyMemory(
        SystemInformation,
        g_SmbiosBlob,
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
    ULONG_PTR information = 0;
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

    case IOCTL_CHECK_VTX_SUPPORT:
    {
        ULONG outputLength =
            stack->Parameters.DeviceIoControl.OutputBufferLength;
        PVTX_CAPABILITIES capabilities;

        if (Irp->AssociatedIrp.SystemBuffer == NULL ||
            outputLength < sizeof(VTX_CAPABILITIES)) {
            status = STATUS_BUFFER_TOO_SMALL;

            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer][HV] VT-x capability output buffer too small: "
                "provided=%lu required=%lu\n",
                outputLength,
                (ULONG)sizeof(VTX_CAPABILITIES)
                );

            break;
        }

        capabilities =
            (PVTX_CAPABILITIES)Irp->AssociatedIrp.SystemBuffer;

        status = HvCheckVtxSupport(capabilities);

        if (NT_SUCCESS(status)) {
            information = sizeof(VTX_CAPABILITIES);

            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_INFO_LEVEL,
                "[HwidSpoofer][HV] Capability report returned: "
                "VT-x=%u EPT=%u VMX-blocked=%u hypervisor=%u CPUs=%lu\n",
                (ULONG)capabilities->VtxSupported,
                (ULONG)capabilities->EptSupported,
                (ULONG)capabilities->VmxLocked,
                (ULONG)capabilities->HypervisorPresent,
                capabilities->ProcessorCount
                );
        }

        break;
    }

    case IOCTL_CHECK_HYPERVISOR:
    {
        ULONG outputLength =
            stack->Parameters.DeviceIoControl.OutputBufferLength;
        PBOOLEAN hypervisorPresent;

        if (Irp->AssociatedIrp.SystemBuffer == NULL ||
            outputLength < sizeof(BOOLEAN)) {
            status = STATUS_BUFFER_TOO_SMALL;

            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer][HV] Hypervisor output buffer too small: "
                "provided=%lu required=%lu\n",
                outputLength,
                (ULONG)sizeof(BOOLEAN)
                );

            break;
        }

        hypervisorPresent =
            (PBOOLEAN)Irp->AssociatedIrp.SystemBuffer;

        *hypervisorPresent = HvCheckHypervisorPresence();
        information = sizeof(BOOLEAN);

        break;
    }

    case IOCTL_QUERY_FAKE_HAL:
    {
        ULONG outputLength =
            stack->Parameters.DeviceIoControl.OutputBufferLength;

        if (InterlockedCompareExchange(&g_HalHookEnabled, 0, 0) == 0) {
            status = STATUS_DEVICE_NOT_READY;
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer] Fake HAL query rejected: hook disabled\n"
                );
            break;
        }

        status = BuildFakeHalBlob();
        if (!NT_SUCCESS(status)) {
            break;
        }

        if (Irp->AssociatedIrp.SystemBuffer == NULL ||
            outputLength < g_HalBlobSize) {
            status = STATUS_BUFFER_TOO_SMALL;
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer] Fake HAL output buffer too small: "
                "provided=%lu required=%lu\n",
                outputLength,
                g_HalBlobSize
                );
            break;
        }

        RtlCopyMemory(
            Irp->AssociatedIrp.SystemBuffer,
            g_HalBlob,
            g_HalBlobSize
            );

        information = g_HalBlobSize;

        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] Returned fake HAL/PCI blob: %lu bytes\n",
            g_HalBlobSize
            );

        break;
    }

    case IOCTL_QUERY_FAKE_FIRMWARE:
    {
        ULONG outputLength =
            stack->Parameters.DeviceIoControl.OutputBufferLength;

        if (InterlockedCompareExchange(&g_FirmwareHookEnabled, 0, 0) == 0) {
            status = STATUS_DEVICE_NOT_READY;
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer] Fake firmware query rejected: hook disabled\n"
                );
            break;
        }

        status = BuildFakeFirmwareBlob();
        if (!NT_SUCCESS(status)) {
            break;
        }

        if (Irp->AssociatedIrp.SystemBuffer == NULL ||
            outputLength < g_FirmwareBlobSize) {
            status = STATUS_BUFFER_TOO_SMALL;
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer] Fake firmware output buffer too small: "
                "provided=%lu required=%lu\n",
                outputLength,
                g_FirmwareBlobSize
                );
            break;
        }

        RtlCopyMemory(
            Irp->AssociatedIrp.SystemBuffer,
            g_FirmwareBlob,
            g_FirmwareBlobSize
            );

        information = g_FirmwareBlobSize;

        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_INFO_LEVEL,
            "[HwidSpoofer] Returned fake firmware blob: %lu bytes\n",
            g_FirmwareBlobSize
            );

        break;
    }

    case IOCTL_QUERY_FAKE_SMBIOS:
    {
        ULONG returnLength = 0;
        ULONG outputLength =
            stack->Parameters.DeviceIoControl.OutputBufferLength;

        //
        // Keep this IOCTL explicitly tied to the existing enable/disable
        // state.  This also guarantees that the proxy never falls through to
        // the real system-information routine for a test request.
        //
        if (InterlockedCompareExchange(&g_SmbiosHookEnabled, 0, 0) == 0) {
            status = STATUS_DEVICE_NOT_READY;
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer] Fake SMBIOS query rejected: hook disabled\n"
                );
            break;
        }

        status = Hooked_NtQuerySystemInformation(
            0,
            Irp->AssociatedIrp.SystemBuffer,
            outputLength,
            &returnLength
            );

        if (NT_SUCCESS(status)) {
            information = returnLength;

            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_INFO_LEVEL,
                "[HwidSpoofer] Returned fake SMBIOS blob: %lu bytes\n",
                returnLength
                );
        }
        else if (status == STATUS_BUFFER_TOO_SMALL) {
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_WARNING_LEVEL,
                "[HwidSpoofer] Fake SMBIOS output buffer too small: "
                "provided=%lu required=%lu\n",
                outputLength,
                returnLength
                );
        }

        break;
    }

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

    CompleteIrp(Irp, status, information);
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
    g_OriginalNtQuerySystemInformation = NULL;

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
    UNICODE_STRING systemRoutineName;

    UNREFERENCED_PARAMETER(RegistryPath);

    RtlInitUnicodeString(&deviceName, HWID_DEVICE_NAME);
    RtlInitUnicodeString(&dosDeviceName, HWID_DOS_DEVICE_NAME);

    //
    // Resolve a supported kernel entry point without modifying the SSDT.
    // It is used only by the proxy's pass-through branch.
    //
    RtlInitUnicodeString(&systemRoutineName, L"ZwQuerySystemInformation");
    g_OriginalNtQuerySystemInformation =
        (PFN_NT_QUERY_SYSTEM_INFORMATION)
        MmGetSystemRoutineAddress(&systemRoutineName);

    if (g_OriginalNtQuerySystemInformation == NULL) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_WARNING_LEVEL,
            "[HwidSpoofer] ZwQuerySystemInformation was not resolved; "
            "proxy pass-through is unavailable\n"
            );
    }

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
