#include "hv.h"

HV_STATE g_HvState = { 0 };

static
BOOLEAN
HvCpuIsIntel(
    VOID
    )
{
    int cpuInfo[4] = { 0 };
    CHAR vendor[13] = { 0 };

    __cpuid(cpuInfo, 0);

    RtlCopyMemory(&vendor[0], &cpuInfo[1], sizeof(ULONG));
    RtlCopyMemory(&vendor[4], &cpuInfo[3], sizeof(ULONG));
    RtlCopyMemory(&vendor[8], &cpuInfo[2], sizeof(ULONG));

    return RtlCompareMemory(
        vendor,
        "GenuineIntel",
        12
        ) == 12;
}

static
BOOLEAN
HvControlRegistersAreValid(
    VOID
    )
{
    ULONG64 cr0;
    ULONG64 cr4;
    ULONG64 cr0Fixed0;
    ULONG64 cr0Fixed1;
    ULONG64 cr4Fixed0;
    ULONG64 cr4Fixed1;

    __try {
        cr0 = __readcr0();
        cr4 = __readcr4() | (1ull << 13);

        cr0Fixed0 = __readmsr(HV_IA32_VMX_CR0_FIXED0);
        cr0Fixed1 = __readmsr(HV_IA32_VMX_CR0_FIXED1);
        cr4Fixed0 = __readmsr(HV_IA32_VMX_CR4_FIXED0);
        cr4Fixed1 = __readmsr(HV_IA32_VMX_CR4_FIXED1);
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return FALSE;
    }

    if ((cr0 & cr0Fixed0) != cr0Fixed0 ||
        (cr0 & ~cr0Fixed1) != 0) {
        return FALSE;
    }

    if ((cr4 & cr4Fixed0) != cr4Fixed0 ||
        (cr4 & ~cr4Fixed1) != 0) {
        return FALSE;
    }

    return TRUE;
}

static
BOOLEAN
HvCpuReportsVmx(
    VOID
    )
{
    int cpuInfo[4] = { 0 };

    __cpuid(cpuInfo, 1);
    return (cpuInfo[2] & (1 << 5)) != 0;
}

static
BOOLEAN
HvCpuReportsHypervisor(
    VOID
    )
{
    int cpuInfo[4] = { 0 };

    __cpuid(cpuInfo, 1);
    return (cpuInfo[2] & (1u << 31)) != 0;
}

static
BOOLEAN
HvFeatureControlAllowsVmx(
    VOID
    )
{
    ULONG64 featureControl;

    __try {
        featureControl = __readmsr(HV_IA32_FEATURE_CONTROL);
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return FALSE;
    }

    //
    // Never write IA32_FEATURE_CONTROL here. The parent hypervisor/firmware
    // must expose VMX in a valid state before this lab driver starts.
    //
    if ((featureControl & 1ull) == 0) {
        return FALSE;
    }

    return (featureControl & (1ull << 2)) != 0;
}

static
BOOLEAN
HvCpuReportsEpt(
    VOID
    )
{
    ULONG64 secondaryControls;

    __try {
        secondaryControls = __readmsr(HV_IA32_VMX_PROCBASED_CTLS2);
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return FALSE;
    }

    return (((ULONG)(secondaryControls >> 32)) &
        HV_SECONDARY_ENABLE_EPT) != 0;
}

