import subprocess
import sys
import os

def install_requirements():
    """Installa le dipendenze necessarie"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("Dipendenze installate con successo!")
        return True
    except subprocess.CalledProcessError:
        print("Errore durante l'installazione delle dipendenze.")
        return False

def create_shortcut():
    """Crea un collegamento sul desktop per eseguire l'applicazione come amministratore"""
    try:
        import winshell
        from win32com.client import Dispatch
        
        desktop = winshell.desktop()
        path = os.path.join(desktop, "Windows MAC & HWID Spoofer.lnk")
        target = os.path.join(os.getcwd(), "main.py")
        wDir = os.getcwd()
        icon = os.path.join(os.getcwd(), "gui", "resources", "icon.ico")
        
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(path)
        shortcut.Targetpath = sys.executable
        shortcut.Arguments = f'"{target}"'
        shortcut.WorkingDirectory = wDir
        shortcut.IconLocation = icon if os.path.exists(icon) else sys.executable
        shortcut.save()
        
        print("Collegamento creato sul desktop!")
        return True
    except ImportError:
        print("Impossibile creare il collegamento automatico. Installa winshell e pywin32.")
        return False
    except Exception as e:
        print(f"Errore durante la creazione del collegamento: {e}")
        return False

def main():
    print("=" * 50)
    print("  Installazione di Windows MAC & HWID Spoofer")
    print("=" * 50)
    
    # Installa le dipendenze
    if not install_requirements():
        input("Premi Invio per uscire...")
        return
    
    # Crea il collegamento
    create_shortcut()
    
    print("\nInstallazione completata!")
    print("Esegui l'applicazione come amministratore per utilizzarla.")
    input("\nPremi Invio per uscire...")

if __name__ == "__main__":
    main()