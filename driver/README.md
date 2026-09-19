# HWID Virtualization Research Driver (WDK)

Questa cartella contiene la traduzione in C/WDK della **logica di controllo**
del prototipo Python `hwid_virtualization_driver.py`.

## Cosa implementa

- `DriverEntry`
- `IRP_MJ_CREATE`
- `IRP_MJ_CLOSE`
- `IRP_MJ_DEVICE_CONTROL`
- device kernel `\\Device\\HwidSpoofer`
- symbolic link `\\DosDevices\\HwidSpoofer`
- accesso user-mode tramite `\\.\\HwidSpoofer`
- i sei IOCTL già usati dalla GUI Python
- tre flag kernel per simulare firmware/HAL/SMBIOS hook on/off
- generazione in memoria di un blob SMBIOS fittizio contenente Type 1

## Cosa NON implementa

Questa versione non modifica SSDT, funzioni kernel, firmware, HAL, tabelle PCI,
SMBIOS del sistema o memoria eseguibile del kernel. Gli IOCTL cambiano soltanto
lo stato delle variabili globali e producono output tramite `DbgPrintEx`.

Il blob SMBIOS viene costruito in memoria a scopo di test ma non viene iniettato
nelle risposte del sistema operativo.

## Struttura

```text
driver/
├── driver.c
├── driver.h
├── hwid_virtualization_driver.vcxproj
├── hwid_virtualization_driver.inf
├── sources
├── dirs
└── README.md
```

## IOCTL

```text
0x80002000  IOCTL_SET_FIRMWARE_HOOK
0x80002004  IOCTL_CLEAR_FIRMWARE_HOOK
0x80002008  IOCTL_SET_HAL_HOOK
0x8000200C  IOCTL_CLEAR_HAL_HOOK
0x80002010  IOCTL_SET_SMBIOS_HOOK
0x80002014  IOCTL_CLEAR_SMBIOS_HOOK
0x00222004  IOCTL_QUERY_FAKE_SMBIOS
```

## Build moderno con Visual Studio + WDK

Prerequisiti:

- Visual Studio con workload **Desktop development with C++**
- Windows SDK
- Windows Driver Kit (WDK)

Da **Developer PowerShell for VS**:

```powershell
msbuild .\driver\hwid_virtualization_driver.vcxproj /p:Configuration=Debug /p:Platform=x64
```

oppure Release:

```powershell
msbuild .\driver\hwid_virtualization_driver.vcxproj /p:Configuration=Release /p:Platform=x64
```

L'output atteso è un file:

```text
hwid_virtualization_driver.sys
```

nella directory di output configurata da MSBuild/WDK.

## `sources` e `dirs`

Sono inclusi perché richiesti nella struttura del progetto e documentano la
vecchia convenzione NTBuild. I WDK moderni usano il file `.vcxproj`; per la
compilazione reale usare quindi il progetto Visual Studio.

## Caricamento in ambiente di test

Un driver kernel deve essere firmato in modo compatibile con la configurazione
di Windows. Per sviluppo e ricerca è consigliabile usare una VM dedicata e la
procedura di test-signing prevista dal WDK.

Il loader Python del repository registra il file come
`SERVICE_KERNEL_DRIVER`, quindi il nome del file prodotto deve restare:

```text
hwid_virtualization_driver.sys
```

## Debug

I cambi di stato vengono registrati con `DbgPrintEx`, ad esempio:

```text
[HwidSpoofer] Firmware hook simulation ENABLED
[HwidSpoofer] HAL hook simulation ENABLED
[HwidSpoofer] SMBIOS hook simulation ENABLED; blob size=...
```

I messaggi possono essere osservati con un debugger kernel/configurazione di
debug appropriata.


## VT-x / EPT research lab

Il branch di ricerca aggiunge `driver/hv/` e tre IOCTL:

```text
0x80002020  IOCTL_START_HYPERVISOR
0x80002024  IOCTL_STOP_HYPERVISOR
0x80002028  IOCTL_SET_SMBIOS_EPT_HOOK
```

La parte VMX esegue il probe di VMX/EPT, alloca VMXON/VMCS per logical
processor, entra/esce da VMX operation con IPI e prepara un EPT identity map
limitato al primo GiB. Il VMCS viene caricato e vengono impostati i controlli
secondari/EPT, ma il branch di laboratorio **non esegue VMLAUNCH** e non
sostituisce lo stato host/guest di Windows.

`IOCTL_SET_SMBIOS_EPT_HOOK` lavora esclusivamente su una pagina SMBIOS Type 1
sintetica allocata dal driver. La pagina viene clonata e modificata, poi una
singola EPT PTE di laboratorio viene preparata per puntare alla shadow page.
Non viene cercato, letto, patchato o rimappato l'SMBIOS reale del computer.

### Hyper-V nested

Eseguire `setup_hypervisor_env.ps1` sull'host Hyper-V. Lo script crea una VM
Generation 2, abilita `ExposeVirtualizationExtensions` a VM spenta e può
configurare RDP/test-signing tramite PowerShell Direct.

Per questo laboratorio non abilitare il ruolo Hyper-V dentro la VM guest:
le estensioni VMX esposte dal parent devono essere disponibili direttamente
al driver di ricerca.

### Debug

I messaggi kernel usano il prefisso:

```text
[HwidHv]
```

Sono registrati probe VMX/EPT, VMXON/VMXOFF, preparazione EPT, mapping della
pagina sintetica e contatori VM-exit/EPT del percorso di laboratorio.
