import winreg
import subprocess
import logging

logger = logging.getLogger(__name__)

REG_KEY_PATH = r"SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}"


class RegistryUtils:
    """Utility class for Windows registry operations related to network adapters."""

    @staticmethod
    def find_adapter_subkey(interface_name):
        """Find the registry subkey index matching the given interface name."""
        try:
            reg_key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, REG_KEY_PATH, 0, winreg.KEY_READ
            )
        except OSError as e:
            logger.error(f"Cannot open registry key: {e}")
            return None, None

        for i in range(1000):
            try:
                subkey_name = winreg.EnumKey(reg_key, i)
                subkey_path = f"{REG_KEY_PATH}\\{subkey_name}"
                try:
                    subkey = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_READ
                    )
                    driver_desc = winreg.QueryValueEx(subkey, "DriverDesc")[0]
                    net_cfg_id = ""
                    try:
                        net_cfg_id = winreg.QueryValueEx(subkey, "NetCfgInstanceId")[0]
                    except FileNotFoundError:
                        pass
                    winreg.CloseKey(subkey)
                    if interface_name.lower() in driver_desc.lower() or interface_name.lower() in net_cfg_id.lower():
                        winreg.CloseKey(reg_key)
                        return subkey_name, subkey_path
                except FileNotFoundError:
                    continue
                except OSError:
                    continue
            except OSError:
                break

        winreg.CloseKey(reg_key)
        return None, None

    @staticmethod
    def set_network_address(subkey_path, mac_without_separators):
        """Set the NetworkAddress value in the registry."""
        try:
            subkey = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_ALL_ACCESS
            )
            winreg.SetValueEx(subkey, "NetworkAddress", 0, winreg.REG_SZ, mac_without_separators)
            winreg.CloseKey(subkey)
            logger.info(f"Set NetworkAddress to {mac_without_separators} at {subkey_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to set NetworkAddress: {e}")
            return False

    @staticmethod
    def remove_network_address(subkey_path):
        """Remove the NetworkAddress value from the registry to restore original MAC."""
        try:
            subkey = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_ALL_ACCESS
            )
            winreg.DeleteValue(subkey, "NetworkAddress")
            winreg.CloseKey(subkey)
            logger.info(f"Removed NetworkAddress at {subkey_path}")
            return True
        except FileNotFoundError:
            logger.info("NetworkAddress not found, already using default MAC.")
            return True
        except OSError as e:
            logger.error(f"Failed to remove NetworkAddress: {e}")
            return False

    @staticmethod
    def backup_registry(subkey_path, backup_file):
        """Export a registry subkey to a .reg file as backup."""
        try:
            cmd = ["reg", "export", subkey_path, backup_file, "/y"]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"Registry backed up to {backup_file}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Registry backup failed: {e}")
            return False