static
PVOID
HvAllocateVmxPage(
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
HvFreeVmxPage(
    _In_opt_ PVOID Page
    )
{
    if (Page != NULL) {
        MmFreeContiguousMemory(Page);
    }
}

PHV_CPU_CONTEXT
HvGetCurrentCpuContext(
    VOID
    )
{
    PROCESSOR_NUMBER processorNumber;
    ULONG index;

    if (g_HvState.CpuContexts == NULL ||
        g_HvState.ProcessorCount == 0) {
        return NULL;
    }

    index = KeGetCurrentProcessorNumberEx(&processorNumber);
    if (index >= g_HvState.ProcessorCount) {
        return NULL;
    }

    return &g_HvState.CpuContexts[index];
}

NTSTATUS
HvInitialize(
    VOID
    )
{
    ULONG index;

    if (InterlockedCompareExchange(
            &g_HvState.Initialized,
            0,
            0) != 0) {
        return STATUS_SUCCESS;
    }

    RtlZeroMemory(&g_HvState, sizeof(g_HvState));
    KeInitializeSpinLock(&g_HvState.Ept.Lock);

    if (!HvCpuIsIntel()) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] This lab implementation supports Intel VT-x only.\n"
            );
        return STATUS_NOT_SUPPORTED;
    }

    g_HvState.HypervisorPresent = HvCpuReportsHypervisor();
    g_HvState.VmxSupported = HvCpuReportsVmx();

    if (!g_HvState.VmxSupported) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] VMX is not exposed to this guest. "
            "Enable nested virtualization on the parent Hyper-V host.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    g_HvState.VmxFeatureControlEnabled =
        HvFeatureControlAllowsVmx();

    if (!g_HvState.VmxFeatureControlEnabled) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] IA32_FEATURE_CONTROL does not permit "
            "VMX outside SMX.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    if (!HvControlRegistersAreValid()) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] Current CR0/CR4 values do not satisfy VMX fixed-bit requirements.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    g_HvState.EptSupported = HvCpuReportsEpt();
    if (!g_HvState.EptSupported) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] EPT is not exposed by the current "
            "virtualization layer.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    g_HvState.ProcessorCount =
        KeQueryActiveProcessorCountEx(ALL_PROCESSOR_GROUPS);

    if (g_HvState.ProcessorCount == 0) {
        return STATUS_UNSUCCESSFUL;
    }

    g_HvState.CpuContexts =
        (PHV_CPU_CONTEXT)ExAllocatePoolWithTag(
            NonPagedPoolNx,
            sizeof(HV_CPU_CONTEXT) *
                g_HvState.ProcessorCount,
            HV_POOL_TAG
            );

    if (g_HvState.CpuContexts == NULL) {
        g_HvState.ProcessorCount = 0;
        return STATUS_INSUFFICIENT_RESOURCES;
    }

    RtlZeroMemory(
        g_HvState.CpuContexts,
        sizeof(HV_CPU_CONTEXT) *
            g_HvState.ProcessorCount
        );

    for (index = 0;
         index < g_HvState.ProcessorCount;
         ++index) {
        g_HvState.CpuContexts[index].ProcessorIndex = index;
        g_HvState.CpuContexts[index].LastStatus =
            STATUS_DEVICE_NOT_READY;
    }

    InterlockedExchange(&g_HvState.Initialized, 1);

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] Initialized: cpus=%lu "
        "hypervisor_present=%u vmx=%u ept=%u\n",
        g_HvState.ProcessorCount,
        g_HvState.HypervisorPresent,
        g_HvState.VmxSupported,
        g_HvState.EptSupported
        );

    return STATUS_SUCCESS;
}

NTSTATUS
HvAllocateVmcs(
    VOID
    )
{
    ULONG index;
    ULONG revisionId;

    if (InterlockedCompareExchange(
            &g_HvState.Initialized,
            0,
            0) == 0) {
        return STATUS_DEVICE_NOT_READY;
    }

    {
        ULONG64 vmxBasic = __readmsr(HV_IA32_VMX_BASIC);
        ULONG regionSize = (ULONG)((vmxBasic >> 32) & 0x1FFFu);
        ULONG memoryType = (ULONG)((vmxBasic >> 50) & 0x0Fu);

        if (regionSize == 0 ||
            regionSize > PAGE_SIZE ||
            memoryType != 6) {
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_ERROR_LEVEL,
                "[HwidHv] Unsupported VMX region requirements: size=%lu type=%lu.\n",
                regionSize,
                memoryType
                );
            return STATUS_NOT_SUPPORTED;
        }

        revisionId =
            (ULONG)(vmxBasic & 0x7FFFFFFFull);
    }

    for (index = 0;
         index < g_HvState.ProcessorCount;
         ++index) {
        PHV_CPU_CONTEXT cpu =
            &g_HvState.CpuContexts[index];

        if (cpu->VmxonRegion == NULL) {
            cpu->VmxonRegion =
                HvAllocateVmxPage(
                    &cpu->VmxonPhysical
                    );

            if (cpu->VmxonRegion == NULL) {
                return STATUS_INSUFFICIENT_RESOURCES;
            }

            *(volatile ULONG*)cpu->VmxonRegion =
                revisionId;
        }

        if (cpu->VmcsRegion == NULL) {
            cpu->VmcsRegion =
                HvAllocateVmxPage(
                    &cpu->VmcsPhysical
                    );

            if (cpu->VmcsRegion == NULL) {
                return STATUS_INSUFFICIENT_RESOURCES;
            }

            *(volatile ULONG*)cpu->VmcsRegion =
                revisionId;
        }
    }

    return STATUS_SUCCESS;
}

