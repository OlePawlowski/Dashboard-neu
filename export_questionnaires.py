#!/usr/bin/env python3
"""
Skript zum Exportieren aller Bedarfsfragebogen-PDFs aus der Datenbank.
"""

import sqlite3
import json
import base64
from datetime import datetime
from pathlib import Path

# Datenbankpfad
DB_PATH = Path(__file__).parent / "data" / "app.db"
EXPORT_DIR = Path(__file__).parent / "exported_questionnaires"

def export_questionnaires():
    """Exportiert alle Bedarfsfragebogen-PDFs aus der Datenbank."""
    if not DB_PATH.exists():
        print(f"❌ Datenbank nicht gefunden: {DB_PATH}")
        return
    
    # Export-Verzeichnis erstellen
    EXPORT_DIR.mkdir(exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
        ORDER BY created_at DESC
    """)
    
    customers = cursor.fetchall()
    
    if not customers:
        print("📭 Keine Bedarfsfragebogen in der Datenbank gefunden.")
        return
    
    print(f"\n📋 Exportiere {len(customers)} Bedarfsfragebogen...\n")
    
    exported_count = 0
    for customer in customers:
        try:
            questionnaire_data = json.loads(customer['questionnaire_data_json'] or '{}')
            
            # PDF-Daten finden (kann in pdf_data oder pdf_base64 sein)
            pdf_base64 = None
            if questionnaire_data.get('pdf_data'):
                pdf_base64 = questionnaire_data['pdf_data']
            elif questionnaire_data.get('pdf_base64'):
                pdf_base64 = questionnaire_data['pdf_base64']
            
            if not pdf_base64:
                print(f"⚠️  Kein PDF für Kunde {customer['name']} (ID: {customer['id']})")
                continue
            
            # PDF-Daten dekodieren
            pdf_bytes = base64.b64decode(pdf_base64)
            
            # Dateiname generieren
            customer_name = customer['name'] or f"Kunde_{customer['id']}"
            # Dateiname sicher machen (keine Sonderzeichen)
            safe_name = "".join(c for c in customer_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_')
            
            # Datum aus sent_at oder created_at
            if questionnaire_data.get('sent_at'):
                date_str = datetime.fromisoformat(questionnaire_data['sent_at'].replace('Z', '+00:00')).strftime('%Y%m%d')
            elif customer['created_at']:
                date_str = datetime.fromisoformat(customer['created_at'].replace('Z', '+00:00')).strftime('%Y%m%d')
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
                filename = f"{date_str}_{safe_name}_ID{customer['id']}_Bedarfsfragebogen.pdf"
            
            filepath = EXPORT_DIR / filename
            
            # PDF speichern
            with open(filepath, 'wb') as f:
                f.write(pdf_bytes)
            
            print(f"✅ Exportiert: {filename} ({len(pdf_bytes)} Bytes)")
            exported_count += 1
            
        except Exception as e:
            print(f"❌ Fehler beim Exportieren von Kunde {customer['name']} (ID: {customer['id']}): {e}")
    
    conn.close()
    print(f"\n✅ {exported_count} von {len(customers)} Bedarfsfragebogen erfolgreich exportiert.")
    print(f"📁 Export-Verzeichnis: {EXPORT_DIR}\n")

if __name__ == "__main__":
    export_questionnaires()
