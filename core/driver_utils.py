import sys
import os
import win32service
import win32file
import win32con
import pywintypes
import time
import hashlib
import shutil

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
DRIVER_FILENAME = "hwid_virtualization_driver.sys"
STABLE_DRIVER_DIR = os.path.join(
    os.environ.get("PROGRAMDATA", os.path.expanduser("~")),
    "HWIDSpoofer",
    "driver",
)

LEGACY_SERVICE_NAME = "HwidSpoofer"
DEVICE_PATH = r"\\.\HwidSpoofer"


def _deploy_embedded_driver(source_path: str) -> str:
    """Copia il driver PyInstaller in un percorso stabile e versionato.

    Un eseguibile --onefile estrae le risorse in una directory _MEI temporanea.
    Un kernel driver non deve dipendere dalla vita di quella directory.
    """
    if not hasattr(sys, "_MEIPASS"):
        return source_path

    hasher = hashlib.sha256()
    with open(source_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)

    digest = hasher.hexdigest()[:16]
    os.makedirs(STABLE_DRIVER_DIR, exist_ok=True)

    target_path = os.path.join(
        STABLE_DRIVER_DIR,
        f"hwid_virtualization_driver_{digest}.sys",
    )

    if not os.path.isfile(target_path):
        shutil.copy2(source_path, target_path)

    return target_path


def get_resource_path(relative_path: str) -> str:
    """Ottiene il percorso assoluto di una risorsa, funzionante sia in sviluppo che in un eseguibile PyInstaller (OneFile)."""
    
    # Se l'app è stata compilata con PyInstaller --onefile, sys._MEIPASS contiene la cartella temporanea estratta
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        # In sviluppo driver_utils.py si trova in core/, mentre il .sys è
        # nella radice del progetto.
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    return os.path.join(base_path, relative_path)



def is_service_running(service_name: str) -> bool:
    scm_handle = None
    svc_handle = None
    try:
        scm_handle = win32service.OpenSCManager(
            None,
            None,
            win32service.SC_MANAGER_CONNECT,
        )
        svc_handle = win32service.OpenService(
            scm_handle,
            service_name,
            win32service.SERVICE_QUERY_STATUS,
        )
        status = win32service.QueryServiceStatus(svc_handle)
        return status[1] == win32service.SERVICE_RUNNING
    except pywintypes.error:
        return False
    finally:
        if svc_handle:
            try:
                win32service.CloseServiceHandle(svc_handle)
            except Exception:
                pass
        if scm_handle:
            try:
                win32service.CloseServiceHandle(scm_handle)
            except Exception:
                pass


