#!/usr/bin/env python3
"""
Skript zum Suchen eines bestimmten Kunden in der Datenbank.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

# Datenbankpfad
DB_PATH = Path(__file__).parent / "data" / "app.db"

def search_customer(name=None, email=None):
    """Sucht einen Kunden nach Name oder E-Mail."""
    if not DB_PATH.exists():
        print(f"❌ Datenbank nicht gefunden: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Suche nach Name oder E-Mail
    if name and email:
        cursor.execute("""
            SELECT * FROM customers
            WHERE (name LIKE ? OR email LIKE ?)
            ORDER BY created_at DESC
        """, (f'%{name}%', f'%{email}%'))
    elif name:
        cursor.execute("""
            SELECT * FROM customers
            WHERE name LIKE ?
            ORDER BY created_at DESC
        """, (f'%{name}%',))
    elif email:
        cursor.execute("""
            SELECT * FROM customers
            WHERE email LIKE ?
            ORDER BY created_at DESC
        """, (f'%{email}%',))
    else:
        print("❌ Bitte geben Sie einen Namen oder eine E-Mail-Adresse an.")
        return
    
    customers = cursor.fetchall()
    
    if not customers:
        print(f"📭 Kein Kunde gefunden für: {name or email}")
        return
    
    print(f"\n📋 Gefundene Kunden: {len(customers)}\n")
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
        
        # Angebotsdaten prüfen
        has_offer = False
        if customer['offer_data_json']:
            try:
                offer_data = json.loads(customer['offer_data_json'] or '{}')
                if offer_data and offer_data != {}:
                    has_offer = True
                    print(f"\n   📄 ANGEBOT vorhanden:")
                    if 'sent_at' in offer_data:
                        sent_at = datetime.fromisoformat(offer_data['sent_at'].replace('Z', '+00:00'))
                        print(f"      Versendet am: {sent_at.strftime('%d.%m.%Y %H:%M:%S')}")
                    if 'pdf_data' in offer_data and offer_data['pdf_data']:
                        pdf_size = len(offer_data['pdf_data'])
                        print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
            except:
                pass
        
        if not has_offer:
            print(f"\n   📄 ANGEBOT: Kein Angebot vorhanden")
        
        # Bedarfsfragebogen-Daten prüfen
        has_questionnaire = False
        if customer['questionnaire_data_json']:
            try:
                questionnaire_data = json.loads(customer['questionnaire_data_json'] or '{}')
                if questionnaire_data and questionnaire_data != {}:
                    has_questionnaire = True
                    print(f"\n   📋 BEDARFSFRAGEBOGEN vorhanden:")
                    if 'sent_at' in questionnaire_data:
                        sent_at = datetime.fromisoformat(questionnaire_data['sent_at'].replace('Z', '+00:00'))
                        print(f"      Versendet am: {sent_at.strftime('%d.%m.%Y %H:%M:%S')}")
                    if 'subject' in questionnaire_data:
                        print(f"      Betreff: {questionnaire_data['subject']}")
                    if 'pdf_data' in questionnaire_data and questionnaire_data['pdf_data']:
                        pdf_size = len(questionnaire_data['pdf_data'])
                        print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
                    elif 'pdf_base64' in questionnaire_data and questionnaire_data['pdf_base64']:
                        pdf_size = len(questionnaire_data['pdf_base64'])
                        print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
            except:
                pass
        
        if not has_questionnaire:
            print(f"\n   📋 BEDARFSFRAGEBOGEN: Kein Fragebogen vorhanden")
        
        print("-" * 80)
    
    conn.close()

if __name__ == "__main__":
    import sys
    name = None
    email = None
    
    if len(sys.argv) > 1:
        # Wenn Argumente übergeben wurden
        arg = sys.argv[1]
        if '@' in arg:
            email = arg
        else:
            name = arg
        if len(sys.argv) > 2:
            if '@' in sys.argv[2]:
                email = sys.argv[2]
            else:
                name = sys.argv[2]
    else:
        # Interaktive Suche nach Sarah Polenski
        name = "Sarah Polenski"
        email = "Papageifische@web.de"
    
    search_customer(name=name, email=email)
