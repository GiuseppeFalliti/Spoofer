#include "hv.h"

static
ULONG
HvAdjustControl(
    _In_ ULONG Requested,
    _In_ ULONG Msr
    )
{
    ULONG64 capability;
    ULONG mustBeOne;
    ULONG mayBeOne;

    capability = __readmsr(Msr);
    mustBeOne = (ULONG)capability;
    mayBeOne = (ULONG)(capability >> 32);

    Requested |= mustBeOne;
    Requested &= mayBeOne;

    return Requested;
}

NTSTATUS
HvConfigureVmcs(
    _Inout_ PHV_CPU_CONTEXT CpuContext
    )
{
    ULONG primaryControls;
    ULONG secondaryControls;
    unsigned char result;

    if (CpuContext == NULL ||
        InterlockedCompareExchange(
            &CpuContext->VmxActive,
            0,
            0) == 0) {
        return STATUS_DEVICE_NOT_READY;
    }

    //
    // Lab boundary:
    // Configure only execution controls required to validate EPT exposure.
    // Host/guest launch state is intentionally not populated, and no code in
    // this branch executes VMLAUNCH.
    //
    primaryControls = HvAdjustControl(
        HV_PRIMARY_ACTIVATE_SECONDARY,
        HV_IA32_VMX_PROCBASED_CTLS
        );

    secondaryControls = HvAdjustControl(
        HV_SECONDARY_ENABLE_EPT,
        HV_IA32_VMX_PROCBASED_CTLS2
        );

    if ((secondaryControls &
         HV_SECONDARY_ENABLE_EPT) == 0) {
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    result = __vmx_vmwrite(
        HV_VMCS_PRIMARY_PROC_CONTROLS,
        primaryControls
        );

    if (result != 0) {
        return STATUS_UNSUCCESSFUL;
    }

    result = __vmx_vmwrite(
        HV_VMCS_SECONDARY_PROC_CONTROLS,
        secondaryControls
        );

    if (result != 0) {
        return STATUS_UNSUCCESSFUL;
    }

    result = __vmx_vmwrite(
        HV_VMCS_EPT_POINTER,
        g_HvState.Ept.EptPointer
        );

    if (result != 0) {
        return STATUS_UNSUCCESSFUL;
    }

    return STATUS_SUCCESS;
}

NTSTATUS
HvPrepareVmcsCurrentCpu(
    _Inout_ PHV_CPU_CONTEXT CpuContext
    )
{
    ULONG64 vmcsPhysical;
    unsigned char result;

    if (CpuContext == NULL ||
        CpuContext->VmcsRegion == NULL) {
        return STATUS_INVALID_PARAMETER;
    }

    vmcsPhysical =
        CpuContext->VmcsPhysical.QuadPart;

    result = __vmx_vmclear(&vmcsPhysical);
    if (result != 0) {
        return STATUS_UNSUCCESSFUL;
    }

    result = __vmx_vmptrld(&vmcsPhysical);
    if (result != 0) {
        return STATUS_UNSUCCESSFUL;
    }

    return HvConfigureVmcs(CpuContext);
}
