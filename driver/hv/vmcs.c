#include "hv.h"

#define HV_CR4_VMXE (1ull << 13)

static
BOOLEAN
HvUsesTrueControls(
    VOID
    )
{
    return (__readmsr(HV_IA32_VMX_BASIC) & (1ull << 55)) != 0;
}

static
ULONG
HvAdjustControl(
    _In_ ULONG Requested,
    _In_ ULONG LegacyMsr,
    _In_ ULONG TrueMsr
    )
{
    ULONG64 capability;
    ULONG mustBeOne;
    ULONG mayBeOne;
    ULONG msr;

    msr = HvUsesTrueControls() ? TrueMsr : LegacyMsr;
    capability = __readmsr(msr);

    mustBeOne = (ULONG)capability;
    mayBeOne = (ULONG)(capability >> 32);

    Requested |= mustBeOne;
    Requested &= mayBeOne;

    return Requested;
}

static
NTSTATUS
HvWriteVmcs(
    _In_ SIZE_T Field,
    _In_ ULONG64 Value
    )
{
    return (__vmx_vmwrite(Field, (SIZE_T)Value) == 0)
        ? STATUS_SUCCESS
        : STATUS_UNSUCCESSFUL;
}

static
BOOLEAN
HvReadVmcs(
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
HvIsCanonicalAddress(
    _In_ ULONG64 Address
    )
{
    ULONG width;
    ULONG shift;
    LONG64 signedAddress;

    width = (__readcr4() & (1ull << 12)) != 0 ? 57u : 48u;
    shift = 64u - width;

    signedAddress = ((LONG64)(Address << shift)) >> shift;
    return (ULONG64)signedAddress == Address;
}

static
NTSTATUS
HvReadSegmentDescriptor(
    _In_ USHORT Selector,
    _In_ PHV_DESCRIPTOR_TABLE_REGISTER Gdtr,
    _Out_ PHV_SEGMENT_STATE Segment
    )
{
    ULONG offset;
    ULONG64 descriptor;
    ULONG descriptorHigh = 0;
    UCHAR access;
    UCHAR flags;
    ULONG limit;
    ULONG64 base;

    if (Gdtr == NULL || Segment == NULL) {
        return STATUS_INVALID_PARAMETER;
    }

    RtlZeroMemory(Segment, sizeof(*Segment));
    Segment->Selector = Selector;

    if (Selector == 0) {
        Segment->AccessRights = (1u << 16);
        return STATUS_SUCCESS;
    }

    // This lab uses the normal Windows GDT.  LDT-backed selectors are not
    // expected on x64 Windows and are rejected rather than guessed.
    if ((Selector & 0x4u) != 0) {
        return STATUS_NOT_SUPPORTED;
    }

    offset = Selector & ~0x7u;
    if (offset + sizeof(ULONG64) - 1 > Gdtr->Limit) {
        return STATUS_INVALID_PARAMETER;
    }

    __try {
        RtlCopyMemory(
            &descriptor,
            (PVOID)(ULONG_PTR)(Gdtr->Base + offset),
            sizeof(descriptor)
            );
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return GetExceptionCode();
    }

    access = (UCHAR)((descriptor >> 40) & 0xFFu);
    flags = (UCHAR)((descriptor >> 52) & 0x0Fu);

    if ((access & 0x80u) == 0) {
        return STATUS_INVALID_PARAMETER;
    }

    limit =
        (ULONG)(descriptor & 0xFFFFu) |
        (ULONG)(((descriptor >> 48) & 0x0Fu) << 16);

    if ((flags & 0x8u) != 0) {
        limit = (limit << 12) | 0xFFFu;
    }

    base =
        ((descriptor >> 16) & 0xFFFFu) |
        (((descriptor >> 32) & 0xFFu) << 16) |
        (((descriptor >> 56) & 0xFFu) << 24);

    // System descriptors such as the 64-bit TSS and LDT are 16 bytes and
    // carry the upper 32 bits of the base in the second qword.
    if ((access & 0x10u) == 0) {
        if (offset + 16u - 1u > Gdtr->Limit) {
            return STATUS_INVALID_PARAMETER;
        }

        __try {
            RtlCopyMemory(
                &descriptorHigh,
                (PVOID)(ULONG_PTR)(Gdtr->Base + offset + 8u),
                sizeof(descriptorHigh)
                );
        }
        __except (EXCEPTION_EXECUTE_HANDLER) {
            return GetExceptionCode();
        }

        base |= ((ULONG64)descriptorHigh << 32);
    }

    Segment->Base = base;
    Segment->Limit = limit;
    Segment->AccessRights =
        (ULONG)access |
        ((ULONG)(flags & 0x0Fu) << 12);

    return STATUS_SUCCESS;
}

static
NTSTATUS
HvWriteGuestSegment(
    _In_ const HV_SEGMENT_STATE* Segment,
    _In_ SIZE_T SelectorField,
    _In_ SIZE_T BaseField,
    _In_ SIZE_T LimitField,
    _In_ SIZE_T AccessRightsField
    )
{
    NTSTATUS status;

    status = HvWriteVmcs(SelectorField, Segment->Selector);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = HvWriteVmcs(BaseField, Segment->Base);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = HvWriteVmcs(LimitField, Segment->Limit);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    return HvWriteVmcs(
        AccessRightsField,
        Segment->AccessRights
        );
}

NTSTATUS
HvConfigureVmcs(
    _Inout_ PHV_CPU_CONTEXT CpuContext
    )
{
    HV_DESCRIPTOR_TABLE_REGISTER gdtr;
    HV_DESCRIPTOR_TABLE_REGISTER idtr;
    HV_SEGMENT_STATE es;
    HV_SEGMENT_STATE cs;
    HV_SEGMENT_STATE ss;
    HV_SEGMENT_STATE ds;
    HV_SEGMENT_STATE fs;
    HV_SEGMENT_STATE gs;
    HV_SEGMENT_STATE ldtr;
    HV_SEGMENT_STATE tr;

    ULONG pinControls;
    ULONG primaryControls;
    ULONG secondaryControls;
    ULONG exitControls;
    ULONG entryControls;

    ULONG64 cr0;
    ULONG64 cr3;
    ULONG64 cr4;
    ULONG64 rflags;
    ULONG64 pat;
    ULONG64 efer;

    NTSTATUS status;

#define HV_WRITE(Field, Value)                                      \
    do {                                                            \
        status = HvWriteVmcs((Field), (ULONG64)(Value));            \
        if (!NT_SUCCESS(status)) {                                  \
            return status;                                          \
        }                                                           \
    } while (0)

    if (CpuContext == NULL ||
        CpuContext->HostStack == NULL ||
        CpuContext->HostStackTop == 0 ||
        g_HvState.MsrBitmap == NULL ||
        g_HvState.Ept.EptPointer == 0 ||
        InterlockedCompareExchange(
            &CpuContext->VmxActive,
            0,
            0) == 0) {
        return STATUS_DEVICE_NOT_READY;
    }

    RtlZeroMemory(&gdtr, sizeof(gdtr));
    RtlZeroMemory(&idtr, sizeof(idtr));

    HvStoreGdtr(&gdtr);
    HvStoreIdtr(&idtr);

    status = HvReadSegmentDescriptor(HvReadEs(), &gdtr, &es);
    if (!NT_SUCCESS(status)) return status;

    status = HvReadSegmentDescriptor(HvReadCs(), &gdtr, &cs);
    if (!NT_SUCCESS(status)) return status;

    status = HvReadSegmentDescriptor(HvReadSs(), &gdtr, &ss);
    if (!NT_SUCCESS(status)) return status;

    status = HvReadSegmentDescriptor(HvReadDs(), &gdtr, &ds);
    if (!NT_SUCCESS(status)) return status;

    status = HvReadSegmentDescriptor(HvReadFs(), &gdtr, &fs);
    if (!NT_SUCCESS(status)) return status;

    status = HvReadSegmentDescriptor(HvReadGs(), &gdtr, &gs);
    if (!NT_SUCCESS(status)) return status;

    status = HvReadSegmentDescriptor(HvReadLdtr(), &gdtr, &ldtr);
    if (!NT_SUCCESS(status)) return status;

    status = HvReadSegmentDescriptor(HvReadTr(), &gdtr, &tr);
    if (!NT_SUCCESS(status)) return status;

    // In 64-bit mode FS/GS bases come from MSRs rather than the descriptor.
    fs.Base = __readmsr(HV_IA32_FS_BASE);
    gs.Base = __readmsr(HV_IA32_GS_BASE);

    cr0 = __readcr0();
    cr3 = __readcr3();
    cr4 = __readcr4();
    rflags = __readeflags();

    pat = __readmsr(HV_IA32_PAT);
    efer = __readmsr(HV_IA32_EFER);

    pinControls = HvAdjustControl(
        0,
        HV_IA32_VMX_PINBASED_CTLS,
        HV_IA32_VMX_TRUE_PINBASED_CTLS
        );

    primaryControls = HvAdjustControl(
        HV_PRIMARY_USE_MSR_BITMAPS |
        HV_PRIMARY_ACTIVATE_SECONDARY,
        HV_IA32_VMX_PROCBASED_CTLS,
        HV_IA32_VMX_TRUE_PROCBASED_CTLS
        );

    if ((primaryControls & HV_PRIMARY_USE_MSR_BITMAPS) == 0 ||
        (primaryControls & HV_PRIMARY_ACTIVATE_SECONDARY) == 0) {
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    secondaryControls = HvAdjustControl(
        HV_SECONDARY_ENABLE_EPT |
        HV_SECONDARY_ENABLE_RDTSCP |
        HV_SECONDARY_ENABLE_INVPCID |
        HV_SECONDARY_ENABLE_XSAVES,
        HV_IA32_VMX_PROCBASED_CTLS2,
        HV_IA32_VMX_PROCBASED_CTLS2
        );

    if ((secondaryControls & HV_SECONDARY_ENABLE_EPT) == 0) {
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    exitControls = HvAdjustControl(
        HV_EXIT_HOST_ADDRESS_SPACE_SIZE |
        HV_EXIT_SAVE_IA32_PAT |
        HV_EXIT_LOAD_IA32_PAT |
        HV_EXIT_SAVE_IA32_EFER |
        HV_EXIT_LOAD_IA32_EFER,
        HV_IA32_VMX_EXIT_CTLS,
        HV_IA32_VMX_TRUE_EXIT_CTLS
        );

    if ((exitControls & HV_EXIT_HOST_ADDRESS_SPACE_SIZE) == 0) {
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    entryControls = HvAdjustControl(
        HV_ENTRY_IA32E_MODE_GUEST |
        HV_ENTRY_LOAD_IA32_PAT |
        HV_ENTRY_LOAD_IA32_EFER,
        HV_IA32_VMX_ENTRY_CTLS,
        HV_IA32_VMX_TRUE_ENTRY_CTLS
        );

    if ((entryControls & HV_ENTRY_IA32E_MODE_GUEST) == 0) {
        return STATUS_HV_FEATURE_UNAVAILABLE;
    }

    HV_WRITE(HV_VMCS_PIN_BASED_CONTROLS, pinControls);
    HV_WRITE(HV_VMCS_PRIMARY_PROC_CONTROLS, primaryControls);
    HV_WRITE(HV_VMCS_SECONDARY_PROC_CONTROLS, secondaryControls);
    HV_WRITE(HV_VMCS_EXIT_CONTROLS, exitControls);
    HV_WRITE(HV_VMCS_ENTRY_CONTROLS, entryControls);

    HV_WRITE(HV_VMCS_EXCEPTION_BITMAP, 0);
    HV_WRITE(HV_VMCS_PAGE_FAULT_ERROR_MASK, 0);
    HV_WRITE(HV_VMCS_PAGE_FAULT_ERROR_MATCH, 0);
    HV_WRITE(HV_VMCS_CR3_TARGET_COUNT, 0);
    HV_WRITE(HV_VMCS_EXIT_MSR_STORE_COUNT, 0);
    HV_WRITE(HV_VMCS_EXIT_MSR_LOAD_COUNT, 0);
    HV_WRITE(HV_VMCS_ENTRY_MSR_LOAD_COUNT, 0);
    HV_WRITE(HV_VMCS_ENTRY_INTR_INFO, 0);

    HV_WRITE(
        HV_VMCS_MSR_BITMAP,
        g_HvState.MsrBitmapPhysical.QuadPart
        );
    HV_WRITE(
        HV_VMCS_EPT_POINTER,
        g_HvState.Ept.EptPointer
        );

    // Keep VMXE set in the hardware guest CR4 so VM-entry satisfies VMX fixed
    // bits, but mask it from the guest-visible CR4 value.
    HV_WRITE(HV_VMCS_CR0_GUEST_HOST_MASK, 0);
    HV_WRITE(HV_VMCS_CR0_READ_SHADOW, cr0);
    HV_WRITE(HV_VMCS_CR4_GUEST_HOST_MASK, HV_CR4_VMXE);
    HV_WRITE(HV_VMCS_CR4_READ_SHADOW, CpuContext->OriginalCr4);

    HV_WRITE(HV_VMCS_GUEST_CR0, cr0);
    HV_WRITE(HV_VMCS_GUEST_CR3, cr3);
    HV_WRITE(HV_VMCS_GUEST_CR4, cr4);

    status = HvWriteGuestSegment(
        &es,
        HV_VMCS_GUEST_ES_SELECTOR,
        HV_VMCS_GUEST_ES_BASE,
        HV_VMCS_GUEST_ES_LIMIT,
        HV_VMCS_GUEST_ES_AR
        );
    if (!NT_SUCCESS(status)) return status;

    status = HvWriteGuestSegment(
        &cs,
        HV_VMCS_GUEST_CS_SELECTOR,
        HV_VMCS_GUEST_CS_BASE,
        HV_VMCS_GUEST_CS_LIMIT,
        HV_VMCS_GUEST_CS_AR
        );
    if (!NT_SUCCESS(status)) return status;

    status = HvWriteGuestSegment(
        &ss,
        HV_VMCS_GUEST_SS_SELECTOR,
        HV_VMCS_GUEST_SS_BASE,
        HV_VMCS_GUEST_SS_LIMIT,
        HV_VMCS_GUEST_SS_AR
        );
    if (!NT_SUCCESS(status)) return status;

    status = HvWriteGuestSegment(
        &ds,
        HV_VMCS_GUEST_DS_SELECTOR,
        HV_VMCS_GUEST_DS_BASE,
        HV_VMCS_GUEST_DS_LIMIT,
        HV_VMCS_GUEST_DS_AR
        );
    if (!NT_SUCCESS(status)) return status;

    status = HvWriteGuestSegment(
        &fs,
        HV_VMCS_GUEST_FS_SELECTOR,
        HV_VMCS_GUEST_FS_BASE,
        HV_VMCS_GUEST_FS_LIMIT,
        HV_VMCS_GUEST_FS_AR
        );
    if (!NT_SUCCESS(status)) return status;

    status = HvWriteGuestSegment(
        &gs,
        HV_VMCS_GUEST_GS_SELECTOR,
        HV_VMCS_GUEST_GS_BASE,
        HV_VMCS_GUEST_GS_LIMIT,
        HV_VMCS_GUEST_GS_AR
        );
    if (!NT_SUCCESS(status)) return status;

    status = HvWriteGuestSegment(
        &ldtr,
        HV_VMCS_GUEST_LDTR_SELECTOR,
        HV_VMCS_GUEST_LDTR_BASE,
        HV_VMCS_GUEST_LDTR_LIMIT,
        HV_VMCS_GUEST_LDTR_AR
        );
    if (!NT_SUCCESS(status)) return status;

    status = HvWriteGuestSegment(
        &tr,
        HV_VMCS_GUEST_TR_SELECTOR,
        HV_VMCS_GUEST_TR_BASE,
        HV_VMCS_GUEST_TR_LIMIT,
        HV_VMCS_GUEST_TR_AR
        );
    if (!NT_SUCCESS(status)) return status;

    HV_WRITE(HV_VMCS_GUEST_GDTR_BASE, gdtr.Base);
    HV_WRITE(HV_VMCS_GUEST_GDTR_LIMIT, gdtr.Limit);
    HV_WRITE(HV_VMCS_GUEST_IDTR_BASE, idtr.Base);
    HV_WRITE(HV_VMCS_GUEST_IDTR_LIMIT, idtr.Limit);

    HV_WRITE(HV_VMCS_GUEST_DR7, 0x400ull);
    HV_WRITE(HV_VMCS_GUEST_RSP, 0);
    HV_WRITE(HV_VMCS_GUEST_RIP, 0);
    HV_WRITE(HV_VMCS_GUEST_RFLAGS, rflags);

    HV_WRITE(HV_VMCS_GUEST_PENDING_DEBUG, 0);
    HV_WRITE(HV_VMCS_GUEST_INTERRUPTIBILITY, 0);
    HV_WRITE(HV_VMCS_GUEST_ACTIVITY_STATE, 0);
    HV_WRITE(HV_VMCS_GUEST_SMBASE, 0);

    HV_WRITE(
        HV_VMCS_GUEST_SYSENTER_CS,
        __readmsr(HV_IA32_SYSENTER_CS)
        );
    HV_WRITE(
        HV_VMCS_GUEST_SYSENTER_ESP,
        __readmsr(HV_IA32_SYSENTER_ESP)
        );
    HV_WRITE(
        HV_VMCS_GUEST_SYSENTER_EIP,
        __readmsr(HV_IA32_SYSENTER_EIP)
        );

    HV_WRITE(HV_VMCS_GUEST_VMCS_LINK_POINTER, MAXULONG64);
    HV_WRITE(HV_VMCS_GUEST_IA32_PAT, pat);
    HV_WRITE(HV_VMCS_GUEST_IA32_EFER, efer);

    // Host state is the same Windows kernel execution environment, but with a
    // dedicated root-mode stack and VM-exit entry point.
    HV_WRITE(HV_VMCS_HOST_CR0, cr0);
    HV_WRITE(HV_VMCS_HOST_CR3, cr3);
    HV_WRITE(HV_VMCS_HOST_CR4, cr4);

    HV_WRITE(HV_VMCS_HOST_ES_SELECTOR, es.Selector & ~0x7u);
    HV_WRITE(HV_VMCS_HOST_CS_SELECTOR, cs.Selector & ~0x7u);
    HV_WRITE(HV_VMCS_HOST_SS_SELECTOR, ss.Selector & ~0x7u);
    HV_WRITE(HV_VMCS_HOST_DS_SELECTOR, ds.Selector & ~0x7u);
    HV_WRITE(HV_VMCS_HOST_FS_SELECTOR, fs.Selector & ~0x7u);
    HV_WRITE(HV_VMCS_HOST_GS_SELECTOR, gs.Selector & ~0x7u);
    HV_WRITE(HV_VMCS_HOST_TR_SELECTOR, tr.Selector & ~0x7u);

    HV_WRITE(HV_VMCS_HOST_FS_BASE, fs.Base);
    HV_WRITE(HV_VMCS_HOST_GS_BASE, gs.Base);
    HV_WRITE(HV_VMCS_HOST_TR_BASE, tr.Base);
    HV_WRITE(HV_VMCS_HOST_GDTR_BASE, gdtr.Base);
    HV_WRITE(HV_VMCS_HOST_IDTR_BASE, idtr.Base);

    HV_WRITE(
        HV_VMCS_HOST_SYSENTER_CS,
        __readmsr(HV_IA32_SYSENTER_CS)
        );
    HV_WRITE(
        HV_VMCS_HOST_SYSENTER_ESP,
        __readmsr(HV_IA32_SYSENTER_ESP)
        );
    HV_WRITE(
        HV_VMCS_HOST_SYSENTER_EIP,
        __readmsr(HV_IA32_SYSENTER_EIP)
        );

    HV_WRITE(HV_VMCS_HOST_IA32_PAT, pat);
    HV_WRITE(HV_VMCS_HOST_IA32_EFER, efer);

    HV_WRITE(HV_VMCS_HOST_RSP, CpuContext->HostStackTop);
    HV_WRITE(HV_VMCS_HOST_RIP, (ULONG64)(ULONG_PTR)HvVmExitStub);

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID,
        DPFLTR_INFO_LEVEL,
        "[HwidHv] CPU %lu VMCS controls: pin=%08X primary=%08X "
        "secondary=%08X exit=%08X entry=%08X\n",
        CpuContext->ProcessorIndex,
        pinControls,
        primaryControls,
        secondaryControls,
        exitControls,
        entryControls
        );

#undef HV_WRITE

    return STATUS_SUCCESS;
}

NTSTATUS
HvSetGuestLaunchState(
    _In_ ULONG64 GuestRsp,
    _In_ ULONG64 GuestRip
    )
{
    PHV_CPU_CONTEXT cpu;
    NTSTATUS status;

    cpu = HvGetCurrentCpuContext();
    if (cpu == NULL) {
        return STATUS_DEVICE_NOT_READY;
    }

    if (!HvIsCanonicalAddress(GuestRsp) ||
        !HvIsCanonicalAddress(GuestRip) ||
        GuestRsp == 0 ||
        GuestRip == 0) {
        return STATUS_INVALID_PARAMETER;
    }

    status = HvWriteVmcs(HV_VMCS_GUEST_RSP, GuestRsp);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = HvWriteVmcs(HV_VMCS_GUEST_RIP, GuestRip);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = HvValidateCurrentVmcs();

    InterlockedExchange(
        &cpu->VmcsValidated,
        NT_SUCCESS(status) ? 1 : 0
        );

    return status;
}

NTSTATUS
HvValidateCurrentVmcs(
    VOID
    )
{
    ULONG64 guestRip;
    ULONG64 guestRsp;
    ULONG64 hostRip;
    ULONG64 hostRsp;
    ULONG64 guestCr0;
    ULONG64 guestCr4;
    ULONG64 primaryControls;
    ULONG64 secondaryControls;
    ULONG64 exitControls;
    ULONG64 entryControls;
    ULONG64 eptPointer;
    ULONG64 cr0Fixed0;
    ULONG64 cr0Fixed1;
    ULONG64 cr4Fixed0;
    ULONG64 cr4Fixed1;

    if (!HvReadVmcs(HV_VMCS_GUEST_RIP, &guestRip) ||
        !HvReadVmcs(HV_VMCS_GUEST_RSP, &guestRsp) ||
        !HvReadVmcs(HV_VMCS_HOST_RIP, &hostRip) ||
        !HvReadVmcs(HV_VMCS_HOST_RSP, &hostRsp) ||
        !HvReadVmcs(HV_VMCS_GUEST_CR0, &guestCr0) ||
        !HvReadVmcs(HV_VMCS_GUEST_CR4, &guestCr4) ||
        !HvReadVmcs(HV_VMCS_PRIMARY_PROC_CONTROLS, &primaryControls) ||
        !HvReadVmcs(HV_VMCS_SECONDARY_PROC_CONTROLS, &secondaryControls) ||
        !HvReadVmcs(HV_VMCS_EXIT_CONTROLS, &exitControls) ||
        !HvReadVmcs(HV_VMCS_ENTRY_CONTROLS, &entryControls) ||
        !HvReadVmcs(HV_VMCS_EPT_POINTER, &eptPointer)) {
        return STATUS_UNSUCCESSFUL;
    }

    if (!HvIsCanonicalAddress(guestRip) ||
        !HvIsCanonicalAddress(guestRsp) ||
        !HvIsCanonicalAddress(hostRip) ||
        !HvIsCanonicalAddress(hostRsp) ||
        guestRip == 0 ||
        guestRsp == 0 ||
        hostRip == 0 ||
        hostRsp == 0 ||
        (hostRsp & 0xFu) != 0) {
        return STATUS_INVALID_PARAMETER;
    }

    cr0Fixed0 = __readmsr(HV_IA32_VMX_CR0_FIXED0);
    cr0Fixed1 = __readmsr(HV_IA32_VMX_CR0_FIXED1);
    cr4Fixed0 = __readmsr(HV_IA32_VMX_CR4_FIXED0);
    cr4Fixed1 = __readmsr(HV_IA32_VMX_CR4_FIXED1);

    if ((guestCr0 & cr0Fixed0) != cr0Fixed0 ||
        (guestCr0 & ~cr0Fixed1) != 0 ||
        (guestCr4 & cr4Fixed0) != cr4Fixed0 ||
        (guestCr4 & ~cr4Fixed1) != 0) {
        return STATUS_INVALID_PARAMETER;
    }

    if ((primaryControls & HV_PRIMARY_ACTIVATE_SECONDARY) == 0 ||
        (primaryControls & HV_PRIMARY_USE_MSR_BITMAPS) == 0 ||
        (secondaryControls & HV_SECONDARY_ENABLE_EPT) == 0 ||
        (exitControls & HV_EXIT_HOST_ADDRESS_SPACE_SIZE) == 0 ||
        (entryControls & HV_ENTRY_IA32E_MODE_GUEST) == 0 ||
        eptPointer == 0) {
        return STATUS_INVALID_PARAMETER;
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

    vmcsPhysical = CpuContext->VmcsPhysical.QuadPart;

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
