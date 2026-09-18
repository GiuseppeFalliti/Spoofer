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

    spoofer = MacSpoofer()
    interfaces = spoofer.get_network_interfaces()

    if not interfaces:
        print("Nessuna interfaccia di rete trovata.")
        input("Premi Invio per uscire...")
        return

    print("Interfacce di rete disponibili:")
    for i, iface in enumerate(interfaces):
        print(f"  {i + 1}. {iface['name']} - MAC: {iface['mac']}")

    try:
        choice = int(input("\nScegli un'interfaccia (numero): ")) - 1
        if choice < 0 or choice >= len(interfaces):
            print("Scelta non valida.")
            input("Premi Invio per uscire...")
            return
    except ValueError:
        print("Input non valido.")
        input("Premi Invio per uscire...")
        return

    selected = interfaces[choice]
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

    input("\nPremi Invio per uscire...")


if __name__ == "__main__":
    main()

