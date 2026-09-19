; vmexit.asm
;
; Lab-only diagnostic thunk.
;
; This routine demonstrates the x64 register-save layout used by a VM-exit
; entry path and calls HvHandleVmExit(). It intentionally returns to its
; caller instead of executing VMRESUME. The research branch never installs
; this function as VMCS HOST_RIP and never executes VMLAUNCH.
;

EXTERN HvHandleVmExit:PROC

.code

HvVmExitStub PROC
    ; Entry RSP is 8 mod 16. 0A8h is also 8 mod 16, so RSP is aligned
    ; for the call below and includes the required 20h shadow space.
    sub     rsp, 0A8h

    ; HV_GUEST_REGISTERS begins at rsp+20h.
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

    add     rsp, 0A8h
    ret
HvVmExitStub ENDP

END
