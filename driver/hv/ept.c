#include "hv.h"

static
PVOID
HvAllocateLowPage(
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
HvFreePage(
    _In_opt_ PVOID Page
    )
{
    if (Page != NULL) {
        MmFreeContiguousMemory(Page);
    }
}

NTSTATUS
HvInitializeEpt(
    VOID
    )
{
    PULONG64 pml4;
    PULONG64 pdpt;
    PULONG64 pd;
    ULONG index;

    if (g_HvState.Ept.Pml4 != NULL) {
        return STATUS_SUCCESS;
    }

    g_HvState.Ept.Pml4 =
        HvAllocateLowPage(
            &g_HvState.Ept.Pml4Physical
            );
    g_HvState.Ept.Pdpt =
        HvAllocateLowPage(
            &g_HvState.Ept.PdptPhysical
            );
    g_HvState.Ept.Pd =
        HvAllocateLowPage(
            &g_HvState.Ept.PdPhysical
            );

    if (g_HvState.Ept.Pml4 == NULL ||
        g_HvState.Ept.Pdpt == NULL ||
        g_HvState.Ept.Pd == NULL) {
        HvTeardownEpt();
        return STATUS_INSUFFICIENT_RESOURCES;
    }

    pml4 = (PULONG64)g_HvState.Ept.Pml4;
    pdpt = (PULONG64)g_HvState.Ept.Pdpt;
    pd = (PULONG64)g_HvState.Ept.Pd;

    pml4[0] =
        (g_HvState.Ept.PdptPhysical.QuadPart &
            HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE;

    pdpt[0] =
        (g_HvState.Ept.PdPhysical.QuadPart &
            HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE;

    //
    // Lab identity map: first 1 GiB with 2 MiB leaves.
    // The synthetic page in smbios_shadow.c is deliberately allocated in
    // this range. This is not a general-purpose physical-memory mapper.
    //
    for (index = 0; index < 512; ++index) {
        ULONG64 physicalBase =
            (ULONG64)index * HV_2MB_SIZE;

        pd[index] =
            (physicalBase & HV_EPT_ADDR_MASK) |
            HV_EPT_READ |
            HV_EPT_WRITE |
            HV_EPT_EXECUTE |
            HV_EPT_MEMTYPE_WB |
            HV_EPT_LARGE_PAGE;
    }

    //
    // EPTP: WB memory type, four-level walk (encoded as 3),
    // accessed/dirty tracking disabled.
    //
    g_HvState.Ept.EptPointer =
        (g_HvState.Ept.Pml4Physical.QuadPart &
            HV_EPT_ADDR_MASK) |
        6ull |
        (3ull << 3);

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] EPT lab map initialized: "
        "first 1 GiB identity-mapped, EPTP=%llX\n",
        g_HvState.Ept.EptPointer
        );

    return STATUS_SUCCESS;
}

NTSTATUS
HvSetupEptForSmbios(
    VOID
    )
{
    KIRQL oldIrql;
    PULONG64 pd;
    PULONG64 pt;
    ULONG64 targetPhysical;
    ULONG64 shadowPhysical;
    ULONG64 twoMbBase;
    ULONG pdIndex;
    ULONG ptIndex;
    ULONG index;
    NTSTATUS status;

    status = HvCreateSmbiosShadow();
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = HvInitializeEpt();
    if (!NT_SUCCESS(status)) {
        return status;
    }

    targetPhysical =
        g_HvState.Ept.LabSmbiosPhysical.QuadPart;
    shadowPhysical =
        g_HvState.Ept.LabShadowPhysical.QuadPart;

    if (targetPhysical >= HV_1GB_SIZE ||
        shadowPhysical >= HV_1GB_SIZE) {
        return STATUS_NOT_SUPPORTED;
    }

    pdIndex =
        (ULONG)((targetPhysical >> 21) & 0x1FF);
    ptIndex =
        (ULONG)((targetPhysical >> 12) & 0x1FF);
    twoMbBase =
        targetPhysical & ~(HV_2MB_SIZE - 1);

    KeAcquireSpinLock(
        &g_HvState.Ept.Lock,
        &oldIrql
        );

    if (g_HvState.Ept.SplitPt == NULL) {
        g_HvState.Ept.SplitPt =
            HvAllocateLowPage(
                &g_HvState.Ept.SplitPtPhysical
                );

        if (g_HvState.Ept.SplitPt == NULL) {
            KeReleaseSpinLock(
                &g_HvState.Ept.Lock,
                oldIrql
                );
            return STATUS_INSUFFICIENT_RESOURCES;
        }
    }

    g_HvState.Ept.SplitPdIndex = pdIndex;

    pd = (PULONG64)g_HvState.Ept.Pd;
    pt = (PULONG64)g_HvState.Ept.SplitPt;

    for (index = 0; index < 512; ++index) {
        ULONG64 pagePhysical =
            twoMbBase +
            ((ULONG64)index * PAGE_SIZE);

        pt[index] =
            (pagePhysical & HV_EPT_ADDR_MASK) |
            HV_EPT_READ |
            HV_EPT_WRITE |
            HV_EPT_EXECUTE |
            HV_EPT_MEMTYPE_WB;
    }

    //
    // Redirect only the driver-owned synthetic lab page to its cloned
    // shadow. No firmware/SMBIOS page from the system is discovered,
    // modified, or remapped by this lab implementation.
    //
    pt[ptIndex] =
        (shadowPhysical & HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE |
        HV_EPT_MEMTYPE_WB;

    KeMemoryBarrier();

    pd[pdIndex] =
        (g_HvState.Ept.SplitPtPhysical.QuadPart &
            HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE;

    KeMemoryBarrier();

    InterlockedExchange(
        &g_HvState.Ept.LabShadowInstalled,
        1
        );

    KeReleaseSpinLock(
        &g_HvState.Ept.Lock,
        oldIrql
        );

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] Synthetic SMBIOS lab mapping prepared: "
        "GPA=%llX -> shadow=%llX\n",
        targetPhysical,
        shadowPhysical
        );

    return STATUS_SUCCESS;
}

VOID
HvTeardownEpt(
    VOID
    )
{
    InterlockedExchange(
        &g_HvState.Ept.LabShadowInstalled,
        0
        );

    HvFreePage(g_HvState.Ept.SplitPt);
    HvFreePage(g_HvState.Ept.Pd);
    HvFreePage(g_HvState.Ept.Pdpt);
    HvFreePage(g_HvState.Ept.Pml4);

    HvFreePage(g_HvState.Ept.LabShadowPage);
    HvFreePage(g_HvState.Ept.LabSmbiosPage);

    g_HvState.Ept.SplitPt = NULL;
    g_HvState.Ept.Pd = NULL;
    g_HvState.Ept.Pdpt = NULL;
    g_HvState.Ept.Pml4 = NULL;
    g_HvState.Ept.LabShadowPage = NULL;
    g_HvState.Ept.LabSmbiosPage = NULL;

    g_HvState.Ept.SplitPtPhysical.QuadPart = 0;
    g_HvState.Ept.PdPhysical.QuadPart = 0;
    g_HvState.Ept.PdptPhysical.QuadPart = 0;
    g_HvState.Ept.Pml4Physical.QuadPart = 0;
    g_HvState.Ept.LabShadowPhysical.QuadPart = 0;
    g_HvState.Ept.LabSmbiosPhysical.QuadPart = 0;
    g_HvState.Ept.EptPointer = 0;
}
