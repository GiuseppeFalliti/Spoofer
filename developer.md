# Guida per Sviluppatori

## Struttura del Progetto

Il progetto è organizzato in modo modulare per facilitare lo sviluppo e la manutenzione:
Windows-MAC-HWID-Spoofer/
├── core/ # Logica di business
│ ├── init.py
│ ├── mac_spoofer.py # Classe per lo spoofing MAC
│ ├── hwid_spoofer.py # Classe per lo spoofing HWID
│ └── registry_utils.py # Utilità per il registro di sistema
├── gui/ # Interfaccia grafica
│ ├── init.py
│ ├── main_window.py # Finestra principale
│ └── config_dialog.py # Finestra di configurazione
├── data/ # Dati persistenti
│ ├── saved_macs.json # MAC originali salvati
│ ├── saved_hwids.json # HWID originali salvati
│ └── spoofer.log # File di log
├── resources/ # Risorse grafiche
│ └── icon.ico # Icona dell'applicazione
├── main.py # Punto di ingresso
├── requirements.txt # Dipendenze
├── config.json # File di configurazione
├── install.py # Script di installazione
├── build.py # Script di build
└── test.py # Script di test

## Come Contribuire

1. Fare un fork del repository
2. Creare un branch per la nuova funzionalità (`git checkout -b feature/nuova-funzionalità`)
3. Commit delle modifiche (`git commit -am 'Aggiunta nuova funzionalità'`)
4. Push al branch (`git push origin feature/nuova-funzionalità`)
5. Creare una Pull Request

## Standard di Codifica

- Seguire PEP 8 per la formattazione del codice
- Utilizzare docstring per documentare classi e metodi
- Aggiungere test per nuove funzionalità
- Aggiornare la documentazione quando necessario

## Test

Eseguire lo script `test.py` per verificare il funzionamento delle funzionalità principali:
