"""
hwid_virtualization_driver.py

Equivalente Python didattico del driver C hwid_virtualization_driver.c.
Riproduce le strutture dati, la logica di dispatch IOCTL e il flusso di
hooking/unhooking a scopo di studio, simulando le chiamate kernel Windows
con funzioni fittizie.

ATTENZIONE: Questo codice è esclusivamente a scopo educativo e di ricerca.
Non esegue alcun hooking reale sul kernel.
"""

import struct
from dataclasses import dataclass, field
from typing import Callable, Optional

# ============================================================================
# Costanti e definizioni IOCTL (replica delle macro CTL_CODE)
# ============================================================================

FILE_DEVICE_HWID_SPOOFER = 0x8000
METHOD_BUFFERED = 0
FILE_ANY_ACCESS = 0

def ctl_code(device_type: int, function: int, method: int, access: int) -> int:
    """Calcola un IOCTL code con la stessa logica della macro CTL_CODE di Windows."""
    return (device_type << 16) | (access << 14) | (function << 2) | method

IOCTL_ENABLE_FIRMWARE_HOOK  = ctl_code(FILE_DEVICE_HWID_SPOOFER, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_DISABLE_FIRMWARE_HOOK = ctl_code(FILE_DEVICE_HWID_SPOOFER, 0x801, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_ENABLE_HAL_HOOK       = ctl_code(FILE_DEVICE_HWID_SPOOFER, 0x802, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_DISABLE_HAL_HOOK      = ctl_code(FILE_DEVICE_HWID_SPOOFER, 0x803, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_SET_SMBIOS_HOOK   = ctl_code(FILE_DEVICE_HWID_SPOOFER, 0x804, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_CLEAR_SMBIOS_HOOK = ctl_code(FILE_DEVICE_HWID_SPOOFER, 0x805, METHOD_BUFFERED, FILE_ANY_ACCESS)

# Codici NTSTATUS usati nel driver originale
STATUS_SUCCESS = 0x00000000
STATUS_NOT_IMPLEMENTED = 0xC0000002
STATUS_ALREADY_REGISTERED = 0xC0000071
STATUS_PROCEDURE_NOT_FOUND = 0xC000007A
STATUS_INVALID_DEVICE_REQUEST = 0xC0000010
STATUS_BUFFER_TOO_SMALL = 0xC0000023

# Costanti HAL
PCI_CONFIGURATION = 1  # BUS_DATA_TYPE per PCIConfiguration
TARGET_PCI_BUS = 0
TARGET_PCI_SLOT = 31

SYSTEM_FIRMWARE_TABLE_INFORMATION_CLASS = 76
RSMB_SIGNATURE = 0x424D5352  # 'RSMB' little-endian

# Dati di test personalizzati (0xDEADBEEF in little-endian)
TEST_BUS_DATA = struct.pack("<I", 0xDEADBEEF)


# ============================================================================
# Tipi funzione originali (simulazione dei typedef C)
# ============================================================================

# Nel driver C questi sono puntatori a funzione kernel.
# Qui li rappresentiamo come Callable opzionali.
FirmwareEnvVarFunc = Callable[[str, str, bytearray, int, int], int]
HalBusDataFunc = Callable[[int, int, int, bytearray, int, int], int]
NtQuerySystemInfoFunc = Callable[[int, bytearray, int, Optional[list]], int]

from smbios_type1 import build_raw_smbios_table


# ============================================================================
# Stato globale del driver (equivalente delle variabili globali C)
# ============================================================================

@dataclass
class DriverState:
    """Contiene tutto lo stato che nel driver C è rappresentato da variabili globali."""
    orig_firmware_func: Optional[FirmwareEnvVarFunc] = None
    orig_hal_func: Optional[HalBusDataFunc] = None
    orig_nt_query_sys_info: Optional[NtQuerySystemInfoFunc] = None

    firmware_trampoline: bytearray = field(default_factory=lambda: bytearray(16))
    hal_trampoline: bytearray = field(default_factory=lambda: bytearray(16))
    smbios_trampoline: bytearray = field(default_factory=lambda: bytearray(16))

    firmware_hook_installed: bool = False
    hal_hook_installed: bool = False
    smbios_hook_installed: bool = False

    spoofed_smbios_blob: bytes = b""

    device_created: bool = False
    symlink_created: bool = False


# Istanza globale (come g_DeviceObject / variabili globali nel C)
g_state = DriverState()


# ============================================================================
# Funzioni simulate del kernel (stub per MmGetSystemRoutineAddress)
# ============================================================================

def original_ex_get_firmware_env_var(
    variable_name: str, vendor_guid: str, value: bytearray,
    value_length: int, attributes: int
) -> int:
    """Simula ExGetFirmwareEnvironmentVariable originale."""
    print(f"  [Kernel] ExGetFirmwareEnvironmentVariable chiamata: var={variable_name}")
    return STATUS_SUCCESS


def original_hal_get_bus_data_by_offset(
    bus_data_type: int, bus_number: int, slot_number: int,
    buffer: bytearray, offset: int, length: int
) -> int:
    """Simula HalGetBusDataByOffset originale."""
    print(f"  [Kernel] HalGetBusDataByOffset chiamata: Bus={bus_number}, Slot={slot_number}")
    return 0

def original_nt_query_system_information(
    info_class: int, buffer: bytearray, length: int, return_length: Optional[list] = None
) -> int:
    print(f"  [Kernel] NtQuerySystemInformation chiamata: class={info_class}")
    if return_length is not None:
        return_length[0] = 0
    return STATUS_SUCCESS


def mm_get_system_routine_address(func_name: str) -> Optional[Callable]:
    """
    Simula MmGetSystemRoutineAddress.
    Risolve il nome della funzione e restituisce un puntatore (qui una callable).
    """
    routines = {
        "ExGetFirmwareEnvironmentVariable": original_ex_get_firmware_env_var,
        "HalGetBusDataByOffset": original_hal_get_bus_data_by_offset,
        "NtQuerySystemInformation": original_nt_query_system_information,
    }
    return routines.get(func_name)


# ============================================================================
# Funzioni Hookate (equivalenti di Hooked_ExGetFirmware... e Hooked_HalGet...)
# ============================================================================

def hooked_ex_get_firmware_environment_variable(
    variable_name: str, vendor_guid: str, value: bytearray,
    value_length: int, attributes: int
) -> int:
    """
    Equivalente di Hooked_ExGetFirmwareEnvironmentVariable.
    Intercetta la chiamata, stampa un log e passa alla funzione originale.
    """
    print("[Spoofer] Hooked_ExGetFirmwareEnvironmentVariable chiamato.")

    # Qui potresti inserire logica di spoofing per variabili specifiche

    if g_state.orig_firmware_func:
        return g_state.orig_firmware_func(
            variable_name, vendor_guid, value, value_length, attributes
        )
    return STATUS_NOT_IMPLEMENTED


def hooked_hal_get_bus_data_by_offset(
    bus_data_type: int, bus_number: int, slot_number: int,
    buffer: bytearray, offset: int, length: int
) -> int:
    """
    Equivalente di Hooked_HalGetBusDataByOffset.
    Intercetta solo le chiamate per PCI bus 0, slot 31.
    """
    if (bus_data_type == PCI_CONFIGURATION and
            bus_number == TARGET_PCI_BUS and
            slot_number == TARGET_PCI_SLOT):
        print(f"[Spoofer] Hooked_HalGetBusDataByOffset: intercettata richiesta "
              f"per Bus {bus_number}, Slot {slot_number}.")

        if buffer is not None and length >= len(TEST_BUS_DATA) and offset == 0:
            # RtlCopyMemory equivalente: copia i dati di test nel buffer
            buffer[:len(TEST_BUS_DATA)] = TEST_BUS_DATA
            return len(TEST_BUS_DATA)

    # Passa tutte le altre chiamate alla funzione originale
    if g_state.orig_hal_func:
        return g_state.orig_hal_func(
            bus_data_type, bus_number, slot_number, buffer, offset, length
        )
    return 0

def hooked_nt_query_system_information(
    info_class: int, buffer: bytearray, length: int, return_length: Optional[list] = None
) -> int:
    if not g_state.smbios_hook_installed:
        if g_state.orig_nt_query_sys_info:
            return g_state.orig_nt_query_sys_info(info_class, buffer, length, return_length)
        return STATUS_NOT_IMPLEMENTED

    if info_class == SYSTEM_FIRMWARE_TABLE_INFORMATION_CLASS:
        print("[Spoofer] Hooked_NtQuerySystemInformation: intercettata richiesta SystemFirmwareTableInformation.")
        header_size = 16
        if buffer is not None and length >= header_size:
            provider_sig = struct.unpack_from("<I", buffer, 0)[0]
            if provider_sig == RSMB_SIGNATURE:
                print("[Spoofer] Richiesta RSMB rilevata. Iniezione struttura SMBIOS Type 1 fittizia.")
                blob = g_state.spoofed_smbios_blob
                total_needed = header_size + len(blob)
                if length >= total_needed:
                    struct.pack_into("<I", buffer, 12, len(blob))
                    buffer[header_size:header_size + len(blob)] = blob
                    if return_length is not None:
                        return_length[0] = total_needed
                    return STATUS_SUCCESS
                else:
                    if return_length is not None:
                        return_length[0] = total_needed
                    return STATUS_BUFFER_TOO_SMALL

    if g_state.orig_nt_query_sys_info:
        return g_state.orig_nt_query_sys_info(info_class, buffer, length, return_length)
    return STATUS_NOT_IMPLEMENTED


def install_smbios_hook() -> int:
    if g_state.smbios_hook_installed:
        return STATUS_ALREADY_REGISTERED
    func = mm_get_system_routine_address("NtQuerySystemInformation")
    if func is None:
        return STATUS_PROCEDURE_NOT_FOUND
    g_state.orig_nt_query_sys_info = func
    g_state.spoofed_smbios_blob = build_raw_smbios_table()
    g_state.smbios_hook_installed = True
    print(f"[Spoofer] Hook SMBIOS RSMB installato. Blob: {len(g_state.spoofed_smbios_blob)} bytes.")
    return STATUS_SUCCESS


def remove_smbios_hook() -> int:
    if not g_state.smbios_hook_installed:
        return STATUS_SUCCESS
    g_state.smbios_hook_installed = False
    g_state.spoofed_smbios_blob = b""
    print("[Spoofer] Hook SMBIOS RSMB rimosso.")
    return STATUS_SUCCESS


# ============================================================================
# Gestione Installazione / Rimozione Hook
# ============================================================================

def install_firmware_hook() -> int:
    """Equivalente di InstallFirmwareHook."""
    if g_state.firmware_hook_installed:
        return STATUS_ALREADY_REGISTERED

    func = mm_get_system_routine_address("ExGetFirmwareEnvironmentVariable")
    if func is None:
        print("[Spoofer] Impossibile risolvere ExGetFirmwareEnvironmentVariable.")
        return STATUS_PROCEDURE_NOT_FOUND

    g_state.orig_firmware_func = func

    # TEORICO: Salva i primi N byte in firmware_trampoline
    # TEORICO: Scrivi un JMP verso hooked_ex_get_firmware_environment_variable

    g_state.firmware_hook_installed = True
    print("[Spoofer] Hook per ExGetFirmwareEnvironmentVariable installato.")
    return STATUS_SUCCESS


def remove_firmware_hook() -> int:
    """Equivalente di RemoveFirmwareHook."""
    if not g_state.firmware_hook_installed:
        return STATUS_SUCCESS

    # TEORICO: Ripristina i byte originali dal trampoline

    g_state.firmware_hook_installed = False
    print("[Spoofer] Hook per ExGetFirmwareEnvironmentVariable rimosso.")
    return STATUS_SUCCESS


def install_hal_hook() -> int:
    """Equivalente di InstallHalGetBusDataHook."""
    if g_state.hal_hook_installed:
        return STATUS_ALREADY_REGISTERED

    func = mm_get_system_routine_address("HalGetBusDataByOffset")
    if func is None:
        print("[Spoofer] Impossibile risolvere HalGetBusDataByOffset.")
        return STATUS_PROCEDURE_NOT_FOUND

    g_state.orig_hal_func = func

    # TEORICO: Salva i primi N byte in hal_trampoline
    # TEORICO: Scrivi un JMP verso hooked_hal_get_bus_data_by_offset

    g_state.hal_hook_installed = True
    print(f"[Spoofer] Hook per HalGetBusDataByOffset installato "
          f"(Target: Bus {TARGET_PCI_BUS}, Slot {TARGET_PCI_SLOT}).")
    return STATUS_SUCCESS


def remove_hal_hook() -> int:
    """Equivalente di RemoveHalGetBusDataHook."""
    if not g_state.hal_hook_installed:
        return STATUS_SUCCESS

    # TEORICO: Ripristina i byte originali dal trampoline

    g_state.hal_hook_installed = False
    print("[Spoofer] Hook per HalGetBusDataByOffset rimosso.")
    return STATUS_SUCCESS


# ============================================================================
# IRP Dispatch (equivalente di DriverDispatch e DriverCreateClose)
# ============================================================================

def driver_dispatch(ioctl_code: int) -> int:
    """
    Simula il dispatch degli IOCTL ricevuto dal driver tramite
    DeviceIoControl. Nel C questo avviene in DriverDispatch tramite
    IoGetCurrentIrpStackLocation.
    """
    handlers = {
        IOCTL_ENABLE_FIRMWARE_HOOK: install_firmware_hook,
        IOCTL_DISABLE_FIRMWARE_HOOK: remove_firmware_hook,
        IOCTL_ENABLE_HAL_HOOK: install_hal_hook,
        IOCTL_DISABLE_HAL_HOOK: remove_hal_hook,
        IOCTL_SET_SMBIOS_HOOK: install_smbios_hook,
        IOCTL_CLEAR_SMBIOS_HOOK: remove_smbios_hook,
    }

    handler = handlers.get(ioctl_code)
    if handler:
        return handler()

    print(f"[Spoofer] IOCTL sconosciuto: 0x{ioctl_code:08X}")
    return STATUS_INVALID_DEVICE_REQUEST


# ============================================================================
# Entry Point e Unload (equivalente di DriverEntry e DriverUnload)
# ============================================================================

def driver_unload():
    """Equivalente di DriverUnload."""
    remove_smbios_hook()
    remove_firmware_hook()
    remove_hal_hook()
    

    if g_state.symlink_created:
        print("[Spoofer] Symbolic link \\DosDevices\\HwidSpoofer eliminato.")
        g_state.symlink_created = False

    if g_state.device_created:
        print("[Spoofer] Device \\Device\\HwidSpoofer eliminato.")
        g_state.device_created = False

    print("[Spoofer] Driver scaricato correttamente.")


def driver_entry() -> int:
    """
    Equivalente di DriverEntry.
    Crea il device object e il symbolic link, registra le funzioni di dispatch.
    """
    dev_name = "\\Device\\HwidSpoofer"
    sym_link = "\\DosDevices\\HwidSpoofer"

    # Simula IoCreateDevice
    print(f"[Spoofer] Creazione device: {dev_name}")
    g_state.device_created = True

    # Simula IoCreateSymbolicLink
    print(f"[Spoofer] Creazione symbolic link: {sym_link}")
    g_state.symlink_created = True

    # Nel C qui si assegnano:
    # DriverObject->DriverUnload = DriverUnload
    # DriverObject->MajorFunction[IRP_MJ_CREATE] = DriverCreateClose
    # DriverObject->MajorFunction[IRP_MJ_CLOSE] = DriverCreateClose
    # DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = DriverDispatch

    print("[Spoofer] Driver caricato con successo. Pronto per ricevere IOCTL.")
    return STATUS_SUCCESS


# ============================================================================
# Main - Simulazione di un client che invia IOCTL al driver
# ============================================================================

def format_ntstatus(status: int) -> str:
    """Formatta un NTSTATUS in esadecimale leggibile."""
    return f"0x{status & 0xFFFFFFFF:08X}"


if __name__ == "__main__":
    print("=" * 60)
    print("  HWID Virtualization Driver - Simulazione Didattica Python")
    print("=" * 60)
    print()

    # 1. Carica il driver
    status = driver_entry()
    print(f"  -> Status: {format_ntstatus(status)}\n")

    # 2. Abilita hook firmware
    print(f"[Client] Invio IOCTL_ENABLE_FIRMWARE_HOOK (0x{IOCTL_ENABLE_FIRMWARE_HOOK:08X})")
    status = driver_dispatch(IOCTL_ENABLE_FIRMWARE_HOOK)
    print(f"  -> Status: {format_ntstatus(status)}\n")

    # 3. Abilita hook HAL
    print(f"[Client] Invio IOCTL_ENABLE_HAL_HOOK (0x{IOCTL_ENABLE_HAL_HOOK:08X})")
    status = driver_dispatch(IOCTL_ENABLE_HAL_HOOK)
    print(f"  -> Status: {format_ntstatus(status)}\n")

    print(f"[Client] Invio IOCTL_SET_SMBIOS_HOOK (0x{IOCTL_SET_SMBIOS_HOOK:08X})")
    status = driver_dispatch(IOCTL_SET_SMBIOS_HOOK)
    print(f"  -> Status: {format_ntstatus(status)}\n")

    print("[Test] Chiamata a hooked_nt_query_system_information (RSMB):")
    smbios_buf = bytearray(512)
    struct.pack_into("<I", smbios_buf, 0, RSMB_SIGNATURE)
    ret_len = [0]
    nt_status = hooked_nt_query_system_information(
        SYSTEM_FIRMWARE_TABLE_INFORMATION_CLASS, smbios_buf, len(smbios_buf), ret_len
    )
    print(f"  -> NTSTATUS: {format_ntstatus(nt_status)}")
    print(f"  -> ReturnLength: {ret_len[0]}")
    if nt_status == STATUS_SUCCESS and ret_len[0] > 16:
        table_data = smbios_buf[16:ret_len[0]]
        print(f"  -> SMBIOS Table ({len(table_data)} bytes): {table_data[:32].hex()}...")
    print()

    print(f"[Client] Invio IOCTL_CLEAR_SMBIOS_HOOK (0x{IOCTL_CLEAR_SMBIOS_HOOK:08X})")
    status = driver_dispatch(IOCTL_CLEAR_SMBIOS_HOOK)
    print(f"  -> Status: {format_ntstatus(status)}\n")

    # 4. Testa la funzione hookata del firmware
    print("[Test] Chiamata a hooked_ex_get_firmware_environment_variable:")
    result = hooked_ex_get_firmware_environment_variable(
        "SecureBoot", "{guid-test}", bytearray(256), 256, 0
    )
    print(f"  -> Result: {format_ntstatus(result)}\n")

    # 5. Testa la funzione hookata HAL (target: bus 0, slot 31)
    print("[Test] Chiamata a hooked_hal_get_bus_data_by_offset (target):")
    buf = bytearray(64)
    bytes_read = hooked_hal_get_bus_data_by_offset(
        PCI_CONFIGURATION, TARGET_PCI_BUS, TARGET_PCI_SLOT, buf, 0, 64
    )
    if bytes_read > 0:
        data = struct.unpack("<I", buf[:4])[0]
        print(f"  -> Bytes letti: {bytes_read}, Data: 0x{data:08X}\n")

    # 6. Testa la funzione hookata HAL (non-target: bus 1, slot 0)
    print("[Test] Chiamata a hooked_hal_get_bus_data_by_offset (non-target):")
    bytes_read = hooked_hal_get_bus_data_by_offset(
        PCI_CONFIGURATION, 1, 0, buf, 0, 64
    )
    print(f"  -> Bytes letti: {bytes_read}\n")

    # 7. Disabilita gli hook
    print(f"[Client] Invio IOCTL_DISABLE_FIRMWARE_HOOK (0x{IOCTL_DISABLE_FIRMWARE_HOOK:08X})")
    status = driver_dispatch(IOCTL_DISABLE_FIRMWARE_HOOK)
    print(f"  -> Status: {format_ntstatus(status)}\n")

    print(f"[Client] Invio IOCTL_DISABLE_HAL_HOOK (0x{IOCTL_DISABLE_HAL_HOOK:08X})")
    status = driver_dispatch(IOCTL_DISABLE_HAL_HOOK)
    print(f"  -> Status: {format_ntstatus(status)}\n")

    # 8. Scarica il driver
    driver_unload()
    print()
    print("=" * 60)

