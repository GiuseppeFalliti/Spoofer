# Architettura Tecnica del Progetto Windows MAC & HWID Spoofer

Questo documento descrive la struttura interna del progetto, il ruolo di ciascun modulo e le interazioni tra i componenti. E' rivolto a chi mantiene o estende il codice.

## Panoramica dell'Architettura

Il progetto segue un'architettura a strati separata:

1.  **Presentation Layer (GUI)**: PyQt5. Finestra principale piu dialogo di configurazione.
2.  **Business Logic Layer (Core)**: due classi sorelle, MacSpoofer e HwidSpoofer, indipendenti dalla UI.
3.  **Data Access / Utility Layer**: RegistryUtils isola ogni contatto diretto col registro; il filesystem (data/) gestisce persistenza e log.
4.  **Configuration**: config.json pilota comportamento e selezione dei componenti; viene letto dal core e scritto dal ConfigDialog.
5.  **Entry Point + Tooling**: main.py avvia l'app; build.py, install.py e test.py sono script ausiliari di packaging, setup e verifica.
---

## Struttura delle Cartelle e dei File

### Radice del Progetto

#### main.py
Punto di ingresso.
- Verifica i privilegi di amministratore all'avvio (necessari per scrivere nel registro).
- Tenta di caricare la GUI (gui.main_window.run_gui).
- In caso di ImportError esegue un fallback CLI (run_cli) che offre lo spoofing MAC da terminale.
- Flusso: Check Admin -> Try GUI -> GUI OR CLI.

#### config.json
File di configurazione utente, JSON piatto. Controlla sia il comportamento generale sia quali componenti HWID partecipare allo spoofing.
- Chiavi generali: auto_save_originals, backup_registry, require_restart, log_level, default_mac_prefix.
- hwid_components: mappa booleana { machine_guid, disk_serial, bios_uuid, motherboard_serial, processor_id }.
- Letto da HwidSpoofer.load_config(); se assente o corrotto, il core usa un set di default内置.

#### requirements.txt
Dipendenze esterne. Attualmente PyQt5>=5.15.0. Moduli come winreg, subprocess, ctypes, uuid, json fanno parte della stdlib Python.
#### install.py
Script di setup assistito.
- install_requirements(): lancia pip install -r requirements.txt.
- create_shortcut(): crea un collegamento sul desktop puntando a main.py tramite python.exe. Richiede winshell e pywin32; se mancanti stampa un avviso e prosegue senza blocco.

#### build.py
Packaging in eseguibile standalone via PyInstaller.
- Opzioni chiave: --onefile, --windowed, inclusione di data/ e config.json come add-data, hidden-import per PyQt5/winreg/ctypes.
- Usa gui/resources/icon.ico come icona solo se presente.
- Auto-installazione di PyInstaller se non disponibile.
- Output atteso: dist/Windows_MAC_HWID_Spoofer.exe.

#### test.py
Suite di smoke-test manuale (non pytest).
- test_mac_spoofer(): valida generate_random_mac, normalize_mac, mac_for_registry.
- test_hwid_spoofer(): valida generate_random_uuid, generate_random_serial e load_config.
- test_registry_utils(): lettura non distruttiva del MachineGuid corrente.
- Tutte le prove evitano scritture sul registro; servono a verificare import e logica pura.
#### developer.md
Guida per contributori: struttura ad alto livello, flusso di lavoro git, standard PEP 8 e docstring, riferimento rapido a test.py.

#### README.md
Documentazione orientata all'utente finale: installazione, uso rapido, disclaimer.

#### ARCHITECTURE.md
Questo documento.
---

### Cartella core/

Logica pura, nessuna dipendenza dalla UI.

#### core/__init__.py
Esporta MacSpoofer e RegistryUtils verso l'esterno del pacchetto.

