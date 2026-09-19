#pragma once

#include <ntddk.h>
#include <intrin.h>

#define HV_POOL_TAG 'LvhH'
#define HV_PAGE_SIZE       0x1000ull
#define HV_2MB_SIZE        0x200000ull
#define HV_1GB_SIZE        0x40000000ull
#define HV_512GB_SIZE      (512ull * HV_1GB_SIZE)
#define HV_HOST_STACK_SIZE 0x6000ull

#define HV_EPT_READ          (1ull << 0)
#define HV_EPT_WRITE         (1ull << 1)
#define HV_EPT_EXECUTE       (1ull << 2)
#define HV_EPT_MEMTYPE_WB    (6ull << 3)
#define HV_EPT_LARGE_PAGE    (1ull << 7)
#define HV_EPT_ADDR_MASK     0x000FFFFFFFFFF000ull

#define HV_EPT_CAP_WB        (1ull << 14)
#define HV_EPT_CAP_2MB_PAGE  (1ull << 16)
#define HV_EPT_CAP_1GB_PAGE  (1ull << 17)
#define HV_EPT_CAP_INVEPT    (1ull << 20)
#define HV_EPT_CAP_INVEPT_SINGLE (1ull << 25)
#define HV_EPT_CAP_INVEPT_ALL    (1ull << 26)

#define HV_IA32_FEATURE_CONTROL         0x03A
#define HV_IA32_SYSENTER_CS             0x174
#define HV_IA32_SYSENTER_ESP            0x175
#define HV_IA32_SYSENTER_EIP            0x176
#define HV_IA32_PAT                     0x277
#define HV_IA32_EFER                    0xC0000080
#define HV_IA32_FS_BASE                 0xC0000100
#define HV_IA32_GS_BASE                 0xC0000101

#define HV_IA32_VMX_BASIC               0x480
#define HV_IA32_VMX_PINBASED_CTLS       0x481
#define HV_IA32_VMX_PROCBASED_CTLS      0x482
#define HV_IA32_VMX_EXIT_CTLS           0x483
#define HV_IA32_VMX_ENTRY_CTLS          0x484
#define HV_IA32_VMX_CR0_FIXED0          0x486
#define HV_IA32_VMX_CR0_FIXED1          0x487
#define HV_IA32_VMX_CR4_FIXED0          0x488
#define HV_IA32_VMX_CR4_FIXED1          0x489
#define HV_IA32_VMX_PROCBASED_CTLS2     0x48B
#define HV_IA32_VMX_EPT_VPID_CAP        0x48C
#define HV_IA32_VMX_TRUE_PINBASED_CTLS  0x48D
#define HV_IA32_VMX_TRUE_PROCBASED_CTLS 0x48E
#define HV_IA32_VMX_TRUE_EXIT_CTLS      0x48F
#define HV_IA32_VMX_TRUE_ENTRY_CTLS     0x490

#define HV_VMCS_GUEST_ES_SELECTOR       0x0800
#define HV_VMCS_GUEST_CS_SELECTOR       0x0802
#define HV_VMCS_GUEST_SS_SELECTOR       0x0804
#define HV_VMCS_GUEST_DS_SELECTOR       0x0806
#define HV_VMCS_GUEST_FS_SELECTOR       0x0808
#define HV_VMCS_GUEST_GS_SELECTOR       0x080A
#define HV_VMCS_GUEST_LDTR_SELECTOR     0x080C
#define HV_VMCS_GUEST_TR_SELECTOR       0x080E

#define HV_VMCS_HOST_ES_SELECTOR        0x0C00
#define HV_VMCS_HOST_CS_SELECTOR        0x0C02
#define HV_VMCS_HOST_SS_SELECTOR        0x0C04
#define HV_VMCS_HOST_DS_SELECTOR        0x0C06
#define HV_VMCS_HOST_FS_SELECTOR        0x0C08
#define HV_VMCS_HOST_GS_SELECTOR        0x0C0A
#define HV_VMCS_HOST_TR_SELECTOR        0x0C0C

#define HV_VMCS_MSR_BITMAP              0x2004
#define HV_VMCS_EPT_POINTER             0x201A

#define HV_VMCS_GUEST_VMCS_LINK_POINTER 0x2800
#define HV_VMCS_GUEST_IA32_PAT          0x2804
#define HV_VMCS_GUEST_IA32_EFER         0x2806
#define HV_VMCS_HOST_IA32_PAT           0x2C00
#define HV_VMCS_HOST_IA32_EFER          0x2C02