static
ULONG_PTR
HvStartCurrentProcessor(
    _In_ ULONG_PTR Context
    )
{
    PHV_CPU_CONTEXT cpu;
    ULONG64 vmxonPhysical;
    ULONG64 originalCr4;
    unsigned char vmxResult;
    NTSTATUS status;

    UNREFERENCED_PARAMETER(Context);

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return 0;
    }

    KeGetCurrentProcessorNumberEx(
        &cpu->ProcessorNumber
        );

    if (InterlockedCompareExchange(
            &cpu->VmxActive,
            0,
            0) != 0) {
        cpu->LastStatus = STATUS_SUCCESS;
        return 0;
    }

    originalCr4 = __readcr4();
    cpu->OriginalCr4 = originalCr4;

    __writecr4(originalCr4 | (1ull << 13));

    vmxonPhysical = cpu->VmxonPhysical.QuadPart;
    vmxResult = __vmx_on(&vmxonPhysical);

    if (vmxResult != 0) {
        __writecr4(originalCr4);
        cpu->LastStatus = STATUS_UNSUCCESSFUL;
        return 0;
    }

    InterlockedExchange(&cpu->VmxActive, 1);

    status = HvPrepareVmcsCurrentCpu(cpu);
    if (!NT_SUCCESS(status)) {
        __vmx_off();
        InterlockedExchange(&cpu->VmxActive, 0);
        __writecr4(originalCr4);
        cpu->LastStatus = status;
        return 0;
    }

    cpu->LastStatus = STATUS_SUCCESS;
    return 0;
}

NTSTATUS
HvStartVmx(
    VOID
    )
{
    NTSTATUS status;
    ULONG index;

    status = HvInitialize();
    if (!NT_SUCCESS(status)) {
        return status;
    }

    if (InterlockedCompareExchange(
            &g_HvState.Running,
            0,
            0) != 0) {
        return STATUS_SUCCESS;
    }

    status = HvAllocateVmcs();
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = HvInitializeEpt();
    if (!NT_SUCCESS(status)) {
        return status;
    }

    KeIpiGenericCall(
        HvStartCurrentProcessor,
        0
        );

    for (index = 0;
         index < g_HvState.ProcessorCount;
         ++index) {
        if (!NT_SUCCESS(
                g_HvState.CpuContexts[index].LastStatus)) {
            status =
                g_HvState.CpuContexts[index].LastStatus;
            HvStopVmx();
            return status;
        }
    }

    InterlockedExchange(&g_HvState.Running, 1);

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] VMXON active on %lu logical "
        "processors. Lab mode does not execute VMLAUNCH.\n",
        g_HvState.ProcessorCount
        );

    return STATUS_SUCCESS;
}

static
ULONG_PTR
HvStopCurrentProcessor(
    _In_ ULONG_PTR Context
    )
{
    PHV_CPU_CONTEXT cpu;

    UNREFERENCED_PARAMETER(Context);

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return 0;
    }

    if (InterlockedCompareExchange(
            &cpu->VmxActive,
            0,
            0) != 0) {
        __vmx_off();
        InterlockedExchange(&cpu->VmxActive, 0);
        __writecr4(cpu->OriginalCr4);
    }

    return 0;
}

VOID
HvStopVmx(
    VOID
    )
{
    if (g_HvState.CpuContexts != NULL) {
        KeIpiGenericCall(
            HvStopCurrentProcessor,
            0
            );
    }

    InterlockedExchange(&g_HvState.Running, 0);

    if (g_HvState.CpuContexts != NULL) {
        ULONG index;

        for (index = 0;
             index < g_HvState.ProcessorCount;
             ++index) {
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_INFO_LEVEL,
                "[HwidHv] CPU %lu stats: vmexit=%lld ept_violation=%lld\n",
                index,
                g_HvState.CpuContexts[index].VmExitCount,
                g_HvState.CpuContexts[index].EptViolationCount
                );
        }
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] VMX stopped on all processors.\n"
        );
}

VOID
HvShutdown(
    VOID
    )
{
    ULONG index;

    HvStopVmx();
    HvTeardownEpt();

    if (g_HvState.CpuContexts != NULL) {
        for (index = 0;
             index < g_HvState.ProcessorCount;
             ++index) {
            HvFreeVmxPage(
                g_HvState.CpuContexts[index].VmcsRegion
                );
            HvFreeVmxPage(
                g_HvState.CpuContexts[index].VmxonRegion
                );

            g_HvState.CpuContexts[index].VmcsRegion =
                NULL;
            g_HvState.CpuContexts[index].VmxonRegion =
                NULL;
        }

        ExFreePoolWithTag(
            g_HvState.CpuContexts,
            HV_POOL_TAG
            );
        g_HvState.CpuContexts = NULL;
    }

    g_HvState.ProcessorCount = 0;
    InterlockedExchange(&g_HvState.Initialized, 0);
}
