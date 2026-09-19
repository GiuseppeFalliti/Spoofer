; vmexit.asm
;
; VT-x lab entry/exit glue.
; The guest is the currently running Windows context.  The VMCS HOST_RSP
; points at a private per-CPU nonpaged stack and HOST_RIP points here.
;
; The stop path is entered only through the internal VMCALL issued by
; HvStopCurrentProcessor while KeIpiGenericCall has every CPU in kernel mode.

OPTION CASEMAP:NONE

EXTERN HvHandleVmExit:PROC
EXTERN HvSetGuestLaunchState:PROC
EXTERN HvCompleteVmxOff:PROC
EXTERN HvRecordVmResumeFailure:PROC
EXTERN HvFatalVmInstructionFailure:PROC

PUBLIC HvVmExitStub
PUBLIC HvVmxLaunch
PUBLIC HvHypercall
PUBLIC HvReadEs
PUBLIC HvReadCs
PUBLIC HvReadSs
PUBLIC HvReadDs
PUBLIC HvReadFs
PUBLIC HvReadGs
PUBLIC HvReadLdtr
PUBLIC HvReadTr
PUBLIC HvStoreGdtr
PUBLIC HvStoreIdtr

.code

; ULONG HvVmxLaunch(void)
;
; At function entry [rsp] is the return address back into
; HvStartCurrentProcessor.  Use that exact stack pointer as the initial guest
; RSP and resume at HvVmxLaunchGuestResume after successful VMLAUNCH.
HvVmxLaunch PROC
    sub     rsp, 028h

    lea     rcx, [rsp+028h]
    lea     rdx, HvVmxLaunchGuestResume
    call    HvSetGuestLaunchState

    add     rsp, 028h

    test    eax, eax
    jnz     HvVmxLaunchPrepareFailed

    vmlaunch

    ; VMLAUNCH returns only on VMfailInvalid/VMfailValid.
    jc      HvVmxLaunchInvalid
    jz      HvVmxLaunchValid

    mov     eax, 3
    ret

HvVmxLaunchInvalid:
    mov     eax, 1
    ret

HvVmxLaunchValid:
    mov     eax, 2
    ret

HvVmxLaunchPrepareFailed:
    mov     eax, 4
    ret

HvVmxLaunchGuestResume:
    xor     eax, eax
    ret
HvVmxLaunch ENDP


; ULONG64 HvHypercall(ULONG64 Operation)
;
; RAX carries a private signature, R10 the operation.  Both are volatile in
; the Windows x64 ABI.  HvHandleVmExit writes the NTSTATUS result into the
; saved guest RAX before VMRESUME.
HvHypercall PROC
    mov     r10, rcx
    mov     rax, 48564C414248564Dh
    vmcall
    ret
HvHypercall ENDP


; HOST_RSP is configured 16-byte aligned.  0D0h is a multiple of 16, so the
; stack stays correctly aligned for calls into C.  The first 20h bytes are
; Windows x64 shadow space; HV_GUEST_REGISTERS starts at rsp+20h.
HvVmExitStub PROC
    sub     rsp, 0D0h

    mov     [rsp+020h], r15
    mov     [rsp+028h], r14
    mov     [rsp+030h], r13
    mov     [rsp+038h], r12
    mov     [rsp+040h], r11
    mov     [rsp+048h], r10
    mov     [rsp+050h], r9
    mov     [rsp+058h], r8
    mov     [rsp+060h], rdi
    mov     [rsp+068h], rsi
    mov     [rsp+070h], rbp
    mov     [rsp+078h], rbx
    mov     [rsp+080h], rdx
    mov     [rsp+088h], rcx
    mov     [rsp+090h], rax

    lea     rcx, [rsp+020h]
    call    HvHandleVmExit

    cmp     eax, 0
    je      HvVmExitResume

    cmp     eax, 1
    je      HvVmExitTerminate

    ; Any unsupported/fatal condition is safer as an explicit hypervisor
    ; failure than silently resuming with a corrupted architectural state.
    mov     ecx, 3
    call    HvFatalVmInstructionFailure
    int     3

