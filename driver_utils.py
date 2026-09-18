import win32service
import win32file
import win32con
import pywintypes
import time


def load_driver(service_name: str, driver_path: str) -> bool:
    scm_handle = None
    svc_handle = None
    try:
        scm_handle = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
        svc_handle = win32service.CreateService(
            scm_handle, service_name, service_name,
            win32service.SERVICE_ALL_ACCESS,
            win32service.SERVICE_KERNEL_DRIVER,
            win32service.SERVICE_DEMAND_START,
            win32service.SERVICE_ERROR_IGNORE,
            driver_path, None, 0, None, None, None
        )
        win32service.StartService(svc_handle, [])
        print(f"[+] Driver '{service_name}' caricato e avviato.")
        return True
    except pywintypes.error as e:
        print(f"[-] Errore: {e}")
        return False
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
        svc_handle = win32service.OpenService(scm_handle, service_name, win32service.SERVICE_STOP | win32service.DELETE)
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
        print(f"[+] IOCTL 0x{ioctl_code:08X} inviato con successo a '{device_path}'.")
        return True, result
    except pywintypes.error as e:
        print(f"[-] Errore durante l'invio dell'IOCTL: {e}")
        return False, b''
    finally:
        if handle is not None:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
