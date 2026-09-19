import ctypes
import json
import logging
import os
import re
import struct
import subprocess
import sys
import winreg
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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
LOG_DIR = os.path.join(STATE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "bootstrap.log")


class VtxState(Enum):
    NORMAL = "normal"
    LAB_PREPARED = "lab_prepared"
    LAB_RUNNING = "lab_running"
    RETURN_PENDING = "return_pending"
    CLEANUP_PENDING = "cleanup_pending"
    ERROR_STALE = "error_stale"


@dataclass
class VtxCapabilities:
    vtx_supported: bool
    ept_supported: bool
    vmx_blocked: bool
    hypervisor_present: bool
    processor_count: int


def _setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("HWIDSpoofer.VtxBootstrap")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        logger.addHandler(fh)
    return logger


log = _setup_logging()


class VirtualizationManager:
    def __init__(self) -> None:
        os.makedirs(STATE_DIR, exist_ok=True)
        log.info("VirtualizationManager initialized")

    @staticmethod
    def _run(args, *, check: bool = True) -> subprocess.CompletedProcess:
        log.debug("Running: %s", subprocess.list2cmdline(args))
        completed = subprocess.run(
            args, capture_output=True, text=True, errors="replace",
            creationflags=CREATE_NO_WINDOW, check=False,
        )
        if check and completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "").strip()
            msg = f"Command failed ({completed.returncode}): {subprocess.list2cmdline(args)}"
            if details:
                msg += f"\n{details}"
            log.error(msg)
            raise RuntimeError(msg)
        log.debug("Exit code: %d", completed.returncode)
        return completed

    @staticmethod
    def is_admin() -> bool:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    @staticmethod
    def is_hypervisor_present() -> bool:
        ps = "$v=(Get-CimInstance Win32_ComputerSystem).HypervisorPresent;if($v){'1'}else{'0'}"
        result = VirtualizationManager._run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ps],
            check=False,
        )
        lines = result.stdout.strip().splitlines()
        present = lines[-1:] == ["1"] if lines else False
        log.info("HypervisorPresent: %s", present)
        return present

    @staticmethod
    def is_vbs_managed_by_policy() -> bool:
        policy_paths = (
            r"SOFTWARE\Policies\Microsoft\Windows\DeviceGuard",
            r"SOFTWARE\Policies\Microsoft\Windows\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity",
        )
        interesting_values = ("EnableVirtualizationBasedSecurity", "HypervisorEnforcedCodeIntegrity", "Enabled")
        for path in policy_paths:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                    for value_name in interesting_values:
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except FileNotFoundError:
                            continue
                        if isinstance(value, int) and value != 0:
                            log.warning("VBS policy enforced at %s\\%s = %d", path, value_name, value)
                            return True
            except (FileNotFoundError, OSError):
                continue
        return False

    @staticmethod
    def bitlocker_protection_enabled() -> Optional[bool]:
        ps = "try{$v=Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop;if($v.ProtectionStatus -eq 'On' -or [int]$v.ProtectionStatus -eq 1){'1'}else{'0'}}catch{'?'}"
        try:
            result = VirtualizationManager._run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ps],
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
        log.info("Scheduling task %s: %s", task_name, command_line)
        VirtualizationManager._run([
            "schtasks.exe", "/Create", "/SC", "ONLOGON", "/TN", task_name,
            "/TR", command_line, "/RL", "HIGHEST", "/IT", "/F",
        ])

    @staticmethod
    def _delete_task(task_name: str) -> None:
        log.info("Deleting task %s", task_name)
        VirtualizationManager._run(
            ["schtasks.exe", "/Delete", "/TN", task_name, "/F"], check=False,
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
        log.info("State saved: phase=%s", state.get("phase"))

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
            log.info("State file deleted")
        except FileNotFoundError:
            pass

    @staticmethod
    def _delete_boot_entry(guid: Optional[str]) -> None:
        if not guid:
            return
        log.info("Deleting boot entry %s", guid)
        VirtualizationManager._run(["bcdedit.exe", "/delete", guid], check=False)

    @staticmethod
    def _boot_entry_text(alias: str) -> str:
        result = VirtualizationManager._run(["bcdedit.exe", "/enum", alias, "/v"], check=False)
        return (result.stdout or "") + "\n" + (result.stderr or "")

    @staticmethod
    def _boot_guid(alias: str) -> Optional[str]:
        text = VirtualizationManager._boot_entry_text(alias)
        match = re.search(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}", text)
        return match.group(0) if match else None

    @staticmethod
    def current_boot_guid() -> Optional[str]:
        return VirtualizationManager._boot_guid("{current}")

    @staticmethod
    def default_boot_guid() -> Optional[str]:
        return VirtualizationManager._boot_guid("{default}")

    @staticmethod
    def current_boot_is_lab() -> bool:
        text = VirtualizationManager._boot_entry_text("{current}")
        return BOOT_DESCRIPTION.lower() in text.lower()

    def get_effective_state(self) -> VtxState:
        """Determina lo stato reale incrociando JSON, BCD e runtime."""
        state = self.load_state()
        current_guid = self.current_boot_guid()
        is_lab_desc = self.current_boot_is_lab()
        hypervisor = self.is_hypervisor_present()

        log.info(
            "Effective state check: json_phase=%s, current_guid=%s, is_lab_desc=%s, hypervisor=%s",
            state.get("phase") if state else None, current_guid, is_lab_desc, hypervisor,
        )

        if not state:
            if is_lab_desc:
                return VtxState.ERROR_STALE
            return VtxState.NORMAL

        phase = state.get("phase")
        lab_guid = state.get("boot_guid")

        if phase == "prepared":
            if is_lab_desc and lab_guid and current_guid and str(lab_guid).lower() == str(current_guid).lower():
                if not hypervisor:
                    return VtxState.LAB_RUNNING
                return VtxState.ERROR_STALE
            if not is_lab_desc:
                return VtxState.ERROR_STALE
            return VtxState.LAB_PREPARED

        if phase == "lab_active":
            if is_lab_desc and not hypervisor:
                return VtxState.LAB_RUNNING
            if not is_lab_desc:
                return VtxState.CLEANUP_PENDING
            return VtxState.ERROR_STALE

        if phase == "return_to_normal_pending":
            if not is_lab_desc:
                return VtxState.CLEANUP_PENDING
            return VtxState.RETURN_PENDING

        if phase == "cleanup_pending":
            if not is_lab_desc:
                return VtxState.CLEANUP_PENDING
            return VtxState.ERROR_STALE

        return VtxState.ERROR_STALE

    def is_current_lab_session(self) -> bool:
        return self.get_effective_state() == VtxState.LAB_RUNNING

    def return_to_normal_boot(self) -> str:
        state = self.load_state() or {}
        return_guid = state.get("return_boot_guid") or self.default_boot_guid()
        if not return_guid:
            raise RuntimeError("Impossibile determinare la voce Windows normale.")

        log.info("Setting bootsequence to normal: %s", return_guid)
        self._run(["bcdedit.exe", "/bootsequence", return_guid])

        state = dict(state)
        state["phase"] = "return_to_normal_pending"
        state["return_boot_guid"] = return_guid
        self._save_state(state)
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
        state = self.load_state()
        if not state:
            self._clear_bootstrap_tasks()
            return True

        lab_guid = state.get("boot_guid")

        if self.current_boot_is_lab():
            log.warning("Still booted from Lab entry, rescheduling cleanup")
            self._schedule_cleanup(state)
            return False

        log.info("Safe to cleanup: removing lab entry %s", lab_guid)
        self._clear_bootstrap_tasks()
        self._delete_boot_entry(lab_guid)
        self._delete_state()
        return True

    def _verify_bcd_settings(self, guid: str) -> bool:
        """Verifica che hypervisorlaunchtype e vsmlaunchtype siano effettivamente Off."""
        text = self._boot_entry_text(guid)
        hv_off = "hypervisorlaunchtype    off" in text.lower().replace("\r", "")
        vsm_off = "vsmlaunchtype           off" in text.lower().replace("\r", "")
        log.info("BCD verify %s: hv_off=%s, vsm_off=%s", guid, hv_off, vsm_off)
        return hv_off and vsm_off

    def prepare_one_shot_lab_boot(self) -> str:
        if not self.is_admin():
            raise PermissionError("Sono necessari privilegi di amministratore.")

        if self.is_vbs_managed_by_policy():
            raise PermissionError("VBS risulta imposto tramite criteri di Windows.")

        effective = self.get_effective_state()
        log.info("Prepare requested, effective state: %s", effective.value)

        if effective == VtxState.ERROR_STALE:
            log.warning("Stale state detected, forcing cleanup before prepare")
            self.cleanup_after_lab_if_safe()
        elif effective not in (VtxState.NORMAL, VtxState.CLEANUP_PENDING):
            if not self.cleanup_after_lab_if_safe():
                raise RuntimeError(
                    "La sessione VT-x Lab precedente è ancora attiva. "
                    "Riavvia Windows normalmente prima di prepararne una nuova."
                )

        source_boot_guid = self.current_boot_guid()
        if not source_boot_guid:
            raise RuntimeError("Impossibile determinare il GUID della voce Windows corrente.")

        created_guid = None
        try:
            copy_result = self._run(["bcdedit.exe", "/copy", "{current}", "/d", BOOT_DESCRIPTION])
            text = (copy_result.stdout or "") + "\n" + (copy_result.stderr or "")
            match = re.search(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}", text)
            if not match:
                raise RuntimeError("BCDEdit ha creato la voce ma non è stato possibile ricavarne il GUID.")

            created_guid = match.group(0)
            log.info("Created lab boot entry: %s", created_guid)

            self._run(["bcdedit.exe", "/set", created_guid, "hypervisorlaunchtype", "off"])
            self._run(["bcdedit.exe", "/set", created_guid, "vsmlaunchtype", "off"])

            if not self._verify_bcd_settings(created_guid):
                raise RuntimeError(
                    "Le impostazioni BCD non sono state applicate correttamente. "
                    "Verifica che BCDEdit abbia i permessi necessari."
                )

            self._run(["bcdedit.exe", "/bootsequence", created_guid])
            log.info("Bootsequence set to %s", created_guid)

            resume_command = self._self_command("--resume-vtx-lab")
            self._clear_bootstrap_tasks()
            self._schedule_logon_task(TASK_RESUME_NAME, resume_command)

            self._save_state({
                "version": 3,
                "phase": "prepared",
                "boot_guid": created_guid,
                "return_boot_guid": source_boot_guid,
                "resume_command": resume_command,
                "created_at": datetime.now().isoformat(),
            })

            return created_guid
        except Exception:
            log.exception("Prepare failed, rolling back")
            self._clear_bootstrap_tasks()
            if created_guid:
                self._delete_boot_entry(created_guid)
            self._delete_state()
            raise

    @staticmethod
    def reboot_now() -> None:
        log.info("Initiating reboot")
        subprocess.Popen(["shutdown.exe", "/r", "/t", "0"], creationflags=CREATE_NO_WINDOW)

    @staticmethod
    def query_driver_capabilities() -> VtxCapabilities:
        handle = win32file.CreateFile(
            DEVICE_PATH,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None, win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None,
        )
        try:
            data = win32file.DeviceIoControl(handle, IOCTL_CHECK_VTX_SUPPORT, b"", 8, None)
        finally:
            win32file.CloseHandle(handle)

        vtx, ept, vmx_blocked, hypervisor, processor_count = struct.unpack("<BBBBI", data)
        caps = VtxCapabilities(
            vtx_supported=bool(vtx), ept_supported=bool(ept),
            vmx_blocked=bool(vmx_blocked), hypervisor_present=bool(hypervisor),
            processor_count=processor_count,
        )
        log.info("Driver capabilities: %s", caps)
        return caps

    def finish_resume(self) -> Optional[VtxCapabilities]:
        state = self.load_state()
        self._delete_task(TASK_RESUME_NAME)

        if not state:
            log.warning("Resume called but no state file found, treating as stale")
            self._clear_bootstrap_tasks()
            return None

        expected_guid = state.get("boot_guid")
        current_guid = self.current_boot_guid()

        log.info("Resume: expected=%s, current=%s, is_lab_desc=%s",
                 expected_guid, current_guid, self.current_boot_is_lab())

        if not self.current_boot_is_lab():
            log.info("Not booted from Lab entry, cleaning up stale state")
            self._clear_bootstrap_tasks()
            self._delete_boot_entry(expected_guid)
            self._delete_state()
            return None

        if expected_guid and current_guid and str(expected_guid).lower() != str(current_guid).lower():
            log.error("GUID mismatch: expected %s but current is %s", expected_guid, current_guid)
            self._schedule_cleanup(state)
            raise RuntimeError(
                "La voce corrente è una VT-x Lab, ma il suo GUID non corrisponde allo stato salvato. "
                "Riavvia nel Windows normale per completare la pulizia."
            )

        if self.is_hypervisor_present():
            log.error("Hypervisor still present despite Lab boot")
            diag = self.get_diagnostics()
            log.error("Diagnostics: %s", json.dumps(diag, indent=2))
            self._schedule_cleanup(state)
            raise RuntimeError(
                "La voce VT-x Lab è stata realmente avviata, ma il Windows hypervisor risulta ancora presente. "
                "Il sistema potrebbe avere VBS/Credential Guard con protezione firmware/UEFI. "
                "Consulta il log in %s per i dettagli diagnostici." % LOG_FILE
            )

        from core.driver_utils import load_driver
        if not load_driver(SERVICE_NAME):
            raise RuntimeError("Impossibile caricare il driver kernel.")

        capabilities = self.query_driver_capabilities()

        state = dict(state)
        state["phase"] = "lab_active"
        self._save_state(state)
        self._schedule_cleanup(state)

        return capabilities

    def get_diagnostics(self) -> dict:
        """Raccoglie informazioni diagnostiche complete senza modificare nulla."""
        diag = {
            "timestamp": datetime.now().isoformat(),
            "current_boot_guid": self.current_boot_guid(),
            "default_boot_guid": self.default_boot_guid(),
            "current_boot_is_lab": self.current_boot_is_lab(),
            "hypervisor_present": self.is_hypervisor_present(),
            "vbs_policy_managed": self.is_vbs_managed_by_policy(),
            "bitlocker": self.bitlocker_protection_enabled(),
            "state_file": self.load_state(),
            "effective_state": self.get_effective_state().value,
        }

        # DeviceGuard status
        try:
            ps = "Get-CimInstance Win32_DeviceGuard | Select-Object VirtualizationBasedSecurityStatus,SecurityServicesConfigured,SecurityServicesRunning | ConvertTo-Json"
            result = self._run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ps], check=False)
            diag["device_guard"] = json.loads(result.stdout) if result.stdout.strip() else None
        except Exception as e:
            diag["device_guard_error"] = str(e)

        # Lab BCD entry details
        state = self.load_state()
        if state and state.get("boot_guid"):
            diag["lab_bcd_entry"] = self._boot_entry_text(state["boot_guid"])

        # Scheduled tasks
        for task_name in (TASK_RESUME_NAME, TASK_CLEANUP_NAME):
            try:
                result = self._run(["schtasks.exe", "/Query", "/TN", task_name, "/V", "/FO", "LIST"], check=False)
                diag[f"task_{task_name}"] = result.stdout.strip() if result.returncode == 0 else "NOT_FOUND"
            except Exception as e:
                diag[f"task_{task_name}_error"] = str(e)

        # Driver/service status
        try:
            from core.driver_utils import is_service_running, is_device_available
            diag["service_running"] = is_service_running(SERVICE_NAME)
            diag["device_available"] = is_device_available()
        except Exception as e:
            diag["driver_check_error"] = str(e)

        log.info("Diagnostics collected: %s", json.dumps(diag, indent=2, default=str))
        return diag