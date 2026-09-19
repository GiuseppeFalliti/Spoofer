import sys
import os
import ctypes
import subprocess

# ---------------------------------------------------------------------------
# Utility: in modalità --windowed non esiste sys.stdin/stdout.
# Reindirizza gli stream mancanti a devnull per evitare crash successivi
# e usa MessageBoxW per i dialoghi bloccanti al posto di input().
# ---------------------------------------------------------------------------
def _fix_windowed_streams() -> None:
    """Reindirizza stdout/stderr a NUL se non disponibili (--windowed)."""
    for attr in ("stdout", "stderr"):
        if getattr(sys, attr, None) is None:
            setattr(sys, attr, open(os.devnull, "w"))


def _msgbox(title: str, message: str, icon: int = 0x10) -> None:
    """Mostra una MessageBox di Windows bloccante (non richiede console).

    icon: 0x10 = MB_ICONERROR, 0x30 = MB_ICONWARNING, 0x40 = MB_ICONINFO
    """
    ctypes.windll.user32.MessageBoxW(0, message, title, icon)


def _no_stdin() -> bool:
    """Restituisce True se non c'è una console collegata (modalità --windowed)."""
    return getattr(sys, "stdin", None) is None


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _ask_yes_no(title: str, message: str) -> bool:
    # MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2
    result = ctypes.windll.user32.MessageBoxW(
        0,
        message,
        title,
        0x00000004 | 0x00000030 | 0x00000100,
    )
    return result == 6  # IDYES


def _relaunch_as_admin() -> bool:
    """Rilancia il processo con UAC mantenendo gli argomenti correnti."""
    try:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            parameters = subprocess.list2cmdline(sys.argv[1:])
        else:
            executable = sys.executable
            parameters = subprocess.list2cmdline(
                [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            )

        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            os.getcwd(),
            1,
        )
        return rc > 32
    except Exception:
        return False


