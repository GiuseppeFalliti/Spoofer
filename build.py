import os
import sys
import shutil
import subprocess
from PyInstaller.utils.hooks import collect_data_files

def build_executable():
    """Compila l'applicazione in un eseguibile standalone"""
    try:
        # Opzioni per PyInstaller
        options = [
            "--name=Windows_MAC_HWID_Spoofer",
            "--onefile",
            "--windowed",
            "--icon=gui/resources/icon.ico" if os.path.exists("gui/resources/icon.ico") else "",
            "--add-data=data;data",
            "--add-data=config.json;.",
            f"--hidden-import=PyQt5",
            f"--hidden-import=winreg",
            f"--hidden-import=ctypes",
            "main.py"
        ]
        
        # Rimuovi opzioni vuote
        options = [opt for opt in options if opt]
        
        # Esegui PyInstaller
        subprocess.check_call([sys.executable, "-m", "PyInstaller"] + options)
        
        print("Build completato con successo!")
        print(f"L'eseguibile si trova in: {os.path.join('dist', 'Windows_MAC_HWID_Spoofer.exe')}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Errore durante la build: {e}")
        return False

def main():
    print("=" * 50)
    print("  Build di Windows MAC & HWID Spoofer")
    print("=" * 50)
    
    # Verifica che PyInstaller sia installato
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller non è installato. Installazione in corso...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Esegui la build
    if build_executable():
        input("\nPremi Invio per uscire...")
    else:
        input("\nBuild fallito. Premi Invio per uscire...")

if __name__ == "__main__":
    main()