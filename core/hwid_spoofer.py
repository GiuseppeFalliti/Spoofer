from datetime import datetime
import json
import os
import sys
import uuid
import random
import logging
import winreg
from .registry_utils import RegistryUtils

logger = logging.getLogger(__name__)


def get_app_data_dir() -> str:
    """Restituisce la cartella 'data/' scrivibile accanto all'eseguibile."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_app_root_dir() -> str:
    """Restituisce la cartella root dell'applicazione (accanto all'exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class HwidSpoofer:
    """Core class for Hardware ID spoofing operations on Windows."""

    def __init__(self):
        self.registry_utils = RegistryUtils()
        self.saved_hwids_file = os.path.join(get_app_data_dir(), "saved_hwids.json")
        self.config_file = os.path.join(get_app_root_dir(), "config.json")
        self.config = self.load_config()
        self._ensure_data_dir()


    def load_config(self):
        """Carica le impostazioni dal file di configurazione"""
        if not os.path.exists(self.config_file):
            return {
                "auto_save_originals": True,
                "backup_registry": True,
                "log_level": "INFO",
                "require_restart": True,
                "default_mac_prefix": "02",
                "hwid_components": {
                    "machine_guid": True,
                    "disk_serial": True,
                    "bios_uuid": True,
                    "motherboard_serial": True,
                    "processor_id": True
                }
            }
        
        try:
            with open(self.config_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading config: {e}")
            return {}

    def spoof_selected_hwids(self):
        """Esegue lo spoofing solo degli identificatori hardware selezionati nel file di configurazione"""
        results = {}
        components = self.config.get("hwid_components", {})
        
        if components.get("machine_guid", True):
            results["Machine GUID"] = self.spoof_machine_guid()
        
        if components.get("disk_serial", True):
            results["Disk Serial"] = self.spoof_disk_serial()
        
        if components.get("bios_uuid", True):
            results["BIOS UUID"] = self.spoof_bios_uuid()
        
        if components.get("motherboard_serial", True):
            results["Motherboard Serial"] = self.spoof_motherboard_serial()
        
        if components.get("processor_id", True):
            results["Processor ID"] = self.spoof_processor_id()
        
        logger.info("Selected HWID spoofing results:")
        for hwid, success in results.items():
            status = "Success" if success else "Failed"
            logger.info(f"{hwid}: {status}")
        
        return all(results.values())

    def _ensure_data_dir(self):
        data_dir = os.path.dirname(self.saved_hwids_file)
        os.makedirs(data_dir, exist_ok=True)

    def save_original_hwid(self, hwid_name, hwid_value):
        """Salva il valore originale di un identificatore hardware"""
        saved = self.load_saved_hwids()
        if hwid_name not in saved:
            saved[hwid_name] = {
                "original_value": hwid_value,
                "saved_at": datetime.now().isoformat()
            }
            self._write_saved_hwids(saved)
            logger.info(f"Saved original {hwid_name}: {hwid_value}")

    def load_saved_hwids(self):
        """Carica gli identificatori hardware salvati"""
        if not os.path.exists(self.saved_hwids_file):
            return {}
        try:
            with open(self.saved_hwids_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading saved HWIDs: {e}")
            return {}

    def _write_saved_hwids(self, data):
        """Scrive gli identificatori hardware salvati nel file"""
        try:
            with open(self.saved_hwids_file, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error(f"Error writing saved HWIDs: {e}")

    def restore_all_hwids(self):
        """Ripristina tutti gli identificatori hardware ai valori originali"""
        saved = self.load_saved_hwids()
        results = {}
        
        for hwid_name, hwid_data in saved.items():
            original_value = hwid_data.get("original_value")
            if original_value:
                if hwid_name == "Machine GUID":
                    results[hwid_name] = self._restore_machine_guid(original_value)
                elif hwid_name == "Disk Serial":
                    results[hwid_name] = self._restore_disk_serial(original_value)
                elif hwid_name == "BIOS UUID":
                    results[hwid_name] = self._restore_bios_uuid(original_value)
                elif hwid_name == "Motherboard Serial":
                    results[hwid_name] = self._restore_motherboard_serial(original_value)
                elif hwid_name == "Processor ID":
                    results[hwid_name] = self._restore_processor_id(original_value)
        
        logger.info("HWID restoration results:")
        for hwid, success in results.items():
            status = "Success" if success else "Failed"
            logger.info(f"{hwid}: {status}")
        
        return all(results.values())

    def _restore_machine_guid(self, original_value):
        """Ripristina il Machine GUID al valore originale"""
        try:
            key_path = r"SOFTWARE\Microsoft\Cryptography"
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE, 
                key_path, 
                "MachineGuid", 
                original_value
            )
            
            if success:
                logger.info(f"Machine GUID restored to: {original_value}")
            
            return success
        except Exception as e:
            logger.error(f"Error restoring Machine GUID: {e}")
            return False

    def _restore_disk_serial(self, original_value):
        """Ripristina il numero di serie del disco al valore originale"""
        try:
            key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "VolumeSerialNumber",
                original_value
            )
            
            if success:
                logger.info(f"Disk serial restored to: {original_value}")
            
            return success
        except Exception as e:
            logger.error(f"Error restoring disk serial: {e}")
            return False

    def _restore_bios_uuid(self, original_value):
        """Ripristina l'UUID del BIOS al valore originale"""
        try:
            key_path = r"SYSTEM\HardwareConfig\Current"
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "BaseBoardUUID",
                original_value
            )
            
            if success:
                logger.info(f"BIOS UUID restored to: {original_value}")
            
            return success
        except Exception as e:
            logger.error(f"Error restoring BIOS UUID: {e}")
            return False

    def _restore_motherboard_serial(self, original_value):
        """Ripristina il numero di serie della scheda madre al valore originale"""
        try:
            key_path = r"SYSTEM\HardwareConfig\Current"
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "BaseBoardSerialNumber",
                original_value
            )
            
            if success:
                logger.info(f"Motherboard serial restored to: {original_value}")
            
            return success
        except Exception as e:
            logger.error(f"Error restoring motherboard serial: {e}")
            return False

    def _restore_processor_id(self, original_value):
        """Ripristina l'ID del processore al valore originale"""
        try:
            key_path = r"SYSTEM\HardwareConfig\Current"
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "ProcessorID",
                original_value
            )
            
            if success:
                logger.info(f"Processor ID restored to: {original_value}")
            
            return success
        except Exception as e:
            logger.error(f"Error restoring processor ID: {e}")
            return False

    @staticmethod
    def generate_random_uuid():
        """Genera un UUID casuale nel formato standard"""
        return str(uuid.uuid4()).upper()

    @staticmethod
    def generate_random_serial(length=12):
        """Genera un numero di serie casuale"""
        return ''.join(random.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(length))

    def spoof_machine_guid(self):
        """Modifica il Machine GUID nel registro di sistema"""
        try:
            # Genera un nuovo GUID
            new_guid = self.generate_random_uuid()
            
            # Percorso nel registro di sistema
            key_path = r"SOFTWARE\Microsoft\Cryptography"
            
            # Modifica il valore MachineGuid
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE, 
                key_path, 
                "MachineGuid", 
                "{" + new_guid + "}"
            )
            
            if success:
                logger.info(f"Machine GUID changed to: {new_guid}")
            
            return success
        except Exception as e:
            logger.error(f"Error changing Machine GUID: {e}")
            return False

    def spoof_disk_serial(self):
        """Simula la modifica del numero di serie del disco"""
        try:
            # Genera un numero di serie casuale
            new_serial = self.generate_random_serial(10)
            
            # Percorso nel registro di sistema per il volume di sistema
            key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            
            # Modifica il valore del numero di serie
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "VolumeSerialNumber",
                new_serial
            )
            
            if success:
                logger.info(f"Disk serial changed to: {new_serial}")
            
            return success
        except Exception as e:
            logger.error(f"Error changing disk serial: {e}")
            return False

    def spoof_bios_uuid(self):
        """Simula la modifica dell'UUID del BIOS"""
        try:
            # Genera un nuovo UUID
            new_uuid = self.generate_random_uuid()
            
            # Percorso nel registro di sistema per le informazioni del sistema
            key_path = r"SYSTEM\HardwareConfig\Current"
            
            # Modifica il valore dell'UUID del BIOS
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "BaseBoardUUID",
                new_uuid
            )
            
            if success:
                logger.info(f"BIOS UUID changed to: {new_uuid}")
            
            return success
        except Exception as e:
            logger.error(f"Error changing BIOS UUID: {e}")
            return False

    def spoof_motherboard_serial(self):
        """Simula la modifica del numero di serie della scheda madre"""
        try:
            # Genera un numero di serie casuale
            new_serial = self.generate_random_serial(12)
            
            # Percorso nel registro di sistema per le informazioni della scheda madre
            key_path = r"SYSTEM\HardwareConfig\Current"
            
            # Modifica il valore del numero di serie della scheda madre
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "BaseBoardSerialNumber",
                new_serial
            )
            
            if success:
                logger.info(f"Motherboard serial changed to: {new_serial}")
            
            return success
        except Exception as e:
            logger.error(f"Error changing motherboard serial: {e}")
            return False

    def spoof_processor_id(self):
        """Simula la modifica dell'ID del processore"""
        try:
            # Genera un ID processore casuale
            new_id = self.generate_random_serial(16)
            
            # Percorso nel registro di sistema per le informazioni del processore
            key_path = r"SYSTEM\HardwareConfig\Current"
            
            # Modifica il valore dell'ID del processore
            success = self.registry_utils.set_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                "ProcessorID",
                new_id
            )
            
            if success:
                logger.info(f"Processor ID changed to: {new_id}")
            
            return success
        except Exception as e:
            logger.error(f"Error changing processor ID: {e}")
            return False

    def spoof_all_hwid(self):
        """Esegue lo spoofing di tutti gli identificatori hardware"""
        results = {
            "Machine GUID": self.spoof_machine_guid(),
            "Disk Serial": self.spoof_disk_serial(),
            "BIOS UUID": self.spoof_bios_uuid(),
            "Motherboard Serial": self.spoof_motherboard_serial(),
            "Processor ID": self.spoof_processor_id()
        }
        
        logger.info("HWID spoofing results:")
        for hwid, success in results.items():
            status = "Success" if success else "Failed"
            logger.info(f"{hwid}: {status}")
        
        return all(results.values())

    def get_current_hwid_info(self):
        """Ottiene informazioni sugli identificatori hardware attuali"""
        hwid_info = {}
        
        try:
            # Machine GUID
            hwid_info["Machine GUID"] = self.registry_utils.get_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                "MachineGuid"
            )
            
            # Disk Serial
            hwid_info["Disk Serial"] = self.registry_utils.get_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                "VolumeSerialNumber"
            )
            
            # BIOS UUID
            hwid_info["BIOS UUID"] = self.registry_utils.get_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\HardwareConfig\Current",
                "BaseBoardUUID"
            )
            
            # Motherboard Serial
            hwid_info["Motherboard Serial"] = self.registry_utils.get_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\HardwareConfig\Current",
                "BaseBoardSerialNumber"
            )
            
            # Processor ID
            hwid_info["Processor ID"] = self.registry_utils.get_registry_value(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\HardwareConfig\Current",
                "ProcessorID"
            )
            
        except Exception as e:
            logger.error(f"Error getting HWID info: {e}")
        
        return hwid_info