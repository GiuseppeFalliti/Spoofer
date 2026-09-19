import subprocess
import sys
import os

# ---------------------------------------------------------------------------
# Percorsi
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_PY = os.path.join(BASE_DIR, "main.py")
ICON_ICO = os.path.join(BASE_DIR, "gui", "resources", "icon.ico")
EXE_NAME = "HWIDSpoofer"

DRIVER_CANDIDATES = [
    os.path.join(
        BASE_DIR,
        "driver",
        "x64",
        "ReleaseTest",
        "hwid_virtualization_driver.sys",
    ),
    os.path.join(
        BASE_DIR,
        "driver",
        "x64",
        "Release",
        "hwid_virtualization_driver.sys",
    ),
    os.path.join(BASE_DIR, "hwid_virtualization_driver.sys"),
]


def find_driver_sys():
    """Preferisce la build WDK piu' recente del laboratorio rispetto al .sys root."""
    for path in DRIVER_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def check_pyinstaller() -> None:
    """Installa PyInstaller se non è disponibile nell'ambiente corrente."""
    try:
        import PyInstaller  # noqa: F401
        print("[OK] PyInstaller è già installato.")
    except ImportError:
        print("[INFO] PyInstaller non trovato. Installazione in corso...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
        )
        print("[OK] PyInstaller installato correttamente.")


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

    driver_sys = find_driver_sys()
    if driver_sys is None:
        print("[AVVISO] Driver non trovato nei percorsi previsti:")
        for candidate in DRIVER_CANDIDATES:
            print(f"         - {candidate}")
        print("         Il file .sys NON verra' incluso nell'eseguibile.")
        include_driver = False
    else:
        print(f"[OK] Driver trovato        : {driver_sys}")
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
        "--onefile",                       # singolo .exe
        "--windowed",                      # nessuna console
        "--uac-admin",                     # manifesta richiesta UAC all'avvio
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
        "--hidden-import=core.virtualization_manager",
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
        cmd.append(f"--add-data={driver_sys};.")

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

    check_pyinstaller()
    build()

    print("=" * 60)
    input("\nPremi Invio per uscire...")