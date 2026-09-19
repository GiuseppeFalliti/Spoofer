"""
hwid_virtualization_driver.py

Simulazione user-mode della logica di un driver kernel Windows per ricerca e test.

IMPORTANTE:
- NON è un driver .sys.
- NON modifica memoria kernel.
- NON installa hook reali.
- NON intercetta realmente chiamate di sistema.
- Usa ctypes soltanto per risolvere/esporre informazioni su API native user-mode,
  così da rendere la simulazione più vicina al flusso concettuale Windows.

La comunicazione "IOCTL" è simulata con una coda di comandi in memoria.
"""

from __future__ import annotations

import ctypes
import queue
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from smbios_type1 import build_raw_smbios_table


# ============================================================================
# IOCTL richiesti
# ============================================================================

IOCTL_SET_FIRMWARE_HOOK = 0x80002000
IOCTL_CLEAR_FIRMWARE_HOOK = 0x80002004

IOCTL_SET_HAL_HOOK = 0x80002008
IOCTL_CLEAR_HAL_HOOK = 0x8000200C

IOCTL_SET_SMBIOS_HOOK = 0x80002010
IOCTL_CLEAR_SMBIOS_HOOK = 0x80002014


# ============================================================================
# NTSTATUS simulati
# ============================================================================

STATUS_SUCCESS = 0x00000000
STATUS_NOT_IMPLEMENTED = 0xC0000002
STATUS_INVALID_PARAMETER = 0xC000000D
STATUS_INVALID_DEVICE_REQUEST = 0xC0000010
STATUS_BUFFER_TOO_SMALL = 0xC0000023
STATUS_ALREADY_REGISTERED = 0xC0000071
STATUS_PROCEDURE_NOT_FOUND = 0xC000007A


# ============================================================================
# Costanti della simulazione
# ============================================================================

# Valore richiesto nel prompt per la simulazione SMBIOS.
SYSTEM_INFORMATION_CLASS_SMBIOS = 0x0F

PCI_CONFIGURATION = 1
TARGET_PCI_BUS = 0
TARGET_PCI_SLOT = 31

DEVICE_NAME = r"\Device\HwidSpoofer"
DOS_DEVICE_NAME = r"\DosDevices\HwidSpoofer"
USER_DEVICE_PATH = r"\\.\HwidSpoofer"

# Buffer PCI fittizio (256 byte, simile a PCI config space base).
FAKE_PCI_CONFIG = bytearray(256)
struct.pack_into("<H", FAKE_PCI_CONFIG, 0x00, 0x1234)  # Vendor ID
struct.pack_into("<H", FAKE_PCI_CONFIG, 0x02, 0x5678)  # Device ID
struct.pack_into("<H", FAKE_PCI_CONFIG, 0x04, 0x0007)  # Command
struct.pack_into("<H", FAKE_PCI_CONFIG, 0x06, 0x0010)  # Status
FAKE_PCI_CONFIG[0x08] = 0x01  # Revision
FAKE_PCI_CONFIG[0x09] = 0x00  # Prog IF
FAKE_PCI_CONFIG[0x0A] = 0x00  # Subclass
FAKE_PCI_CONFIG[0x0B] = 0x02  # Class code (network controller, esempio)


FAKE_FIRMWARE_VALUES: dict[str, bytes] = {
    "SecureBoot": b"\x00",
    "SystemSerial": b"RESEARCH-SERIAL-0001\x00",
    "BoardSerial": b"RESEARCH-BOARD-0001\x00",
    "ProductName": b"VirtualResearchPlatform\x00",
}


# ============================================================================
# Tipi di callback simulati
# ============================================================================

FirmwareEnvVarFunc = Callable[[str, str, bytearray, int, int], int]
HalBusDataFunc = Callable[[int, int, int, bytearray, int, int], int]
NtQuerySystemInformationFunc = Callable[
    [int, bytearray, int, Optional[list[int]]], int
]


# ============================================================================
# Risoluzione API native con ctypes (solo introspezione user-mode)
# ============================================================================

