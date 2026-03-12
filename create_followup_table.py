#!/usr/bin/env python3
"""Skript zum Erstellen der Follow-up und CustomerNote Tabellen"""
import sys
import os

# Füge das aktuelle Verzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import FollowUp, CustomerNote

with app.app_context():
    try:
        # Erstelle alle Tabellen
        db.create_all()
        print("✅ Tabellen erfolgreich erstellt/aktualisiert")
        
        # Prüfe ob die Tabellen existieren
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        if 'follow_ups' in tables:
            print("✅ Tabelle 'follow_ups' existiert")
        else:
            print("❌ Tabelle 'follow_ups' fehlt")
            
        if 'customer_notes' in tables:
            print("✅ Tabelle 'customer_notes' existiert")
        else:
            print("❌ Tabelle 'customer_notes' fehlt")
            
    except Exception as e:
        print(f"❌ Fehler beim Erstellen der Tabellen: {e}")
        import traceback
        traceback.print_exc()

