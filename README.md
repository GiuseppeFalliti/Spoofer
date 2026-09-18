Ecco un file README.md completo che puoi fornire a Codex per l'implementazione del tuo progetto di spoofer per Windows, incluso uno script Python ottimizzato per Windows:

```markdown
# Windows MAC Spoofer

## Descrizione del Progetto

Questo progetto consiste in un'applicazione per Windows che permette di modificare (spooferare) l'indirizzo MAC delle schede di rete. Lo scopo principale è evitare che i giochi anti-cheat identifichino il computer tramite l'indirizzo MAC quando vengono utilizzati cheat, prevenendo così ban permanenti legati all'hardware.

## Funzionalità Principali

- Scansione automatica delle interfacce di rete disponibili
- Modifica dell'indirizzo MAC con valori casuali o personalizzati
- Salvataggio/ripristino degli indirizzi MAC originali
- Interfaccia grafica intuitiva per un facile utilizzo
- Compatibilità con Windows 10/11

## Script di Base per Windows (Python)

```python
import subprocess
import random
import re
import sys
import os
import uuid

def get_network_interfaces():
    """Ottiene la lista delle interfacce di rete disponibili su Windows"""
    try:
        result = subprocess.check_output(["getmac", "/v", "/fo", "csv"], stderr=subprocess.STDOUT)
        interfaces = []
        for line in result.decode().split('\n')[1:]:
            if line.strip():
                parts = line.replace('"', '').split(',')
                if len(parts) >= 4 and parts[3].strip():
                    interfaces.append({
                        'name': parts[0].strip(),
                        'mac': parts[3].strip()
                    })
        return interfaces
    except subprocess.CalledProcessError as e:
        print(f"Errore nell'ottenere le interfacce di rete: {e}")
        return []

def get_current_mac(interface_name):
    """Ottiene l'indirizzo MAC attuale di un'interfaccia specifica"""
    try:
        result = subprocess.check_output(["getmac", "/v", "/nh", "/fo", "csv"], stderr=subprocess.STDOUT)
        for line in result.decode().split('\n'):
            if interface_name in line:
                parts = line.replace('"', '').split(',')
                if len(parts) >= 4 and parts[3].strip():
                    return parts[3].strip()
        return None
    except subprocess.CalledProcessError:
        return None

def generate_random_mac():
    """Genera un indirizzo MAC casuale con il primo byte impostato a 02 (indica un MAC casuale)"""
    return "02:%02x:%02x:%02x:%02x:%02x" % (
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255)
    )

def change_mac(interface_name, new_mac):
    """Cambia l'indirizzo MAC dell'interfaccia di rete specificata su Windows"""
    try:
        # Disattiva l'interfaccia di rete
        subprocess.run(["netsh", "interface", "set", "interface", interface_name, "admin=disable"], check=True)
        
        # Cambia l'indirizzo MAC nel registro di sistema
        import winreg
        key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}"
        
        # Apre la chiave del registro
        reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        
        # Cerca la sottochiave corrispondente all'interfaccia
        for i in range(1000):
            try:
                subkey_name = winreg.EnumKey(reg_key, i)
                subkey_path = f"{key_path}\\{subkey_name}"
                subkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_ALL_ACCESS)
                
                try:
                    # Controlla se questa è l'interfaccia giusta confrontando il DriverDesc
                    driver_desc = winreg.QueryValueEx(subkey, "DriverDesc")[0]
                    if interface_name in driver_desc:
                        # Imposta il nuovo indirizzo MAC
                        winreg.SetValueEx(subkey, "NetworkAddress", 0, winreg.REG_SZ, new_mac)
                        winreg.CloseKey(subkey)
                        break
                except FileNotFoundError:
                    pass
                
                winreg.CloseKey(subkey)
            except OSError:
                break
        
        winreg.CloseKey(reg_key)
        
        # Riattiva l'interfaccia di rete
        subprocess.run(["netsh", "interface", "set", "interface", interface_name, "admin=enable"], check=True)
        
        return True
    except Exception as e:
        print(f"Errore durante il cambio dell'indirizzo MAC: {e}")
        return False

def main():
    # Controlla se l'utente ha i permessi di amministratore
    try:
        is_admin = os.getuid() == 0
    except AttributeError:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    
    if not is_admin:
        print("Questo script richiede privilegi di amministratore. Eseguilo come amministratore.")
        input("Premi Invio per uscire...")
        sys.exit(1)
    
    # Ottieni la lista delle interfacce di rete
    interfaces = get_network_interfaces()
    
    if not interfaces:
        print("Nessuna interfaccia di rete trovata.")
        input("Premi Invio per uscire...")
        return
    
    # Mostra le interfacce disponibili
    print("Interfacce di rete disponibili:")
    for i, interface in enumerate(interfaces):
        print(f"{i+1}. {interface['name']} - MAC: {interface['mac']}")
    
    # Chiedi all'utente di scegliere un'interfaccia
    try:
        choice = int(input("Scegli un'interfaccia (inserisci il numero): ")) - 1
        if choice < 0 or choice >= len(interfaces):
            print("Scelta non valida.")
            input("Premi Invio per uscire...")
            return
        
        selected_interface = interfaces[choice]
        interface_name = selected_interface['name']
        current_mac = selected_interface['mac']
        
        print(f"Interfaccia selezionata: {interface_name}")
        print(f"Indirizzo MAC attuale: {current_mac}")
        
        # Genera un nuovo indirizzo MAC casuale
        new_mac = generate_random_mac()
        
        # Chiedi all'utente se vuole usare un MAC personalizzato
        custom_mac = input(f"Inserisci un MAC personalizzato (lascia vuoto per usare {new_mac}): ").strip()
        if custom_mac:
            # Validazione del formato MAC
            if not re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', custom_mac):
                print("Formato MAC non valido. Uso quello casuale.")
            else:
                new_mac = custom_mac
        
        print(f"Cambio dell'indirizzo MAC a {new_mac}...")
        
        # Cambia l'indirizzo MAC
        if change_mac(interface_name, new_mac):
            print("Indirizzo MAC cambiato con successo!")
            
            # Verifica che il cambio sia avvenuto con successo
            updated_mac = get_current_mac(interface_name)
            if updated_mac and updated_mac.replace('-', ':') == new_mac.replace('-', ':'):
                print(f"Verifica completata. Nuovo MAC: {updated_mac}")
            else:
                print("Attenzione: la verifica non è riuscita. Potrebbe essere necessario riavviare.")
        else:
            print("Impossibile cambiare l'indirizzo MAC.")
        
        input("Premi Invio per uscire...")
    except ValueError:
        print("Input non valido.")
        input("Premi Invio per uscire...")

