import subprocess
from datetime import datetime
import json
import sys
import os
from PyQt5.QtWidgets import (
    QAction, QApplication, QMainWindow, QTableWidget, QTableWidgetItem, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QLineEdit, QGroupBox,
    QTextEdit, QMessageBox, QStatusBar, QFileDialog, QCheckBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.mac_spoofer import MacSpoofer
from core.hwid_spoofer import HwidSpoofer
from core.driver_utils import load_driver, unload_driver, send_ioctl
from core.smbios_type1 import generate_random_uuid
from gui.config_dialog import ConfigDialog

# ---------------------------------------------------------------------------
# Costanti driver — devono corrispondere al nome servizio registrato in SCM
# e al symbolic link esposto dal driver nel namespace di I/O di Windows.
# ---------------------------------------------------------------------------
SERVICE_NAME = "HWIDVirtualizationDriver"
DEVICE_PATH  = r"\\.\HwidSpoofer"


class WorkerThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, func, *args):
        super().__init__()
        self.func = func
        self.args = args

    def run(self):
        try:
            result = self.func(*self.args)
            self.finished.emit(True, str(result) if result is not None else "")
        except Exception as e:
            self.finished.emit(False, str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.spoofer = MacSpoofer()
        self.hwid_spoofer = HwidSpoofer()
        self.config = self.hwid_spoofer.config
        self.interfaces = []
        self.worker = None
        self.init_ui()
        self.refresh_interfaces()
        self._apply_startup_driver_config()

    def init_ui(self):
        self.setWindowTitle("Windows MAC & HWID Spoofer")
        self.setMinimumSize(600, 700)

        menubar = self.menuBar()

        file_menu = menubar.addMenu('File')
        exit_action = QAction('Esci', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu('Strumenti')
        config_action = QAction('Configurazione', self)
        config_action.triggered.connect(self.show_config_dialog)
        tools_menu.addAction(config_action)
        backup_action = QAction('Backup Registro', self)
        backup_action.triggered.connect(self.backup_registry)
        tools_menu.addAction(backup_action)

        help_menu = menubar.addMenu('Aiuto')
        about_action = QAction('Informazioni', self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        iface_group = QGroupBox("Interfaccia di Rete")
        iface_layout = QVBoxLayout(iface_group)

        row1 = QHBoxLayout()
        self.combo_interfaces = QComboBox()
        self.combo_interfaces.currentIndexChanged.connect(self.on_interface_selected)
        btn_refresh = QPushButton("Aggiorna")
        btn_refresh.clicked.connect(self.refresh_interfaces)
        row1.addWidget(QLabel("Seleziona interfaccia:"))
        row1.addWidget(self.combo_interfaces)
        row1.addWidget(btn_refresh)
        iface_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.lbl_current_mac = QLabel("MAC Attuale: N/A")
        self.lbl_current_mac.setStyleSheet("font-weight: bold; color: #333;")
        row2.addWidget(self.lbl_current_mac)
        row2.addStretch()
        iface_layout.addLayout(row2)

        layout.addWidget(iface_group)

        # --- Driver Kernel Group ---
        driver_group = QGroupBox("Controllo Driver Kernel")
        driver_layout = QVBoxLayout(driver_group)

        top_row = QHBoxLayout()
        self.btn_load_driver = QPushButton("Carica Driver")
        self.btn_unload_driver = QPushButton("Scarica Driver")
        self.btn_unload_driver.setEnabled(False)
        self.lbl_driver_status = QLabel("Stato: Non Caricato")
        self.lbl_driver_status.setStyleSheet("font-weight: bold; color: red;")

        top_row.addWidget(self.btn_load_driver)
        top_row.addWidget(self.btn_unload_driver)
        top_row.addStretch()
        top_row.addWidget(self.lbl_driver_status)
        driver_layout.addLayout(top_row)

        hooks_row = QHBoxLayout()
        self.cb_firmware_hook = QCheckBox("Firmware Hook (0x80002000)")
        self.cb_hal_hook = QCheckBox("HAL Hook (0x80002008)")
        self.cb_smbios_hook = QCheckBox("SMBIOS Hook (0x80002010)")

        self.cb_firmware_hook.setEnabled(False)
        self.cb_hal_hook.setEnabled(False)
        self.cb_smbios_hook.setEnabled(False)

        hooks_row.addWidget(self.cb_firmware_hook)
        hooks_row.addWidget(self.cb_hal_hook)
        hooks_row.addWidget(self.cb_smbios_hook)
        driver_layout.addLayout(hooks_row)

        uuid_row = QHBoxLayout()
        self.btn_generate_uuid = QPushButton("Genera UUID")
        self.btn_generate_uuid.setEnabled(False)
        self.txt_new_uuid = QLineEdit()
        self.txt_new_uuid.setReadOnly(True)
        self.txt_new_uuid.setPlaceholderText("Nuovo SMBIOS UUID...")

        uuid_row.addWidget(self.btn_generate_uuid)
        uuid_row.addWidget(self.txt_new_uuid)
        driver_layout.addLayout(uuid_row)

        layout.addWidget(driver_group)
        # ---------------------------

        mac_group = QGroupBox("Configurazione MAC")
        mac_layout = QVBoxLayout(mac_group)

        row3 = QHBoxLayout()
        self.radio_random = QPushButton("Genera MAC Casuale")
        self.radio_random.clicked.connect(self.generate_random)
        row3.addWidget(self.radio_random)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("MAC Personalizzato:"))
        self.txt_custom_mac = QLineEdit()
        self.txt_custom_mac.setPlaceholderText("Es: 02:AA:BB:CC:DD:EE")
        self.txt_custom_mac.setMaxLength(17)
        row4.addWidget(self.txt_custom_mac)
        mac_layout.addLayout(row3)
        mac_layout.addLayout(row4)

        row5 = QHBoxLayout()
        self.btn_apply = QPushButton("Applica MAC")
        self.btn_apply.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        self.btn_apply.clicked.connect(self.apply_mac)
        self.btn_restore = QPushButton("Ripristina Originale")
        self.btn_restore.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; padding: 8px;")
        self.btn_restore.clicked.connect(self.restore_mac)
        row5.addWidget(self.btn_apply)
        row5.addWidget(self.btn_restore)
        mac_layout.addLayout(row5)

        layout.addWidget(mac_group)

        hwid_group = QGroupBox("Hardware ID (HWID)")
        hwid_layout = QVBoxLayout(hwid_group)

        row6 = QHBoxLayout()
        self.btn_refresh_hwid = QPushButton("Aggiorna Info HWID")
        self.btn_refresh_hwid.clicked.connect(self.refresh_hwid_info)
        row6.addWidget(self.btn_refresh_hwid)
        hwid_layout.addLayout(row6)

        self.hwids_table = QTableWidget()
        self.hwids_table.setColumnCount(2)
        self.hwids_table.setHorizontalHeaderLabels(["Identificatore", "Valore Attuale"])
        self.hwids_table.horizontalHeader().setStretchLastSection(True)
        self.hwids_table.setMaximumHeight(150)
        hwid_layout.addWidget(self.hwids_table)

        row7 = QHBoxLayout()
        self.btn_spoof_all = QPushButton("Spoof Tutti gli HWID")
        self.btn_spoof_all.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold; padding: 8px;")
        self.btn_spoof_all.clicked.connect(self.spoof_all_hwid)
        self.btn_restore_hwid = QPushButton("Ripristina HWID Originali")
        self.btn_restore_hwid.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 8px;")
        self.btn_restore_hwid.clicked.connect(self.restore_hwid)
        row7.addWidget(self.btn_spoof_all)
        row7.addWidget(self.btn_restore_hwid)
        hwid_layout.addLayout(row7)

        layout.addWidget(hwid_group)

        log_group = QGroupBox("Log Operazioni")
        log_layout = QVBoxLayout(log_group)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(150)
        log_layout.addWidget(self.txt_log)
        layout.addWidget(log_group)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Pronto")

        # Connessioni segnali driver
        self.btn_load_driver.clicked.connect(self.on_load_driver)
        self.btn_unload_driver.clicked.connect(self.on_unload_driver)
        self.btn_generate_uuid.clicked.connect(self.on_generate_uuid)
        self.cb_firmware_hook.stateChanged.connect(self.on_hook_state_changed)
        self.cb_hal_hook.stateChanged.connect(self.on_hook_state_changed)
        self.cb_smbios_hook.stateChanged.connect(self.on_hook_state_changed)

    def _apply_startup_driver_config(self):
        """Applica le preferenze di avvio dal config dialog."""
        if self.config.get("start_with_driver", False):
            self.on_load_driver()
            if self.config.get("auto_enable_hooks", False):
                # Blocca i segnali per evitare chiamate IOCTL multiple durante l'avvio
                self.cb_firmware_hook.blockSignals(True)
                self.cb_hal_hook.blockSignals(True)
                self.cb_smbios_hook.blockSignals(True)
                
                self.cb_firmware_hook.setChecked(True)
                self.cb_hal_hook.setChecked(True)
                self.cb_smbios_hook.setChecked(True)
                
                self.cb_firmware_hook.blockSignals(False)
                self.cb_hal_hook.blockSignals(False)
                self.cb_smbios_hook.blockSignals(False)
                
                # Invia gli IOCTL manualmente una volta sola
                self._send_ioctl_safe(0x80002000, 1)
                self._send_ioctl_safe(0x80002008, 1)
                self._send_ioctl_safe(0x80002010, 1)

    def _set_driver_widgets_enabled(self, enabled):
        """Abilita o disabilita i widget dipendenti dallo stato del driver."""
        self.btn_unload_driver.setEnabled(enabled)
        self.btn_load_driver.setEnabled(not enabled)
        self.cb_firmware_hook.setEnabled(enabled)
        self.cb_hal_hook.setEnabled(enabled)
        self.cb_smbios_hook.setEnabled(enabled)
        self.btn_generate_uuid.setEnabled(enabled)

    def _send_ioctl_safe(self, ioctl_code, payload):
        """Wrapper sicuro per inviare IOCTL senza crashare la GUI."""
        try:
            in_buffer = payload.to_bytes(4, byteorder="little") if isinstance(payload, int) else payload
            send_ioctl(DEVICE_PATH, ioctl_code, in_buffer)
            return True
        except Exception as e:
            self.log_message(f"Errore IOCTL 0x{ioctl_code:08X}: {e}")
            QMessageBox.warning(self, "Errore IOCTL", f"Fallita comunicazione con il driver:\n{str(e)}")
            return False

    def on_load_driver(self):
        try:
            if not load_driver(SERVICE_NAME):
                raise RuntimeError(f"Impossibile avviare il servizio driver '{SERVICE_NAME}'.")
            self.lbl_driver_status.setText("Stato: Caricato")
            self.lbl_driver_status.setStyleSheet("font-weight: bold; color: green;")
            self._set_driver_widgets_enabled(True)
            self.log_message("Driver kernel caricato con successo.")
        except Exception as e:
            QMessageBox.critical(self, "Errore Driver", f"Impossibile caricare il driver:\n{str(e)}")
            self.log_message(f"Errore caricamento driver: {e}")

    def on_unload_driver(self):
        try:
            # Disattiva tutti gli hook prima di scaricare
            if self.cb_firmware_hook.isChecked():
                self.cb_firmware_hook.setChecked(False)
            if self.cb_hal_hook.isChecked():
                self.cb_hal_hook.setChecked(False)
            if self.cb_smbios_hook.isChecked():
                self.cb_smbios_hook.setChecked(False)

            if not unload_driver(SERVICE_NAME):
                raise RuntimeError(f"Impossibile arrestare o eliminare il servizio '{SERVICE_NAME}'.")
            self.lbl_driver_status.setText("Stato: Non Caricato")
            self.lbl_driver_status.setStyleSheet("font-weight: bold; color: red;")
            self._set_driver_widgets_enabled(False)
            self.log_message("Driver kernel scaricato.")
        except Exception as e:
            QMessageBox.critical(self, "Errore Driver", f"Impossibile scaricare il driver:\n{str(e)}")
            self.log_message(f"Errore scaricamento driver: {e}")

    def on_hook_state_changed(self, state):
        sender = self.sender()
        if not sender:
            return

        ioctl_map = {
            self.cb_firmware_hook: 0x80002000,
            self.cb_hal_hook: 0x80002008,
            self.cb_smbios_hook: 0x80002010,
        }

        ioctl_code = ioctl_map.get(sender)
        if ioctl_code is None:
            return

        # Qt.Checked è 2, inviamo 1 per abilitare e 0 per disabilitare
        payload = 1 if state == Qt.Checked else 0
        
        if not self._send_ioctl_safe(ioctl_code, payload):
            # Se fallisce, ripristina lo stato della checkbox senza triggerare di nuovo il segnale
            sender.blockSignals(True)
            sender.setChecked(state != Qt.Checked)
            sender.blockSignals(False)

    def on_generate_uuid(self):
        try:
            new_uuid = generate_random_uuid()
            self.txt_new_uuid.setText(str(new_uuid))
            self.log_message(f"Nuovo UUID generato: {new_uuid}")
        except Exception as e:
            QMessageBox.warning(self, "Errore UUID", f"Impossibile generare l'UUID:\n{str(e)}")
            self.log_message(f"Errore generazione UUID: {e}")

    def log_message(self, msg):
        self.txt_log.append(msg)

    def refresh_interfaces(self):
        if not self.spoofer.is_admin():
            QMessageBox.warning(self, "Permessi insufficienti",
                                "Questa applicazione richiede privilegi di amministratore.")
            return

        self.interfaces = self.spoofer.get_network_interfaces()
        self.combo_interfaces.clear()
        for iface in self.interfaces:
            self.combo_interfaces.addItem(f"{iface['name']} ({iface['mac']})")

        if self.interfaces:
            self.log_message(f"Trovate {len(self.interfaces)} interfacce di rete.")
        else:
            self.log_message("Nessuna interfaccia di rete trovata.")

    def on_interface_selected(self, index):
        if 0 <= index < len(self.interfaces):
            mac = self.interfaces[index]["mac"]
            self.lbl_current_mac.setText(f"MAC Attuale: {mac}")
        else:
            self.lbl_current_mac.setText("MAC Attuale: N/A")

    def generate_random(self):
        new_mac = self.spoofer.generate_random_mac()
        self.txt_custom_mac.setText(new_mac)
        self.log_message(f"MAC casuale generato: {new_mac}")

    def apply_mac(self):
        idx = self.combo_interfaces.currentIndex()
        if idx < 0 or idx >= len(self.interfaces):
            QMessageBox.warning(self, "Errore", "Seleziona un'interfaccia valida.")
            return

        new_mac = self.txt_custom_mac.text().strip()
        if not new_mac:
            new_mac = self.spoofer.generate_random_mac()
            self.txt_custom_mac.setText(new_mac)

        if not self.spoofer.validate_mac(new_mac):
            QMessageBox.warning(self, "Errore", "Formato MAC non valido. Usa formato XX:XX:XX:XX:XX:XX")
            return

        iface_name = self.interfaces[idx]["name"]
        self.log_message(f"Cambio MAC per {iface_name} a {new_mac}...")
        self.statusBar.showMessage("Operazione in corso...")
        self.set_buttons_enabled(False)

        self.worker = WorkerThread(self.spoofer.change_mac, iface_name, new_mac)
        self.worker.finished.connect(self.on_change_finished)
        self.worker.start()

    def restore_mac(self):
        idx = self.combo_interfaces.currentIndex()
        if idx < 0 or idx >= len(self.interfaces):
            QMessageBox.warning(self, "Errore", "Seleziona un'interfaccia valida.")
            return

        iface_name = self.interfaces[idx]["name"]
        saved = self.spoofer.load_saved_macs()
        if iface_name not in saved:
            QMessageBox.information(self, "Info", "Nessun MAC originale salvato per questa interfaccia.")
            return

        self.log_message(f"Ripristino MAC originale per {iface_name}...")
        self.statusBar.showMessage("Ripristino in corso...")
        self.set_buttons_enabled(False)

        self.worker = WorkerThread(self.spoofer.restore_mac, iface_name)
        self.worker.finished.connect(self.on_restore_finished)
        self.worker.start()

    def on_change_finished(self, success, msg):
        self.set_buttons_enabled(True)
        if success:
            self.log_message("MAC cambiato con successo!")
            self.statusBar.showMessage("Operazione completata")
            self.refresh_interfaces()
        else:
            self.log_message(f"Errore durante il cambio MAC: {msg}")
            self.statusBar.showMessage("Errore")
            QMessageBox.critical(self, "Errore", f"Impossibile cambiare il MAC:\n{msg}")

    def on_restore_finished(self, success, msg):
        self.set_buttons_enabled(True)
        if success:
            self.log_message("MAC originale ripristinato con successo!")
            self.statusBar.showMessage("Ripristino completato")
            self.refresh_interfaces()
        else:
            self.log_message(f"Errore durante il ripristino: {msg}")
            self.statusBar.showMessage("Errore")
            QMessageBox.critical(self, "Errore", f"Impossibile ripristinare il MAC:\n{msg}")

    def set_buttons_enabled(self, enabled):
        self.btn_apply.setEnabled(enabled)
        self.btn_restore.setEnabled(enabled)
        self.combo_interfaces.setEnabled(enabled)
        self.btn_spoof_all.setEnabled(enabled)
        self.btn_restore_hwid.setEnabled(enabled)
        self.btn_refresh_hwid.setEnabled(enabled)

    def refresh_hwid_info(self):
        if not self.spoofer.is_admin():
            QMessageBox.warning(self, "Permessi insufficienti",
                            "Questa operazione richiede privilegi di amministratore.")
            return

        self.log_message("Caricamento informazioni HWID...")
        self.hwids_table.setRowCount(0)

        hwid_info = self.hwid_spoofer.get_current_hwid_info()

        if hwid_info:
            row = 0
            for hwid_name, hwid_value in hwid_info.items():
                self.hwids_table.insertRow(row)
                self.hwids_table.setItem(row, 0, QTableWidgetItem(hwid_name))
                self.hwids_table.setItem(row, 1, QTableWidgetItem(hwid_value or "N/D"))
                row += 1
            self.log_message(f"Trovate {len(hwid_info)} informazioni HWID.")
        else:
            self.log_message("Impossibile ottenere informazioni HWID.")

    def spoof_all_hwid(self):
        if not self.spoofer.is_admin():
            QMessageBox.warning(self, "Permessi insufficienti",
                               "Questa operazione richiede privilegi di amministratore.")
            return

        reply = QMessageBox.question(
            self, "Conferma",
            "Sei sicuro di voler modificare tutti gli identificatori hardware?\nQuesta operazione potrebbe richiedere un riavvio.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.log_message("Inizio spoofing HWID...")
            self.statusBar.showMessage("Operazione in corso...")
            self.set_buttons_enabled(False)

            self.worker = WorkerThread(self.hwid_spoofer.spoof_selected_hwids)
            self.worker.finished.connect(self.on_hwid_spoof_finished)
            self.worker.start()

    def on_hwid_spoof_finished(self, success, msg):
        self.set_buttons_enabled(True)
        if success:
            self.log_message("HWID spoofing completato con successo!")
            self.statusBar.showMessage("Operazione completata")
            self.refresh_hwid_info()
            QMessageBox.information(
                self, "Operazione Completata",
                "HWID spoofing completato. Si consiglia un riavvio del sistema per applicare tutte le modifiche."
            )
        else:
            self.log_message(f"Errore durante lo spoofing HWID: {msg}")
            self.statusBar.showMessage("Errore")
            QMessageBox.critical(self, "Errore", f"Impossibile completare lo spoofing HWID:\n{msg}")

    def restore_hwid(self):
        if not self.spoofer.is_admin():
            QMessageBox.warning(self, "Permessi insufficienti",
                               "Questa operazione richiede privilegi di amministratore.")
            return

        reply = QMessageBox.question(
            self, "Conferma",
            "Sei sicuro di voler ripristinare tutti gli identificatori hardware ai valori originali?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.log_message("Inizio ripristino HWID...")
            self.statusBar.showMessage("Operazione in corso...")
            self.set_buttons_enabled(False)

            self.worker = WorkerThread(self.hwid_spoofer.restore_all_hwids)
            self.worker.finished.connect(self.on_hwid_restore_finished)
            self.worker.start()

    def on_hwid_restore_finished(self, success, msg):
        self.set_buttons_enabled(True)
        if success:
            self.log_message("Ripristino HWID completato con successo!")
            self.statusBar.showMessage("Operazione completata")
            self.refresh_hwid_info()
            QMessageBox.information(
                self, "Operazione Completata",
                "Ripristino HWID completato. Si consiglia un riavvio del sistema per applicare tutte le modifiche."
            )
        else:
            self.log_message(f"Errore durante il ripristino HWID: {msg}")
            self.statusBar.showMessage("Errore")
            QMessageBox.critical(self, "Errore", f"Impossibile completare il ripristino HWID:\n{msg}")

    def show_config_dialog(self):
        dialog = ConfigDialog(self.config, self)
        if dialog.exec_():
            self.config = dialog.get_config()
            self.hwid_spoofer.config = self.config
            try:
                with open(self.hwid_spoofer.config_file, "w") as f:
                    json.dump(self.config, f, indent=2)
                self.log_message("Configurazione salvata con successo.")
            except IOError as e:
                self.log_message(f"Errore durante il salvataggio della configurazione: {e}")

    def backup_registry(self):
        if not self.spoofer.is_admin():
            QMessageBox.warning(self, "Permessi insufficienti",
                               "Questa operazione richiede privilegi di amministratore.")
            return

        default_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        suggested = os.path.join(default_dir, f"full_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.reg")
        backup_file, _ = QFileDialog.getSaveFileName(
            self, "Salva backup registro", suggested, "Registry files (*.reg);;All files (*)"
        )
        if not backup_file:
            return

        try:
            cmd = ["reg", "export", r"HKLM\SYSTEM", backup_file, "/y"]
            subprocess.run(cmd, check=True, capture_output=True)
            self.log_message(f"Backup del registro salvato in: {backup_file}")
            QMessageBox.information(self, "Backup Completato",
                                   f"Backup del registro salvato in:\n{backup_file}")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="replace")
            self.log_message(f"Errore durante il backup del registro: {err}")
            QMessageBox.critical(self, "Errore", f"Impossibile eseguire il backup del registro:\n{err}")

    def show_about_dialog(self):
        QMessageBox.about(self, "Informazioni",
                         "Windows MAC & HWID Spoofer\n\n"
                         "Versione: 1.0\n"
                         "Un tool per la modifica di indirizzi MAC e identificatori hardware su Windows.\n\n"
                         "AVVERTENZA: L'utilizzo di questo strumento per bypassare sistemi anti-cheat potrebbe "
                         "violare i termini di servizio di alcuni giochi. Utilizzare con responsabilita.")


def run_gui():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())