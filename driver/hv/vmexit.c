#include "hv.h"

static
BOOLEAN
HvReadVmcs64(
    _In_ SIZE_T Field,
    _Out_ PULONG64 Value
    )
{
    SIZE_T localValue = 0;

    if (Value == NULL) {
        return FALSE;
    }

    if (__vmx_vmread(Field, &localValue) != 0) {
        *Value = 0;
        return FALSE;
    }

    *Value = (ULONG64)localValue;
    return TRUE;
}

static
BOOLEAN
HvWriteVmcs64(
    _In_ SIZE_T Field,
    _In_ ULONG64 Value
    )
{
    return __vmx_vmwrite(Field, (SIZE_T)Value) == 0;
}

static
BOOLEAN
HvCaptureGuestState(
    _Inout_ PHV_GUEST_REGISTERS GuestRegisters
    )
{
    return
        HvReadVmcs64(
            HV_VMCS_GUEST_RSP,
            &GuestRegisters->GuestRsp) &&
        HvReadVmcs64(
            HV_VMCS_GUEST_RIP,
            &GuestRegisters->GuestRip) &&
        HvReadVmcs64(
            HV_VMCS_GUEST_RFLAGS,
            &GuestRegisters->GuestRflags) &&
        HvReadVmcs64(
            HV_VMCS_GUEST_CR0,
            &GuestRegisters->GuestCr0) &&
        HvReadVmcs64(
            HV_VMCS_GUEST_CR3,
            &GuestRegisters->GuestCr3) &&
        HvReadVmcs64(
            HV_VMCS_GUEST_CR4,
            &GuestRegisters->GuestCr4);
}

static
BOOLEAN
HvAdvanceGuestRip(
    _Inout_ PHV_GUEST_REGISTERS GuestRegisters
    )
{
    ULONG64 instructionLength;
    ULONG64 newRip;

    if (!HvReadVmcs64(
            HV_VMCS_EXIT_INSTRUCTION_LENGTH,
            &instructionLength)) {
        return FALSE;
    }

    if (instructionLength == 0 ||
        instructionLength > 15) {
        return FALSE;
    }

    newRip =
        GuestRegisters->GuestRip +
        instructionLength;

    if (!HvWriteVmcs64(
            HV_VMCS_GUEST_RIP,
            newRip)) {
        return FALSE;
    }

    GuestRegisters->GuestRip = newRip;
    return TRUE;
}

BOOLEAN
HvHandleEptViolation(
    _In_ ULONG64 GuestPhysicalAddress,
    _In_ ULONG64 Qualification
    )
{
    PHV_CPU_CONTEXT cpu;
    ULONG64 pageBase;
    ULONG64 labPageBase;

    BOOLEAN readAccess;
    BOOLEAN writeAccess;
    BOOLEAN executeAccess;

    NTSTATUS status;

    cpu = HvGetCurrentCpuContext();
    if (cpu != NULL) {
        InterlockedIncrement64(
            &cpu->EptViolationCount
            );

        cpu->LastExitQualification = Qualification;
        cpu->LastGuestPhysicalAddress =
            GuestPhysicalAddress;
    }

    readAccess =
        (Qualification & (1ull << 0)) != 0;
    writeAccess =
        (Qualification & (1ull << 1)) != 0;
    executeAccess =
        (Qualification & (1ull << 2)) != 0;

    pageBase =
        GuestPhysicalAddress &
        ~(HV_PAGE_SIZE - 1);

    labPageBase =
        g_HvState.Ept.LabSmbiosPhysical.QuadPart &
        ~(HV_PAGE_SIZE - 1);

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_TRACE_LEVEL,
        "[HwidHv] EPT violation: gpa=%llX qualification=%llX "
        "R=%u W=%u X=%u\n",
        GuestPhysicalAddress,
        Qualification,
        readAccess,
        writeAccess,
        executeAccess
        );

    if (g_HvState.Ept.LabSmbiosPage == NULL ||
        pageBase != labPageBase) {
        return FALSE;
    }

    //
    // A second processor can still hold the old no-access translation after
    // another processor has already installed the shared shadow leaf.  A
    // local INVEPT is sufficient in that case.
    //
    if (InterlockedCompareExchange(
            &g_HvState.Ept.LabShadowInstalled,
            0,
            0) != 0) {
        if (HvInvalidateEptCurrentProcessor()) {
            return TRUE;
        }

        return HvRollbackLabSmbiosEptCurrentProcessor();
    }

    if (InterlockedCompareExchange(
            &g_HvState.Ept.LabTrapArmed,
            0,
            0) == 0) {
        //
        // The hook is no longer armed, so this is a stale translation.
        //
        return HvRollbackLabSmbiosEptCurrentProcessor();
    }

    status = HvInjectSmbiosData();
    if (!NT_SUCCESS(status)) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] Synthetic SMBIOS patch failed during EPT exit: "
            "0x%08X\n",
            status
            );

        return HvRollbackLabSmbiosEptCurrentProcessor();
    }

    status = HvRedirectToSmbiosShadow(
        GuestPhysicalAddress
        );

    if (!NT_SUCCESS(status)) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] Synthetic EPT redirect failed: 0x%08X\n",
            status
            );

        return HvRollbackLabSmbiosEptCurrentProcessor();
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] Synthetic EPT access redirected: gpa=%llX "
        "shadow_pa=%llX\n",
        GuestPhysicalAddress,
        g_HvState.Ept.LabShadowPhysical.QuadPart
        );

    return TRUE;
}

