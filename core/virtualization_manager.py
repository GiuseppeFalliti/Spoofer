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
TASK_RESUME_NAME = "HWIDSpoofer-VtxResume"
TASK_CLEANUP_NAME = "HWIDSpoofer-VtxCleanup"
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
    def _self_command(flag: str) -> str:
        if getattr(sys, "frozen", False):
            parts = [sys.executable, flag]
        else:
            main_path = os.path.abspath(sys.argv[0])
            parts = [sys.executable, main_path, flag]
        return subprocess.list2cmdline(parts)

    @staticmethod
    def _schedule_logon_task(task_name: str, command_line: str) -> None:
        # /IT rende il task interattivo; /RL HIGHEST mantiene i privilegi
        # gia' autorizzati dall'utente durante la preparazione.
        VirtualizationManager._run(
            [
                "schtasks.exe",
                "/Create",
                "/SC",
                "ONLOGON",
                "/TN",
                task_name,
                "/TR",
                command_line,
                "/RL",
                "HIGHEST",
                "/IT",
                "/F",
            ]
        )

    @staticmethod
    def _delete_task(task_name: str) -> None:
        VirtualizationManager._run(
            [
                "schtasks.exe",
                "/Delete",
                "/TN",
                task_name,
                "/F",
            ],
            check=False,
        )

    @staticmethod
    def _clear_bootstrap_tasks() -> None:
        VirtualizationManager._delete_task(TASK_RESUME_NAME)
        VirtualizationManager._delete_task(TASK_CLEANUP_NAME)

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

    @staticmethod
    def _boot_entry_text(alias: str) -> str:
        result = VirtualizationManager._run(
            ["bcdedit.exe", "/enum", alias, "/v"],
            check=False,
        )
        return (result.stdout or "") + "\n" + (result.stderr or "")

    @staticmethod
    def _boot_guid(alias: str) -> Optional[str]:
        text = VirtualizationManager._boot_entry_text(alias)
        match = re.search(
            r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}",
            text,
        )
        return match.group(0) if match else None

    @staticmethod
    def current_boot_guid() -> Optional[str]:
        return VirtualizationManager._boot_guid("{current}")

    @staticmethod
    def default_boot_guid() -> Optional[str]:
        return VirtualizationManager._boot_guid("{default}")

    @staticmethod
    def current_boot_is_lab() -> bool:
        # Evita falsi positivi dovuti a GUID stale/duplicati: una sessione
        # viene considerata Lab solo se la voce {current} porta davvero la
        # descrizione che abbiamo assegnato alla copia BCD.
        text = VirtualizationManager._boot_entry_text("{current}")
        return BOOT_DESCRIPTION.lower() in text.lower()

    def is_current_lab_session(self) -> bool:
        state = self.load_state()
        if not state or not self.current_boot_is_lab():
            return False

        lab_guid = state.get("boot_guid")
        current_guid = self.current_boot_guid()

        # La descrizione e' il discriminante principale. Se entrambi i GUID
        # sono disponibili, richiedi anche la corrispondenza.
        if lab_guid and current_guid:
            return str(lab_guid).lower() == str(current_guid).lower()

        return True

    def return_to_normal_boot(self) -> str:
        """Imposta il prossimo boot sulla voce Windows originale/default."""
        state = self.load_state() or {}

        return_guid = state.get("return_boot_guid")
        if not return_guid:
            return_guid = self.default_boot_guid()

        if not return_guid:
            raise RuntimeError(
                "Impossibile determinare la voce Windows normale da usare "
                "per il prossimo avvio."
            )

        self._run(
            [
                "bcdedit.exe",
                "/bootsequence",
                return_guid,
            ]
        )

        state = dict(state)
        state["phase"] = "return_to_normal_pending"
        state["return_boot_guid"] = return_guid
        self._schedule_cleanup(state)
        return return_guid

    def _schedule_cleanup(self, state: dict) -> None:
        state = dict(state)
        state["phase"] = "cleanup_pending"
        cleanup_command = self._self_command("--cleanup-vtx-lab")
        state["cleanup_command"] = cleanup_command
        self._save_state(state)
        self._delete_task(TASK_RESUME_NAME)
        self._schedule_logon_task(TASK_CLEANUP_NAME, cleanup_command)

    def cleanup_after_lab_if_safe(self) -> bool:
        """Rimuove la voce Lab solo quando non e' la voce Windows corrente."""
        state = self.load_state()
        if not state:
            self._clear_bootstrap_tasks()
            return True

        lab_guid = state.get("boot_guid")
        current_guid = self.current_boot_guid()

        if self.current_boot_is_lab():
            # Siamo ancora avviati da una voce che porta realmente la
            # descrizione Lab. Non cancellare la voce BCD corrente.
            self._schedule_cleanup(state)
            return False

        self._clear_bootstrap_tasks()
        self._delete_boot_entry(lab_guid)
        self._delete_state()
        return True

    def prepare_one_shot_lab_boot(self) -> str:
        if not self.is_admin():
            raise PermissionError("Sono necessari privilegi di amministratore.")

        if self.is_vbs_managed_by_policy():
            raise PermissionError(
                "VBS risulta imposto tramite criteri di Windows. "
                "La modalita' VT-x Lab non modifica o aggira policy gestite."
            )

        stale = self.load_state()
        if stale and not self.cleanup_after_lab_if_safe():
            raise RuntimeError(
                "La sessione VT-x Lab precedente e' ancora attiva. "
                "Riavvia Windows normalmente prima di prepararne una nuova."
            )

        source_boot_guid = self.current_boot_guid()
        if not source_boot_guid:
            raise RuntimeError(
                "Impossibile determinare il GUID della voce Windows corrente."
            )

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

            # Windows espone VSM come opzione BCD distinta dall'hypervisor.
            # La disabilitiamo esclusivamente sulla copia one-shot del boot,
            # mai sulla voce Windows normale.
            self._run(
                [
                    "bcdedit.exe",
                    "/set",
                    created_guid,
                    "vsmlaunchtype",
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

            resume_command = self._self_command("--resume-vtx-lab")
            self._clear_bootstrap_tasks()
            self._schedule_logon_task(TASK_RESUME_NAME, resume_command)

            self._save_state(
                {
                    "version": 2,
                    "phase": "prepared",
                    "boot_guid": created_guid,
                    "return_boot_guid": source_boot_guid,
                    "resume_command": resume_command,
                }
            )

            return created_guid
        except Exception:
            self._clear_bootstrap_tasks()
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

    def finish_resume(self) -> Optional[VtxCapabilities]:
        """Completa un resume valido; None indica un resume stale/orfano."""
        state = self.load_state()
        self._delete_task(TASK_RESUME_NAME)

        # Un task rimasto da una vecchia build non deve mai far credere
        # all'app che Windows sia avviato nella Lab.
        if not state:
            self._clear_bootstrap_tasks()
            return None

        expected_guid = state.get("boot_guid")
        current_guid = self.current_boot_guid()

        # La descrizione reale della voce corrente e' il primo discriminante.
        # Se siamo su Windows normale, qualsiasi resume rimasto e' stale.
        if not self.current_boot_is_lab():
            self._clear_bootstrap_tasks()
            self._delete_boot_entry(expected_guid)
            self._delete_state()
            return None

        # Se la descrizione e' Lab ma il GUID noto non coincide, non eseguire
        # il driver: e' uno stato BCD ambiguo che va ripulito.
        if (
            expected_guid
            and current_guid
            and str(expected_guid).lower() != str(current_guid).lower()
        ):
            self._schedule_cleanup(state)
            raise RuntimeError(
                "La voce corrente e' una VT-x Lab, ma il suo GUID non "
                "corrisponde allo stato salvato. Riavvia nel Windows normale "
                "per completare la pulizia."
            )

        # Solo da qui sappiamo che {current} e' davvero una voce Lab.
        if self.is_hypervisor_present():
            self._schedule_cleanup(state)
            raise RuntimeError(
                "La voce VT-x Lab e' stata realmente avviata, ma il Windows "
                "hypervisor risulta ancora presente anche con "
                "hypervisorlaunchtype=off e vsmlaunchtype=off. Il sistema "
                "potrebbe avere VBS/Credential Guard con protezione "
                "firmware/UEFI oppure un'altra policy di piattaforma. "
                "Nessuna protezione firmware viene forzata o rimossa "
                "automaticamente."
            )

        from core.driver_utils import load_driver

        if not load_driver(SERVICE_NAME):
            raise RuntimeError("Impossibile caricare il driver kernel.")

        capabilities = self.query_driver_capabilities()

        state = dict(state)
        state["phase"] = "lab_active"
        self._schedule_cleanup(state)

        return capabilities
