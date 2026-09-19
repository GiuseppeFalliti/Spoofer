#pragma once

#include <ntddk.h>
#include <intrin.h>

#define HV_POOL_TAG 'LvhH'
#define HV_PAGE_SIZE 0x1000ull
#define HV_2MB_SIZE  0x200000ull
#define HV_1GB_SIZE  0x40000000ull

#define HV_EPT_READ       (1ull << 0)
#define HV_EPT_WRITE      (1ull << 1)
#define HV_EPT_EXECUTE    (1ull << 2)
#define HV_EPT_MEMTYPE_WB (6ull << 3)
#define HV_EPT_LARGE_PAGE (1ull << 7)
#define HV_EPT_ADDR_MASK  0x000FFFFFFFFFF000ull

#define HV_IA32_FEATURE_CONTROL        0x03A
#define HV_IA32_VMX_BASIC              0x480
#define HV_IA32_VMX_PROCBASED_CTLS     0x482
#define HV_IA32_VMX_PROCBASED_CTLS2    0x48B
#define HV_IA32_VMX_EPT_VPID_CAP       0x48C
#define HV_IA32_VMX_CR0_FIXED0          0x486
#define HV_IA32_VMX_CR0_FIXED1          0x487
#define HV_IA32_VMX_CR4_FIXED0          0x488
#define HV_IA32_VMX_CR4_FIXED1          0x489

#define HV_VMCS_PRIMARY_PROC_CONTROLS   0x4002
#define HV_VMCS_SECONDARY_PROC_CONTROLS 0x401E
#define HV_VMCS_EPT_POINTER             0x201A

#define HV_PRIMARY_ACTIVATE_SECONDARY   (1u << 31)
#define HV_SECONDARY_ENABLE_EPT         (1u << 1)

#define HV_VMCS_EXIT_REASON             0x4402
#define HV_VMCS_EXIT_QUALIFICATION      0x6400
#define HV_VMCS_GUEST_PHYSICAL_ADDRESS  0x2400
#define HV_EXIT_REASON_EPT_VIOLATION    48u

typedef struct _HV_GUEST_REGISTERS {
    ULONG64 R15;
    ULONG64 R14;
    ULONG64 R13;
    ULONG64 R12;
    ULONG64 R11;
    ULONG64 R10;
    ULONG64 R9;
    ULONG64 R8;
    ULONG64 Rdi;
    ULONG64 Rsi;
    ULONG64 Rbp;
    ULONG64 Rbx;
    ULONG64 Rdx;
    ULONG64 Rcx;
    ULONG64 Rax;
} HV_GUEST_REGISTERS, *PHV_GUEST_REGISTERS;

typedef struct _HV_CPU_CONTEXT {
    ULONG ProcessorIndex;
    PROCESSOR_NUMBER ProcessorNumber;

    PVOID VmxonRegion;
    PHYSICAL_ADDRESS VmxonPhysical;

    PVOID VmcsRegion;
    PHYSICAL_ADDRESS VmcsPhysical;

    ULONG64 OriginalCr4;

    volatile LONG VmxActive;
    NTSTATUS LastStatus;

    volatile LONG64 VmExitCount;
    volatile LONG64 EptViolationCount;
} HV_CPU_CONTEXT, *PHV_CPU_CONTEXT;

typedef struct _HV_EPT_STATE {
    PVOID Pml4;
    PHYSICAL_ADDRESS Pml4Physical;

    PVOID Pdpt;
    PHYSICAL_ADDRESS PdptPhysical;

    PVOID Pd;
    PHYSICAL_ADDRESS PdPhysical;

    PVOID SplitPt;
    PHYSICAL_ADDRESS SplitPtPhysical;
    ULONG SplitPdIndex;

    ULONG64 EptPointer;

    PVOID LabSmbiosPage;
    PHYSICAL_ADDRESS LabSmbiosPhysical;

    PVOID LabShadowPage;
    PHYSICAL_ADDRESS LabShadowPhysical;

    volatile LONG LabShadowInstalled;
    KSPIN_LOCK Lock;
} HV_EPT_STATE, *PHV_EPT_STATE;

typedef struct _HV_STATE {
    volatile LONG Initialized;
    volatile LONG Running;

    BOOLEAN HypervisorPresent;
    BOOLEAN VmxSupported;
    BOOLEAN EptSupported;
    BOOLEAN VmxFeatureControlEnabled;

    ULONG ProcessorCount;
    PHV_CPU_CONTEXT CpuContexts;

    HV_EPT_STATE Ept;
} HV_STATE, *PHV_STATE;

extern HV_STATE g_HvState;

NTSTATUS HvInitialize(VOID);
NTSTATUS HvAllocateVmcs(VOID);
NTSTATUS HvStartVmx(VOID);
VOID HvStopVmx(VOID);
VOID HvShutdown(VOID);

PHV_CPU_CONTEXT HvGetCurrentCpuContext(VOID);

NTSTATUS
HvPrepareVmcsCurrentCpu(
    _Inout_ PHV_CPU_CONTEXT CpuContext
    );

NTSTATUS
HvConfigureVmcs(
    _Inout_ PHV_CPU_CONTEXT CpuContext
    );

NTSTATUS HvInitializeEpt(VOID);
VOID HvTeardownEpt(VOID);
NTSTATUS HvSetupEptForSmbios(VOID);
NTSTATUS HvCreateSmbiosShadow(VOID);

NTSTATUS
HvPatchSmbiosType1(
    _Inout_updates_bytes_(PageSize) PVOID Page,
    _In_ SIZE_T PageSize
    );

BOOLEAN
HvHandleVmExit(
    _Inout_opt_ PHV_GUEST_REGISTERS GuestRegisters
    );

BOOLEAN
HvHandleEptViolation(
    _In_ ULONG64 GuestPhysicalAddress,
    _In_ ULONG64 Qualification
    );

NTSTATUS HvInjectSmbiosData(VOID);
VOID HvVmExitStub(VOID);