class NativeApiResolver:
    """
    Risolve indirizzi di API native user-mode.

    Non modifica codice, non installa hook e non scrive memoria eseguibile.
    Serve soltanto a mostrare come un componente di ricerca potrebbe verificare
    la presenza di API native in un processo user-mode.
    """

    def __init__(self) -> None:
        self.available = False
        self.ntdll = None
        self.kernel32 = None

        if hasattr(ctypes, "WinDLL"):
            try:
                self.ntdll = ctypes.WinDLL("ntdll.dll")
                self.kernel32 = ctypes.WinDLL("kernel32.dll")
                self.available = True
            except OSError:
                self.available = False

    def resolve_ntdll_export(self, name: str) -> Optional[int]:
        if not self.available or self.ntdll is None:
            return None

        try:
            proc = getattr(self.ntdll, name)
            return ctypes.cast(proc, ctypes.c_void_p).value
        except AttributeError:
            return None


native_api = NativeApiResolver()


# ============================================================================
# Stato globale del driver simulato
# ============================================================================

@dataclass
class DriverState:
    loaded: bool = False
    device_created: bool = False
    symbolic_link_created: bool = False

    firmware_hook_installed: bool = False
    hal_hook_installed: bool = False
    smbios_hook_installed: bool = False

    orig_firmware_func: Optional[FirmwareEnvVarFunc] = None
    orig_hal_func: Optional[HalBusDataFunc] = None
    orig_nt_query_system_information: Optional[NtQuerySystemInformationFunc] = None

    spoofed_smbios_blob: bytes = b""

    command_count: int = 0
    last_ioctl: Optional[int] = None

    lock: threading.RLock = field(default_factory=threading.RLock)


g_state = DriverState()


# ============================================================================
# Implementazioni "originali" simulate
# ============================================================================

def original_ex_get_firmware_environment_variable(
    variable_name: str,
    vendor_guid: str,
    value: bytearray,
    value_length: int,
    attributes: int,
) -> int:
    print(
        "[Kernel-Sim] ExGetFirmwareEnvironmentVariable("
        f"name={variable_name!r}, guid={vendor_guid!r})"
    )
    return STATUS_NOT_IMPLEMENTED


def original_hal_get_bus_data_by_offset(
    bus_data_type: int,
    bus_number: int,
    slot_number: int,
    buffer: bytearray,
    offset: int,
    length: int,
) -> int:
    print(
        "[Kernel-Sim] HalGetBusDataByOffset("
        f"type={bus_data_type}, bus={bus_number}, slot={slot_number}, "
        f"offset={offset}, length={length})"
    )
    return 0


def original_nt_query_system_information(
    info_class: int,
    buffer: bytearray,
    length: int,
    return_length: Optional[list[int]] = None,
) -> int:
    print(
        "[Kernel-Sim] NtQuerySystemInformation("
        f"class=0x{info_class:02X}, length={length})"
    )

    if return_length is not None:
        return_length[:] = [0]

    return STATUS_NOT_IMPLEMENTED


def mm_get_system_routine_address(func_name: str) -> Optional[Callable]:
    """
    Simulazione di MmGetSystemRoutineAddress.

    Le funzioni kernel non vengono risolte realmente: la routine restituisce
    callback Python che fungono da implementazione originale simulata.
    """
    routines: dict[str, Callable] = {
        "ExGetFirmwareEnvironmentVariable":
            original_ex_get_firmware_environment_variable,
        "HalGetBusDataByOffset":
            original_hal_get_bus_data_by_offset,
        "NtQuerySystemInformation":
            original_nt_query_system_information,
    }
    return routines.get(func_name)


# ============================================================================
# Hook firmware simulato
# ============================================================================

def hooked_ex_get_firmware_environment_variable(
    variable_name: str,
    vendor_guid: str,
    value: bytearray,
    value_length: int,
    attributes: int,
) -> int:
    """
    Simula l'intercettazione di ExGetFirmwareEnvironmentVariable.

    Se l'hook è attivo e la variabile è presente nel dizionario fake,
    copia il valore fittizio nel buffer fornito dal chiamante.
    """
    with g_state.lock:
        enabled = g_state.firmware_hook_installed

    if enabled:
        fake = FAKE_FIRMWARE_VALUES.get(variable_name)

        if fake is not None:
            if value is None or value_length < len(fake):
                return STATUS_BUFFER_TOO_SMALL

            value[:len(fake)] = fake
            print(
                f"[Firmware Hook] {variable_name!r} -> "
                f"{fake!r} ({len(fake)} byte)"
            )
            return STATUS_SUCCESS

    if g_state.orig_firmware_func is not None:
        return g_state.orig_firmware_func(
            variable_name,
            vendor_guid,
            value,
            value_length,
            attributes,
        )

    return STATUS_NOT_IMPLEMENTED