#### core/registry_utils.py
Classe statica RegistryUtils. Unico punto di contatto col registro.
- Costante REG_KEY_PATH: classe di dispositivo Network Adapter ({4D36E972-E325-11CE-BFC1-08002BE10318}).
- find_adapter_subkey(interface_name): scorre le sottochiavi numeriche e fa match su DriverDesc; restituisce il percorso completo della sottochiave.
- set_registry_value(hive, key_path, value_name, data): scrittura REG_SZ, usata sia per NetworkAddress (MAC) sia per i campi HWID.
- get_registry_value(hive, key_path, value_name): lettura sicura con gestione errori.
- delete_registry_value(...): rimuove una forzatura per tornare al valore nativo.
- backup_registry_key(key_path, backup_file): export .reg pre-write, usato quando backup_registry e attivo.
#### core/mac_spoofer.py
Classe MacSpoofer. Orchestrazione dello spoofing MAC.
- get_network_interfaces(): esegue getmac /v /fo csv via subprocess e restituisce [{name, mac}].
- get_current_mac(interface_name): rilegge l'output CSV filtrando per nome.
- generate_random_mac(): prefisso 02 (locally administered) configurabile tramite default_mac_prefix.
- validate_mac(s), normalize_mac(s), mac_for_registry(s): parsing, normalizzazione a AA:BB:... e conversione in forma compatta AABBCCDDEEFF richiesta dal campo NetworkAddress.
- change_mac(name, new_mac): disabilita NIC via netsh, delega la scrittura a RegistryUtils, riabilita NIC.
- save_original_mac() / restore_original_mac(): persistenza su data/saved_macs.json con timestamp.
- is_admin(): wrapper ctypes.windll.shell32.IsUserAnAdmin().
- Setup logging su data/spoofer.log al costruttore.
#### core/hwid_spoofer.py
Classe HwidSpoofer. Speculare a MacSpoofer ma operante su identificatori hardware letti/scritti nel registro.
- Costruttore istanzia RegistryUtils, carica config.json e prepara data/.
- load_config(): legge config.json; in assenza restituisce un default hardcoded con tutti i componenti abilitati.
- Generatori: generate_random_uuid() (uuid4 maiuscolo) e generate_random_serial(length) (alfanumerico uppercase).
- Singoli spoof_* ciascuno mappato a una coppia hive/chiove/valore:
  - spoof_machine_guid -> HKLM SOFTWARE\Microsoft\Cryptography : MachineGuid
  - spoof_disk_serial -> HKLM SOFTWARE\Microsoft\Windows NT\CurrentVersion : VolumeSerialNumber
  - spoof_bios_uuid -> HKLM SYSTEM\HardwareConfig\Current : BaseBoardUUID
  - spoof_motherboard_serial -> HKLM SYSTEM\HardwareConfig\Current : BaseBoardSerialNumber
  - spoof_processor_id -> HKLM SYSTEM\HardwareConfig\Current : ProcessorID
- spoof_all_hwid(): esegue tutti e cinque e ritorna AND dei risultati.
- spoof_selected_hwids(): rispetta hwid_components da config.json, saltando quelli disabilitati.
- get_current_hwid_info(): lettura non distruttiva dei cinque valori attuali, restituita come dizionario {nome: valore}.
- save_original_hwid / load_saved_hwids / _write_saved_hwids: persistenza su data/saved_hwids.json.
- restore_all_hwids(): ricostruisce ogni campo dai valori originali salvati usando i mirror privati _restore_*.
Nota tecnica: i percorsi HWID usati sono chiavi di registro leggibili/modificabili da utenti admin, ma NON corrispondono necessariamente ai valori SMBIOS/DMI reali esposti via WMI. Alcuni anti-cheat leggono direttamente da WMI o firmware, quindi queste scritture hanno efficacia limitata e vanno considerate sperimentali. La documentazione resta focalizzata sul meccanismo implementato, non sull'efficacia contro sistemi specifici.
---

### Cartella gui/

#### gui/__init__.py
Espone MainWindow.

