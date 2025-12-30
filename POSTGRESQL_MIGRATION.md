# PostgreSQL Migration - Anleitung

## 🚀 Schnellstart

Die App verwendet jetzt automatisch PostgreSQL statt SQLite für bessere Performance.

### 1. Docker neu starten (PostgreSQL wird automatisch gestartet)

```bash
docker compose down
docker compose up -d
```

### 2. Datenbank-Tabellen erstellen

Die Tabellen werden beim ersten Start automatisch erstellt. Falls nicht, kannst du manuell migrieren:

```bash
docker compose exec dashboard python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### 3. Bestehende SQLite-Daten migrieren (optional)

Falls du bereits Daten in SQLite hast und diese übernehmen möchtest:

```bash
# Setze DATABASE_URL (wird automatisch von docker-compose gesetzt)
export DATABASE_URL=postgresql://helpcare:helpcare_secure_password_change_me@localhost:5432/helpcare

# Führe Migration aus
python migrate_to_postgres.py
```

## 🔐 Passwort ändern

Das Standard-PostgreSQL-Passwort ist `helpcare_secure_password_change_me`. 

**Für Produktion ändern:**

1. Erstelle eine `.env`-Datei:
```bash
POSTGRES_PASSWORD=dein_sicheres_passwort_hier
```

2. Oder setze es direkt in `docker-compose.yml`:
```yaml
environment:
  POSTGRES_PASSWORD: dein_sicheres_passwort_hier
```

## 📊 Vorteile von PostgreSQL

- ✅ **Bessere Performance** bei vielen gleichzeitigen Zugriffen
- ✅ **Transaktionen** und ACID-Compliance
- ✅ **Skalierbarkeit** für wachsende Datenmengen
- ✅ **Erweiterte Features** (JSON-Queries, Full-Text-Search, etc.)

## 🔍 PostgreSQL-Verbindung prüfen

```bash
# Verbinde dich zur PostgreSQL-Datenbank
docker compose exec postgres psql -U helpcare -d helpcare

# Zeige alle Tabellen
\dt

# Zeige Datenbank-Größe
SELECT pg_size_pretty(pg_database_size('helpcare'));
```

## 🛠️ Troubleshooting

### PostgreSQL startet nicht
```bash
# Prüfe Logs
docker compose logs postgres

# Prüfe ob Port 5432 frei ist
lsof -i :5432
```

### Datenbank-Verbindungsfehler
- Stelle sicher, dass `DATABASE_URL` in docker-compose.yml korrekt ist
- Prüfe ob PostgreSQL-Container läuft: `docker compose ps`
- Prüfe PostgreSQL-Logs: `docker compose logs postgres`

### Migration schlägt fehl
- Stelle sicher, dass beide Datenbanken (SQLite und PostgreSQL) erreichbar sind
- Prüfe ob Tabellen in PostgreSQL existieren
- Führe Migration Schritt für Schritt aus