# ============================================================================
# Hook HAL/PCI simulato
# ============================================================================

def hooked_hal_get_bus_data_by_offset(
    bus_data_type: int,
    bus_number: int,
    slot_number: int,
    buffer: bytearray,
    offset: int,
    length: int,
) -> int:
    """
    Simula l'intercettazione di HalGetBusDataByOffset.

    Per il target PCI configurato restituisce dati PCI fittizi.
    """
    with g_state.lock:
        enabled = g_state.hal_hook_installed

    target_match = (
        enabled
        and bus_data_type == PCI_CONFIGURATION
        and bus_number == TARGET_PCI_BUS
        and slot_number == TARGET_PCI_SLOT
    )

    if target_match:
        if offset < 0 or length < 0:
            return 0

        if offset >= len(FAKE_PCI_CONFIG):
            return 0

        end = min(offset + length, len(FAKE_PCI_CONFIG))
        chunk = FAKE_PCI_CONFIG[offset:end]

        if buffer is None or len(buffer) < len(chunk):
            return 0

        buffer[:len(chunk)] = chunk

        print(
            "[HAL Hook] restituiti dati PCI fittizi: "
            f"bus={bus_number}, slot={slot_number}, "
            f"offset={offset}, bytes={len(chunk)}"
        )
        return len(chunk)

    if g_state.orig_hal_func is not None:
        return g_state.orig_hal_func(
            bus_data_type,
            bus_number,
            slot_number,
            buffer,
            offset,
            length,
        )

    return 0


# ============================================================================
# Hook SMBIOS simulato
# ============================================================================

def hooked_nt_query_system_information(
    info_class: int,
    buffer: bytearray,
    length: int,
    return_length: Optional[list[int]] = None,
) -> int:
    """
    Simula l'intercettazione di NtQuerySystemInformation.

    Per SYSTEM_INFORMATION_CLASS_SMBIOS (0x0F, come richiesto dalla simulazione)
    restituisce direttamente il blob costruito da smbios_type1.py.

    Layout della risposta simulata:
        DWORD DataLength
        BYTE  Data[DataLength]
    """
    with g_state.lock:
        enabled = g_state.smbios_hook_installed
        blob = g_state.spoofed_smbios_blob

    if enabled and info_class == SYSTEM_INFORMATION_CLASS_SMBIOS:
        header_size = 4
        total_needed = header_size + len(blob)

        if return_length is not None:
            return_length[:] = [total_needed]

        if buffer is None or length < total_needed:
            return STATUS_BUFFER_TOO_SMALL

        struct.pack_into("<I", buffer, 0, len(blob))
        buffer[header_size:header_size + len(blob)] = blob

        print(
            "[SMBIOS Hook] restituito blob SMBIOS fittizio: "
            f"{len(blob)} byte"
        )
        return STATUS_SUCCESS

    if g_state.orig_nt_query_system_information is not None:
        return g_state.orig_nt_query_system_information(
            info_class,
            buffer,
            length,
            return_length,
        )

    return STATUS_NOT_IMPLEMENTED


# ============================================================================
# Installazione/rimozione hook simulati
# ============================================================================

def install_firmware_hook() -> int:
    with g_state.lock:
        if g_state.firmware_hook_installed:
            return STATUS_ALREADY_REGISTERED

        func = mm_get_system_routine_address(
            "ExGetFirmwareEnvironmentVariable"
        )
        if func is None:
            return STATUS_PROCEDURE_NOT_FOUND

        g_state.orig_firmware_func = func
        g_state.firmware_hook_installed = True

    print("[Driver] firmware hook simulato ATTIVO")
    return STATUS_SUCCESS


def remove_firmware_hook() -> int:
    with g_state.lock:
        g_state.firmware_hook_installed = False

    print("[Driver] firmware hook simulato DISATTIVO")
    return STATUS_SUCCESS


def install_hal_hook() -> int:
    with g_state.lock:
        if g_state.hal_hook_installed:
            return STATUS_ALREADY_REGISTERED

        func = mm_get_system_routine_address("HalGetBusDataByOffset")
        if func is None:
            return STATUS_PROCEDURE_NOT_FOUND

        g_state.orig_hal_func = func
        g_state.hal_hook_installed = True

    print("[Driver] HAL hook simulato ATTIVO")
    return STATUS_SUCCESS


