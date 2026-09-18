import json
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, 
                            QCheckBox, QLabel, QComboBox, QPushButton, 
                            QDialogButtonBox, QFormLayout, QSpinBox)
from PyQt5.QtCore import Qt

class ConfigDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Configurazione")
        self.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # Sezione generale
        general_group = QGroupBox("Impostazioni Generali")
        general_layout = QFormLayout(general_group)
        
        self.cb_auto_save = QCheckBox()
        self.cb_auto_save.setChecked(self.config.get("auto_save_originals", True))
        general_layout.addRow("Salva automaticamente gli originali:", self.cb_auto_save)
        
        self.cb_backup = QCheckBox()
        self.cb_backup.setChecked(self.config.get("backup_registry", True))
        general_layout.addRow("Backup del registro:", self.cb_backup)
        
        self.cb_restart = QCheckBox()
        self.cb_restart.setChecked(self.config.get("require_restart", True))
        general_layout.addRow("Richiede riavvio:", self.cb_restart)
        
        self.combo_log_level = QComboBox()
        self.combo_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.combo_log_level.setCurrentText(self.config.get("log_level", "INFO"))
        general_layout.addRow("Livello di log:", self.combo_log_level)
        
        layout.addWidget(general_group)
        
        # Sezione MAC
        mac_group = QGroupBox("Impostazioni MAC")
        mac_layout = QFormLayout(mac_group)
        
        self.spinbox_mac_prefix = QSpinBox()
        self.spinbox_mac_prefix.setRange(0, 255)
        self.spinbox_mac_prefix.setValue(int(self.config.get("default_mac_prefix", "02"), 16))
        mac_layout.addRow("Prefisso MAC (esadecimale):", self.spinbox_mac_prefix)
        
        layout.addWidget(mac_group)
        
        # Sezione HWID
        hwid_group = QGroupBox("Componenti HWID")
        hwid_layout = QVBoxLayout(hwid_group)
        
        hwid_components = self.config.get("hwid_components", {})
        
        self.cb_machine_guid = QCheckBox("Machine GUID")
        self.cb_machine_guid.setChecked(hwid_components.get("machine_guid", True))
        hwid_layout.addWidget(self.cb_machine_guid)
        
        self.cb_disk_serial = QCheckBox("Numero di serie del disco")
        self.cb_disk_serial.setChecked(hwid_components.get("disk_serial", True))
        hwid_layout.addWidget(self.cb_disk_serial)
        
        self.cb_bios_uuid = QCheckBox("UUID del BIOS")
        self.cb_bios_uuid.setChecked(hwid_components.get("bios_uuid", True))
        hwid_layout.addWidget(self.cb_bios_uuid)
        
        self.cb_motherboard_serial = QCheckBox("Numero di serie della scheda madre")
        self.cb_motherboard_serial.setChecked(hwid_components.get("motherboard_serial", True))
        hwid_layout.addWidget(self.cb_motherboard_serial)
        
        self.cb_processor_id = QCheckBox("ID del processore")
        self.cb_processor_id.setChecked(hwid_components.get("processor_id", True))
        hwid_layout.addWidget(self.cb_processor_id)
        
        layout.addWidget(hwid_group)
        
        # Pulsanti
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_config(self):
        """Restituisce la configurazione aggiornata"""
        self.config["auto_save_originals"] = self.cb_auto_save.isChecked()
        self.config["backup_registry"] = self.cb_backup.isChecked()
        self.config["require_restart"] = self.cb_restart.isChecked()
        self.config["log_level"] = self.combo_log_level.currentText()
        self.config["default_mac_prefix"] = f"{self.spinbox_mac_prefix.value():02X}"
        
        hwid_components = self.config.get("hwid_components", {})
        hwid_components["machine_guid"] = self.cb_machine_guid.isChecked()
        hwid_components["disk_serial"] = self.cb_disk_serial.isChecked()
        hwid_components["bios_uuid"] = self.cb_bios_uuid.isChecked()
        hwid_components["motherboard_serial"] = self.cb_motherboard_serial.isChecked()
        hwid_components["processor_id"] = self.cb_processor_id.isChecked()
        self.config["hwid_components"] = hwid_components
        
        return self.config