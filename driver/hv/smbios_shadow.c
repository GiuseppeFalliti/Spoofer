#include "hv.h"

#pragma pack(push, 1)

typedef struct _HV_LAB_SMBIOS_TYPE1 {
    CHAR Signature[8];
    UCHAR Type;
    UCHAR Length;
    USHORT Handle;

    CHAR Manufacturer[32];
    CHAR ProductName[32];
    CHAR Version[16];
    CHAR SerialNumber[32];

    UCHAR Uuid[16];
} HV_LAB_SMBIOS_TYPE1, *PHV_LAB_SMBIOS_TYPE1;

#pragma pack(pop)

static
PVOID
HvAllocateLowShadowPage(
    _Out_ PPHYSICAL_ADDRESS PhysicalAddress
    )
{
    PHYSICAL_ADDRESS lowest;
    PHYSICAL_ADDRESS highest;
    PHYSICAL_ADDRESS boundary;
    PVOID page;

    lowest.QuadPart = 0;
    highest.QuadPart = HV_1GB_SIZE - 1;
    boundary.QuadPart = 0;

    page = MmAllocateContiguousMemorySpecifyCache(
        PAGE_SIZE,
        lowest,
        highest,
        boundary,
        MmCached
        );

    if (page == NULL) {
        PhysicalAddress->QuadPart = 0;
        return NULL;
    }

    RtlZeroMemory(page, PAGE_SIZE);
    *PhysicalAddress = MmGetPhysicalAddress(page);
    return page;
}

static
VOID
HvCopyFixedString(
    _Out_writes_bytes_(DestinationSize) PCHAR Destination,
    _In_ SIZE_T DestinationSize,
    _In_z_ PCSTR Source
    )
{
    SIZE_T sourceLength;

    if (Destination == NULL ||
        DestinationSize == 0 ||
        Source == NULL) {
        return;
    }

    RtlZeroMemory(Destination, DestinationSize);

    sourceLength = strlen(Source);
    if (sourceLength >= DestinationSize) {
        sourceLength = DestinationSize - 1;
    }

    RtlCopyMemory(
        Destination,
        Source,
        sourceLength
        );
}

NTSTATUS
HvPatchSmbiosType1(
    _Inout_updates_bytes_(PageSize) PVOID Page,
    _In_ SIZE_T PageSize
    )
{
    PHV_LAB_SMBIOS_TYPE1 type1;
    static const UCHAR labUuid[16] = {
        0x48, 0x56, 0x4C, 0x41,
        0x42, 0x2D, 0x45, 0x50,
        0x54, 0x2D, 0x54, 0x45,
        0x53, 0x54, 0x30, 0x31
    };

    if (Page == NULL ||
        PageSize < sizeof(HV_LAB_SMBIOS_TYPE1)) {
        return STATUS_BUFFER_TOO_SMALL;
    }

    type1 = (PHV_LAB_SMBIOS_TYPE1)Page;

    if (RtlCompareMemory(
            type1->Signature,
            "HVLAB01",
            7) != 7 ||
        type1->Type != 1) {
        return STATUS_INVALID_PARAMETER;
    }

    //
    // Only the synthetic record created by this module is patched.
    // This function never parses or changes the machine's real SMBIOS.
    //
    HvCopyFixedString(
        type1->Manufacturer,
        sizeof(type1->Manufacturer),
        "OpenAI-HV-Lab"
        );

    HvCopyFixedString(
        type1->ProductName,
        sizeof(type1->ProductName),
        "EPT-Shadow-Test"
        );

    HvCopyFixedString(
        type1->Version,
        sizeof(type1->Version),
        "lab-1.0"
        );

    HvCopyFixedString(
        type1->SerialNumber,
        sizeof(type1->SerialNumber),
        "LAB-SHADOW-0001"
        );

    RtlCopyMemory(
        type1->Uuid,
        labUuid,
        sizeof(labUuid)
        );

    return STATUS_SUCCESS;
}

NTSTATUS
HvCreateSmbiosShadow(
    VOID
    )
{
    PHV_LAB_SMBIOS_TYPE1 original;
    NTSTATUS status;

    if (g_HvState.Ept.LabSmbiosPage != NULL &&
        g_HvState.Ept.LabShadowPage != NULL) {
        return STATUS_SUCCESS;
    }

    g_HvState.Ept.LabSmbiosPage =
        HvAllocateLowShadowPage(
            &g_HvState.Ept.LabSmbiosPhysical
            );

    if (g_HvState.Ept.LabSmbiosPage == NULL) {
        return STATUS_INSUFFICIENT_RESOURCES;
    }

    g_HvState.Ept.LabShadowPage =
        HvAllocateLowShadowPage(
            &g_HvState.Ept.LabShadowPhysical
            );

    if (g_HvState.Ept.LabShadowPage == NULL) {
        MmFreeContiguousMemory(
            g_HvState.Ept.LabSmbiosPage
            );
        g_HvState.Ept.LabSmbiosPage = NULL;
        g_HvState.Ept.LabSmbiosPhysical.QuadPart = 0;
        return STATUS_INSUFFICIENT_RESOURCES;
    }

    original =
        (PHV_LAB_SMBIOS_TYPE1)
            g_HvState.Ept.LabSmbiosPage;

    RtlZeroMemory(
        original,
        sizeof(*original)
        );

    RtlCopyMemory(
        original->Signature,
        "HVLAB01",
        7
        );

    original->Type = 1;
    original->Length =
        (UCHAR)sizeof(*original);
    original->Handle = 1;

    HvCopyFixedString(
        original->Manufacturer,
        sizeof(original->Manufacturer),
        "Original-Lab"
        );

    HvCopyFixedString(
        original->ProductName,
        sizeof(original->ProductName),
        "Synthetic-Page"
        );

    HvCopyFixedString(
        original->Version,
        sizeof(original->Version),
        "original"
        );

    HvCopyFixedString(
        original->SerialNumber,
        sizeof(original->SerialNumber),
        "LAB-ORIGINAL-0001"
        );

    RtlCopyMemory(
        g_HvState.Ept.LabShadowPage,
        g_HvState.Ept.LabSmbiosPage,
        PAGE_SIZE
        );

    status = HvPatchSmbiosType1(
        g_HvState.Ept.LabShadowPage,
        PAGE_SIZE
        );

    if (!NT_SUCCESS(status)) {
        return status;
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] Synthetic Type-1 shadow created: "
        "source_pa=%llX shadow_pa=%llX\n",
        g_HvState.Ept.LabSmbiosPhysical.QuadPart,
        g_HvState.Ept.LabShadowPhysical.QuadPart
        );

    return STATUS_SUCCESS;
}

NTSTATUS
HvInjectSmbiosData(
    VOID
    )
{
    if (InterlockedCompareExchange(
            &g_HvState.Ept.LabShadowInstalled,
            0,
            0) == 0) {
        return STATUS_DEVICE_NOT_READY;
    }

    //
    // EPT redirection already points the synthetic GPA at the synthetic
    // shadow page. Re-applying the deterministic lab patch is sufficient for
    // repeatable tests without touching system firmware identifiers.
    //
    return HvPatchSmbiosType1(
        g_HvState.Ept.LabShadowPage,
        PAGE_SIZE
        );
}