def remove_hal_hook() -> int:
    with g_state.lock:
        g_state.hal_hook_installed = False

    print("[Driver] HAL hook simulato DISATTIVO")
    return STATUS_SUCCESS


def install_smbios_hook() -> int:
    with g_state.lock:
        if g_state.smbios_hook_installed:
            return STATUS_ALREADY_REGISTERED

        func = mm_get_system_routine_address("NtQuerySystemInformation")
        if func is None:
            return STATUS_PROCEDURE_NOT_FOUND

        g_state.orig_nt_query_system_information = func
        g_state.spoofed_smbios_blob = build_raw_smbios_table()
        g_state.smbios_hook_installed = True

        size = len(g_state.spoofed_smbios_blob)

    print(f"[Driver] SMBIOS hook simulato ATTIVO ({size} byte)")
    return STATUS_SUCCESS


def remove_smbios_hook() -> int:
    with g_state.lock:
        g_state.smbios_hook_installed = False
        g_state.spoofed_smbios_blob = b""

    print("[Driver] SMBIOS hook simulato DISATTIVO")
    return STATUS_SUCCESS


# ============================================================================
# Dispatcher IOCTL simulato
# ============================================================================

def driver_dispatch(ioctl_code: int) -> int:
    handlers: dict[int, Callable[[], int]] = {
        IOCTL_SET_FIRMWARE_HOOK: install_firmware_hook,
        IOCTL_CLEAR_FIRMWARE_HOOK: remove_firmware_hook,

        IOCTL_SET_HAL_HOOK: install_hal_hook,
        IOCTL_CLEAR_HAL_HOOK: remove_hal_hook,

        IOCTL_SET_SMBIOS_HOOK: install_smbios_hook,
        IOCTL_CLEAR_SMBIOS_HOOK: remove_smbios_hook,
    }

    with g_state.lock:
        if not g_state.loaded:
            return STATUS_INVALID_DEVICE_REQUEST

        g_state.command_count += 1
        g_state.last_ioctl = ioctl_code

    handler = handlers.get(ioctl_code)

    if handler is None:
        print(f"[Driver] IOCTL sconosciuto: 0x{ioctl_code:08X}")
        return STATUS_INVALID_DEVICE_REQUEST

    return handler()


# ============================================================================
# Canale user-mode <-> driver simulato
# ============================================================================

@dataclass
class IoctlRequest:
    code: int
    completed: threading.Event = field(default_factory=threading.Event)
    status: int = STATUS_NOT_IMPLEMENTED