def is_device_available(device_path: str = DEVICE_PATH) -> bool:
    handle = None
    try:
        handle = win32file.CreateFile(
            device_path,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        return True
    except pywintypes.error:
        return False
    finally:
        if handle is not None:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass


def _cleanup_legacy_service() -> None:
    """Rimuove il vecchio servizio HwidSpoofer se appartiene a questa app."""
    scm_handle = None
    svc_handle = None
    try:
        scm_handle = win32service.OpenSCManager(
            None,
            None,
            win32service.SC_MANAGER_ALL_ACCESS,
        )
        try:
            svc_handle = win32service.OpenService(
                scm_handle,
                LEGACY_SERVICE_NAME,
                win32service.SERVICE_ALL_ACCESS,
            )
        except pywintypes.error as e:
            if e.winerror == 1060:
                return
            raise

        try:
            config = win32service.QueryServiceConfig(svc_handle)
            image_path = str(config[3] or "")
        except Exception:
            image_path = ""

        if "hwid_virtualization_driver" not in image_path.lower():
            return

        try:
            win32service.ControlService(
                svc_handle,
                win32service.SERVICE_CONTROL_STOP,
            )
        except pywintypes.error as e:
            if e.winerror not in (1062, 1052):
                raise

        for _ in range(20):
            try:
                status = win32service.QueryServiceStatus(svc_handle)
                if status[1] == win32service.SERVICE_STOPPED:
                    break
            except Exception:
                break
            time.sleep(0.1)

        try:
            win32service.DeleteService(svc_handle)
        except pywintypes.error as e:
            if e.winerror not in (1060, 1072):
                raise
    finally:
        if svc_handle:
            try:
                win32service.CloseServiceHandle(svc_handle)
            except Exception:
                pass
        if scm_handle:
            try:
                win32service.CloseServiceHandle(scm_handle)
            except Exception:
                pass


def load_driver(service_name: str, driver_path: str = DRIVER_FILENAME) -> bool:
    """Registra e avvia un driver kernel tramite il Service Control Manager.

    Il parametro ``driver_path`` può essere:
    - Un percorso assoluto (es. ``C:\\drivers\\mio.sys``) → usato così com'è.
    - Un percorso relativo o solo il nome file (es. ``hwid_virtualization_driver.sys``)
      → risolto tramite :func:`get_resource_path`.
    """
    if not os.path.isabs(driver_path):
        driver_path = get_resource_path(driver_path)

    if not os.path.isfile(driver_path):
        raise FileNotFoundError(
            f"File driver non trovato: '{driver_path}'\n\n"
            f"Assicurati che il file '{os.path.basename(driver_path)}' sia incluso "
            "nella build o presente nel progetto."
        )

    driver_path = _deploy_embedded_driver(driver_path)

    # Evita conflitti con il vecchio servizio HwidSpoofer che esponeva
    # lo stesso device/symbolic link.
    if service_name != LEGACY_SERVICE_NAME:
        _cleanup_legacy_service()

    scm_handle = None
    svc_handle = None
    try:
        scm_handle = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
        try:
            svc_handle = win32service.CreateService(
                scm_handle, service_name, service_name,
                win32service.SERVICE_ALL_ACCESS,
                win32service.SERVICE_KERNEL_DRIVER,
                win32service.SERVICE_DEMAND_START,
                win32service.SERVICE_ERROR_IGNORE,
                driver_path, None, 0, None, None, None
            )
        except pywintypes.error as e:
            if e.winerror == 1073:  # ERROR_SERVICE_EXISTS
                svc_handle = win32service.OpenService(
                    scm_handle,
                    service_name,
                    win32service.SERVICE_ALL_ACCESS,
                )

                # Il path estratto da PyInstaller --onefile cambia a ogni
                # esecuzione. Aggiorna sempre ImagePath così il prossimo
                # avvio del servizio usa il .sys corrente.
                win32service.ChangeServiceConfig(
                    svc_handle,
                    win32service.SERVICE_NO_CHANGE,
                    win32service.SERVICE_NO_CHANGE,
                    win32service.SERVICE_NO_CHANGE,
                    driver_path,
                    None,
                    0,
                    None,
                    None,
                    None,
                    service_name,
                )
            else:
                raise

        try:
            win32service.StartService(svc_handle, [])
        except pywintypes.error as e:
            if e.winerror == 1056:  # ERROR_SERVICE_ALREADY_RUNNING
                pass
            else:
                raise

        print(f"[+] Driver '{service_name}' caricato e avviato da: {driver_path}")
        return True
    finally:
        if svc_handle:
            try: win32service.CloseServiceHandle(svc_handle)
            except: pass
        if scm_handle:
            try: win32service.CloseServiceHandle(scm_handle)
            except: pass




def unload_driver(service_name: str) -> bool:
    scm_handle = None
    svc_handle = None
    try:
        scm_handle = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
        delete_flag = getattr(win32con, "DELETE", 0x00010000)
        svc_handle = win32service.OpenService(scm_handle, service_name, win32service.SERVICE_STOP | delete_flag)
        try:
            win32service.ControlService(svc_handle, win32service.SERVICE_CONTROL_STOP)
            for _ in range(10):
                status = win32service.QueryServiceStatus(svc_handle)
                if status[1] == win32service.SERVICE_STOPPED:
                    break
                time.sleep(0.5)
        except pywintypes.error as e:
            if e.winerror != 1062:
                raise
        win32service.DeleteService(svc_handle)
        print(f"[+] Servizio '{service_name}' fermato ed eliminato.")
        return True
    except pywintypes.error as e:
        if e.winerror == 1060:
            print(f"[-] Il servizio '{service_name}' non esiste.")
        else:
            print(f"[-] Errore: {e}")
        return False
    finally:
        if svc_handle:
            try: win32service.CloseServiceHandle(svc_handle)
            except: pass
        if scm_handle:
            try: win32service.CloseServiceHandle(scm_handle)
            except: pass


def send_ioctl(device_path: str, ioctl_code: int, in_buffer: bytes = b'', out_buffer_size: int = 0) -> tuple:
    handle = None
    # Mantiene compatibile il ritorno (success, data), ma rende disponibile
    # alla GUI il codice Win32 dell'ultimo errore DeviceIoControl.
    send_ioctl.last_error = None
    try:
        handle = win32file.CreateFile(
            device_path,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None
        )
        result = win32file.DeviceIoControl(
            handle,
            ioctl_code,
            in_buffer,
            out_buffer_size,
            None
        )
        send_ioctl.last_error = 0
        print(f"[+] IOCTL 0x{ioctl_code:08X} inviato con successo a '{device_path}'.")
        return True, result
    except pywintypes.error as e:
        send_ioctl.last_error = getattr(e, "winerror", None)
        if send_ioctl.last_error is None and e.args:
            send_ioctl.last_error = e.args[0]
        print(f"[-] Errore durante l'invio dell'IOCTL: {e}")
        return False, b''
    finally:
        if handle is not None:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
