#include "hv.h"

typedef __declspec(align(16)) struct _HV_INVEPT_DESCRIPTOR {
    ULONG64 EptPointer;
    ULONG64 Reserved;
} HV_INVEPT_DESCRIPTOR, *PHV_INVEPT_DESCRIPTOR;

static
PVOID
HvAllocateEptPage(
    _Out_ PPHYSICAL_ADDRESS PhysicalAddress
    )
{
    PHYSICAL_ADDRESS lowest;
    PHYSICAL_ADDRESS highest;
    PHYSICAL_ADDRESS boundary;
    PVOID page;

    lowest.QuadPart = 0;
    highest.QuadPart = MAXLONGLONG;
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

static
BOOLEAN
HvEptCapabilitiesAreUsable(
    _Out_opt_ PULONG64 Capability
    )
{
    ULONG64 capability;

    capability = __readmsr(HV_IA32_VMX_EPT_VPID_CAP);

    if (Capability != NULL) {
        *Capability = capability;
    }

    return
        (capability & HV_EPT_CAP_WB) != 0 &&
        (capability & HV_EPT_CAP_2MB_PAGE) != 0 &&
        (capability & HV_EPT_CAP_1GB_PAGE) != 0 &&
        (capability & HV_EPT_CAP_INVEPT) != 0 &&
        ((capability & HV_EPT_CAP_INVEPT_SINGLE) != 0 ||
         (capability & HV_EPT_CAP_INVEPT_ALL) != 0);
}

NTSTATUS
HvInitializeEpt(
    VOID
    )
{
    PULONG64 pml4;
    PULONG64 pdpt;
    ULONG64 capability;
    ULONG index;

    if (g_HvState.Ept.Pml4 != NULL &&
        g_HvState.Ept.Pdpt != NULL &&
        g_HvState.Ept.EptPointer != 0) {
        return STATUS_SUCCESS;
    }

    if (!HvEptCapabilitiesAreUsable(&capability)) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] EPT lab requires WB, 2 MiB/1 GiB leaves and INVEPT; "
            "capabilities=%llX\n",
            capability
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    g_HvState.Ept.Pml4 =
        HvAllocateEptPage(
            &g_HvState.Ept.Pml4Physical
            );

    g_HvState.Ept.Pdpt =
        HvAllocateEptPage(
            &g_HvState.Ept.PdptPhysical
            );

    if (g_HvState.Ept.Pml4 == NULL ||
        g_HvState.Ept.Pdpt == NULL) {
        HvTeardownEpt();
        return STATUS_INSUFFICIENT_RESOURCES;
    }

    pml4 = (PULONG64)g_HvState.Ept.Pml4;
    pdpt = (PULONG64)g_HvState.Ept.Pdpt;

    pml4[0] =
        (g_HvState.Ept.PdptPhysical.QuadPart &
            HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE;

    //
    // Short-lived lab identity map: PML4[0] covers the first 512 GiB.
    // 1 GiB leaves keep the baseline EPT compact.  The single synthetic lab
    // page is split to 2 MiB and then 4 KiB only while the test hook is armed.
    //
    for (index = 0; index < 512; ++index) {
        ULONG64 physicalBase =
            (ULONG64)index * HV_1GB_SIZE;

        pdpt[index] =
            (physicalBase & HV_EPT_ADDR_MASK) |
            HV_EPT_READ |
            HV_EPT_WRITE |
            HV_EPT_EXECUTE |
            HV_EPT_MEMTYPE_WB |
            HV_EPT_LARGE_PAGE;
    }

    //
    // EPTP: write-back memory type and four-level walk.
    //
    g_HvState.Ept.EptPointer =
        (g_HvState.Ept.Pml4Physical.QuadPart &
            HV_EPT_ADDR_MASK) |
        6ull |
        (3ull << 3);

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] EPT initialized: 512 GiB identity map, EPTP=%llX "
        "cap=%llX\n",
        g_HvState.Ept.EptPointer,
        capability
        );

    return STATUS_SUCCESS;
}