class SimulatedDeviceChannel:
    """
    Simula una device queue che riceve DeviceIoControl da user-mode.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Optional[IoctlRequest]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="HwidSpooferIoctlWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)

        if self._thread:
            self._thread.join(timeout=2.0)

    def device_io_control(self, ioctl_code: int, timeout: float = 2.0) -> int:
        request = IoctlRequest(code=ioctl_code)
        self._queue.put(request)

        if not request.completed.wait(timeout):
            raise TimeoutError(
                f"Timeout IOCTL 0x{ioctl_code:08X}"
            )

        return request.status

    def _worker_loop(self) -> None:
        print(
            f"[Driver] loop IOCTL simulato in ascolto su {USER_DEVICE_PATH}"
        )

        while not self._stop_event.is_set():
            request = self._queue.get()

            if request is None:
                break

            try:
                request.status = driver_dispatch(request.code)
            except Exception as exc:
                print(f"[Driver] errore dispatch: {exc}")
                request.status = STATUS_INVALID_DEVICE_REQUEST
            finally:
                request.completed.set()

        print("[Driver] loop IOCTL simulato terminato")


device_channel = SimulatedDeviceChannel()


# ============================================================================
# DriverEntry / DriverUnload simulati
# ============================================================================

def driver_entry() -> int:
    with g_state.lock:
        if g_state.loaded:
            return STATUS_ALREADY_REGISTERED

        print(f"[DriverEntry] IoCreateDevice -> {DEVICE_NAME}")
        g_state.device_created = True

        print(
            "[DriverEntry] IoCreateSymbolicLink -> "
            f"{DOS_DEVICE_NAME}"
        )
        g_state.symbolic_link_created = True
        g_state.loaded = True

    if native_api.available:
        address = native_api.resolve_ntdll_export(
            "NtQuerySystemInformation"
        )

        if address:
            print(
                "[ctypes] NtQuerySystemInformation risolta in ntdll.dll "
                f"all'indirizzo 0x{address:X}"
            )
        else:
            print(
                "[ctypes] NtQuerySystemInformation non risolta"
            )
    else:
        print(
            "[ctypes] API native Windows non disponibili "
            "(piattaforma non Windows o DLL non caricabile)"
        )

    device_channel.start()

    print("[DriverEntry] driver simulato caricato")
    return STATUS_SUCCESS


def driver_unload() -> None:
    device_channel.stop()

    remove_smbios_hook()
    remove_hal_hook()
    remove_firmware_hook()

    with g_state.lock:
        if g_state.symbolic_link_created:
            print(
                "[DriverUnload] IoDeleteSymbolicLink -> "
                f"{DOS_DEVICE_NAME}"
            )
            g_state.symbolic_link_created = False

        if g_state.device_created:
            print(f"[DriverUnload] IoDeleteDevice -> {DEVICE_NAME}")
            g_state.device_created = False

        g_state.loaded = False

    print("[DriverUnload] driver simulato scaricato")


# ============================================================================
# Utility di test
# ============================================================================

def format_ntstatus(status: int) -> str:
    return f"0x{status & 0xFFFFFFFF:08X}"


def test_firmware_hook() -> None:
    output = bytearray(128)

    status = hooked_ex_get_firmware_environment_variable(
        "SystemSerial",
        "{00000000-0000-0000-0000-000000000000}",
        output,
        len(output),
        0,
    )

    print(
        "[Test Firmware] status="
        f"{format_ntstatus(status)}, "
        f"data={bytes(output).split(chr(0).encode())[0]!r}"
    )


def test_hal_hook() -> None:
    output = bytearray(64)

    bytes_read = hooked_hal_get_bus_data_by_offset(
        PCI_CONFIGURATION,
        TARGET_PCI_BUS,
        TARGET_PCI_SLOT,
        output,
        0,
        len(output),
    )

    print(
        f"[Test HAL] bytes={bytes_read}, "
        f"header={output[:16].hex(' ')}"
    )


def test_smbios_hook() -> None:
    # Prima richiesta: scopre la dimensione necessaria.
    needed = [0]

    status = hooked_nt_query_system_information(
        SYSTEM_INFORMATION_CLASS_SMBIOS,
        bytearray(),
        0,
        needed,
    )

    if status != STATUS_BUFFER_TOO_SMALL or not needed[0]:
        print(
            "[Test SMBIOS] query dimensione fallita: "
            f"{format_ntstatus(status)}"
        )
        return

    output = bytearray(needed[0])

    status = hooked_nt_query_system_information(
        SYSTEM_INFORMATION_CLASS_SMBIOS,
        output,
        len(output),
        needed,
    )

    if status != STATUS_SUCCESS:
        print(
            "[Test SMBIOS] query dati fallita: "
            f"{format_ntstatus(status)}"
        )
        return

    blob_length = struct.unpack_from("<I", output, 0)[0]
    blob = output[4:4 + blob_length]

    print(
        f"[Test SMBIOS] status={format_ntstatus(status)}, "
        f"blob={len(blob)} byte, "
        f"first32={blob[:32].hex(' ')}"
    )


def run_demo() -> None:
    print("=" * 72)
    print("HWID Virtualization Driver - simulazione Python")
    print("=" * 72)

    status = driver_entry()
    print(f"DriverEntry -> {format_ntstatus(status)}")

    commands = [
        IOCTL_SET_FIRMWARE_HOOK,
        IOCTL_SET_HAL_HOOK,
        IOCTL_SET_SMBIOS_HOOK,
    ]

    for code in commands:
        result = device_channel.device_io_control(code)
        print(
            f"DeviceIoControl(0x{code:08X}) -> "
            f"{format_ntstatus(result)}"
        )

    print()
    test_firmware_hook()
    test_hal_hook()
    test_smbios_hook()
    print()

    commands = [
        IOCTL_CLEAR_SMBIOS_HOOK,
        IOCTL_CLEAR_HAL_HOOK,
        IOCTL_CLEAR_FIRMWARE_HOOK,
    ]

    for code in commands:
        result = device_channel.device_io_control(code)
        print(
            f"DeviceIoControl(0x{code:08X}) -> "
            f"{format_ntstatus(result)}"
        )

    driver_unload()

if __name__ == "__main__":
    run_demo()
