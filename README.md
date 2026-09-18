# Windows MAC & HWID Spoofer

Guida rapida per avviare l'applicazione.

## Prerequisiti

- Windows 10 o 11 a 64 bit
- Python 3.8 o superiore installato nel PATH

## Primo avvio

Dalla cartella del progetto, apri PowerShell come amministratore ed esegui:

```powershell
python install.py
```

Lo script crea l'ambiente virtuale .venv e installa le dipendenze necessarie.

## Avviare il programma

Esegui sempre come amministratore, altrimenti lo spoofing di MAC e HWID non funzionera:

```powershell
.venv\Scripts\python.exe main.py
```

Si apre la finestra grafica con le sezioni Interfaccia di Rete, Configurazione MAC, Hardware ID e Log Operazioni.

## Verificare che tutto funzioni

Per controllare generatori, parser e utilita del registro senza toccare nulla di sistema:

```powershell
.venv\Scripts\python.exe test.py
```

I test non richiedono privilegi di amministratore.
