#!/usr/bin/env python3
"""
Skript zum Exportieren aller Bedarfsfragebogen-PDFs aus PostgreSQL.
Kann direkt ausgeführt werden oder die PDFs werden in ein Verzeichnis exportiert.
"""

import os
import json
import base64
from datetime import datetime
from pathlib import Path
import psycopg2
from dotenv import load_dotenv

# .env laden
load_dotenv()

# Datenbankverbindung aus Umgebungsvariablen
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fallback für lokale Docker-Umgebung
    DATABASE_URL = "postgresql://helpcare:helpcare_secure_password_change_me@localhost:5432/helpcare"

# Heroku-Style postgres:// → postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

EXPORT_DIR = Path(__file__).parent / "exported_questionnaires"

def export_questionnaires():
    """Exportiert alle Bedarfsfragebogen-PDFs aus PostgreSQL."""
    # Export-Verzeichnis erstellen
    EXPORT_DIR.mkdir(exist_ok=True)
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Alle Kunden mit Bedarfsfragebogen abfragen
        cursor.execute("""
            SELECT 
                id,
                name,
                email,
                questionnaire_data_json,
                created_at
            FROM customers
            WHERE questionnaire_data_json IS NOT NULL 
              AND questionnaire_data_json != '{}'
              AND questionnaire_data_json != ''
              AND questionnaire_data_json::jsonb->>'pdf_data' IS NOT NULL
            ORDER BY created_at DESC
        """)
        
        customers = cursor.fetchall()
        
        if not customers:
            print("📭 Keine Bedarfsfragebogen mit PDFs in der Datenbank gefunden.")
            return
        
        print(f"\n📋 Exportiere {len(customers)} Bedarfsfragebogen-PDFs...\n")
        
        exported_count = 0
        for customer in customers:
            try:
                customer_id, name, email, questionnaire_data_json, created_at = customer
                
                questionnaire_data = json.loads(questionnaire_data_json or '{}')
                
                # PDF-Daten finden (kann in pdf_data oder pdf_base64 sein)
                pdf_base64 = None
                if questionnaire_data.get('pdf_data'):
                    pdf_base64 = questionnaire_data['pdf_data']
                elif questionnaire_data.get('pdf_base64'):
                    pdf_base64 = questionnaire_data['pdf_base64']
                
                if not pdf_base64:
                    print(f"⚠️  Kein PDF für Kunde {name} (ID: {customer_id})")
                    continue
                
                # Base64-Präfix entfernen, falls vorhanden (data:application/pdf;base64,...)
                if pdf_base64.startswith('data:'):
                    pdf_base64 = pdf_base64.split(',', 1)[1]
                
                # PDF-Daten dekodieren
                try:
                    pdf_bytes = base64.b64decode(pdf_base64)
                except Exception as e:
                    print(f"❌ Fehler beim Dekodieren der PDF für Kunde {name} (ID: {customer_id}): {e}")
                    continue
                
                # Dateiname generieren
                customer_name = name or f"Kunde_{customer_id}"
                # Dateiname sicher machen (keine Sonderzeichen)
                safe_name = "".join(c for c in customer_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_name = safe_name.replace(' ', '_')
                
                # Datum aus sent_at oder created_at
                if questionnaire_data.get('sent_at'):
                    try:
                        date_str = datetime.fromisoformat(questionnaire_data['sent_at'].replace('Z', '+00:00')).strftime('%Y%m%d')
                    except:
                        date_str = created_at.strftime('%Y%m%d') if created_at else datetime.now().strftime('%Y%m%d')
                elif created_at:
                    date_str = created_at.strftime('%Y%m%d')
                else:
                    date_str = datetime.now().strftime('%Y%m%d')
                
                # Original-Dateiname aus questionnaire_data verwenden, falls vorhanden
                if questionnaire_data.get('filename'):
                    original_filename = questionnaire_data['filename']
                    # Dateierweiterung sicherstellen
                    if not original_filename.endswith('.pdf'):
                        original_filename += '.pdf'
                    filename = f"{date_str}_{safe_name}_{original_filename}"
                else:
                    filename = f"{date_str}_{safe_name}_ID{customer_id}_Bedarfsfragebogen.pdf"
                
                filepath = EXPORT_DIR / filename
                
                # PDF speichern
                with open(filepath, 'wb') as f:
                    f.write(pdf_bytes)
                
                print(f"✅ Exportiert: {filename} ({len(pdf_bytes)} Bytes)")
                exported_count += 1
                
            except Exception as e:
                print(f"❌ Fehler beim Exportieren von Kunde {name} (ID: {customer_id}): {e}")
                import traceback
                traceback.print_exc()
        
        conn.close()
        print(f"\n✅ {exported_count} von {len(customers)} Bedarfsfragebogen erfolgreich exportiert.")
        print(f"📁 Export-Verzeichnis: {EXPORT_DIR.absolute()}\n")
        
    except Exception as e:
        print(f"❌ Fehler bei der Datenbankverbindung: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    export_questionnaires()
