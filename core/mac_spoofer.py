import subprocess
import random
import re
import json
import os
import logging
from datetime import datetime
from .registry_utils import RegistryUtils

logger = logging.getLogger(__name__)

SAVED_MACS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "saved_macs.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "spoofer.log")


def setup_logging():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )


class MacSpoofer:
    """Core class for MAC address spoofing operations on Windows."""

    def __init__(self):
        setup_logging()
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        data_dir = os.path.dirname(SAVED_MACS_FILE)
        os.makedirs(data_dir, exist_ok=True)

    @staticmethod
    def get_network_interfaces():
        interfaces = []
        try:
            result = subprocess.check_output(
                ["getmac", "/v", "/fo", "csv"], stderr=subprocess.STDOUT
            )
            lines = result.decode("utf-8", errors="replace").strip().split("\n")
            for line in lines[1:]:
                if not line.strip():
                    continue
                parts = line.replace('"', "").split(",")
                if len(parts) >= 4 and parts[3].strip() and parts[3].strip().upper() != "N/A":
                    interfaces.append({
                        "name": parts[0].strip(),
                        "transport": parts[1].strip() if len(parts) > 1 else "",
                        "type": parts[2].strip() if len(parts) > 2 else "",
                        "mac": parts[3].strip()
                    })
        except subprocess.CalledProcessError as e:
            logger.error(f"Error getting interfaces: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting interfaces: {e}")
        return interfaces

    @staticmethod
    def generate_random_mac():
        octets = [0x02] + [random.randint(0, 255) for _ in range(5)]
        return ":".join(f"{b:02X}" for b in octets)

    @staticmethod
    def validate_mac(mac):
        pattern = r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"
        return bool(re.match(pattern, mac))

    @staticmethod
    def normalize_mac(mac):
        return mac.replace("-", ":").upper()

    @staticmethod
    def mac_for_registry(mac):
        return mac.replace(":", "").replace("-", "").upper()

    def save_original_mac(self, interface_name, mac):
        saved = self.load_saved_macs()
        if interface_name not in saved:
            saved[interface_name] = {
                "original_mac": mac,
                "saved_at": datetime.now().isoformat()
            }
            self._write_saved_macs(saved)
            logger.info(f"Saved original MAC for {interface_name}: {mac}")

    def load_saved_macs(self):
        if not os.path.exists(SAVED_MACS_FILE):
            return {}
        try:
            with open(SAVED_MACS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading saved MACs: {e}")
            return {}

    def _write_saved_macs(self, data):
        try:
            with open(SAVED_MACS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error(f"Error writing saved MACs: {e}")

    def change_mac(self, interface_name, new_mac):
        new_mac = self.normalize_mac(new_mac)
        if not self.validate_mac(new_mac):
            logger.error(f"Invalid MAC format: {new_mac}")
            return False

        current_mac = self.get_current_mac(interface_name)
        if current_mac:
            self.save_original_mac(interface_name, current_mac)

        subkey_name, subkey_path = RegistryUtils.find_adapter_subkey(interface_name)
        if not subkey_path:
            logger.error(f"Could not find registry subkey for {interface_name}")
            return False

        backup_file = os.path.join(
            os.path.dirname(SAVED_MACS_FILE),
            f"backup_{subkey_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.reg"
        )
        RegistryUtils.backup_registry(subkey_path, backup_file)

        self._toggle_interface(interface_name, disable=True)

        reg_mac = self.mac_for_registry(new_mac)
        success = RegistryUtils.set_network_address(subkey_path, reg_mac)

        self._toggle_interface(interface_name, disable=False)

        if success:
            logger.info(f"MAC changed for {interface_name}: {current_mac} -> {new_mac}")
        return success

    def restore_mac(self, interface_name):
        saved = self.load_saved_macs()
        if interface_name not in saved:
            logger.warning(f"No saved MAC found for {interface_name}")
            return False

        subkey_name, subkey_path = RegistryUtils.find_adapter_subkey(interface_name)
        if not subkey_path:
            logger.error(f"Could not find registry subkey for {interface_name}")
            return False

        self._toggle_interface(interface_name, disable=True)
        success = RegistryUtils.remove_network_address(subkey_path)
        self._toggle_interface(interface_name, disable=False)

        if success:
            original_mac = saved[interface_name]["original_mac"]
            logger.info(f"MAC restored for {interface_name}: {original_mac}")
            del saved[interface_name]
            self._write_saved_macs(saved)
        return success

    def get_current_mac(self, interface_name):
        try:
            result = subprocess.check_output(
                ["getmac", "/v", "/nh", "/fo", "csv"], stderr=subprocess.STDOUT
            )
            for line in result.decode("utf-8", errors="replace").split("\n"):
                if interface_name in line:
                    parts = line.replace('"', "").split(",")
                    if len(parts) >= 4 and parts[3].strip():
                        return parts[3].strip()
        except subprocess.CalledProcessError:
            pass
        return None

    @staticmethod
    def _toggle_interface(interface_name, disable=True):
        state = "disable" if disable else "enable"
        try:
            subprocess.run(
                ["netsh", "interface", "set", "interface", interface_name, f"admin={state}"],
                check=True, capture_output=True
            )
            logger.info(f"Interface {interface_name} {state}d")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to {state} interface {interface_name}: {e}")

    @staticmethod
    def is_admin():
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