if __name__ == "__main__":
    main()
```

## Requisiti di Sistema

- Windows 10 o 11
- Python 3.7 o superiore
- Privilegi di amministratore per eseguire l'applicazione

## Struttura del Progetto

```
windows-mac-spoofer/
├── README.md
├── main.py                 # Script principale
├── gui/
│   ├── __init__.py
│   ├── main_window.py      # Finestra principale dell'interfaccia grafica
│   └── resources/
│       └── icon.ico        # Icona dell'applicazione
├── core/
│   ├── __init__.py
│   ├── mac_spoofer.py      # Funzionalità di spoofer
│   └── registry_utils.py   # Utilità per la modifica del registro
├── data/
│   └── saved_macs.json     # File per salvare i MAC originali
└── requirements.txt        # Dipendenze Python
```

### 11. Aggiornare il file `README.md`

Aggiungi una sezione per descrivere le funzionalità HWID:

```markdown
## Funzionalità HWID

Oltre allo spoofing degli indirizzi MAC, il progetto ora supporta anche la modifica degli identificatori hardware (HWID):

- Modifica del Machine GUID
- Modifica del numero di serie del disco
- Modifica dell'UUID del BIOS
- Modifica del numero di serie della scheda madre
- Modifica dell'ID del processore
- Salvataggio e ripristino degli identificatori hardware originali

## Utilizzo

### Interfaccia Grafica

1. Avvia l'applicazione come amministratore
2. Per lo spoofing MAC:
   - Seleziona un'interfaccia di rete dalla lista
   - Genera un MAC casuale o inseriscine uno personalizzato
   - Clicca "Applica MAC" per applicare le modifiche
   - Clicca "Ripristina Originale" per ripristinare il MAC originale
3. Per lo spoofing HWID:
   - Clicca "Aggiorna Info HWID" per visualizzare gli identificatori hardware attuali
   ### 11. Aggiornare il file `README.md`

Aggiungi una sezione per descrivere le funzionalità HWID:

```markdown
## Funzionalità HWID

Oltre allo spoofing degli indirizzi MAC, il progetto ora supporta anche la modifica degli identificatori hardware (HWID):

- Modifica del Machine GUID
- Modifica del numero di serie del disco
- Modifica dell'UUID del BIOS
- Modifica del numero di serie della scheda madre
- Modifica dell'ID del processore
- Salvataggio e ripristino degli identificatori hardware originali

## Utilizzo

### Interfaccia Grafica

1. Avvia l'applicazione come amministratore
2. Per lo spoofing MAC:
   - Seleziona un'interfaccia di rete dalla lista
   - Genera un MAC casuale o inseriscine uno personalizzato
   - Clicca "Applica MAC" per applicare le modifiche
   - Clicca "Ripristina Originale" per ripristinare il MAC originale
3. Per lo spoofing HWID:
   - Clicca "Aggiorna Info HWID" per visualizzare gli identificatori hardware attuali
   - Clicca "Ripristina HWID Originali" per ripristinare gli identificatori hardware originali
4. Controlla il log delle operazioni per verificare l'esito delle modifiche

### Interfaccia a Riga di Comando (CLI)

1. Esegui lo script come amministratore
2. Scegli tra "Spoof MAC address" o "Spoof Hardware ID (HWID)"
3. Segui le istruzioni per completare l'operazione desiderata

## Avvertenze Importanti

- L'utilizzo di questo strumento per bypassare sistemi anti-cheat potrebbe violare i termini di servizio di alcuni giochi
- Si consiglia sempre di salvare gli identificatori originali prima di applicare modifiche
- Potrebbe essere necessario riavviare il sistema per applicare completamente tutte le modifiche
- Alcuni identificatori hardware potrebbero essere protetti da sistemi di sicurezza più avanzati

## Note Importanti

- Alcuni giochi anti-cheat più avanzati utilizzano metodi di identificazione più sofisticati che non si limitano all'indirizzo MAC
- Potrebbe essere necessario riavviare il computer affinché le modifiche abbiano effetto completo
- L'utilizzo di questo strumento potrebbe violare i termini di servizio di alcuni giochi

## Installazione

1. Clonare il repository
2. Installare le dipendenze con `pip install -r requirements.txt`
3. Eseguire come amministratore

## Licenza

Questo software è fornito "così com'è" senza garanzia di alcun tipo. L'utente è responsabile dell'utilizzo appropriato dello strumento.