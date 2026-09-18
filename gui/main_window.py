import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QLineEdit, QGroupBox,
    QTextEdit, QMessageBox, QStatusBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.mac_spoofer import MacSpoofer


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
        self.interfaces = []
        self.worker = None
        self.init_ui()
        self.refresh_interfaces()

    def init_ui(self):
        self.setWindowTitle("Windows MAC Spoofer")
        self.setMinimumSize(600, 500)

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


def run_gui():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

