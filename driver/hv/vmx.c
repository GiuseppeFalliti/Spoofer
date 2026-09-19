#include "hv.h"

#define HV_CR4_VMXE (1ull << 13)
#define HV_BUGCHECK_CODE 0x00020001u

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
        cr4 = __readcr4() | HV_CR4_VMXE;

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
        featureControl =
            __readmsr(HV_IA32_FEATURE_CONTROL);
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return FALSE;
    }

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
        secondaryControls =
            __readmsr(HV_IA32_VMX_PROCBASED_CTLS2);
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return FALSE;
    }

    return (((ULONG)(secondaryControls >> 32)) &
        HV_SECONDARY_ENABLE_EPT) != 0;
}

VOID
HvQueryCapabilities(
    _Out_ PUCHAR VtxSupported,
    _Out_ PUCHAR EptSupported,
    _Out_ PUCHAR VmxBlocked,
    _Out_ PUCHAR HypervisorPresent,
    _Out_ PULONG ProcessorCount
    )
{
    BOOLEAN vmx;
    BOOLEAN ept = FALSE;
    BOOLEAN featureControl = FALSE;

    if (VtxSupported == NULL ||
        EptSupported == NULL ||
        VmxBlocked == NULL ||
        HypervisorPresent == NULL ||
        ProcessorCount == NULL) {
        return;
    }

    *VtxSupported = 0;
    *EptSupported = 0;
    *VmxBlocked = 0;
    *HypervisorPresent = 0;
    *ProcessorCount = 0;

    if (!HvCpuIsIntel()) {
        *ProcessorCount =
            KeQueryActiveProcessorCountEx(
                ALL_PROCESSOR_GROUPS
                );
        return;
    }

    vmx = HvCpuReportsVmx();

    *VtxSupported = vmx ? 1 : 0;
    *HypervisorPresent =
        HvCpuReportsHypervisor() ? 1 : 0;
    *ProcessorCount =
        KeQueryActiveProcessorCountEx(
            ALL_PROCESSOR_GROUPS
            );

    if (!vmx) {
        return;
    }

    featureControl =
        HvFeatureControlAllowsVmx();

    *VmxBlocked =
        featureControl ? 0 : 1;

    if (featureControl) {
        ept = HvCpuReportsEpt();
        *EptSupported = ept ? 1 : 0;
    }
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

    page =
        MmAllocateContiguousMemorySpecifyCache(
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
    *PhysicalAddress =
        MmGetPhysicalAddress(page);

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

static
PVOID
HvAllocateHostStack(
    _Out_ PULONG64 StackTop
    )
{
    PVOID stack;
    ULONG_PTR top;

    if (StackTop == NULL) {
        return NULL;
    }

    *StackTop = 0;

    stack = ExAllocatePool2(
        POOL_FLAG_NON_PAGED,
        HV_HOST_STACK_SIZE,
        HV_POOL_TAG
        );

    if (stack == NULL) {
        return NULL;
    }

    RtlZeroMemory(
        stack,
        HV_HOST_STACK_SIZE
        );

    top =
        (ULONG_PTR)stack +
        HV_HOST_STACK_SIZE;

    top &= ~(ULONG_PTR)0xFull;

    *StackTop = (ULONG64)top;
    return stack;
}

static
VOID
HvFreeHostStack(
    _In_opt_ PVOID Stack
    )
{
    if (Stack != NULL) {
        ExFreePoolWithTag(
            Stack,
            HV_POOL_TAG
            );
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

    index =
        KeGetCurrentProcessorNumberEx(
            &processorNumber
            );

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

    RtlZeroMemory(
        &g_HvState,
        sizeof(g_HvState)
        );

    KeInitializeSpinLock(
        &g_HvState.Ept.Lock
        );

    if (!HvCpuIsIntel()) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] Intel VT-x is required.\n"
            );
        return STATUS_NOT_SUPPORTED;
    }

    g_HvState.HypervisorPresent =
        HvCpuReportsHypervisor();
    g_HvState.VmxSupported =
        HvCpuReportsVmx();

    if (!g_HvState.VmxSupported) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] VMX is not exposed to this environment. "
            "Nested virtualization must be enabled when running in a VM.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    g_HvState.VmxFeatureControlEnabled =
        HvFeatureControlAllowsVmx();

    if (!g_HvState.VmxFeatureControlEnabled) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] IA32_FEATURE_CONTROL blocks VMX outside SMX.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    if (!HvControlRegistersAreValid()) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] CR0/CR4 do not satisfy VMX fixed-bit requirements.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    g_HvState.EptSupported =
        HvCpuReportsEpt();

    if (!g_HvState.EptSupported) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] EPT is not exposed by the current virtualization layer.\n"
            );
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    g_HvState.ProcessorCount =
        KeQueryActiveProcessorCountEx(
            ALL_PROCESSOR_GROUPS
            );

    if (g_HvState.ProcessorCount == 0) {
        return STATUS_UNSUCCESSFUL;
    }

    g_HvState.CpuContexts =
        (PHV_CPU_CONTEXT)ExAllocatePool2(
            POOL_FLAG_NON_PAGED,
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
        g_HvState.CpuContexts[index].ProcessorIndex =
            index;
        g_HvState.CpuContexts[index].LastStatus =
            STATUS_DEVICE_NOT_READY;
    }

    InterlockedExchange(
        &g_HvState.Initialized,
        1
        );

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] Initialized: cpus=%lu hypervisor_present=%u "
        "vmx=%u ept=%u\n",
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
        ULONG64 vmxBasic =
            __readmsr(HV_IA32_VMX_BASIC);
        ULONG regionSize =
            (ULONG)((vmxBasic >> 32) & 0x1FFFu);
        ULONG memoryType =
            (ULONG)((vmxBasic >> 50) & 0x0Fu);

        if (regionSize == 0 ||
            regionSize > PAGE_SIZE ||
            memoryType != 6) {
            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_ERROR_LEVEL,
                "[HwidHv] Unsupported VMX region requirements: "
                "size=%lu type=%lu.\n",
                regionSize,
                memoryType
                );
            return STATUS_NOT_SUPPORTED;
        }

        revisionId =
            (ULONG)(vmxBasic & 0x7FFFFFFFull);
    }

    if (g_HvState.MsrBitmap == NULL) {
        g_HvState.MsrBitmap =
            HvAllocateVmxPage(
                &g_HvState.MsrBitmapPhysical
                );

        if (g_HvState.MsrBitmap == NULL) {
            return STATUS_INSUFFICIENT_RESOURCES;
        }

        //
        // A zeroed MSR bitmap allows RDMSR/WRMSR to execute natively for the
        // architecturally covered ranges.  The lab does not intercept MSRs.
        //
        RtlZeroMemory(
            g_HvState.MsrBitmap,
            PAGE_SIZE
            );
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

        if (cpu->HostStack == NULL) {
            cpu->HostStack =
                HvAllocateHostStack(
                    &cpu->HostStackTop
                    );

            if (cpu->HostStack == NULL) {
                return STATUS_INSUFFICIENT_RESOURCES;
            }
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
    ULONG64 instructionError = 0;
    ULONG launchResult;
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

    cpu->LastVmInstructionError = 0;

    originalCr4 = __readcr4();
    cpu->OriginalCr4 = originalCr4;

    __writecr4(
        originalCr4 | HV_CR4_VMXE
        );

    vmxonPhysical =
        cpu->VmxonPhysical.QuadPart;

    vmxResult =
        __vmx_on(
            &vmxonPhysical
            );

    if (vmxResult != 0) {
        __writecr4(originalCr4);
        cpu->LastStatus = STATUS_UNSUCCESSFUL;
        return 0;
    }

    InterlockedExchange(
        &cpu->VmxActive,
        1
        );

    status =
        HvPrepareVmcsCurrentCpu(cpu);

    if (!NT_SUCCESS(status)) {
        __vmx_off();
        InterlockedExchange(
            &cpu->VmxActive,
            0
            );
        __writecr4(originalCr4);
        cpu->LastStatus = status;
        return 0;
    }

    launchResult = HvVmxLaunch();

    if (launchResult != 0) {
        if (__vmx_vmread(
                HV_VMCS_VM_INSTRUCTION_ERROR,
                (SIZE_T*)&instructionError) == 0) {
            cpu->LastVmInstructionError =
                (ULONG)instructionError;
        }

        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] CPU %lu VMLAUNCH failed: result=%lu "
            "vm_instruction_error=%lu\n",
            cpu->ProcessorIndex,
            launchResult,
            cpu->LastVmInstructionError
            );

        __vmx_off();

        InterlockedExchange(
            &cpu->VmxActive,
            0
            );
        InterlockedExchange(
            &cpu->Launched,
            0
            );

        __writecr4(originalCr4);

        cpu->LastStatus = STATUS_UNSUCCESSFUL;
        return 0;
    }

    //
    // Execution reaches here in VMX non-root after HvVmxLaunchGuestResume.
    //
    InterlockedExchange(
        &cpu->Launched,
        1
        );

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
        PHV_CPU_CONTEXT cpu =
            &g_HvState.CpuContexts[index];

        if (!NT_SUCCESS(cpu->LastStatus) ||
            InterlockedCompareExchange(
                &cpu->VmxActive,
                0,
                0) == 0 ||
            InterlockedCompareExchange(
                &cpu->Launched,
                0,
                0) == 0 ||
            InterlockedCompareExchange(
                &cpu->VmcsValidated,
                0,
                0) == 0) {

            status =
                NT_SUCCESS(cpu->LastStatus)
                    ? STATUS_UNSUCCESSFUL
                    : cpu->LastStatus;

            HvStopVmx();
            return status;
        }
    }

    InterlockedExchange(
        &g_HvState.Running,
        1
        );

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] VMLAUNCH completed on %lu logical processors.\n",
        g_HvState.ProcessorCount
        );

    return STATUS_SUCCESS;
}