def _handle_virtualization_bootstrap() -> bool:
    """Gestisce il boot VT-x Lab. False indica che il processo deve terminare."""
    from core.virtualization_manager import VirtualizationManager

    manager = VirtualizationManager()
    cleanup_requested = "--cleanup-vtx-lab" in sys.argv
    resume_requested = "--resume-vtx-lab" in sys.argv

    if cleanup_requested:
        try:
            manager.cleanup_after_lab_if_safe()
        except Exception as exc:
            _msgbox(
                "Pulizia VT-x Lab",
                "Non e' stato possibile rimuovere automaticamente la voce "
                f"temporanea di boot:\n\n{exc}",
                icon=0x30,
            )
        return True

    if resume_requested:
        try:
            capabilities = manager.finish_resume()
        except Exception as exc:
            _msgbox(
                "VT-x Lab - errore",
                "Impossibile completare il resume VT-x Lab:\n\n"
                f"{exc}\n\n"
                "Windows continuera' con la configurazione corrente.",
                icon=0x10,
            )
            return True

        if (
            capabilities.vtx_supported
            and capabilities.ept_supported
            and not capabilities.vmx_blocked
            and not capabilities.hypervisor_present
        ):
            _msgbox(
                "VT-x Lab pronto",
                "Riavvio VT-x Lab completato.\n\n"
                f"VT-x: SI\n"
                f"EPT: SI\n"
                f"Hypervisor Windows: NO\n"
                f"Processori logici: {capabilities.processor_count}\n\n"
                "Il driver kernel e' stato caricato. "
                "L'avvio del laboratorio VMX/EPT resta un'azione esplicita "
                "dall'applicazione.",
                icon=0x40,
            )
        else:
            _msgbox(
                "VT-x Lab non disponibile",
                "Il driver e' stato caricato, ma i requisiti VT-x/EPT "
                "non risultano disponibili:\n\n"
                f"VT-x: {capabilities.vtx_supported}\n"
                f"EPT: {capabilities.ept_supported}\n"
                f"VMX bloccato: {capabilities.vmx_blocked}\n"
                f"Hypervisor Windows: {capabilities.hypervisor_present}",
                icon=0x30,
            )
        return True

    try:
        hypervisor_present = manager.is_hypervisor_present()
    except Exception as exc:
        _msgbox(
            "Controllo virtualizzazione",
            "Non e' stato possibile verificare lo stato dell'hypervisor "
            f"Windows:\n\n{exc}\n\n"
            "L'applicazione verra' avviata senza modificare il boot.",
            icon=0x30,
        )
        return True

    if not hypervisor_present:
        return True

    if manager.is_vbs_managed_by_policy():
        _msgbox(
            "VT-x Lab non disponibile",
            "La Virtualization Based Security risulta configurata tramite "
            "criteri di Windows.\n\n"
            "L'applicazione non modifichera' o aggirera' policy gestite.",
            icon=0x30,
        )
        return True

    bitlocker = manager.bitlocker_protection_enabled()
    bitlocker_note = ""
    if bitlocker is True:
        bitlocker_note = (
            "\n\nBitLocker risulta attivo. La configurazione non verra' "
            "sospesa automaticamente: assicurati di avere disponibile la "
            "chiave di ripristino prima di continuare."
        )

    confirmed = _ask_yes_no(
        "Preparare VT-x Lab?",
        "Windows Hypervisor e' attivo e impedisce l'accesso diretto a VT-x/EPT.\n\n"
        "L'applicazione puo' creare una voce di avvio temporanea che, SOLO "
        "per il prossimo riavvio, avvia Windows con l'hypervisor disattivato.\n\n"
        "Il boot Windows normale non viene modificato. Hyper-V, WSL2, "
        "Windows Sandbox e le funzioni che dipendono da VBS non saranno "
        "disponibili durante quella sessione."
        + bitlocker_note
        + "\n\nRiavviare ora nella modalita' VT-x Lab?",
    )

    if not confirmed:
        return True

    try:
        manager.prepare_one_shot_lab_boot()
    except Exception as exc:
        _msgbox(
            "Preparazione VT-x Lab fallita",
            f"Impossibile preparare il boot temporaneo:\n\n{exc}",
            icon=0x10,
        )
        return True

    _msgbox(
        "VT-x Lab",
        "La modalita' VT-x Lab e' pronta. Il PC verra' riavviato ora.\n\n"
        "Dopo l'accesso a Windows l'applicazione ripartira' automaticamente "
        "e verifichera' VT-x/EPT.",
        icon=0x40,
    )
    manager.reboot_now()
    return False


def main():
    _fix_windowed_streams()

    if not is_admin():
        if _relaunch_as_admin():
            return

        msg = (
            "Questo programma richiede privilegi di amministratore.\n\n"
            "La richiesta UAC non e' stata completata."
        )
        _msgbox("Privilegi insufficienti", msg, icon=0x10)
        sys.exit(1)

    if not _handle_virtualization_bootstrap():
        return

    try:
        from gui.main_window import run_gui
        run_gui()
    except ImportError as e:
        err = f"Impossibile caricare l'interfaccia grafica:\n{e}"
        if _no_stdin():
            _msgbox("Errore di avvio", err, icon=0x10)
        else:
            print(err)
            print("Avvio in modalita terminale...\n")
            run_cli()


