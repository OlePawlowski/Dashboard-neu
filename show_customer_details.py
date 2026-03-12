#!/usr/bin/env python3
"""
Skript zum Anzeigen aller Details eines Kunden inkl. Kontakthistorie.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

# Datenbankpfad
DB_PATH = Path(__file__).parent / "data" / "app.db"

def show_customer_details(email):
    """Zeigt alle Details eines Kunden an."""
    if not DB_PATH.exists():
        print(f"❌ Datenbank nicht gefunden: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Kunde suchen
    cursor.execute("""
        SELECT * FROM customers
        WHERE email LIKE ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (f'%{email}%',))
    
    customer = cursor.fetchone()
    
    if not customer:
        print(f"📭 Kein Kunde gefunden für: {email}")
        return
    
    print(f"\n📋 KUNDENDETAILS\n")
    print("=" * 80)
    print(f"Name: {customer['name']}")
    print(f"ID: {customer['id']}")
    print(f"E-Mail: {customer['email'] or 'N/A'}")
    print(f"Telefon: {customer['phone'] or 'N/A'}")
    print(f"Status: {customer['status'] or 'N/A'}")
    print(f"Notizen: {customer['notes'] or 'Keine'}")
    
    if customer['created_at']:
        created = datetime.fromisoformat(customer['created_at'].replace('Z', '+00:00'))
        print(f"Erstellt: {created.strftime('%d.%m.%Y %H:%M:%S')}")
    
    if customer['last_contact']:
        last_contact = datetime.fromisoformat(customer['last_contact'].replace('Z', '+00:00'))
        print(f"Letzter Kontakt: {last_contact.strftime('%d.%m.%Y %H:%M:%S')}")
    
    # Kontakthistorie anzeigen
    if customer['contact_history_json']:
        try:
            contact_history = json.loads(customer['contact_history_json'] or '[]')
            if contact_history:
                print(f"\n📞 KONTAKTHISTORIE ({len(contact_history)} Einträge):")
                print("-" * 80)
                for entry in contact_history:
                    entry_type = entry.get('type', 'unknown')
                    timestamp = entry.get('timestamp', '')
                    details = entry.get('details', {})
                    
                    if timestamp:
                        try:
                            ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            time_str = ts.strftime('%d.%m.%Y %H:%M:%S')
                        except:
                            time_str = timestamp
                    else:
                        time_str = "Unbekannt"
                    
                    type_names = {
                        'offer_sent': 'Angebot versendet',
                        'questionnaire_sent': 'Bedarfsfragebogen versendet',
                        'manual_note': 'Manuelle Notiz'
                    }
                    type_name = type_names.get(entry_type, entry_type)
                    
                    print(f"\n  {time_str} - {type_name}")
                    if details:
                        if isinstance(details, dict):
                            for key, value in details.items():
                                if key not in ['pdf_data', 'pdf_base64']:  # PDF-Daten nicht anzeigen
                                    value_str = str(value)
                                    if len(value_str) > 100:
                                        value_str = value_str[:100] + "..."
                                    print(f"    • {key}: {value_str}")
        except Exception as e:
            print(f"\n⚠️  Fehler beim Lesen der Kontakthistorie: {e}")
    
    # Angebotsdaten
    if customer['offer_data_json']:
        try:
            offer_data = json.loads(customer['offer_data_json'] or '{}')
            if offer_data and offer_data != {}:
                print(f"\n📄 ANGEBOTSDATEN:")
                print("-" * 80)
                for key, value in offer_data.items():
                    if key not in ['pdf_data', 'pdf_base64']:  # PDF-Daten nicht anzeigen
                        value_str = str(value)
                        if len(value_str) > 100:
                            value_str = value_str[:100] + "..."
                        print(f"  • {key}: {value_str}")
        except Exception as e:
            print(f"\n⚠️  Fehler beim Lesen der Angebotsdaten: {e}")
    
    # Fragebogendaten
    if customer['questionnaire_data_json']:
        try:
            questionnaire_data = json.loads(customer['questionnaire_data_json'] or '{}')
            if questionnaire_data and questionnaire_data != {}:
                print(f"\n📋 FRAGEBOGENDATEN:")
                print("-" * 80)
                for key, value in questionnaire_data.items():
                    if key not in ['pdf_data', 'pdf_base64']:  # PDF-Daten nicht anzeigen
                        value_str = str(value)
                        if len(value_str) > 100:
                            value_str = value_str[:100] + "..."
                        print(f"  • {key}: {value_str}")
        except Exception as e:
            print(f"\n⚠️  Fehler beim Lesen der Fragebogendaten: {e}")
    
    print("\n" + "=" * 80)
    conn.close()

if __name__ == "__main__":
    import sys
    email = "Papageifische@web.de"
    if len(sys.argv) > 1:
        email = sys.argv[1]
    show_customer_details(email)
