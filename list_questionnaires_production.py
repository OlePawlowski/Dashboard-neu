#!/usr/bin/env python3
"""
Skript zum Anzeigen aller Bedarfsfragebogen aus der PRODUKTIONS-Datenbank.
Verwendet die gleiche Datenbankverbindung wie die Flask-App.
"""

import sys
import os
from pathlib import Path

# Füge das Projektverzeichnis zum Python-Pfad hinzu
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Importiere Flask-App und Models
try:
    from app import app, db
    from models import Customer
    import json
    from datetime import datetime
    
    def list_all_questionnaires():
        """Listet alle Bedarfsfragebogen aus der Produktions-Datenbank auf."""
        with app.app_context():
            # Alle Kunden mit Bedarfsfragebogen abfragen
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
                        if 'pdf_data' in questionnaire_data and questionnaire_data['pdf_data']:
                            pdf_size = len(questionnaire_data['pdf_data'])
                            print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
                        elif 'pdf_base64' in questionnaire_data and questionnaire_data['pdf_base64']:
                            pdf_size = len(questionnaire_data['pdf_base64'])
                            print(f"      PDF vorhanden: Ja ({pdf_size} Zeichen Base64)")
                        else:
                            print(f"      PDF vorhanden: Nein")
                except json.JSONDecodeError as e:
                    print(f"   ⚠️  Fehler beim Parsen der Fragebogendaten: {e}")
                except Exception as e:
                    print(f"   ⚠️  Fehler: {e}")
                
                print("-" * 80)
            
            print(f"\n✅ Insgesamt {len(customers)} Bedarfsfragebogen gefunden.\n")
    
    if __name__ == "__main__":
        list_all_questionnaires()
        
except ImportError as e:
    print(f"❌ Fehler beim Importieren: {e}")
    print("Stelle sicher, dass die Flask-App korrekt konfiguriert ist.")
    sys.exit(1)
except Exception as e:
    print(f"❌ Fehler: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
