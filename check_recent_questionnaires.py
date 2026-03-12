#!/usr/bin/env python3
"""
Skript zum Prüfen, ob kürzlich versendete Bedarfsfragebogen in der DB fehlen.
"""

import sqlite3
from pathlib import Path
import json
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "data" / "app.db"

def check_recent_questionnaires():
    """Prüft, ob kürzlich versendete Fragebogen fehlen."""
    if not DB_PATH.exists():
        print(f"❌ Datenbank nicht gefunden: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Alle Kunden der letzten 7 Tage
    cursor.execute('''
        SELECT id, name, email, created_at, last_contact, 
               questionnaire_data_json, offer_data_json
        FROM customers
        WHERE datetime(created_at) >= datetime('now', '-7 days')
           OR datetime(last_contact) >= datetime('now', '-7 days')
        ORDER BY COALESCE(last_contact, created_at) DESC
    ''')
    
    customers = cursor.fetchall()
    
    print(f"\n📋 Analyse der letzten 7 Tage:\n")
    print("=" * 80)
    
    with_questionnaire = []
    without_questionnaire = []
    
    for c in customers:
        has_questionnaire = False
        q_sent_at = None
        
        if c['questionnaire_data_json']:
            try:
                q_data = json.loads(c['questionnaire_data_json'] or '{}')
                if q_data and q_data != {}:
                    has_questionnaire = True
                    q_sent_at = q_data.get('sent_at', '')
            except:
                pass
        
        date_str = (c['last_contact'] or c['created_at'])[:10] if (c['last_contact'] or c['created_at']) else 'N/A'
        
        if has_questionnaire:
            with_questionnaire.append((c, q_sent_at))
        else:
            without_questionnaire.append((c, date_str))
    
    print(f"\n✅ Kunden MIT Bedarfsfragebogen ({len(with_questionnaire)}):")
    print("-" * 80)
    for c, sent_at in with_questionnaire:
        date_str = (c['last_contact'] or c['created_at'])[:10] if (c['last_contact'] or c['created_at']) else 'N/A'
        sent_date = sent_at[:10] if sent_at and len(sent_at) > 10 else 'N/A'
        print(f"  {date_str} - {c['name']} ({c['email']}) - versendet: {sent_date}")
    
    print(f"\n❌ Kunden OHNE Bedarfsfragebogen ({len(without_questionnaire)}):")
    print("-" * 80)
    for c, date_str in without_questionnaire:
        print(f"  {date_str} - {c['name']} ({c['email']})")
    
    # Prüfe auch den "Befragungsbogen"-Kunden (team@helpcare.de)
    cursor.execute('''
        SELECT id, name, email, created_at, last_contact, questionnaire_data_json
        FROM customers
        WHERE email LIKE '%befragungsbogen%' OR email LIKE '%team@helpcare%'
        ORDER BY last_contact DESC
        LIMIT 5
    ''')
    
    system_customers = cursor.fetchall()
    if system_customers:
        print(f"\n📧 System-Kunden (Befragungsbogen/Team):")
        print("-" * 80)
        for c in system_customers:
            has_q = False
            if c['questionnaire_data_json']:
                try:
                    q_data = json.loads(c['questionnaire_data_json'] or '{}')
                    if q_data and q_data != {}:
                        has_q = True
                        sent_at = q_data.get('sent_at', 'N/A')
                        print(f"  {c['name']} ({c['email']}) - Fragebogen: {'✅' if has_q else '❌'}", end='')
                        if has_q:
                            print(f" - versendet: {sent_at[:10] if len(sent_at) > 10 else sent_at}")
                        else:
                            print()
                except:
                    print(f"  {c['name']} ({c['email']}) - Fragebogen: ❌")
    
    print("\n" + "=" * 80)
    print(f"\n💡 Hinweis: Wenn Bedarfsfragebogen über /api/send-offer versendet werden")
    print(f"   und keine Kunden-ID ausgewählt ist, werden sie möglicherweise")
    print(f"   unter 'team@helpcare.de' gespeichert statt beim eigentlichen Kunden.\n")
    
    conn.close()

if __name__ == "__main__":
    check_recent_questionnaires()