#define HV_VMCS_PIN_BASED_CONTROLS      0x4000
#define HV_VMCS_PRIMARY_PROC_CONTROLS   0x4002
#define HV_VMCS_EXCEPTION_BITMAP        0x4004
#define HV_VMCS_PAGE_FAULT_ERROR_MASK   0x4006
#define HV_VMCS_PAGE_FAULT_ERROR_MATCH  0x4008
#define HV_VMCS_CR3_TARGET_COUNT        0x400A
#define HV_VMCS_EXIT_CONTROLS           0x400C
#define HV_VMCS_EXIT_MSR_STORE_COUNT    0x400E
#define HV_VMCS_EXIT_MSR_LOAD_COUNT     0x4010
#define HV_VMCS_ENTRY_CONTROLS          0x4012
#define HV_VMCS_ENTRY_MSR_LOAD_COUNT    0x4014
#define HV_VMCS_ENTRY_INTR_INFO         0x4016
#define HV_VMCS_SECONDARY_PROC_CONTROLS 0x401E

#define HV_VMCS_VM_INSTRUCTION_ERROR    0x4400
#define HV_VMCS_EXIT_REASON             0x4402
#define HV_VMCS_EXIT_INSTRUCTION_LENGTH 0x440C

#define HV_VMCS_GUEST_ES_LIMIT          0x4800
#define HV_VMCS_GUEST_CS_LIMIT          0x4802
#define HV_VMCS_GUEST_SS_LIMIT          0x4804
#define HV_VMCS_GUEST_DS_LIMIT          0x4806
#define HV_VMCS_GUEST_FS_LIMIT          0x4808
#define HV_VMCS_GUEST_GS_LIMIT          0x480A
#define HV_VMCS_GUEST_LDTR_LIMIT        0x480C
#define HV_VMCS_GUEST_TR_LIMIT          0x480E
#define HV_VMCS_GUEST_GDTR_LIMIT        0x4810
#define HV_VMCS_GUEST_IDTR_LIMIT        0x4812
#define HV_VMCS_GUEST_ES_AR             0x4814
#define HV_VMCS_GUEST_CS_AR             0x4816
#define HV_VMCS_GUEST_SS_AR             0x4818
#define HV_VMCS_GUEST_DS_AR             0x481A
#define HV_VMCS_GUEST_FS_AR             0x481C
#define HV_VMCS_GUEST_GS_AR             0x481E
#define HV_VMCS_GUEST_LDTR_AR           0x4820
#define HV_VMCS_GUEST_TR_AR             0x4822
#define HV_VMCS_GUEST_INTERRUPTIBILITY  0x4824
#define HV_VMCS_GUEST_ACTIVITY_STATE    0x4826
#define HV_VMCS_GUEST_SMBASE            0x4828
#define HV_VMCS_GUEST_SYSENTER_CS       0x482A
#define HV_VMCS_HOST_SYSENTER_CS        0x4C00

#define HV_VMCS_CR0_GUEST_HOST_MASK     0x6000
#define HV_VMCS_CR4_GUEST_HOST_MASK     0x6002
#define HV_VMCS_CR0_READ_SHADOW         0x6004
#define HV_VMCS_CR4_READ_SHADOW         0x6006

#define HV_VMCS_EXIT_QUALIFICATION      0x6400
#define HV_VMCS_GUEST_PHYSICAL_ADDRESS  0x2400

#define HV_VMCS_GUEST_CR0               0x6800
#define HV_VMCS_GUEST_CR3               0x6802
#define HV_VMCS_GUEST_CR4               0x6804
#define HV_VMCS_GUEST_ES_BASE           0x6806
#define HV_VMCS_GUEST_CS_BASE           0x6808
#define HV_VMCS_GUEST_SS_BASE           0x680A
#define HV_VMCS_GUEST_DS_BASE           0x680C
#define HV_VMCS_GUEST_FS_BASE           0x680E
#define HV_VMCS_GUEST_GS_BASE           0x6810
#define HV_VMCS_GUEST_LDTR_BASE         0x6812
#define HV_VMCS_GUEST_TR_BASE           0x6814
#define HV_VMCS_GUEST_GDTR_BASE         0x6816
#define HV_VMCS_GUEST_IDTR_BASE         0x6818
#define HV_VMCS_GUEST_DR7               0x681A
#define HV_VMCS_GUEST_RSP               0x681C
#define HV_VMCS_GUEST_RIP               0x681E
#define HV_VMCS_GUEST_RFLAGS            0x6820
#define HV_VMCS_GUEST_PENDING_DEBUG     0x6822
#define HV_VMCS_GUEST_SYSENTER_ESP      0x6824
#define HV_VMCS_GUEST_SYSENTER_EIP      0x6826