def run_cli():
    from core.mac_spoofer import MacSpoofer
    from core.hwid_spoofer import HwidSpoofer

    spoofer = MacSpoofer()
    hwid_spoofer = HwidSpoofer()
    
    print("=" * 50)
    print("  Windows MAC & HWID Spoofer")
    print("=" * 50)
    
    choice = input("\nCosa vuoi fare?\n1. Spoof MAC address\n2. Spoof Hardware ID (HWID)\nScelta (1-2): ")
    
    if choice == "1":
        # Codice esistente per lo spoofing MAC
        interfaces = spoofer.get_network_interfaces()

        if not interfaces:
            print("Nessuna interfaccia di rete trovata.")
            input("\nPremi Invio per uscire...")
            return

        print("\nInterfacce di rete disponibili:")
        for i, iface in enumerate(interfaces):
            print(f"  {i + 1}. {iface['name']} - MAC: {iface['mac']}")

        try:
            iface_choice = int(input("\nScegli un'interfaccia (numero): ")) - 1
            if iface_choice < 0 or iface_choice >= len(interfaces):
                print("Scelta non valida.")
            input("\nPremi Invio per uscire...")
            return
        except ValueError:
            print("Input non valido.")
            input("\nPremi Invio per uscire...")
            return

        selected = interfaces[iface_choice]
        iface_name = selected["name"]
        current_mac = selected["mac"]

        print(f"\nInterfaccia: {iface_name}")
        print(f"MAC attuale: {current_mac}")

        new_mac = spoofer.generate_random_mac()
        custom = input(f"Inserisci MAC personalizzato (Invio per {new_mac}): ").strip()
        if custom:
            if spoofer.validate_mac(custom):
                new_mac = custom
            else:
                print("Formato non valido, uso MAC casuale.")

        print(f"\nCambio MAC a {new_mac}...")
        if spoofer.change_mac(iface_name, new_mac):
            print("MAC cambiato con successo!")
            updated = spoofer.get_current_mac(iface_name)
            if updated:
                print(f"Verifica: {updated}")
        else:
            print("Errore durante il cambio MAC.")

    elif choice == "2":
        # Codice per lo spoofing HWID
        print("\nInformazioni HWID attuali:")
        hwid_info = hwid_spoofer.get_current_hwid_info()
        
        for hwid_name, hwid_value in hwid_info.items():
            print(f"  {hwid_name}: {hwid_value or 'N/D'}")
        
        hwid_choice = input("\nVuoi modificare tutti gli HWID? (s/n): ").lower()
        
        if hwid_choice == "s":
            print("\nInizio spoofing HWID...")
            if hwid_spoofer.spoof_all_hwid():
                print("HWID spoofing completato con successo!")
                print("Si consiglia un riavvio del sistema per applicare tutte le modifiche.")
            else:
                print("Errore durante lo spoofing HWID.")
        else:
            print("\nSeleziona gli identificatori da modificare:")
            print("1. Machine GUID")
            print("2. Numero di serie del disco")
            print("3. UUID del BIOS")
            print("4. Numero di serie della scheda madre")
            print("5. ID del processore")
            
            try:
                id_choice = int(input("Scelta (1-5): "))
                
                if id_choice == 1:
                    print("\nModifica Machine GUID...")
                    if hwid_spoofer.spoof_machine_guid():
                        print("Machine GUID modificato con successo!")
                    else:
                        print("Errore durante la modifica del Machine GUID.")
                elif id_choice == 2:
                    print("\nModifica numero di serie del disco...")
                    if hwid_spoofer.spoof_disk_serial():
                        print("Numero di serie del disco modificato con successo!")
                    else:
                        print("Errore durante la modifica del numero di serie del disco.")
                elif id_choice == 3:
                    print("\nModifica UUID del BIOS...")
                    if hwid_spoofer.spoof_bios_uuid():
                        print("UUID del BIOS modificato con successo!")
                    else:
                        print("Errore durante la modifica dell'UUID del BIOS.")
                elif id_choice == 4:
                    print("\nModifica numero di serie della scheda madre...")
                    if hwid_spoofer.spoof_motherboard_serial():
                        print("Numero di serie della scheda madre modificato con successo!")
                    else:
                        print("Errore durante la modifica del numero di serie della scheda madre.")
                elif id_choice == 5:
                    print("\nModifica ID del processore...")
                    if hwid_spoofer.spoof_processor_id():
                        print("ID del processore modificato con successo!")
                    else:
                        print("Errore durante la modifica dell'ID del processore.")
                else:
                    print("Scelta non valida.")
                
                print("\nSi consiglia un riavvio del sistema per applicare tutte le modifiche.")
            except ValueError:
                print("Input non valido.")
    else:
        print("Scelta non valida.")

    input("\nPremi Invio per uscire...")


if __name__ == "__main__":
    main()