ULONG
HvHandleVmExit(
    _Inout_ PHV_GUEST_REGISTERS GuestRegisters
    )
{
    PHV_CPU_CONTEXT cpu;
    ULONG64 startTsc;
    ULONG64 endTsc;
    ULONG64 rawExitReason;
    ULONG64 qualification = 0;
    ULONG64 guestPhysicalAddress = 0;
    ULONG exitReason;
    ULONG action;

    startTsc = __rdtsc();
    action = HV_VMEXIT_ACTION_FATAL;

    if (GuestRegisters == NULL) {
        return HV_VMEXIT_ACTION_FATAL;
    }

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return HV_VMEXIT_ACTION_FATAL;
    }

    InterlockedIncrement64(
        &cpu->VmExitCount
        );

    if (!HvCaptureGuestState(
            GuestRegisters)) {
        goto Exit;
    }

    if (!HvReadVmcs64(
            HV_VMCS_EXIT_REASON,
            &rawExitReason)) {
        goto Exit;
    }

    if ((rawExitReason & (1ull << 31)) != 0) {
        cpu->LastExitReason =
            (ULONG)(rawExitReason & 0xFFFFu);
        goto Exit;
    }

    exitReason =
        (ULONG)(rawExitReason & 0xFFFFu);

    cpu->LastExitReason = exitReason;

    switch (exitReason) {
    case HV_EXIT_REASON_CPUID:
    {
        int registers[4];

        InterlockedIncrement64(
            &cpu->CpuidExitCount
            );

        __cpuidex(
            registers,
            (int)(ULONG)GuestRegisters->Rax,
            (int)(ULONG)GuestRegisters->Rcx
            );

        GuestRegisters->Rax =
            (ULONG)registers[0];
        GuestRegisters->Rbx =
            (ULONG)registers[1];
        GuestRegisters->Rcx =
            (ULONG)registers[2];
        GuestRegisters->Rdx =
            (ULONG)registers[3];

        if (!HvAdvanceGuestRip(
                GuestRegisters)) {
            goto Exit;
        }

        action = HV_VMEXIT_ACTION_RESUME;
        break;
    }

    case HV_EXIT_REASON_VMCALL:
    {
        NTSTATUS hypercallStatus;

        InterlockedIncrement64(
            &cpu->VmcallExitCount
            );

        if (GuestRegisters->Rax !=
            HV_HYPERCALL_SIGNATURE) {
            goto Exit;
        }

        switch (GuestRegisters->R10) {
        case HV_HYPERCALL_INVEPT:
            hypercallStatus =
                HvInvalidateEptCurrentProcessor()
                    ? STATUS_SUCCESS
                    : STATUS_UNSUCCESSFUL;

            GuestRegisters->Rax =
                (ULONG64)(LONG64)hypercallStatus;

            if (!HvAdvanceGuestRip(
                    GuestRegisters)) {
                goto Exit;
            }

            action = HV_VMEXIT_ACTION_RESUME;
            break;

        case HV_HYPERCALL_STOP:
            GuestRegisters->Rax =
                (ULONG64)(LONG64)STATUS_SUCCESS;

            if (!HvAdvanceGuestRip(
                    GuestRegisters)) {
                goto Exit;
            }

            action =
                HV_VMEXIT_ACTION_TERMINATE;
            break;

        default:
            GuestRegisters->Rax =
                (ULONG64)(LONG64)
                    STATUS_INVALID_DEVICE_REQUEST;

            if (!HvAdvanceGuestRip(
                    GuestRegisters)) {
                goto Exit;
            }

            action = HV_VMEXIT_ACTION_RESUME;
            break;
        }

        break;
    }

    case HV_EXIT_REASON_EPT_VIOLATION:
        if (!HvReadVmcs64(
                HV_VMCS_EXIT_QUALIFICATION,
                &qualification) ||
            !HvReadVmcs64(
                HV_VMCS_GUEST_PHYSICAL_ADDRESS,
                &guestPhysicalAddress)) {
            goto Exit;
        }

        cpu->LastExitQualification =
            qualification;
        cpu->LastGuestPhysicalAddress =
            guestPhysicalAddress;

        if (!HvHandleEptViolation(
                guestPhysicalAddress,
                qualification)) {
            goto Exit;
        }

        //
        // EPT violations are fault-like exits: do not advance RIP.  The
        // original memory access is retried after VMRESUME.
        //
        action = HV_VMEXIT_ACTION_RESUME;
        break;

    default:
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID,
            DPFLTR_ERROR_LEVEL,
            "[HwidHv] Unsupported VM-exit reason=%lu on CPU %lu\n",
            exitReason,
            cpu->ProcessorIndex
            );

        action = HV_VMEXIT_ACTION_FATAL;
        break;
    }

Exit:
    endTsc = __rdtsc();

    InterlockedExchangeAdd64(
        &cpu->VmExitCycles,
        (LONG64)(endTsc - startTsc)
        );

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_TRACE_LEVEL,
        "[HwidHv] VM-exit cpu=%lu reason=%lu qualification=%llX "
        "gpa=%llX action=%lu\n",
        cpu->ProcessorIndex,
        cpu->LastExitReason,
        qualification,
        guestPhysicalAddress,
        action
        );

    return action;
}
