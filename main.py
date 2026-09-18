import sys
import os
import ctypes


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def main():
    if not is_admin():
        print("=" * 50)
        print("  Windows MAC Spoofer")
        print("=" * 50)
        print("\nQuesto programma richiede privilegi di amministratore.")
        print("Fai clic destro sull'eseguibile e seleziona 'Esegui come amministratore'.")
        input("\nPremi Invio per uscire...")
        sys.exit(1)

    try:
        from gui.main_window import run_gui
        run_gui()
    except ImportError as e:
        print(f"Impossibile caricare l'interfaccia grafica: {e}")
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

