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


## EXE one-file e modalita VT-x Lab

Per creare l'eseguibile finale:

1. Compila e firma il driver corrente in
   `driver\x64\ReleaseTest\hwid_virtualization_driver.sys`.
2. Esegui `python build.py`.
3. L'output viene creato come `dist\HWIDSpoofer.exe`.

La build PyInstaller usa `--onefile`, `--windowed` e `--uac-admin`.
Il driver incorporato viene copiato a runtime in un percorso stabile sotto
`%ProgramData%\HWIDSpoofer\driver\`, invece di essere caricato
direttamente dalla cartella temporanea di PyInstaller.

Quando il Windows hypervisor e' attivo, l'EXE propone in modo esplicito la
modalita VT-x Lab. Se l'utente conferma, l'app:

- crea una copia temporanea della voce BCD corrente;
- imposta `hypervisorlaunchtype off` solo sulla copia;
- usa `bcdedit /bootsequence` per selezionarla soltanto al prossimo boot;
- crea un'attivita ONLOGON con privilegi elevati per riprendere il flusso;
- riavvia Windows;
- al resume carica il driver e verifica VT-x/EPT;
- pianifica la rimozione sicura della voce temporanea quando non e' piu'
  la voce di boot corrente.

Il boot Windows predefinito non viene modificato. Il flusso non sospende
BitLocker automaticamente e non modifica o aggira configurazioni VBS imposte
tramite policy. L'avvio effettivo del laboratorio VMX/EPT resta un'azione
esplicita.
