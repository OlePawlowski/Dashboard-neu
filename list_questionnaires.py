#!/usr/bin/env python3
"""
Skript zum Anzeigen aller Bedarfsfragebogen aus der Datenbank.
Verwendet die gleiche Datenbankverbindung wie die Flask-App.
"""

import sys
import os
from pathlib import Path

# Füge das Projektverzeichnis zum Python-Pfad hinzu
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Versuche zuerst, die Flask-App zu verwenden (für PostgreSQL)
try:
    from app import app, db
    from models import Customer
    USE_FLASK = True
except ImportError:
    USE_FLASK = False
    import sqlite3
    import json
    from datetime import datetime

# Datenbankpfad für SQLite-Fallback
DB_PATH = Path(__file__).parent / "data" / "app.db"

def list_all_questionnaires():
    """Listet alle Bedarfsfragebogen aus der Datenbank auf."""
    if USE_FLASK:
        # Verwende Flask-App und SQLAlchemy (für PostgreSQL)
        with app.app_context():
            customers = Customer.query.filter(
                Customer.questionnaire_data_json.isnot(None),
                Customer.questionnaire_data_json != '{}',
                Customer.questionnaire_data_json != ''
            ).order_by(Customer.created_at.desc()).all()
            
            if not customers:
                print("📭 Keine Bedarfsfragebogen in der Datenbank gefunden.")
                return
            
            print(f"\n📋 Gefundene Bedarfsfragebogen: {len(customers)}\n")
            print("=" * 80)
            
            for idx, customer in enumerate(customers, 1):
                print(f"\n{idx}. Kunde: {customer.name}")
                print(f"   ID: {customer.id}")
                print(f"   E-Mail: {customer.email or 'N/A'}")
                print(f"   Telefon: {customer.phone or 'N/A'}")
                print(f"   Status: {customer.status or 'N/A'}")
                
                if customer.created_at:
                    print(f"   Erstellt: {customer.created_at.strftime('%d.%m.%Y %H:%M:%S')}")
                
                if customer.last_contact:
                    print(f"   Letzter Kontakt: {customer.last_contact.strftime('%d.%m.%Y %H:%M:%S')}")
                
                # Fragebogendaten parsen
                try:
                    questionnaire_data = json.loads(customer.questionnaire_data_json or '{}')
                    _print_questionnaire_details(questionnaire_data)
                except json.JSONDecodeError as e:
                    print(f"   ⚠️  Fehler beim Parsen der Fragebogendaten: {e}")
                except Exception as e:
                    print(f"   ⚠️  Fehler: {e}")
                
                print("-" * 80)
            
            print(f"\n✅ Insgesamt {len(customers)} Bedarfsfragebogen gefunden.\n")
            return
    
    # Fallback: SQLite
    if not DB_PATH.exists():
        print(f"❌ Datenbank nicht gefunden: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Alle Kunden mit Bedarfsfragebogen abfragen
    cursor.execute("""
        SELECT 
            id,
            name,
            email,
            phone,
            status,
            questionnaire_data_json,
            created_at,
            last_contact
        FROM customers
        WHERE questionnaire_data_json IS NOT NULL 
          AND questionnaire_data_json != '{}'
          AND questionnaire_data_json != ''
        ORDER BY created_at DESC
    """)
    
    customers = cursor.fetchall()
    
    if not customers:
        print("📭 Keine Bedarfsfragebogen in der Datenbank gefunden.")
        return
    
    print(f"\n📋 Gefundene Bedarfsfragebogen: {len(customers)}\n")
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
        
        # Fragebogendaten parsen
        try:
            questionnaire_data = json.loads(customer['questionnaire_data_json'] or '{}')
            _print_questionnaire_details(questionnaire_data)
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Fehler beim Parsen der Fragebogendaten: {e}")
        except Exception as e:
            print(f"   ⚠️  Fehler: {e}")
        
        print("-" * 80)
    
    conn.close()
    print(f"\n✅ Insgesamt {len(customers)} Bedarfsfragebogen gefunden.\n")


def _print_questionnaire_details(questionnaire_data):
    """Hilfsfunktion zum Anzeigen der Fragebogendetails."""
    import json
    from datetime import datetime
    
    if questionnaire_data:
        print(f"\n   📄 Fragebogendetails:")
        if 'subject' in questionnaire_data:
            print(f"      Betreff: {questionnaire_data['subject']}")
        if 'filename' in questionnaire_data:
            print(f"      Dateiname: {questionnaire_data['filename']}")
        if 'sent_at' in questionnaire_data:
            try:
                sent_at = datetime.fromisoformat(questionnaire_data['sent_at'].replace('Z', '+00:00'))
                print(f"      Versendet am: {sent_at.strftime('%d.%m.%Y %H:%M:%S')}")
            except:
                print(f"      Versendet am: {questionnaire_data['sent_at']}")
        if 'lastName' in questionnaire_data:
            print(f"      Nachname: {questionnaire_data['lastName']}")
        if 'sms_name' in questionnaire_data:
            print(f"      SMS Name: {questionnaire_data['sms_name']}")
        if 'sms_number' in questionnaire_data:
            print(f"      SMS Nummer: {questionnaire_data['sms_number']}")
        if 'bcc_recipients' in questionnaire_data:
            bcc = questionnaire_data['bcc_recipients']
            if isinstance(bcc, list) and bcc:
                print(f"      BCC Empfänger: {', '.join(bcc)}")
            elif isinstance(bcc, str):
                print(f"      BCC Empfänger: {bcc}")
        
        # Ausgefüllte Felder anzeigen
        if 'fields' in questionnaire_data:
            fields = questionnaire_data['fields']
            if isinstance(fields, dict) and fields:
                print(f"\n      📝 Ausgefüllte Felder:")
                for key, value in fields.items():
                    # Lange Werte kürzen
                    value_str = str(value)
                    if len(value_str) > 60:
                        value_str = value_str[:60] + "..."
                    print(f"         • {key}: {value_str}")
            elif isinstance(fields, list) and fields:
                print(f"\n      📝 Ausgefüllte Felder ({len(fields)} Einträge):")
                for field in fields[:5]:  # Erste 5 anzeigen
                    print(f"         • {field}")
                if len(fields) > 5:
                    print(f"         ... und {len(fields) - 5} weitere")
        
        # PDF-Daten prüfen
        if 'pdf_data' in questionnaire_data and questionnaire_data['pdf_data']:
            pdf_size = len(questionnaire_data['pdf_data'])
            print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
        elif 'pdf_base64' in questionnaire_data and questionnaire_data['pdf_base64']:
            pdf_size = len(questionnaire_data['pdf_base64'])
            print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
        else:
            print(f"      PDF vorhanden: Nein")

if __name__ == "__main__":
    list_all_questionnaires()
