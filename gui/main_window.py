import logging
import os
import sys
import threading
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QTextEdit, QMessageBox, QFrame,
)

from core.driver_utils import (
    load_driver, unload_driver, is_service_running, is_device_available,
    send_ioctl, DEVICE_PATH, SERVICE_NAME,
)
from core.virtualization_manager import VirtualizationManager, VtxState

log = logging.getLogger("HWIDSpoofer.GUI")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HWID Spoofer - VT-x Lab")
        self.setMinimumSize(700, 500)

        self.manager = VirtualizationManager()
        self.driver_loaded = False
        self.vtx_capabilities = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- Status Group ---
        status_group = QGroupBox("Stato Sistema")
        status_layout = QVBoxLayout(status_group)

        self.lbl_driver_status = QLabel("Driver: Verifica in corso...")
        self.lbl_driver_status.setStyleSheet("color: gray; font-weight: bold;")
        status_layout.addWidget(self.lbl_driver_status)

        self.lbl_vtx_state = QLabel("Stato VT-x: -")
        status_layout.addWidget(self.lbl_vtx_state)

        self.lbl_hypervisor = QLabel("Hypervisor: -")
        status_layout.addWidget(self.lbl_hypervisor)

        layout.addWidget(status_group)

        # --- Driver Controls ---
        driver_group = QGroupBox("Gestione Driver Kernel")
        driver_layout = QHBoxLayout(driver_group)

        self.btn_load_driver = QPushButton("Carica Driver")
        self.btn_load_driver.clicked.connect(self._on_load_driver)
        driver_layout.addWidget(self.btn_load_driver)

        self.btn_unload_driver = QPushButton("Scarica Driver")
        self.btn_unload_driver.clicked.connect(self._on_unload_driver)
        driver_layout.addWidget(self.btn_unload_driver)

        self.btn_test_smbios = QPushButton("Test SMBIOS")
        self.btn_test_smbios.clicked.connect(self._on_test_smbios)
        driver_layout.addWidget(self.btn_test_smbios)

        layout.addWidget(driver_group)

        # --- VT-x Lab Controls ---
        vtx_group = QGroupBox("Laboratorio VT-x / EPT")
        vtx_layout = QVBoxLayout(vtx_group)

        self.btn_prepare_lab = QPushButton("Prepara VT-x Lab (Richiede Reboot)")
        self.btn_prepare_lab.clicked.connect(self._on_prepare_lab)
        vtx_layout.addWidget(self.btn_prepare_lab)

        self.btn_return_normal = QPushButton("Torna a Windows Normale")
        self.btn_return_normal.clicked.connect(self._on_return_normal)
        vtx_layout.addWidget(self.btn_return_normal)

        self.btn_diagnose = QPushButton("Diagnostica Completa")
        self.btn_diagnose.clicked.connect(self._on_diagnose)
        vtx_layout.addWidget(self.btn_diagnose)

        layout.addWidget(vtx_group)

        # --- Log Output ---
        log_group = QGroupBox("Log Operazioni")
        log_layout = QVBoxLayout(log_group)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(180)
        log_layout.addWidget(self.txt_log)
        layout.addWidget(log_group)

        # Initial state sync
        self.refresh_driver_state()
        self._update_vtx_ui()

        # Periodic refresh every 5 seconds to catch external state changes
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_driver_state)
        self._refresh_timer.start(5000)

        self._log("GUI avviata. Stato iniziale sincronizzato.")

    def _log(self, message: str) -> None:
        self.txt_log.append(message)
        log.info(message)

    def refresh_driver_state(self) -> None:
        """Sincronizza lo stato GUI con lo stato reale di SCM e device.
        
        Questa è l'unica fonte di verità per lo stato del driver nella GUI.
        Deve essere chiamata dopo ogni operazione che può cambiare lo stato
        del servizio kernel o del device.
        """
        service_ok = is_service_running(SERVICE_NAME)
        device_ok = is_device_available()

        self.driver_loaded = service_ok and device_ok

        # Update driver status label
        if self.driver_loaded:
            self.lbl_driver_status.setText("Driver: ATTIVO ✓")
            self.lbl_driver_status.setStyleSheet("color: green; font-weight: bold;")
        elif service_ok and not device_ok:
            self.lbl_driver_status.setText("Driver: Servizio attivo ma device non disponibile ⚠")
            self.lbl_driver_status.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.lbl_driver_status.setText("Driver: Non attivo")
            self.lbl_driver_status.setStyleSheet("color: gray; font-weight: bold;")

        # Update button states based on REAL state
        self.btn_test_smbios.setEnabled(self.driver_loaded)
        self.btn_unload_driver.setEnabled(self.driver_loaded)
        self.btn_load_driver.setEnabled(not service_ok)

        # Update VT-x state info
        try:
            effective = self.manager.get_effective_state()
            self.lbl_vtx_state.setText(f"Stato VT-x: {effective.value}")

            hypervisor = self.manager.is_hypervisor_present()
            self.lbl_hypervisor.setText(
                f"Hypervisor: {'Presente ✗' if hypervisor else 'Assente ✓'}"
            )
            self.lbl_hypervisor.setStyleSheet(
                "color: red;" if hypervisor else "color: green;"
            )

            # Enable/disable lab buttons based on state
            can_prepare = effective in (VtxState.NORMAL, VtxState.CLEANUP_PENDING, VtxState.ERROR_STALE)
            can_return = effective in (VtxState.LAB_RUNNING, VtxState.RETURN_PENDING)

            self.btn_prepare_lab.setEnabled(can_prepare and not hypervisor)
            self.btn_return_normal.setEnabled(can_return)

        except Exception as e:
            self.lbl_vtx_state.setText(f"Stato VT-x: Errore ({e})")
            self.btn_prepare_lab.setEnabled(False)
            self.btn_return_normal.setEnabled(False)

        log.debug(
            "Driver state refreshed: service=%s, device=%s, loaded=%s",
            service_ok, device_ok, self.driver_loaded,
        )

    def _update_vtx_ui(self) -> None:
        """Aggiorna UI VT-x dopo cambiamenti di stato."""
        self.refresh_driver_state()

    def _on_load_driver(self) -> None:
        self._log("Caricamento driver...")
        try:
            success = load_driver(SERVICE_NAME)
            if success:
                self._log("Driver caricato con successo.")
            else:
                self._log("Caricamento driver fallito.")
        except Exception as e:
            self._log(f"Errore caricamento driver: {e}")
            QMessageBox.critical(self, "Errore Driver", str(e))
        finally:
            self.refresh_driver_state()

    def _on_unload_driver(self) -> None:
        self._log("Scaricamento driver...")
        try:
            success = unload_driver(SERVICE_NAME)
            if success:
                self._log("Driver scaricato con successo.")
            else:
                self._log("Scaricamento driver fallito.")
        except Exception as e:
            self._log(f"Errore scaricamento driver: {e}")
            QMessageBox.critical(self, "Errore Driver", str(e))
        finally:
            self.refresh_driver_state()

    def _on_test_smbios(self) -> None:
        # Always verify real state before attempting IOCTL
        self.refresh_driver_state()

        if not self.driver_loaded:
            QMessageBox.warning(
                self, "Driver Non Attivo",
                "Il driver kernel non è attivo. Caricalo prima di eseguire il test.",
            )
            return

        self._log("Esecuzione test SMBIOS sintetico...")
        try:
            IOCTL_SMBIOS_TEST = 0x80002020
            success, data = send_ioctl(DEVICE_PATH, IOCTL_SMBIOS_TEST, b"", 256)
            if success:
                self._log(f"Test SMBIOS OK. Dati ricevuti: {len(data)} byte")
                QMessageBox.information(
                    self, "Test SMBIOS",
                    f"Test completato con successo.\nDati sintetici ricevuti: {len(data)} byte",
                )
            else:
                self._log("Test SMBIOS fallito: IOCTL non riuscito.")
                QMessageBox.warning(self, "Test SMBIOS", "IOCTL fallito. Controlla il log.")
        except Exception as e:
            self._log(f"Errore test SMBIOS: {e}")
            QMessageBox.critical(self, "Errore Test", str(e))
        finally:
            self.refresh_driver_state()

    def _on_prepare_lab(self) -> None:
        reply = QMessageBox.question(
            self, "Conferma VT-x Lab",
            "Questo creerà una voce di boot temporanea e riavvierà il PC.\n"
            "Hyper-V e WSL2 non saranno disponibili nella sessione Lab.\n\n"
            "Continuare?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._log("Preparazione VT-x Lab...")
        try:
            guid = self.manager.prepare_one_shot_lab_boot()
            self._log(f"Voce Lab creata: {guid}")
            QMessageBox.information(
                self, "VT-x Lab Pronta",
                "La voce di boot temporanea è stata creata.\n"
                "Il PC verrà riavviato ora.",
            )
            self.manager.reboot_now()
        except Exception as e:
            self._log(f"Errore preparazione Lab: {e}")
            QMessageBox.critical(self, "Errore VT-x Lab", str(e))
        finally:
            self.refresh_driver_state()

    def _on_return_normal(self) -> None:
        reply = QMessageBox.question(
            self, "Conferma Ritorno",
            "Impostare il prossimo avvio su Windows normale?\n"
            "Il PC verrà riavviato.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._log("Impostazione ritorno a Windows normale...")
        try:
            guid = self.manager.return_to_normal_boot()
            self._log(f"Bootsequence impostato su: {guid}")
            QMessageBox.information(
                self, "Ritorno Impostato",
                "Il prossimo avvio sarà su Windows normale.\n"
                "Il PC verrà riavviato ora.",
            )
            self.manager.reboot_now()
        except Exception as e:
            self._log(f"Errore ritorno normale: {e}")
            QMessageBox.critical(self, "Errore", str(e))
        finally:
            self.refresh_driver_state()

    def _on_diagnose(self) -> None:
        self._log("Raccolta diagnostica...")
        try:
            diag = self.manager.get_diagnostics()
            import json
            diag_text = json.dumps(diag, indent=2, default=str)
            self._log(f"Diagnostica raccolta:\n{diag_text}")

            QMessageBox.information(
                self, "Diagnostica",
                f"Diagnostica salvata nel log.\n\n"
                f"Stato effettivo: {diag.get('effective_state', 'N/A')}\n"
                f"Hypervisor: {diag.get('hypervisor_present', 'N/A')}\n"
                f"Service running: {diag.get('service_running', 'N/A')}\n"
                f"Device available: {diag.get('device_available', 'N/A')}\n\n"
                f"Log completo in:\n{diag.get('state_file', 'N/A')}",
            )
        except Exception as e:
            self._log(f"Errore diagnostica: {e}")
            QMessageBox.critical(self, "Errore Diagnostica", str(e))


def run_gui() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())