#define HV_VMCS_HOST_CR0                0x6C00
#define HV_VMCS_HOST_CR3                0x6C02
#define HV_VMCS_HOST_CR4                0x6C04
#define HV_VMCS_HOST_FS_BASE            0x6C06
#define HV_VMCS_HOST_GS_BASE            0x6C08
#define HV_VMCS_HOST_TR_BASE            0x6C0A
#define HV_VMCS_HOST_GDTR_BASE          0x6C0C
#define HV_VMCS_HOST_IDTR_BASE          0x6C0E
#define HV_VMCS_HOST_SYSENTER_ESP       0x6C10
#define HV_VMCS_HOST_SYSENTER_EIP       0x6C12
#define HV_VMCS_HOST_RSP                0x6C14
#define HV_VMCS_HOST_RIP                0x6C16

#define HV_PRIMARY_USE_MSR_BITMAPS      (1u << 28)
#define HV_PRIMARY_ACTIVATE_SECONDARY   (1u << 31)

#define HV_SECONDARY_ENABLE_EPT         (1u << 1)
#define HV_SECONDARY_ENABLE_RDTSCP      (1u << 3)
#define HV_SECONDARY_ENABLE_INVPCID     (1u << 12)
#define HV_SECONDARY_ENABLE_XSAVES      (1u << 20)

#define HV_EXIT_HOST_ADDRESS_SPACE_SIZE (1u << 9)
#define HV_EXIT_SAVE_IA32_PAT           (1u << 18)
#define HV_EXIT_LOAD_IA32_PAT           (1u << 19)
#define HV_EXIT_SAVE_IA32_EFER          (1u << 20)
#define HV_EXIT_LOAD_IA32_EFER          (1u << 21)

#define HV_ENTRY_IA32E_MODE_GUEST       (1u << 9)
#define HV_ENTRY_LOAD_IA32_PAT          (1u << 14)
#define HV_ENTRY_LOAD_IA32_EFER         (1u << 15)

#define HV_EXIT_REASON_CPUID             10u
#define HV_EXIT_REASON_VMCALL            18u
#define HV_EXIT_REASON_EPT_VIOLATION     48u

#define HV_VMEXIT_ACTION_RESUME          0u
#define HV_VMEXIT_ACTION_TERMINATE       1u
#define HV_VMEXIT_ACTION_FATAL           2u

#define HV_HYPERCALL_SIGNATURE 0x48564C414248564Dull
#define HV_HYPERCALL_INVEPT    1ull
#define HV_HYPERCALL_STOP      2ull

#pragma pack(push, 1)
typedef struct _HV_DESCRIPTOR_TABLE_REGISTER {
    USHORT Limit;
    ULONG64 Base;
} HV_DESCRIPTOR_TABLE_REGISTER, *PHV_DESCRIPTOR_TABLE_REGISTER;
#pragma pack(pop)

typedef struct _HV_SEGMENT_STATE {
    USHORT Selector;
    ULONG Limit;
    ULONG AccessRights;
    ULONG64 Base;
} HV_SEGMENT_STATE, *PHV_SEGMENT_STATE;

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

    ULONG64 GuestRsp;
    ULONG64 GuestRip;
    ULONG64 GuestRflags;
    ULONG64 GuestCr0;
    ULONG64 GuestCr3;
    ULONG64 GuestCr4;
} HV_GUEST_REGISTERS, *PHV_GUEST_REGISTERS;

C_ASSERT(FIELD_OFFSET(HV_GUEST_REGISTERS, Rax) == 0x70);
C_ASSERT(FIELD_OFFSET(HV_GUEST_REGISTERS, GuestRsp) == 0x78);
C_ASSERT(FIELD_OFFSET(HV_GUEST_REGISTERS, GuestRip) == 0x80);
C_ASSERT(FIELD_OFFSET(HV_GUEST_REGISTERS, GuestRflags) == 0x88);
C_ASSERT(FIELD_OFFSET(HV_GUEST_REGISTERS, GuestCr0) == 0x90);
C_ASSERT(FIELD_OFFSET(HV_GUEST_REGISTERS, GuestCr3) == 0x98);
C_ASSERT(FIELD_OFFSET(HV_GUEST_REGISTERS, GuestCr4) == 0xA0);
C_ASSERT(sizeof(HV_GUEST_REGISTERS) == 0xA8);

