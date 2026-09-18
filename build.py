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
        "--onefile",                       # singolo .exe
        "--windowed",                      # nessuna console
        f"--name={EXE_NAME}",             # nome dell'eseguibile
        # Hidden imports utili per PyQt5 + winreg + ctypes
        "--hidden-import=PyQt5",
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=PyQt5.QtGui",
        "--hidden-import=PyQt5.QtWidgets",
        "--hidden-import=winreg",
        "--hidden-import=ctypes",
    ]

    # Driver kernel (.sys) — incluso nella radice della cartella temporanea
    if include_driver:
        # Sintassi Windows per --add-data: "sorgente;destinazione"
        cmd.append(f"--add-data={DRIVER_SYS};.")

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