HvVmExitResume:
    mov     r15, [rsp+020h]
    mov     r14, [rsp+028h]
    mov     r13, [rsp+030h]
    mov     r12, [rsp+038h]
    mov     r11, [rsp+040h]
    mov     r10, [rsp+048h]
    mov     r9,  [rsp+050h]
    mov     r8,  [rsp+058h]
    mov     rdi, [rsp+060h]
    mov     rsi, [rsp+068h]
    mov     rbp, [rsp+070h]
    mov     rbx, [rsp+078h]
    mov     rdx, [rsp+080h]
    mov     rcx, [rsp+088h]
    mov     rax, [rsp+090h]

    add     rsp, 0D0h
    vmresume

    ; VMRESUME failed.  Re-open the frame so diagnostics can inspect the
    ; original guest state, then fail deterministically.
    sub     rsp, 0D0h
    call    HvRecordVmResumeFailure
    mov     ecx, 1
    call    HvFatalVmInstructionFailure
    int     3

HvVmExitTerminate:
    ; This path is used only by the controlled STOP hypercall while the guest
    ; is executing the kernel IPI callback.
    vmxoff
    jc      HvVmExitVmxoffFailure
    jz      HvVmExitVmxoffFailure

    call    HvCompleteVmxOff

    lea     rdx, [rsp+020h]

    ; Restore the guest control-register state before returning to native
    ; execution.  CR4.VMXE is an implementation detail of VMX root and must
    ; not remain set once VMXOFF has completed.
    mov     rax, [rdx+090h]
    mov     cr0, rax

    mov     rax, [rdx+0A0h]
    btr     rax, 13
    mov     cr4, rax

    mov     rax, [rdx+098h]
    mov     cr3, rax

    ; Create a tiny native-return frame below the guest RSP:
    ;   [0]  guest RFLAGS
    ;   [8]  original guest RAX
    ;   [16] guest RIP
    ; popfq/pop rax/ret restores everything while leaving RSP exactly equal
    ; to the VMCS guest RSP.
    mov     rax, [rdx+078h]
    sub     rax, 018h

    mov     rcx, [rdx+088h]
    mov     [rax+000h], rcx

    mov     rcx, [rdx+070h]
    mov     [rax+008h], rcx

    mov     rcx, [rdx+080h]
    mov     [rax+010h], rcx

    mov     r15, [rdx+000h]
    mov     r14, [rdx+008h]
    mov     r13, [rdx+010h]
    mov     r12, [rdx+018h]
    mov     r11, [rdx+020h]
    mov     r10, [rdx+028h]
    mov     r9,  [rdx+030h]
    mov     r8,  [rdx+038h]
    mov     rdi, [rdx+040h]
    mov     rsi, [rdx+048h]
    mov     rbp, [rdx+050h]
    mov     rbx, [rdx+058h]
    mov     rcx, [rdx+068h]
    mov     rdx, [rdx+060h]

    mov     rsp, rax
    popfq
    pop     rax
    ret

HvVmExitVmxoffFailure:
    mov     ecx, 2
    call    HvFatalVmInstructionFailure
    int     3
HvVmExitStub ENDP


HvReadEs PROC
    xor     eax, eax
    mov     ax, es
    ret
HvReadEs ENDP

HvReadCs PROC
    xor     eax, eax
    mov     ax, cs
    ret
HvReadCs ENDP

HvReadSs PROC
    xor     eax, eax
    mov     ax, ss
    ret
HvReadSs ENDP

HvReadDs PROC
    xor     eax, eax
    mov     ax, ds
    ret
HvReadDs ENDP

HvReadFs PROC
    xor     eax, eax
    mov     ax, fs
    ret
HvReadFs ENDP

HvReadGs PROC
    xor     eax, eax
    mov     ax, gs
    ret
HvReadGs ENDP

HvReadLdtr PROC
    xor     eax, eax
    sldt    ax
    ret
HvReadLdtr ENDP

HvReadTr PROC
    xor     eax, eax
    str     ax
    ret
HvReadTr ENDP

HvStoreGdtr PROC
    sgdt    [rcx]
    ret
HvStoreGdtr ENDP

HvStoreIdtr PROC
    sidt    [rcx]
    ret
HvStoreIdtr ENDP

END
