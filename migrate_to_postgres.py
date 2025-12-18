#!/usr/bin/env python3
"""
Migrationsskript: SQLite → PostgreSQL
Führt alle Daten von der SQLite-Datenbank in PostgreSQL über.
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json

# SQLite-Datenbank laden
sqlite_path = os.path.join(os.getcwd(), 'data', 'app.db')
if not os.path.exists(sqlite_path):
    print(f"❌ SQLite-Datenbank nicht gefunden: {sqlite_path}")
    sys.exit(1)

sqlite_url = f"sqlite:///{sqlite_path}"
sqlite_engine = create_engine(sqlite_url, echo=False)

# PostgreSQL-Verbindung
postgres_url = os.getenv('DATABASE_URL', 'postgresql://helpcare:helpcare_secure_password_change_me@localhost:5432/helpcare')
postgres_engine = create_engine(postgres_url, echo=False)

print(f"📦 Migriere von SQLite ({sqlite_path}) nach PostgreSQL...")
print(f"   PostgreSQL: {postgres_url.replace(postgres_url.split('@')[0].split('//')[1].split(':')[1], '***')}")

# Teste PostgreSQL-Verbindung
try:
    with postgres_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("✅ PostgreSQL-Verbindung erfolgreich")
except Exception as e:
    print(f"❌ PostgreSQL-Verbindung fehlgeschlagen: {e}")
    print("   Stelle sicher, dass PostgreSQL läuft und DATABASE_URL korrekt ist.")
    sys.exit(1)

# Tabellen-Liste aus SQLite
with sqlite_engine.connect() as conn:
    tables = conn.execute(text("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)).fetchall()
    table_names = [t[0] for t in tables]

print(f"\n📋 Gefundene Tabellen: {', '.join(table_names)}")

# Für jede Tabelle: Daten migrieren
for table_name in table_names:
    print(f"\n🔄 Migriere Tabelle: {table_name}")
    
    # Spalten aus SQLite holen
    with sqlite_engine.connect() as conn:
        columns = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        column_names = [col[1] for col in columns]
        
        # Daten aus SQLite lesen
        rows = conn.execute(text(f"SELECT * FROM {table_name}")).fetchall()
    
    if not rows:
        print(f"   ⏭️  Keine Daten in {table_name}")
        continue
    
    print(f"   📊 {len(rows)} Zeilen gefunden")
    
    # Daten in PostgreSQL einfügen
    try:
        with postgres_engine.connect() as conn:
            # Prüfe ob Tabelle existiert
            table_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = :table_name
                )
            """), {"table_name": table_name}).scalar()
            
            if not table_exists:
                print(f"   ⚠️  Tabelle {table_name} existiert nicht in PostgreSQL - überspringe")
                continue
            
            # Lösche vorhandene Daten (optional - kommentiere aus, wenn du Daten behalten willst)
            # conn.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
            # conn.commit()
            
            # Füge Daten ein (Einzelne Inserts mit besserer Fehlerbehandlung)
            inserted = 0
            failed = 0
            
            for row in rows:
                row_dict = dict(zip(column_names, row))
                # Konvertiere None zu NULL, JSON-Strings bleiben Strings
                values = {}
                for k, v in row_dict.items():
                    if v is None:
                        values[k] = None
                    elif isinstance(v, bytes):
                        # Binary-Daten als Hex-String
                        values[k] = v.hex() if v else None
                    else:
                        values[k] = v
                
                # Einzelner Insert mit eigener Transaktion
                try:
                    cols = ', '.join([f'"{col}"' for col in column_names])
                    placeholders = ', '.join([f':{col}' for col in column_names])
                    insert_sql = f'INSERT INTO "{table_name}" ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
                    
                    conn.execute(text(insert_sql), values)
                    conn.commit()
                    inserted += 1
                except Exception as e:
                    # Bei Fehler: Transaktion zurücksetzen
                    conn.rollback()
                    failed += 1
                    if failed <= 5:  # Nur erste 5 Fehler anzeigen
                        error_msg = str(e)[:200]  # Erste 200 Zeichen
                        print(f"   ⚠️  Fehler bei Zeile (überspringe): {error_msg}")
            
            if failed > 0:
                print(f"   ✅ {inserted} Zeilen erfolgreich migriert, {failed} übersprungen")
            else:
                print(f"   ✅ {inserted} Zeilen erfolgreich migriert")
    
    except Exception as e:
        print(f"   ❌ Fehler bei Tabelle {table_name}: {e}")
        continue

print("\n✅ Migration abgeschlossen!")
print("\n💡 Nächste Schritte:")
print("   1. Prüfe die Daten in PostgreSQL")
print("   2. Starte die App neu: docker compose restart dashboard")
print("   3. Die App verwendet jetzt PostgreSQL automatisch")