typedef struct _HV_CPU_CONTEXT {
    ULONG ProcessorIndex;
    PROCESSOR_NUMBER ProcessorNumber;

    PVOID VmxonRegion;
    PHYSICAL_ADDRESS VmxonPhysical;

    PVOID VmcsRegion;
    PHYSICAL_ADDRESS VmcsPhysical;

    PVOID HostStack;
    ULONG64 HostStackTop;

    ULONG64 OriginalCr4;

    volatile LONG VmxActive;
    volatile LONG Launched;
    volatile LONG VmcsValidated;
    NTSTATUS LastStatus;

    ULONG LastVmInstructionError;
    ULONG LastExitReason;
    ULONG64 LastExitQualification;
    ULONG64 LastGuestPhysicalAddress;

    volatile LONG64 VmExitCount;
    volatile LONG64 EptViolationCount;
    volatile LONG64 CpuidExitCount;
    volatile LONG64 VmcallExitCount;
    volatile LONG64 InveptCount;
    volatile LONG64 VmResumeFailureCount;
    volatile LONG64 VmExitCycles;
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

    ULONG SplitPdptIndex;
    ULONG SplitPdIndex;
    ULONG SplitPtIndex;

    ULONG64 EptPointer;

    PVOID LabSmbiosPage;
    PHYSICAL_ADDRESS LabSmbiosPhysical;

    PVOID LabShadowPage;
    PHYSICAL_ADDRESS LabShadowPhysical;

    volatile LONG LabTrapArmed;
    volatile LONG LabShadowInstalled;
    volatile LONG ConfigBusy;
    volatile LONG64 LabRedirectCount;
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

    PVOID MsrBitmap;
    PHYSICAL_ADDRESS MsrBitmapPhysical;

    HV_EPT_STATE Ept;
} HV_STATE, *PHV_STATE;

extern HV_STATE g_HvState;

VOID
HvQueryCapabilities(
    _Out_ PUCHAR VtxSupported,
    _Out_ PUCHAR EptSupported,
    _Out_ PUCHAR VmxBlocked,
    _Out_ PUCHAR HypervisorPresent,
    _Out_ PULONG ProcessorCount
    );

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

NTSTATUS
HvSetGuestLaunchState(
    _In_ ULONG64 GuestRsp,
    _In_ ULONG64 GuestRip
    );

NTSTATUS HvValidateCurrentVmcs(VOID);

NTSTATUS HvInitializeEpt(VOID);
VOID HvTeardownEpt(VOID);
NTSTATUS HvSetupEptForSmbios(VOID);
VOID HvDisableLabSmbiosEptHook(VOID);

BOOLEAN HvInvalidateEptCurrentProcessor(VOID);
NTSTATUS HvInvalidateEptAllProcessors(VOID);

NTSTATUS
HvRedirectToSmbiosShadow(
    _In_ ULONG64 GuestPhysicalAddress
    );

NTSTATUS HvCreateSmbiosShadow(VOID);

NTSTATUS
HvPatchSmbiosType1(
    _Inout_updates_bytes_(PageSize) PVOID Page,
    _In_ SIZE_T PageSize
    );

NTSTATUS
HvCopyLabSmbiosShadowSnapshot(
    _Out_writes_bytes_(BufferSize) PVOID Buffer,
    _In_ ULONG BufferSize,
    _Out_ PULONG BytesWritten
    );

ULONG
HvHandleVmExit(
    _Inout_ PHV_GUEST_REGISTERS GuestRegisters
    );

BOOLEAN
HvHandleEptViolation(
    _In_ ULONG64 GuestPhysicalAddress,
    _In_ ULONG64 Qualification
    );

NTSTATUS HvInjectSmbiosData(VOID);

VOID HvCompleteVmxOff(VOID);
VOID HvRecordVmResumeFailure(VOID);
DECLSPEC_NORETURN VOID HvFatalVmInstructionFailure(_In_ ULONG FailureCode);

ULONG HvVmxLaunch(VOID);
ULONG64 HvHypercall(_In_ ULONG64 Operation);
ULONG HvInvept(_In_ ULONG Type, _In_ PVOID Descriptor);
VOID HvVmExitStub(VOID);

USHORT HvReadEs(VOID);
USHORT HvReadCs(VOID);
USHORT HvReadSs(VOID);
USHORT HvReadDs(VOID);
USHORT HvReadFs(VOID);
USHORT HvReadGs(VOID);
USHORT HvReadLdtr(VOID);
USHORT HvReadTr(VOID);
VOID HvStoreGdtr(_Out_ PHV_DESCRIPTOR_TABLE_REGISTER Gdtr);
VOID HvStoreIdtr(_Out_ PHV_DESCRIPTOR_TABLE_REGISTER Idtr);
