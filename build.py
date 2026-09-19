import subprocess
import sys
import os

# ---------------------------------------------------------------------------
# Percorsi
# ---------------------------------------------------------------------------
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MAIN_PY    = os.path.join(BASE_DIR, "main.py")
DRIVER_SYS = os.path.join(BASE_DIR, "hwid_virtualization_driver.sys")
ICON_ICO   = os.path.join(BASE_DIR, "gui", "resources", "icon.ico")
EXE_NAME   = "HWIDSpoofer"


def check_build_dependencies() -> None:
    """Verifica/installa le dipendenze necessarie prima della build."""
    requirements = os.path.join(BASE_DIR, "requirements.txt")

    required_imports = {
        "PyInstaller": "pyinstaller",
        "PyQt5": "PyQt5",
        "win32service": "pywin32",
        "win32file": "pywin32",
        "pywintypes": "pywin32",
    }

    missing_packages = set()

    for module_name, package_name in required_imports.items():
        try:
            __import__(module_name)
        except ImportError:
            missing_packages.add(package_name)

    if not missing_packages:
        print("[OK] Dipendenze di build già installate.")
        return

    print(
        "[INFO] Dipendenze mancanti: "
        + ", ".join(sorted(missing_packages))
    )

    if os.path.isfile(requirements):
        print(f"[INFO] Installazione da: {requirements}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", requirements],
            check=True,
        )
    else:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                *sorted(missing_packages),
            ],
            check=True,
        )

    # Verifica esplicita di pywin32: PyInstaller può completare la build anche
    # se un hidden-import non è disponibile, producendo poi un errore runtime.
    for module_name in ("win32service", "win32file", "win32con", "pywintypes"):
        try:
            __import__(module_name)
        except ImportError as exc:
            raise RuntimeError(
                f"Dipendenza Windows mancante dopo l'installazione: "
                f"{module_name}"
            ) from exc

    print("[OK] Dipendenze di build verificate.")


def build() -> None:
    """Lancia PyInstaller con i parametri richiesti e gestisce gli errori."""

    # ------------------------------------------------------------------
    # Verifica dei file necessari
    # ------------------------------------------------------------------
    print("-" * 60)

    if not os.path.isfile(MAIN_PY):
        print(f"[ERRORE] File principale non trovato: {MAIN_PY}")
        sys.exit(1)
    else:
        print(f"[OK] Entry point trovato  : {MAIN_PY}")

    if not os.path.isfile(DRIVER_SYS):
        print(f"[AVVISO] Driver non trovato: {DRIVER_SYS}")
        print("         Il file .sys NON verrà incluso nell'eseguibile.")
        include_driver = False
    else:
        print(f"[OK] Driver trovato        : {DRIVER_SYS}")
        include_driver = True

    if os.path.isfile(ICON_ICO):
        print(f"[OK] Icona trovata         : {ICON_ICO}")
    else:
        print(f"[INFO] Icona non trovata   : {ICON_ICO} — verrà usata quella di default.")

    print("-" * 60)

    # ------------------------------------------------------------------
    # Costruzione dei parametri di PyInstaller
    # ------------------------------------------------------------------
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",                         # pulisce la cache PyInstaller
        "--onefile",                       # singolo .exe
        "--windowed",                      # nessuna console
        f"--name={EXE_NAME}",             # nome dell'eseguibile
        # --- PyQt5 ---
        "--hidden-import=PyQt5",
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=PyQt5.QtGui",
        "--hidden-import=PyQt5.QtWidgets",
        # --- Moduli core del progetto ---
        "--hidden-import=core",
        "--hidden-import=core.mac_spoofer",
        "--hidden-import=core.hwid_spoofer",
        "--hidden-import=core.registry_utils",
        "--hidden-import=core.driver_utils",
        "--hidden-import=core.smbios_type1",
        # --- Moduli gui del progetto ---
        "--hidden-import=gui",
        "--hidden-import=gui.main_window",
        "--hidden-import=gui.config_dialog",
        # --- Librerie Windows ---
        "--hidden-import=winreg",
        "--hidden-import=ctypes",
        "--hidden-import=win32service",
        "--hidden-import=win32file",
        "--hidden-import=win32con",
        "--hidden-import=pywintypes",
        "--hidden-import=win32api",
    ]

    # Driver kernel (.sys) — incluso nella radice della cartella temporanea
    if include_driver:
        # Sintassi Windows per --add-data: "sorgente;destinazione"
        cmd.append(f"--add-data={DRIVER_SYS};.")

    # config.json — copiato accanto all'exe (non nella _MEI temporanea)
    config_json = os.path.join(BASE_DIR, "config.json")
    if os.path.isfile(config_json):
        cmd.append(f"--add-data={config_json};.")
        print(f"[OK] config.json incluso  : {config_json}")
    else:
        print(f"[INFO] config.json non trovato — verrà creato al primo avvio.")

    # Icona (opzionale)
    if os.path.isfile(ICON_ICO):
        cmd.append(f"--icon={ICON_ICO}")

    # File principale (deve essere l'ultimo argomento posizionale)
    cmd.append(MAIN_PY)

    # ------------------------------------------------------------------
    # Esecuzione
    # ------------------------------------------------------------------
    print("Inizio build...\n")
    print("Comando:", " ".join(cmd))
    print("-" * 60)

    result = subprocess.run(cmd, check=False)

    print("-" * 60)
    if result.returncode == 0:
        exe_path = os.path.join(BASE_DIR, "dist", f"{EXE_NAME}.exe")
        print(f"[OK] Build completata con successo!")
        print(f"     Eseguibile: {exe_path}")
    else:
        print(f"[ERRORE] PyInstaller ha restituito il codice {result.returncode}.")
        print("         Controlla i log qui sopra per i dettagli.")
        sys.exit(result.returncode)


if __name__ == "__main__":
    print("=" * 60)
    print(f"  Build di {EXE_NAME}")
    print("=" * 60)

    check_build_dependencies()
    build()

    print("=" * 60)
    input("\nPremi Invio per uscire...")