VOID
HvCompleteVmxOff(
    VOID
    )
{
    PHV_CPU_CONTEXT cpu;

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return;
    }

    InterlockedExchange(
        &cpu->Launched,
        0
        );
    InterlockedExchange(
        &cpu->VmxActive,
        0
        );

    cpu->LastStatus = STATUS_SUCCESS;
}

VOID
HvRecordVmResumeFailure(
    VOID
    )
{
    PHV_CPU_CONTEXT cpu;
    SIZE_T instructionError = 0;

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return;
    }

    InterlockedIncrement64(
        &cpu->VmResumeFailureCount
        );

    if (__vmx_vmread(
            HV_VMCS_VM_INSTRUCTION_ERROR,
            &instructionError) == 0) {
        cpu->LastVmInstructionError =
            (ULONG)instructionError;
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_ERROR_LEVEL,
        "[HwidHv] CPU %lu VMRESUME failed; vm_instruction_error=%lu\n",
        cpu->ProcessorIndex,
        cpu->LastVmInstructionError
        );
}

DECLSPEC_NORETURN
VOID
HvFatalVmInstructionFailure(
    _In_ ULONG FailureCode
    )
{
    PHV_CPU_CONTEXT cpu;
    ULONG processorIndex = MAXULONG;
    ULONG instructionError = 0;
    ULONG exitReason = 0;

    cpu = HvGetCurrentCpuContext();

    if (cpu != NULL) {
        processorIndex = cpu->ProcessorIndex;
        instructionError =
            cpu->LastVmInstructionError;
        exitReason =
            cpu->LastExitReason;
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_ERROR_LEVEL,
        "[HwidHv] Fatal VMX state: code=%lu cpu=%lu "
        "vm_instruction_error=%lu last_exit=%lu\n",
        FailureCode,
        processorIndex,
        instructionError,
        exitReason
        );

    KeBugCheckEx(
        HV_BUGCHECK_CODE,
        FailureCode,
        processorIndex,
        instructionError,
        exitReason
        );

    __assume(0);
}

