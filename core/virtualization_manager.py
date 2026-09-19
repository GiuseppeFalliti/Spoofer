import ctypes
import json
import os
import re
import struct
import subprocess
import sys
import winreg
from dataclasses import dataclass
from typing import Optional

import win32con
import win32file


BOOT_DESCRIPTION = "Windows - HWID VT-x Runtime"
RUNONCE_NAME = "HWIDSpooferVtxResume"
SERVICE_NAME = "HWIDVirtualizationDriver"
DEVICE_PATH = r"\\.\HwidSpoofer"

IOCTL_CHECK_VTX_SUPPORT = 0x80002018

CREATE_NO_WINDOW = 0x08000000
STATE_DIR = os.path.join(
    os.environ.get("PROGRAMDATA", os.path.expanduser("~")),
    "HWIDSpoofer",
)
STATE_FILE = os.path.join(STATE_DIR, "vtx_boot_state.json")


@dataclass
class VtxCapabilities:
    vtx_supported: bool
    ept_supported: bool
    vmx_blocked: bool
    hypervisor_present: bool
    processor_count: int


class VirtualizationManager:
    """Gestisce il boot one-shot usato esclusivamente dal laboratorio VT-x/EPT.

    Il boot Windows normale non viene modificato. Viene creata una copia della
    voce corrente con hypervisorlaunchtype=off e usata solo tramite
    BCDEdit /bootsequence per il riavvio successivo.
    """

    def __init__(self) -> None:
        os.makedirs(STATE_DIR, exist_ok=True)

    @staticmethod
    def _run(
        args,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if check and completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                f"Comando fallito ({completed.returncode}): "
                f"{subprocess.list2cmdline(args)}"
                + (f"\n{details}" if details else "")
            )
        return completed

    @staticmethod
    def is_admin() -> bool:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    @staticmethod
    def is_hypervisor_present() -> bool:
        """Legge Win32_ComputerSystem.HypervisorPresent senza dipendere dal driver."""
        ps = (
            "$v=(Get-CimInstance Win32_ComputerSystem).HypervisorPresent;"
            "if($v){'1'}else{'0'}"
        )
        result = VirtualizationManager._run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps,
            ]
        )
        return result.stdout.strip().splitlines()[-1:] == ["1"]

    @staticmethod
    def is_vbs_managed_by_policy() -> bool:
        """Non modifica ambienti in cui VBS e' imposto tramite Windows policy."""
        policy_paths = (
            r"SOFTWARE\Policies\Microsoft\Windows\DeviceGuard",
            r"SOFTWARE\Policies\Microsoft\Windows\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity",
        )
        interesting_values = (
            "EnableVirtualizationBasedSecurity",
            "HypervisorEnforcedCodeIntegrity",
            "Enabled",
        )

        for path in policy_paths:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                    for value_name in interesting_values:
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except FileNotFoundError:
                            continue
                        if isinstance(value, int) and value != 0:
                            return True
            except FileNotFoundError:
                continue
            except OSError:
                continue

        return False

    @staticmethod
    def bitlocker_protection_enabled() -> Optional[bool]:
        """Best effort: non sospende BitLocker e non ne cambia la configurazione."""
        ps = (
            "try {"
            "$v=Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop;"
            "if($v.ProtectionStatus -eq 'On' -or [int]$v.ProtectionStatus -eq 1){'1'}else{'0'}"
            "} catch {'?'}"
        )
        try:
            result = VirtualizationManager._run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    ps,
                ],
                check=False,
            )
            output = result.stdout.strip().splitlines()
            if not output:
                return None
            if output[-1] == "1":
                return True
            if output[-1] == "0":
                return False
        except Exception:
            pass
        return None

    @staticmethod
    def _resume_command() -> str:
        if getattr(sys, "frozen", False):
            parts = [sys.executable, "--resume-vtx-lab"]
        else:
            main_path = os.path.abspath(sys.argv[0])
            parts = [sys.executable, main_path, "--resume-vtx-lab"]
        return subprocess.list2cmdline(parts)

    @staticmethod
    def _set_runonce(command_line: str) -> None:
        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                RUNONCE_NAME,
                0,
                winreg.REG_SZ,
                command_line,
            )

    @staticmethod
    def _clear_runonce() -> None:
        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                try:
                    winreg.DeleteValue(key, RUNONCE_NAME)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @staticmethod
    def _save_state(state: dict) -> None:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
        os.replace(tmp_path, STATE_FILE)

    @staticmethod
    def load_state() -> Optional[dict]:
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            if isinstance(state, dict):
                return state
        except (FileNotFoundError, OSError, ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _delete_state() -> None:
        try:
            os.remove(STATE_FILE)
        except FileNotFoundError:
            pass

    @staticmethod
    def _delete_boot_entry(guid: Optional[str]) -> None:
        if not guid:
            return
        VirtualizationManager._run(
            ["bcdedit.exe", "/delete", guid],
            check=False,
        )

    def cleanup_pending_state(self) -> None:
        state = self.load_state()
        self._clear_runonce()
        if state:
            self._delete_boot_entry(state.get("boot_guid"))
        self._delete_state()

    def prepare_one_shot_lab_boot(self) -> str:
        if not self.is_admin():
            raise PermissionError("Sono necessari privilegi di amministratore.")

        if self.is_vbs_managed_by_policy():
            raise PermissionError(
                "VBS risulta imposto tramite criteri di Windows. "
                "La modalita' VT-x Lab non modifica o aggira policy gestite."
            )

        stale = self.load_state()
        if stale:
            self._delete_boot_entry(stale.get("boot_guid"))
            self._clear_runonce()
            self._delete_state()

        created_guid = None
        try:
            copy_result = self._run(
                [
                    "bcdedit.exe",
                    "/copy",
                    "{current}",
                    "/d",
                    BOOT_DESCRIPTION,
                ]
            )
            text = (copy_result.stdout or "") + "\n" + (copy_result.stderr or "")
            match = re.search(
                r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}",
                text,
            )
            if not match:
                raise RuntimeError(
                    "BCDEdit ha creato la voce ma non e' stato possibile "
                    "ricavarne il GUID."
                )

            created_guid = match.group(0)

            self._run(
                [
                    "bcdedit.exe",
                    "/set",
                    created_guid,
                    "hypervisorlaunchtype",
                    "off",
                ]
            )

            # /bootsequence non cambia il boot predefinito: vale soltanto per
            # il riavvio successivo.
            self._run(
                [
                    "bcdedit.exe",
                    "/bootsequence",
                    created_guid,
                ]
            )

            resume_command = self._resume_command()
            self._set_runonce(resume_command)

            self._save_state(
                {
                    "version": 1,
                    "phase": "prepared",
                    "boot_guid": created_guid,
                    "resume_command": resume_command,
                }
            )

            return created_guid
        except Exception:
            self._clear_runonce()
            if created_guid:
                self._delete_boot_entry(created_guid)
            self._delete_state()
            raise

    @staticmethod
    def reboot_now() -> None:
        subprocess.Popen(
            ["shutdown.exe", "/r", "/t", "0"],
            creationflags=CREATE_NO_WINDOW,
        )

    @staticmethod
    def query_driver_capabilities() -> VtxCapabilities:
        handle = win32file.CreateFile(
            DEVICE_PATH,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        try:
            data = win32file.DeviceIoControl(
                handle,
                IOCTL_CHECK_VTX_SUPPORT,
                b"",
                8,
                None,
            )
        finally:
            win32file.CloseHandle(handle)

        vtx, ept, vmx_blocked, hypervisor, processor_count = struct.unpack(
            "<BBBBI",
            data,
        )
        return VtxCapabilities(
            vtx_supported=bool(vtx),
            ept_supported=bool(ept),
            vmx_blocked=bool(vmx_blocked),
            hypervisor_present=bool(hypervisor),
            processor_count=processor_count,
        )

    def finish_resume(self) -> VtxCapabilities:
        """Completa il resume: verifica il boot Lab, carica il driver e misura VMX/EPT."""
        state = self.load_state()

        if self.is_hypervisor_present():
            self.cleanup_pending_state()
            raise RuntimeError(
                "Il riavvio VT-x Lab non ha disattivato il Windows hypervisor. "
                "Nessuna configurazione di sicurezza e' stata forzata."
            )

        from core.driver_utils import load_driver

        if not load_driver(SERVICE_NAME):
            raise RuntimeError("Impossibile caricare il driver kernel.")

        capabilities = self.query_driver_capabilities()

        # Il boot one-shot e' gia' stato consumato. Prova anche a rimuovere
        # la voce copiata; se Windows non consente la rimozione della voce
        # corrente, restera' innocua e potra' essere rimossa al prossimo avvio.
        self._clear_runonce()
        if state:
            self._delete_boot_entry(state.get("boot_guid"))
        self._delete_state()

        return capabilities