BOOLEAN
HvInvalidateEptCurrentProcessor(
    VOID
    )
{
    HV_INVEPT_DESCRIPTOR descriptor;
    ULONG64 capability;
    ULONG type;
    PHV_CPU_CONTEXT cpu;

    capability = __readmsr(HV_IA32_VMX_EPT_VPID_CAP);

    RtlZeroMemory(&descriptor, sizeof(descriptor));

    if ((capability & HV_EPT_CAP_INVEPT_SINGLE) != 0) {
        type = 1;
        descriptor.EptPointer = g_HvState.Ept.EptPointer;
    }
    else if ((capability & HV_EPT_CAP_INVEPT_ALL) != 0) {
        type = 2;
    }
    else {
        return FALSE;
    }

    if (HvInvept(type, &descriptor) != 0) {
        return FALSE;
    }

    cpu = HvGetCurrentCpuContext();
    if (cpu != NULL) {
        InterlockedIncrement64(&cpu->InveptCount);
    }

    return TRUE;
}

static
ULONG_PTR
HvInvalidateEptIpi(
    _In_ ULONG_PTR Context
    )
{
    PHV_CPU_CONTEXT cpu;
    ULONG64 result;

    UNREFERENCED_PARAMETER(Context);

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return 0;
    }

    if (InterlockedCompareExchange(
            &cpu->VmxActive,
            0,
            0) == 0 ||
        InterlockedCompareExchange(
            &cpu->Launched,
            0,
            0) == 0) {
        cpu->LastStatus = STATUS_SUCCESS;
        return 0;
    }

    result = HvHypercall(HV_HYPERCALL_INVEPT);
    cpu->LastStatus = (NTSTATUS)result;
    return (ULONG_PTR)result;
}

NTSTATUS
HvInvalidateEptAllProcessors(
    VOID
    )
{
    ULONG index;

    if (InterlockedCompareExchange(
            &g_HvState.Running,
            0,
            0) == 0) {
        return STATUS_SUCCESS;
    }

    KeIpiGenericCall(
        HvInvalidateEptIpi,
        0
        );

    for (index = 0;
         index < g_HvState.ProcessorCount;
         ++index) {
        PHV_CPU_CONTEXT cpu = &g_HvState.CpuContexts[index];

        if (InterlockedCompareExchange(
                &cpu->Launched,
                0,
                0) != 0 &&
            !NT_SUCCESS(cpu->LastStatus)) {
            return cpu->LastStatus;
        }
    }

    return STATUS_SUCCESS;
}

static
NTSTATUS
HvEnsureSplitTables(
    VOID
    )
{
    if (g_HvState.Ept.Pd == NULL) {
        g_HvState.Ept.Pd =
            HvAllocateEptPage(
                &g_HvState.Ept.PdPhysical
                );

        if (g_HvState.Ept.Pd == NULL) {
            return STATUS_INSUFFICIENT_RESOURCES;
        }
    }

    if (g_HvState.Ept.SplitPt == NULL) {
        g_HvState.Ept.SplitPt =
            HvAllocateEptPage(
                &g_HvState.Ept.SplitPtPhysical
                );

        if (g_HvState.Ept.SplitPt == NULL) {
            return STATUS_INSUFFICIENT_RESOURCES;
        }
    }

    return STATUS_SUCCESS;
}