static
ULONG_PTR
HvStopCurrentProcessor(
    _In_ ULONG_PTR Context
    )
{
    PHV_CPU_CONTEXT cpu;
    NTSTATUS status;

    UNREFERENCED_PARAMETER(Context);

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return 0;
    }

    if (InterlockedCompareExchange(
            &cpu->VmxActive,
            0,
            0) == 0) {
        cpu->LastStatus = STATUS_SUCCESS;
        return 0;
    }

    if (InterlockedCompareExchange(
            &cpu->Launched,
            0,
            0) != 0) {

        status =
            (NTSTATUS)HvHypercall(
                HV_HYPERCALL_STOP
                );

        if (!NT_SUCCESS(status) ||
            InterlockedCompareExchange(
                &cpu->VmxActive,
                0,
                0) != 0) {
            cpu->LastStatus = STATUS_UNSUCCESSFUL;
            return 0;
        }

        cpu->LastStatus = STATUS_SUCCESS;
        return 0;
    }

    __vmx_off();

    InterlockedExchange(
        &cpu->VmxActive,
        0
        );

    __writecr4(
        cpu->OriginalCr4
        );

    cpu->LastStatus = STATUS_SUCCESS;
    return 0;
}

VOID
HvStopVmx(
    VOID
    )
{
    ULONG index;

    if (InterlockedCompareExchange(
            &g_HvState.Running,
            0,
            0) != 0) {
        //
        // Restore the baseline EPT while VMCALL/INVEPT are still available.
        //
        HvDisableLabSmbiosEptHook();
    }

    if (g_HvState.CpuContexts != NULL) {
        KeIpiGenericCall(
            HvStopCurrentProcessor,
            0
            );
    }

    InterlockedExchange(
        &g_HvState.Running,
        0
        );

    if (g_HvState.CpuContexts != NULL) {
        for (index = 0;
             index < g_HvState.ProcessorCount;
             ++index) {
            PHV_CPU_CONTEXT cpu =
                &g_HvState.CpuContexts[index];

            DbgPrintEx(
                DPFLTR_IHVDRIVER_ID,
                DPFLTR_INFO_LEVEL,
                "[HwidHv] CPU %lu stats: vmexit=%lld ept=%lld cpuid=%lld "
                "vmcall=%lld invept=%lld vmresume_fail=%lld cycles=%lld "
                "last_reason=%lu last_qual=%llX last_gpa=%llX\n",
                index,
                cpu->VmExitCount,
                cpu->EptViolationCount,
                cpu->CpuidExitCount,
                cpu->VmcallExitCount,
                cpu->InveptCount,
                cpu->VmResumeFailureCount,
                cpu->VmExitCycles,
                cpu->LastExitReason,
                cpu->LastExitQualification,
                cpu->LastGuestPhysicalAddress
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
            PHV_CPU_CONTEXT cpu =
                &g_HvState.CpuContexts[index];

            HvFreeHostStack(
                cpu->HostStack
                );
            HvFreeVmxPage(
                cpu->VmcsRegion
                );
            HvFreeVmxPage(
                cpu->VmxonRegion
                );

            cpu->HostStack = NULL;
            cpu->HostStackTop = 0;
            cpu->VmcsRegion = NULL;
            cpu->VmxonRegion = NULL;
        }

        ExFreePoolWithTag(
            g_HvState.CpuContexts,
            HV_POOL_TAG
            );

        g_HvState.CpuContexts = NULL;
    }

    HvFreeVmxPage(
        g_HvState.MsrBitmap
        );

    g_HvState.MsrBitmap = NULL;
    g_HvState.MsrBitmapPhysical.QuadPart = 0;

    g_HvState.ProcessorCount = 0;

    InterlockedExchange(
        &g_HvState.Initialized,
        0
        );
}
