#include "hv.h"

static
BOOLEAN
HvReadVmcs64(
    _In_ SIZE_T Field,
    _Out_ PULONG64 Value
    )
{
    size_t localValue = 0;
    unsigned char result;

    if (Value == NULL) {
        return FALSE;
    }

    result = __vmx_vmread(
        Field,
        &localValue
        );

    if (result != 0) {
        *Value = 0;
        return FALSE;
    }

    *Value = (ULONG64)localValue;
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

    cpu = HvGetCurrentCpuContext();
    if (cpu != NULL) {
        InterlockedIncrement64(
            &cpu->EptViolationCount
            );
    }

    pageBase =
        GuestPhysicalAddress &
        ~(HV_PAGE_SIZE - 1);

    labPageBase =
        g_HvState.Ept.LabSmbiosPhysical.QuadPart &
        ~(HV_PAGE_SIZE - 1);

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] EPT violation: gpa=%llX qualification=%llX\n",
        GuestPhysicalAddress,
        Qualification
        );

    //
    // The only address this lab recognizes is its own synthetic page.
    // Real SMBIOS/firmware physical ranges are intentionally not discovered.
    //
    if (g_HvState.Ept.LabSmbiosPage != NULL &&
        pageBase == labPageBase) {
        return NT_SUCCESS(HvInjectSmbiosData());
    }

    return FALSE;
}

BOOLEAN
HvHandleVmExit(
    _Inout_opt_ PHV_GUEST_REGISTERS GuestRegisters
    )
{
    PHV_CPU_CONTEXT cpu;
    ULONG64 exitReason;
    ULONG64 qualification;
    ULONG64 guestPhysicalAddress;

    UNREFERENCED_PARAMETER(GuestRegisters);

    cpu = HvGetCurrentCpuContext();
    if (cpu != NULL) {
        InterlockedIncrement64(
            &cpu->VmExitCount
            );
    }

    if (!HvReadVmcs64(
            HV_VMCS_EXIT_REASON,
            &exitReason)) {
        return FALSE;
    }

    exitReason &= 0xFFFFu;

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] VM-exit reason=%llu\n",
        exitReason
        );

    switch ((ULONG)exitReason) {
    case HV_EXIT_REASON_EPT_VIOLATION:
        qualification = 0;
        guestPhysicalAddress = 0;

        if (!HvReadVmcs64(
                HV_VMCS_EXIT_QUALIFICATION,
                &qualification) ||
            !HvReadVmcs64(
                HV_VMCS_GUEST_PHYSICAL_ADDRESS,
                &guestPhysicalAddress)) {
            return FALSE;
        }

        return HvHandleEptViolation(
            guestPhysicalAddress,
            qualification
            );

    default:
        return FALSE;
    }
}