NTSTATUS
HvSetupEptForSmbios(
    VOID
    )
{
    KIRQL oldIrql;
    PULONG64 pdpt;
    PULONG64 pd;
    PULONG64 pt;

    ULONG64 targetPhysical;
    ULONG64 shadowPhysical;
    ULONG64 oneGbBase;
    ULONG64 twoMbBase;

    ULONG pdptIndex;
    ULONG pdIndex;
    ULONG ptIndex;
    ULONG index;

    NTSTATUS status;

    if (InterlockedCompareExchange(
            &g_HvState.Ept.ConfigBusy,
            1,
            0) != 0) {
        return STATUS_DEVICE_BUSY;
    }

    status = HvCreateSmbiosShadow();
    if (!NT_SUCCESS(status)) {
        goto Exit;
    }

    status = HvInitializeEpt();
    if (!NT_SUCCESS(status)) {
        goto Exit;
    }

    status = HvEnsureSplitTables();
    if (!NT_SUCCESS(status)) {
        goto Exit;
    }

    targetPhysical =
        g_HvState.Ept.LabSmbiosPhysical.QuadPart;
    shadowPhysical =
        g_HvState.Ept.LabShadowPhysical.QuadPart;

    if (targetPhysical >= HV_512GB_SIZE ||
        shadowPhysical >= HV_512GB_SIZE) {
        status = STATUS_NOT_SUPPORTED;
        goto Exit;
    }

    pdptIndex =
        (ULONG)((targetPhysical >> 30) & 0x1FF);
    pdIndex =
        (ULONG)((targetPhysical >> 21) & 0x1FF);
    ptIndex =
        (ULONG)((targetPhysical >> 12) & 0x1FF);

    oneGbBase =
        targetPhysical & ~(HV_1GB_SIZE - 1);
    twoMbBase =
        targetPhysical & ~(HV_2MB_SIZE - 1);

    pdpt = (PULONG64)g_HvState.Ept.Pdpt;
    pd = (PULONG64)g_HvState.Ept.Pd;
    pt = (PULONG64)g_HvState.Ept.SplitPt;

    KeAcquireSpinLock(
        &g_HvState.Ept.Lock,
        &oldIrql
        );

    InterlockedExchange(
        &g_HvState.Ept.LabTrapArmed,
        0
        );
    InterlockedExchange(
        &g_HvState.Ept.LabShadowInstalled,
        0
        );

    for (index = 0; index < 512; ++index) {
        ULONG64 pagePhysical =
            oneGbBase +
            ((ULONG64)index * HV_2MB_SIZE);

        pd[index] =
            (pagePhysical & HV_EPT_ADDR_MASK) |
            HV_EPT_READ |
            HV_EPT_WRITE |
            HV_EPT_EXECUTE |
            HV_EPT_MEMTYPE_WB |
            HV_EPT_LARGE_PAGE;
    }

    for (index = 0; index < 512; ++index) {
        ULONG64 pagePhysical =
            twoMbBase +
            ((ULONG64)index * HV_PAGE_SIZE);

        pt[index] =
            (pagePhysical & HV_EPT_ADDR_MASK) |
            HV_EPT_READ |
            HV_EPT_WRITE |
            HV_EPT_EXECUTE |
            HV_EPT_MEMTYPE_WB;
    }

    //
    // Remove R/W/X only from the driver-owned synthetic target.  The first
    // access must therefore produce a real EPT violation.  The VM-exit
    // handler replaces this leaf with the synthetic shadow and resumes the
    // faulting instruction.
    //
    pt[ptIndex] =
        (targetPhysical & HV_EPT_ADDR_MASK) |
        HV_EPT_MEMTYPE_WB;

    KeMemoryBarrier();

    pd[pdIndex] =
        (g_HvState.Ept.SplitPtPhysical.QuadPart &
            HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE;

    KeMemoryBarrier();

    pdpt[pdptIndex] =
        (g_HvState.Ept.PdPhysical.QuadPart &
            HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE;

    KeMemoryBarrier();

    g_HvState.Ept.SplitPdptIndex = pdptIndex;
    g_HvState.Ept.SplitPdIndex = pdIndex;
    g_HvState.Ept.SplitPtIndex = ptIndex;

    InterlockedExchange(
        &g_HvState.Ept.LabTrapArmed,
        1
        );

    KeReleaseSpinLock(
        &g_HvState.Ept.Lock,
        oldIrql
        );

    status = HvInvalidateEptAllProcessors();
    if (!NT_SUCCESS(status)) {
        HvDisableLabSmbiosEptHook();
        goto Exit;
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] Synthetic EPT trap armed: GPA=%llX shadow=%llX "
        "pdpt=%lu pd=%lu pt=%lu\n",
        targetPhysical,
        shadowPhysical,
        pdptIndex,
        pdIndex,
        ptIndex
        );

    status = STATUS_SUCCESS;

Exit:
    InterlockedExchange(
        &g_HvState.Ept.ConfigBusy,
        0
        );

    return status;
}

NTSTATUS
HvRedirectToSmbiosShadow(
    _In_ ULONG64 GuestPhysicalAddress
    )
{
    PULONG64 pt;
    ULONG64 targetPage;
    ULONG64 requestedPage;
    ULONG64 targetPhysical;
    ULONG64 shadowPhysical;
    ULONG64 shadowEntry;
    ULONG64 identityEntry;

    targetPhysical =
        g_HvState.Ept.LabSmbiosPhysical.QuadPart;
    shadowPhysical =
        g_HvState.Ept.LabShadowPhysical.QuadPart;

    if (g_HvState.Ept.SplitPt == NULL ||
        targetPhysical == 0 ||
        shadowPhysical == 0) {
        return STATUS_DEVICE_NOT_READY;
    }

    targetPage =
        targetPhysical & ~(HV_PAGE_SIZE - 1);
    requestedPage =
        GuestPhysicalAddress & ~(HV_PAGE_SIZE - 1);

    if (requestedPage != targetPage) {
        return STATUS_NOT_FOUND;
    }

    pt = (PULONG64)g_HvState.Ept.SplitPt;

    shadowEntry =
        (shadowPhysical & HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE |
        HV_EPT_MEMTYPE_WB;

    identityEntry =
        (targetPhysical & HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE |
        HV_EPT_MEMTYPE_WB;

    InterlockedExchange64(
        (volatile LONG64*)&pt[g_HvState.Ept.SplitPtIndex],
        (LONG64)shadowEntry
        );

    KeMemoryBarrier();

    InterlockedExchange(
        &g_HvState.Ept.LabShadowInstalled,
        1
        );
    InterlockedExchange(
        &g_HvState.Ept.LabTrapArmed,
        0
        );

    if (!HvInvalidateEptCurrentProcessor()) {
        //
        // A failed INVEPT must never leave the synthetic GPA inaccessible.
        // Restore an identity 4 KiB leaf so the faulting access can complete
        // after a successful retry/invalidation or a controlled shutdown.
        //
        InterlockedExchange64(
            (volatile LONG64*)&pt[g_HvState.Ept.SplitPtIndex],
            (LONG64)identityEntry
            );

        KeMemoryBarrier();

        InterlockedExchange(
            &g_HvState.Ept.LabShadowInstalled,
            0
            );
        InterlockedExchange(
            &g_HvState.Ept.LabTrapArmed,
            0
            );

        (VOID)HvInvalidateEptCurrentProcessor();
        return STATUS_UNSUCCESSFUL;
    }

    InterlockedIncrement64(
        &g_HvState.Ept.LabRedirectCount
        );

    return STATUS_SUCCESS;
}

VOID
HvDisableLabSmbiosEptHook(
    VOID
    )
{
    KIRQL oldIrql;
    PULONG64 pdpt;
    ULONG pdptIndex;
    ULONG64 oneGbBase;
    BOOLEAN wasActive;
    NTSTATUS status;

    wasActive =
        InterlockedExchange(
            &g_HvState.Ept.LabTrapArmed,
            0) != 0 ||
        InterlockedExchange(
            &g_HvState.Ept.LabShadowInstalled,
            0) != 0;

    if (!wasActive ||
        g_HvState.Ept.Pdpt == NULL ||
        g_HvState.Ept.LabSmbiosPhysical.QuadPart == 0) {
        return;
    }

    pdptIndex = g_HvState.Ept.SplitPdptIndex;
    oneGbBase =
        g_HvState.Ept.LabSmbiosPhysical.QuadPart &
        ~(HV_1GB_SIZE - 1);

    pdpt = (PULONG64)g_HvState.Ept.Pdpt;

    KeAcquireSpinLock(
        &g_HvState.Ept.Lock,
        &oldIrql
        );

    pdpt[pdptIndex] =
        (oneGbBase & HV_EPT_ADDR_MASK) |
        HV_EPT_READ |
        HV_EPT_WRITE |
        HV_EPT_EXECUTE |
        HV_EPT_MEMTYPE_WB |
        HV_EPT_LARGE_PAGE;

    KeMemoryBarrier();

    KeReleaseSpinLock(
        &g_HvState.Ept.Lock,
        oldIrql
        );

    status = HvInvalidateEptAllProcessors();

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        NT_SUCCESS(status) ? DPFLTR_INFO_LEVEL : DPFLTR_WARNING_LEVEL,
        "[HwidHv] Synthetic EPT hook disabled; 1 GiB identity leaf restored "
        "(status=0x%08X)\n",
        status
        );
}

VOID
HvTeardownEpt(
    VOID
    )
{
    HvDisableLabSmbiosEptHook();

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

    g_HvState.Ept.SplitPdptIndex = 0;
    g_HvState.Ept.SplitPdIndex = 0;
    g_HvState.Ept.SplitPtIndex = 0;
    g_HvState.Ept.EptPointer = 0;

    InterlockedExchange(
        &g_HvState.Ept.LabTrapArmed,
        0
        );
    InterlockedExchange(
        &g_HvState.Ept.LabShadowInstalled,
        0
        );
    InterlockedExchange(
        &g_HvState.Ept.ConfigBusy,
        0
        );
}