#### gui/main_window.py
Finestra principale QMainWindow.
- Widget: QComboBox interfacce, QLineEdit MAC custom, QPushButton (Spoof Random, Apply Custom, Restore Original, Refresh, Config, Spoof HWID Selected, Restore HWID), QTextEdit log integrato, QStatusBar.
- WorkerThread(QThread): esegue le chiamate core bloccanti fuori dal thread UI ed emette finished(bool, str); la UI aggiorna solo su segnale.
- Integrazione core: istanzia MacSpoofer e HwidSpoofer e invoca i relativi metodi passando i parametri scelti dall'utente.
- Apertura ConfigDialog tramite pulsante Config; al ritorno salva config.json e ricarica i valori nel core.

#### gui/config_dialog.py
QDialog modale per editare config.json.
- Sezione Impostazioni Generali: checkbox auto_save_originals, backup_registry, require_restart; combo log_level (DEBUG/INFO/WARNING/ERROR).
- Sezione Impostazioni MAC: QSpinBox default_mac_prefix interpretato come esadecimale (0-255).
- Sezione Componenti HWID: cinque QCheckBox, uno per campo, vincolati alla mappa hwid_components.
- get_config(): raccoglie i widget e restituisce il dizionario aggiornato pronto per la serializzazione JSON.

#### gui/resources/
Cartella asset. icon.ico viene usata da build.py se presente; altrimenti il build procede senza icona.
---

### Cartella data/

Stato locale applicativo. Tutti i file qui sono generati o modificati a runtime.

#### data/saved_macs.json
Mappa { nome_interfaccia: { original_mac, saved_at } }. Consente il ripristino anche dopo riavvii, fintantoche il nome dell'interfaccia resta stabile.

#### data/saved_hwids.json
Mappa { nome_hwid: { original_value, saved_at } }. Stessa idea per i cinque identificatori hardware.

#### data/spoofer.log
Log testuale piano scritto dal logger configurato in mac_spoofer.py (e riusato da hwid_spoofer.py). Registra errori di registro, esiti netsh, risultati aggregati degli spoof. Fondamentale per debug quando la GUI mostra messaggi generici.

---

## Flussi Dati Critici

### Spoofing MAC

User -> GUI (Spoof Random) -> WorkerThread(change_mac) -> OS netsh disable -> RegistryUtils.find_adapter_subkey -> SetValueEx(NetworkAddress) -> OS netsh enable -> signal finished -> GUI aggiorna status bar e log.

### Spoofing HWID selezionato

User -> GUI (Spoof HWID Selected) -> WorkerThread(spoof_selected_hwids) -> HwidSpoofer itera hwid_components da config.json -> per ogni componente abilitato: RegistryUtils.set_registry_value sulla chiave target -> ritorna AND -> signal finished -> GUI logga esiti singoli.

### Caricamento configurazione

App boot -> HwidSpoofer.__init__ -> load_config() -> se config.json manca usa default interni. Pulsante Config -> ConfigDialog(config) -> accept -> get_config() -> main scrive config.json -> successivo spoof rispecchia le scelte.
---

## Considerazioni Tecniche e Limitazioni

1. Persistenza post-riavvio: la modifica MAC via registro NetworkAddress sopravvive finche la sottochiave esiste; driver aggiornati o reset di rete possono cancellarla. Il mapping Nome Interfaccia -> Sottochiave va riverificato dopo cambi hardware.
2. Virtualizzazione: il filtro sulle interfacce virtuali basato su getmac non e infallibile; l'utente deve confermare manualmente di non stare toccando una NIC VM.
3. Campo HWID vs SMBIOS reale: le chiavi usate da HwidSpoofer sono copie di comodo nel registro, non le tabelle ACPI/SMBIOS esposte via WMI. Per questo l'effetto pratico su sistemi che interrogano WMI/firmware e limitato; il modulo va trattato come sperimentale.
4. Sicurezza registro: quando backup_registry e attivo, prima di ogni scrittura viene tentato un export .reg; se fallisce per permessi, l'operazione viene interrotta per evitare corruzione irreversibile.
5. Privilegi: tutte le scritture richiedono HKLM, quindi esecuzione come amministratore obbligatoria. main.py blocca l'avvio senza elevazione.
6. Thread safety: le operazioni core sono invocate esclusivamente dentro WorkerThread; nessun accesso diretto dal thread UI, cosi da non congelare la finestra durante netsh o registrazioni lunghe.
