#!/usr/bin/env python3
"""
Skript zum Anzeigen aller erstellten Angebote aus der Datenbank.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

# Datenbankpfad
DB_PATH = Path(__file__).parent / "data" / "app.db"

def list_all_offers():
    """Listet alle Angebote aus der Datenbank auf."""
    if not DB_PATH.exists():
        print(f"❌ Datenbank nicht gefunden: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Alle Kunden mit Angeboten abfragen
    cursor.execute("""
        SELECT 
            id,
            name,
            email,
            phone,
            status,
            offer_data_json,
            created_at,
            last_contact
        FROM customers
        WHERE offer_data_json IS NOT NULL 
          AND offer_data_json != '{}'
          AND offer_data_json != ''
        ORDER BY created_at DESC
    """)
    
    customers = cursor.fetchall()
    
    if not customers:
        print("📭 Keine Angebote in der Datenbank gefunden.")
        return
    
    print(f"\n📋 Gefundene Angebote: {len(customers)}\n")
    print("=" * 80)
    
    for idx, customer in enumerate(customers, 1):
        print(f"\n{idx}. Kunde: {customer['name']}")
        print(f"   ID: {customer['id']}")
        print(f"   E-Mail: {customer['email'] or 'N/A'}")
        print(f"   Telefon: {customer['phone'] or 'N/A'}")
        print(f"   Status: {customer['status'] or 'N/A'}")
        
        if customer['created_at']:
            created = datetime.fromisoformat(customer['created_at'].replace('Z', '+00:00'))
            print(f"   Erstellt: {created.strftime('%d.%m.%Y %H:%M:%S')}")
        
        if customer['last_contact']:
            last_contact = datetime.fromisoformat(customer['last_contact'].replace('Z', '+00:00'))
            print(f"   Letzter Kontakt: {last_contact.strftime('%d.%m.%Y %H:%M:%S')}")
        
        # Angebotsdaten parsen
        try:
            offer_data = json.loads(customer['offer_data_json'] or '{}')
            if offer_data:
                print(f"\n   📄 Angebotsdetails:")
                if 'subject' in offer_data:
                    print(f"      Betreff: {offer_data['subject']}")
                if 'filename' in offer_data:
                    print(f"      Dateiname: {offer_data['filename']}")
                if 'sent_at' in offer_data:
                    sent_at = datetime.fromisoformat(offer_data['sent_at'].replace('Z', '+00:00'))
                    print(f"      Versendet am: {sent_at.strftime('%d.%m.%Y %H:%M:%S')}")
                if 'to_email' in offer_data:
                    print(f"      An: {offer_data['to_email']}")
                if 'customer_name' in offer_data:
                    print(f"      Kundenname: {offer_data['customer_name']}")
                if 'pdf_data' in offer_data and offer_data['pdf_data']:
                    pdf_size = len(offer_data['pdf_data'])
                    print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
                else:
                    print(f"      PDF vorhanden: Nein")
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Fehler beim Parsen der Angebotsdaten: {e}")
        
        print("-" * 80)
    
    conn.close()
    print(f"\n✅ Insgesamt {len(customers)} Angebot(e) gefunden.\n")

if __name__ == "__main__":
    list_all_offers()
