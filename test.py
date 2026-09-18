import sys
import os
import winreg

# Aggiungi la directory principale al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.mac_spoofer import MacSpoofer
from core.hwid_spoofer import HwidSpoofer

def test_mac_spoofer():
    """Testa le funzionalità dello spoofer MAC"""
    print("Test dello spoofer MAC...")
    
    spoofer = MacSpoofer()
    
    # Test generazione MAC
    mac = spoofer.generate_random_mac()
    print(f"MAC generato: {mac}")
    assert spoofer.validate_mac(mac), "MAC generato non valido"
    
    # Test normalizzazione MAC
    normalized = spoofer.normalize_mac("02-aa-bb-cc-dd-ee")
    print(f"MAC normalizzato: {normalized}")
    assert normalized == "02:AA:BB:CC:DD:EE", "Normalizzazione MAC fallita"
    
    # Test conversione MAC per registro
    reg_mac = spoofer.mac_for_registry("02:AA:BB:CC:DD:EE")
    print(f"MAC per registro: {reg_mac}")
    assert reg_mac == "02AABBCCDDEE", "Conversione MAC per registro fallita"
    
    print("Test dello spoofer MAC completato con successo!")

def test_hwid_spoofer():
    """Testa le funzionalità dello spoofer HWID"""
    print("\nTest dello spoofer HWID...")
    
    hwid_spoofer = HwidSpoofer()
    
    # Test generazione UUID
    uuid = hwid_spoofer.generate_random_uuid()
    print(f"UUID generato: {uuid}")
    assert len(uuid) == 36, "UUID generato non valido"
    
    # Test generazione numero di serie
    serial = hwid_spoofer.generate_random_serial(12)
    print(f"Numero di serie generato: {serial}")
    assert len(serial) == 12, "Numero di serie generato non valido"
    
    # Test caricamento configurazione
    config = hwid_spoofer.load_config()
    print("Configurazione caricata:")
    for key, value in config.items():
        if isinstance(value, dict):
            print(f"  {key}:")
            for sub_key, sub_value in value.items():
                print(f"    {sub_key}: {sub_value}")
        else:
            print(f"  {key}: {value}")
    
    print("Test dello spoofer HWID completato con successo!")

def test_registry_utils():
    """Testa le funzionalità delle utilità del registro"""
    print("\nTest delle utilità del registro...")
    
    from core.registry_utils import RegistryUtils
    
    # Test lettura valore esistente
    try:
        value = RegistryUtils.get_registry_value(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            "MachineGuid"
        )
        print(f"Machine GUID letto: {value}")
    except Exception as e:
        print(f"Errore durante la lettura del Machine GUID: {e}")
    
    print("Test delle utilità del registro completato!")

def main():
    print("=" * 50)
    print("  Test di Windows MAC & HWID Spoofer")
    print("=" * 50)
    
    try:
        test_mac_spoofer()
        test_hwid_spoofer()
        test_registry_utils()
        
        print("\n" + "=" * 50)
        print("  Tutti i test completati con successo!")
        print("=" * 50)
    except AssertionError as e:
        print(f"\nTest fallito: {e}")
    except Exception as e:
        print(f"\nErrore durante i test: {e}")
    
    input("\nPremi Invio per uscire...")

if __name__ == "__main__":
    main()