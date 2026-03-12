from flask import Flask, render_template, request, redirect, session, jsonify, url_for, send_file, send_from_directory
from flask_compress import Compress
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
import os
import datetime
from dotenv import load_dotenv
import json
import re
import requests

# DocuSign imports (vereinfacht - nur für Typen)
# from docusign_esign import ApiClient, EnvelopesApi, EnvelopeDefinition, Document, Signer, SignHere, Tabs, Recipients
import uuid
from models import db, User, Anfrage, TeamNote, GmailCredential, ExchangeCredential, PdfDocument, Customer, Kooperationspartner, Caregiver, Dienstleistungsvertrag, Kooperationsvertrag, CustomerNote, FollowUp, Invoice
from werkzeug.middleware.proxy_fix import ProxyFix
from base64 import urlsafe_b64encode
import base64
from werkzeug.utils import secure_filename
import queue
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import smtplib
import imaplib
import email
import socket
from email.header import decode_header

# 🔃 .env laden (lokal)
load_dotenv()

# Hilfsfunktion für deutsches Währungsformat
def format_currency(value):
    """Formatiert eine Zahl im deutschen Währungsformat (z.B. 3.500,00 €)"""
    if value is None or value == '':
        return ''
    # Konvertiere zu Float und formatiere mit 2 Nachkommastellen
    formatted = f"{value:,.2f}"
    # Ersetze Punkt durch Komma für Dezimalstelle und Komma durch Punkt für Tausender
    formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"{formatted} €"


def prepare_sms_utf8(text):
    """
    Stellt – analog zur PHP-Funktion prepare_sms_utf8 – sicher, dass der
    SMS-Text als Unicode/UTF‑8 vorliegt und normalisiert Umlaute.
    """
    if text is None:
        return ''

    # Bytes → String mit robuster Dekodierung
    if isinstance(text, (bytes, bytearray)):
        for enc in ('utf-8', 'latin-1', 'cp1252'):
            try:
                text = text.decode(enc)
                break
            except Exception:
                continue
        else:
            # Fallback – unklare Kodierung, aber kein Absturz
            text = text.decode('utf-8', errors='replace')

    # Sicherstellen, dass wir einen String haben
    text = str(text)

    # Unicode-Normalisierung (z.B. kombinierte Zeichen → NFC)
    try:
        import unicodedata
        text = unicodedata.normalize('NFC', text)
    except Exception:
        # Falls unicodedata nicht verfügbar ist, Text unverändert zurückgeben
        pass

    return text

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback")
# Template-Caching aktivieren für bessere Performance
app.config['TEMPLATES_AUTO_RELOAD'] = False
app.jinja_env.cache = {}

# 📦 Persistente Ablage – Basisverzeichnis (standard: ./data)
APP_DATA_DIR = os.getenv('APP_DATA_DIR') or os.path.join(os.getcwd(), 'data')
os.makedirs(APP_DATA_DIR, exist_ok=True)

# Export-Verzeichnis für Bedarfsfragebogen
QUESTIONNAIRE_EXPORT_DIR = os.path.join(APP_DATA_DIR, 'exported_questionnaires')
os.makedirs(QUESTIONNAIRE_EXPORT_DIR, exist_ok=True)

# Export-Verzeichnis für Angebote
OFFER_EXPORT_DIR = os.path.join(APP_DATA_DIR, 'exported_offers')
os.makedirs(OFFER_EXPORT_DIR, exist_ok=True)

# Export-Verzeichnis für Profile (Profilersteller)
PROFILE_EXPORT_DIR = os.path.join(APP_DATA_DIR, 'exported_profiles')
os.makedirs(PROFILE_EXPORT_DIR, exist_ok=True)

# Export-Verzeichnis für Kooperationsverträge
KOOPERATIONSVERTRAG_EXPORT_DIR = os.path.join(APP_DATA_DIR, 'exported_kooperationsvertraege')
os.makedirs(KOOPERATIONSVERTRAG_EXPORT_DIR, exist_ok=True)

# Hinter Proxy (Railway) korrekte Host/Proto übernehmen
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config['PREFERRED_URL_SCHEME'] = 'https'

# DB-Config (SQLite default im APP_DATA_DIR, Postgres via DATABASE_URL)
database_url = os.getenv("DATABASE_URL")
if not database_url:
    sqlite_path = os.path.join(APP_DATA_DIR, 'app.db')
    database_url = f"sqlite:///{sqlite_path}"
# Heroku-Style postgres:// → postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Performance-Optimierungen für Datenbankverbindungen
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,  # Prüft Verbindungen vor Nutzung
    "pool_recycle": 3600,   # Recycelt Verbindungen nach 1 Stunde
    "pool_size": 10,        # Connection Pool Größe
    "max_overflow": 20,    # Zusätzliche Verbindungen bei Bedarf
    "connect_args": {"check_same_thread": False} if "sqlite" in database_url else {}
}

CORS(app)
Compress(app)

db.init_app(app)

with app.app_context():
    db.create_all()
    # Leichtgewichtige Migration: fehlende Spalten hinzufügen (SQLite & PostgreSQL kompatibel)
    try:
        from sqlalchemy import text, inspect
        is_sqlite = "sqlite" in database_url
        
        # PostgreSQL-Sequenzen synchronisieren (behebt UniqueViolation-Fehler)
        if not is_sqlite:
            try:
                with db.engine.connect() as conn:
                    # Synchronisiere alle Sequenzen mit den tatsächlichen MAX(id) Werten
                    tables_with_sequences = [
                        ('team_notes', 'team_notes_id_seq'),
                        ('anfragen', 'anfragen_id_seq'),
                        ('customers', 'customers_id_seq'),
                        ('users', 'users_id_seq'),
                        ('pdf_documents', 'pdf_documents_id_seq'),
                        ('kooperationspartner', 'kooperationspartner_id_seq'),
                        ('kooperationsvertraege', 'kooperationsvertraege_id_seq'),
                        ('dienstleistungsvertraege', 'dienstleistungsvertraege_id_seq'),
                    ]
                    for table_name, seq_name in tables_with_sequences:
                        try:
                            # Prüfe ob Tabelle existiert
                            result = conn.execute(text("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables 
                                    WHERE table_name = :table_name
                                )
                            """), {"table_name": table_name}).scalar()
                            if result:
                                # Hole MAX(id) von der Tabelle
                                max_id_result = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table_name}")).scalar()
                                if max_id_result is not None:
                                    # Setze Sequenz auf MAX(id) + 1 (oder 1 wenn Tabelle leer)
                                    conn.execute(text(f"SELECT setval('{seq_name}', GREATEST({max_id_result}, 1), true)"))
                                    conn.commit()
                                    print(f"✅ Sequenz {seq_name} auf {max_id_result + 1} gesetzt")
                        except Exception as seq_e:
                            # Sequenz existiert möglicherweise noch nicht - ignoriere
                            pass
            except Exception as seq_sync_e:
                print(f"⚠️ Sequenz-Synchronisierung übersprungen: {seq_sync_e}")
        
        def get_table_columns(conn, table_name):
            """Holt Spalten einer Tabelle - kompatibel mit SQLite und PostgreSQL"""
            if is_sqlite:
                result = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                return [row[1] for row in result]
            else:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name
                """), {"table_name": table_name}).fetchall()
                return [row[0] for row in result]
        
        with db.engine.connect() as conn:
            # Team notes migration
            cols = get_table_columns(conn, "team_notes")
            if 'parent_id' not in cols:
                conn.execute(text("ALTER TABLE team_notes ADD COLUMN parent_id INTEGER"))
                conn.commit()
            if 'reactions_json' not in cols:
                conn.execute(text("ALTER TABLE team_notes ADD COLUMN reactions_json TEXT DEFAULT '[]'"))
                conn.commit()
            
            # Signature data migration für beide Vertrags-Tabellen
            koop_cols = get_table_columns(conn, "kooperationsvertraege")
            if 'signature_data' not in koop_cols:
                conn.execute(text("ALTER TABLE kooperationsvertraege ADD COLUMN signature_data TEXT"))
                conn.commit()
            if 'custom_html' not in koop_cols:
                conn.execute(text("ALTER TABLE kooperationsvertraege ADD COLUMN custom_html TEXT"))
                conn.commit()
            
            dlv_cols = get_table_columns(conn, "dienstleistungsvertraege")
            if 'signature_data' not in dlv_cols:
                conn.execute(text("ALTER TABLE dienstleistungsvertraege ADD COLUMN signature_data TEXT"))
                conn.commit()
            if 'custom_html' not in dlv_cols:
                conn.execute(text("ALTER TABLE dienstleistungsvertraege ADD COLUMN custom_html TEXT"))
                conn.commit()
            
            # Migration für ExchangeCredential: signature-Feld hinzufügen
            try:
                exc_cols = get_table_columns(conn, "exchange_credentials")
                if 'signature' not in exc_cols:
                    conn.execute(text("ALTER TABLE exchange_credentials ADD COLUMN signature TEXT"))
                    conn.commit()
                    print("✅ Migration: signature-Feld zu exchange_credentials hinzugefügt")
            except Exception as e:
                print(f"⚠️ Migration-Fehler für exchange_credentials.signature: {e}")

            # Migration für Kooperationspartner: notes-Feld hinzufügen
            try:
                partner_cols = get_table_columns(conn, "kooperationspartner")
                if 'notes' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN notes TEXT"))
                    conn.commit()
                    print("✅ Migration: notes-Feld zu kooperationspartner hinzugefügt")
            except Exception as e:
                print(f"⚠️ Migration-Fehler für kooperationspartner.notes: {e}")
    except Exception as e:
        print(f"Migration-Fehler: {e}")
        pass
    
    # Migration für Customer-Tabelle: Neue Spalten hinzufügen (falls nicht vorhanden)
    try:
        from sqlalchemy import text
        is_sqlite = "sqlite" in database_url
        
        def get_table_columns(conn, table_name):
            """Holt Spalten einer Tabelle - kompatibel mit SQLite und PostgreSQL"""
            if is_sqlite:
                result = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                return [row[1] for row in result]
            else:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name
                """), {"table_name": table_name}).fetchall()
                return [row[0] for row in result]
        
        def table_exists(conn, table_name):
            """Prüft ob Tabelle existiert - kompatibel mit SQLite und PostgreSQL"""
            if is_sqlite:
                result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": table_name}).fetchone()
                return result is not None
            else:
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = :table_name
                    )
                """), {"table_name": table_name}).scalar()
                return result
        
        with db.engine.connect() as conn:
            cols = get_table_columns(conn, "customers")
            if 'offer_data_json' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN offer_data_json TEXT DEFAULT '{}'"))
            if 'questionnaire_data_json' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN questionnaire_data_json TEXT DEFAULT '{}'"))
            if 'profile_data_json' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN profile_data_json TEXT DEFAULT '[]'"))
            if 'contact_history_json' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN contact_history_json TEXT DEFAULT '[]'"))
            if 'contract_data_json' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN contract_data_json TEXT DEFAULT '{}'"))
            if 'street_address' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN street_address VARCHAR(255)"))
            if 'postal_code' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN postal_code VARCHAR(20)"))
            if 'city' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN city VARCHAR(100)"))
            if 'contract_number' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN contract_number VARCHAR(100)"))
            if 'monthly_rate' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN monthly_rate FLOAT"))
            if 'daily_rate' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN daily_rate FLOAT"))
            if 'mobile_phone' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN mobile_phone VARCHAR(64)"))
                conn.commit()
                print("✅ Migration: mobile_phone-Feld zu customers hinzugefügt")
            
            # Indizes für Performance hinzufügen (falls nicht vorhanden)
            try:
                # Customer Indizes
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_customers_created_at ON customers(created_at)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_customers_last_contact ON customers(last_contact)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_customers_status ON customers(status)"))
                
                # Dienstleistungsvertrag Indizes
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dlv_customer_id ON dienstleistungsvertraege(customer_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dlv_partner_id ON dienstleistungsvertraege(kooperationspartner_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dlv_created_at ON dienstleistungsvertraege(created_at)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dlv_status ON dienstleistungsvertraege(status)"))
                
                # Kooperationsvertrag Indizes
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_kv_sender_id ON kooperationsvertraege(sender_partner_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_kv_receiver_id ON kooperationsvertraege(receiver_partner_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_kv_created_at ON kooperationsvertraege(created_at)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_kv_status ON kooperationsvertraege(status)"))
                
                conn.commit()
            except Exception as idx_e:
                print(f"Index-Erstellung Fehler (kann ignoriert werden, wenn bereits vorhanden): {idx_e}")
                pass
            # Neuer Kundenstatus
            if 'status' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN status VARCHAR(50)"))
            
            # Kooperationspartner-Tabelle erstellen falls nicht vorhanden (nur für SQLite, PostgreSQL nutzt db.create_all())
            if not table_exists(conn, "kooperationspartner") and is_sqlite:
                conn.execute(text("""
                    CREATE TABLE kooperationspartner (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(200) NOT NULL,
                        email VARCHAR(200) NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                print("✅ kooperationspartner Tabelle erstellt")
            else:
                # Neue Spalten zu bestehender Kooperationspartner-Tabelle hinzufügen
                partner_cols = get_table_columns(conn, "kooperationspartner")
                if 'company_name' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN company_name VARCHAR(255)"))
                if 'street_address' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN street_address VARCHAR(255)"))
                if 'phone' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN phone VARCHAR(64)"))
                if 'identification_number' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN identification_number VARCHAR(100)"))
                if 'commercial_register' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN commercial_register VARCHAR(100)"))
                if 'vat_id' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN vat_id VARCHAR(100)"))
                if 'managing_director' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN managing_director VARCHAR(255)"))
                if 'emergency_phone' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN emergency_phone VARCHAR(64)"))
                if 'partner_company' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN partner_company VARCHAR(255)"))
                if 'contract_data_json' not in partner_cols:
                    conn.execute(text("ALTER TABLE kooperationspartner ADD COLUMN contract_data_json TEXT DEFAULT '{}'"))
            
            # Kooperationsvertrag-Tabelle erstellen falls nicht vorhanden (nur für SQLite, PostgreSQL nutzt db.create_all())
            if not table_exists(conn, "kooperationsvertraege") and is_sqlite:
                conn.execute(text("""
                    CREATE TABLE kooperationsvertraege (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender_partner_id INTEGER NOT NULL,
                        receiver_partner_id INTEGER NOT NULL,
                        contract_number VARCHAR(100) NOT NULL,
                        contract_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                        contract_location VARCHAR(255),
                        status VARCHAR(50) DEFAULT 'draft',
                        envelope_id VARCHAR(255),
                        pdf_filename VARCHAR(255),
                        signed_pdf_filename VARCHAR(255),
                        contract_data_json TEXT DEFAULT '{}',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (sender_partner_id) REFERENCES kooperationspartner (id),
                        FOREIGN KEY (receiver_partner_id) REFERENCES kooperationspartner (id)
                    )
                """))
                print("✅ kooperationsvertraege Tabelle erstellt")
            
            # Dienstleistungsvertrag-Tabelle erstellen falls nicht vorhanden (nur für SQLite, PostgreSQL nutzt db.create_all())
            if not table_exists(conn, "dienstleistungsvertraege") and is_sqlite:
                conn.execute(text("""
                    CREATE TABLE dienstleistungsvertraege (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_id INTEGER NOT NULL,
                        kooperationspartner_id INTEGER NOT NULL,
                        contract_number VARCHAR(100) NOT NULL,
                        contract_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                        monthly_rate FLOAT,
                        daily_rate FLOAT,
                        contract_location VARCHAR(100),
                        status VARCHAR(50) DEFAULT 'draft',
                        zoho_request_id VARCHAR(255),
                        pdf_filename VARCHAR(255),
                        signed_pdf_filename VARCHAR(255),
                        contract_data_json TEXT DEFAULT '{}',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (customer_id) REFERENCES customers (id),
                        FOREIGN KEY (kooperationspartner_id) REFERENCES kooperationspartner (id)
                    )
                """))
                print("✅ dienstleistungsvertraege Tabelle erstellt")
    except Exception:
        pass

# 👥 Benutzer (Session-basierter Zugang für aktuelles Template)
USERS = {}
# Dynamisch alle USER_*_NAME / USER_*_PASS laden
for key, value in os.environ.items():
    # Suche nach Paarkeys USER_<X>_NAME
    if key.startswith('USER_') and key.endswith('_NAME'):
        suffix = key[len('USER_'):-len('_NAME')]
        name = value
        pw = os.getenv(f"USER_{suffix}_PASS")
        if name and pw:
            USERS[name] = pw

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
SEND_SCOPES = ['https://www.googleapis.com/auth/gmail.send']
SETTINGS_SCOPES = ['https://www.googleapis.com/auth/gmail.settings.basic']

# 📬 Google OAuth Flow Builder (env or credentials.json fallback)
def build_google_flow(redirect_uri: str, state: str = None, scopes=None) -> Flow:
    use_scopes = scopes or SCOPES
    client_config_json = os.getenv('GOOGLE_CLIENT_CONFIG_JSON')
    client_config_path = os.getenv('GOOGLE_CLIENT_CONFIG_PATH') or 'credentials.json'
    # 1) Try JSON from env (robust to accidental extra quotes and double-encoded JSON)
    if client_config_json:
        def normalize_json_text(t: str) -> str:
            s = (t or '').strip()
            for _ in range(2):
                if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                    s = s[1:-1]
            s = s.replace('\\"', '"')
            return s
        txt = normalize_json_text(client_config_json)
        for _ in range(3):
            try:
                maybe = json.loads(txt)
                if isinstance(maybe, dict):
                    return Flow.from_client_config(maybe, scopes=use_scopes, redirect_uri=redirect_uri, state=state)
                if isinstance(maybe, str):
                    txt = normalize_json_text(maybe)
                    continue
                break
            except Exception:
                break
    # 2) Try credentials file
    if os.path.exists(client_config_path):
        return Flow.from_client_secrets_file(client_config_path, scopes=use_scopes, redirect_uri=redirect_uri, state=state)
    # 3) Fallback to individual ID/SECRET
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    if client_id and client_secret:
        client_config = {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
            }
        }
        return Flow.from_client_config(client_config, scopes=use_scopes, redirect_uri=redirect_uri, state=state)
    raise RuntimeError("Google OAuth ist nicht konfiguriert. Setze GOOGLE_CLIENT_CONFIG_JSON (als reines JSON ohne zusätzliche Anführungszeichen), oder lege credentials.json ab, oder setze GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET.")

# 📬 E-Mail Auth über Environment (Fallback)
def load_credentials_from_env():
    token_str = os.getenv("TOKEN_JSON")
    if not token_str:
        raise Exception("TOKEN_JSON nicht gesetzt")
    token_data = json.loads(token_str)
    return Credentials.from_authorized_user_info(token_data, SCOPES)

# 📬 Nutzerbezogene Gmail-Creds
def load_user_gmail_credentials(username: str):
    cred = GmailCredential.query.filter_by(username=username).order_by(GmailCredential.id.desc()).first()
    if not cred:
        return None
    try:
        token_data = json.loads(cred.token_json)
        # Allow send scope if token already has it
        scopes = token_data.get('scopes') or token_data.get('_scopes') or []
        want = list({*SCOPES, *([s for s in SEND_SCOPES if any('gmail.send' in sc for sc in scopes)]), *([s for s in SETTINGS_SCOPES if any('gmail.settings' in sc for sc in scopes)])})
        return Credentials.from_authorized_user_info(token_data, want)
    except Exception:
        return None

# 📬 Gmail OAuth start
@app.route('/gmail/connect')
def gmail_connect():
    if "user" not in session:
        return redirect("/")
    try:
        # Optional: which slot (1..3) is being connected from the UI
        slot = request.args.get('slot')
        if slot in {"1", "2", "3"}:
            session['gmail_connect_slot'] = slot
        redirect_uri = url_for('gmail_callback', _external=True)
        # Request both read and send scopes to enable emailing PDFs
        requested_scopes = list({*SCOPES, *SEND_SCOPES, *SETTINGS_SCOPES})
        flow = build_google_flow(redirect_uri, scopes=requested_scopes)
        # Validate client type and redirect URI allowlist to prevent Google "invalid request"
        try:
            if getattr(flow, 'client_type', None) != 'web':
                return (
                    "Zugriff blockiert: Falscher OAuth-Clienttyp. Bitte in der Google Cloud Console einen 'Webanwendung'-OAuth-Client verwenden (nicht 'Installed').",
                    400,
                )
            allowed = (flow.client_config or {}).get('redirect_uris', [])
            if allowed and redirect_uri not in allowed:
                return (
                    f"Zugriff blockiert: Redirect URI nicht erlaubt. Füge {redirect_uri} in der Google Cloud Console unter 'Authorized redirect URIs' hinzu.",
                    400,
                )
        except Exception:
            pass
        authorization_url, state = flow.authorization_url(
            access_type='offline', include_granted_scopes='true', prompt='consent'
        )
        session['oauth_state'] = state
        # Persist PKCE code_verifier for the callback token exchange
        if getattr(flow, 'code_verifier', None):
            session['oauth_code_verifier'] = flow.code_verifier
        return redirect(authorization_url)
    except Exception as e:
        return f"Google OAuth Fehler ({url_for('gmail_callback', _external=True)}): {str(e)}", 400

# 📬 Gmail OAuth callback
@app.route('/gmail/callback')
def gmail_callback():
    if "user" not in session:
        return redirect("/")
    # optional: validate state
    expected_state = session.get('oauth_state')
    incoming_state = request.args.get('state')
    if expected_state and incoming_state and expected_state != incoming_state:
        return "Ungültiger OAuth-Status (state mismatch)", 400
    redirect_uri = url_for('gmail_callback', _external=True)
    try:
        # Recreate flow with same state and same scopes as initial request (read + send)
        requested_scopes = list({*SCOPES, *SEND_SCOPES, *SETTINGS_SCOPES})
        flow = build_google_flow(redirect_uri, state=expected_state, scopes=requested_scopes)
        code_verifier = session.get('oauth_code_verifier')
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        return f"Google OAuth Fehler: {str(e)}", 400
    creds: Credentials = flow.credentials
    token_json = creds.to_json()

    entry = GmailCredential(username=session.get('user'), token_json=token_json)
    db.session.add(entry)
    db.session.commit()
    session.pop('oauth_state', None)
    session.pop('oauth_code_verifier', None)
    return redirect('/dashboard')

# 📬 Exchange/Outlook IMAP-Verbindung (für IONOS Exchange)
@app.route('/api/exchange/connect', methods=['POST'])
def exchange_connect_imap():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    email_addr = data.get('email', '').strip()
    password = data.get('password', '').strip()
    imap_server = data.get('imap_server', 'imap.ionos.de').strip()
    imap_port = int(data.get('imap_port', 993))
    imap_use_ssl = data.get('imap_use_ssl', True)
    
    if not email_addr or not password:
        return jsonify({"error": "E-Mail-Adresse und Passwort erforderlich"}), 400
    
    # Teste IMAP-Verbindung
    try:
        # Timeout für Verbindung setzen
        socket.setdefaulttimeout(10)  # 10 Sekunden Timeout
        
        if imap_use_ssl:
            mail = imaplib.IMAP4_SSL(imap_server, imap_port, timeout=10)
        else:
            mail = imaplib.IMAP4(imap_server, imap_port, timeout=10)
        
        mail.login(email_addr, password)
        mail.select('INBOX')
        mail.logout()
        
        # Verbindung erfolgreich - speichern
        # Passwort verschlüsselt in token_json speichern (Base64 für einfache Verschlüsselung)
        # In Produktion sollte man eine bessere Verschlüsselung verwenden (z.B. Fernet)
        password_encrypted = base64.b64encode(password.encode()).decode()
        token_json = json.dumps({"password": password_encrypted, "method": "imap"})
        
        entry = ExchangeCredential(
            username=session.get('user'),
            email=email_addr,
            imap_server=imap_server,
            imap_port=imap_port,
            imap_use_ssl=imap_use_ssl,
            password=None,  # Nicht mehr im password-Feld speichern
            token_json=token_json
        )
        db.session.add(entry)
        db.session.commit()
        
        return jsonify({"success": True, "message": "Exchange-Konto erfolgreich verbunden"})
    except (socket.gaierror, OSError) as e:
        error_msg = str(e)
        if 'Name or service not known' in error_msg or '[Errno -2]' in error_msg or 'nodename nor servname provided' in error_msg:
            return jsonify({
                "error": f"DNS-Fehler: Server '{imap_server}' konnte nicht gefunden werden. Bitte überprüfen Sie den IMAP-Server-Namen.\n\nFür IONOS Exchange sollte der Server sein: exchange.ionos.eu\n\nBitte prüfen Sie auch Ihre IONOS Exchange Administration Tool Einstellungen."
            }), 400
        return jsonify({"error": f"Netzwerk-Fehler: {error_msg}"}), 400
    except socket.timeout as e:
        return jsonify({"error": f"Verbindungs-Timeout: Server '{imap_server}' antwortet nicht innerhalb von 10 Sekunden. Bitte überprüfen Sie Server und Port."}), 400
    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        if isinstance(error_msg, bytes):
            error_msg = error_msg.decode('utf-8', errors='ignore')
        if 'AUTHENTICATE failed' in error_msg or 'LOGIN failed' in error_msg or 'authentication failed' in error_msg.lower():
            return jsonify({
                "error": f"Authentifizierung fehlgeschlagen für {email_addr}.\n\nMögliche Ursachen:\n1. Falsches Passwort - Bitte überprüfen Sie das Passwort\n2. 2FA aktiviert - Erstellen Sie ein App-Passwort in IONOS\n3. IMAP nicht aktiviert - Prüfen Sie die IONOS Exchange-Einstellungen\n4. Sonderzeichen im Passwort - Versuchen Sie es ohne Sonderzeichen oder mit App-Passwort\n\nTipp: Falls Sie 2-Faktor-Authentifizierung aktiviert haben, müssen Sie in IONOS ein App-Passwort erstellen und dieses verwenden."
            }), 400
        return jsonify({"error": f"IMAP-Fehler: {error_msg}"}), 400
    except Exception as e:
        error_msg = str(e)
        if 'Name or service not known' in error_msg or '[Errno -2]' in error_msg:
            return jsonify({
                "error": f"Server '{imap_server}' konnte nicht gefunden werden. Bitte überprüfen Sie den IMAP-Server-Namen.\n\nFür IONOS Exchange sollte der Server sein: exchange.ionos.eu"
            }), 400
        return jsonify({"error": f"Fehler beim Verbinden: {error_msg}"}), 500

# 📬 Microsoft Exchange/Outlook OAuth start (Fallback für Microsoft 365)
@app.route('/exchange/connect')
def exchange_connect():
    if "user" not in session:
        return redirect("/")
    try:
        from requests_oauthlib import OAuth2Session
        import secrets
        
        # Microsoft OAuth-Konfiguration
        client_id = os.getenv('MICROSOFT_CLIENT_ID')
        client_secret = os.getenv('MICROSOFT_CLIENT_SECRET')
        redirect_uri = url_for('exchange_callback', _external=True)
        
        if not client_id or not client_secret:
            return "Microsoft OAuth ist nicht konfiguriert. Bitte setze MICROSOFT_CLIENT_ID und MICROSOFT_CLIENT_SECRET in .env", 400
        
        # Microsoft Graph API Scopes
        scopes = [
            'https://graph.microsoft.com/Mail.Read',
            'https://graph.microsoft.com/Mail.Send',
            'https://graph.microsoft.com/User.Read'
        ]
        
        # OAuth2Session erstellen
        oauth = OAuth2Session(
            client_id,
            redirect_uri=redirect_uri,
            scope=scopes
        )
        
        # Authorization URL generieren
        authorization_url, state = oauth.authorization_url(
            'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
            access_type='offline',
            prompt='consent'
        )
        
        session['exchange_oauth_state'] = state
        session['exchange_client_secret'] = client_secret
        
        return redirect(authorization_url)
    except Exception as e:
        return f"Microsoft OAuth Fehler: {str(e)}", 400

# 📬 Microsoft Exchange/Outlook OAuth callback
@app.route('/exchange/callback')
def exchange_callback():
    if "user" not in session:
        return redirect("/")
    
    expected_state = session.get('exchange_oauth_state')
    incoming_state = request.args.get('state')
    client_secret = session.get('exchange_client_secret')
    
    if expected_state and incoming_state and expected_state != incoming_state:
        return "Ungültiger OAuth-Status (state mismatch)", 400
    
    if not client_secret:
        return "OAuth-Session abgelaufen. Bitte erneut versuchen.", 400
    
    try:
        from requests_oauthlib import OAuth2Session
        
        client_id = os.getenv('MICROSOFT_CLIENT_ID')
        redirect_uri = url_for('exchange_callback', _external=True)
        
        oauth = OAuth2Session(
            client_id,
            redirect_uri=redirect_uri,
            state=expected_state
        )
        
        # Token abrufen
        token_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
        token = oauth.fetch_token(
            token_url,
            authorization_response=request.url,
            client_secret=client_secret
        )
        
        # Token in Datenbank speichern
        token_json = json.dumps(token)
        
        # E-Mail-Adresse abrufen
        email = None
        try:
            headers = {'Authorization': f"Bearer {token['access_token']}"}
            profile_response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
            if profile_response.ok:
                profile_data = profile_response.json()
                email = profile_data.get('mail') or profile_data.get('userPrincipalName')
        except Exception:
            pass
        
        entry = ExchangeCredential(
            username=session.get('user'),
            token_json=token_json,
            email=email or "Microsoft 365 Konto"
        )
        db.session.add(entry)
        db.session.commit()
        
        session.pop('exchange_oauth_state', None)
        session.pop('exchange_client_secret', None)
        return redirect('/dashboard')
    except Exception as e:
        return f"Microsoft OAuth Fehler: {str(e)}", 400

# 📥 Anfrage empfangen (extern)
@app.route("/api/externe-anfrage", methods=["POST"])
def externe_anfrage():
    try:
        data = request.get_json() or {}
        name = data.get("name")
        tel = data.get("tel")
        if not name:
            return jsonify({"error": "Ungültige Daten"}), 400
        anfrage = Anfrage(name=name, tel=tel)
        db.session.add(anfrage)
        db.session.commit()
        return jsonify({"success": True, "id": anfrage.id})
    except Exception as e:
        print(f"❌ Fehler in /api/externe-anfrage: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Fehler beim Speichern der Anfrage: {str(e)}"}), 500

# 📥 Anfrage anlegen (intern)
@app.route("/api/anfrage", methods=["POST"])
def neue_anfrage():
    data = request.get_json() or {}
    name = data.get("name")
    tel = data.get("tel")
    if not name:
        return jsonify({"error": "Ungültige Daten"}), 400
    anfrage = Anfrage(name=name, tel=tel)
    db.session.add(anfrage)
    db.session.commit()
    return jsonify({"success": True, "id": anfrage.id})

@app.route("/api/get-anfragen")
def get_anfragen():
    try:
        anfragen = Anfrage.query.order_by(Anfrage.id.desc()).limit(100).all()
        return jsonify([a.to_dict() for a in anfragen])
    except Exception as e:
        print(f"❌ Fehler in /api/get-anfragen: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Fehler beim Laden der Anfragen: {str(e)}"}), 500

# 🗑️ Anfrage löschen
@app.route('/api/anfragen/<int:anfrage_id>', methods=['DELETE'])
def delete_anfrage(anfrage_id: int):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    a = Anfrage.query.get(anfrage_id)
    if not a:
        return jsonify({"error": "Nicht gefunden"}), 404
    db.session.delete(a)
    db.session.commit()
    return jsonify({"success": True})

# 🔐 Login (Session)
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if USERS.get(username) == password:
            session["user"] = username
            return redirect("/dashboard")
        return "❌ Falscher Login", 401
    return render_template("login.html")

# 📊 Dashboard
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")
    
    # Deutsche Datumsformatierung
    now = datetime.datetime.now()
    wochentage_de = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
    monate_de = ['', 'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 
                 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']
    
    wochentag = wochentage_de[now.weekday()]
    monat = monate_de[now.month]
    aktuelles_datum = f"{wochentag}, {now.day}. {monat} {now.year}"
    
    username = session.get("user")
    return render_template("index.html", aktuelles_datum=aktuelles_datum, username=username)


@app.route("/profilersteller")
def profilersteller():
    """
    Liefert die Profilersteller-Standalone-App eingebettet unter /profilersteller.
    Assets (CSS, JS, Bilder) werden über /profilersteller/<path:filename> bereitgestellt.
    """
    return send_from_directory(os.path.join(os.getcwd(), "Profilersteller"), "index.html")


@app.route("/profilersteller/<path:filename>")
def profilersteller_static(filename):
    return send_from_directory(os.path.join(os.getcwd(), "Profilersteller"), filename)

# 📄 PDF Ablage – Konfiguration
UPLOAD_FOLDER = os.getenv('PDF_UPLOAD_DIR') or os.path.join(APP_DATA_DIR, 'uploaded_pdfs')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_PDF_EXTENSIONS = {'.pdf'}

def _is_pdf_filename(name: str) -> bool:
    _, ext = os.path.splitext(name.lower())
    return ext in ALLOWED_PDF_EXTENSIONS

# 🚀 Default-Vorlage (Befragungsbogen) einmalig importieren
def _seed_befragungsbogen_template():
    try:
        # Bereits vorhanden?
        existing = PdfDocument.query.filter(PdfDocument.filename.ilike('%Befragungsbogen%')).first()
        if existing:
            return
        # Quelldatei im Projektverzeichnis
        project_root = os.getcwd()
        source_path = os.path.join(project_root, 'bedarfsfragebogen.pdf')
        if not os.path.exists(source_path):
            return
        # In Upload-Ablage kopieren und in DB registrieren
        unique_name = uuid.uuid4().hex + '.pdf'
        dest_path = os.path.join(UPLOAD_FOLDER, unique_name)
        with open(source_path, 'rb') as src, open(dest_path, 'wb') as dst:
            dst.write(src.read())
        doc = PdfDocument(filename='Befragungsbogen.pdf', stored_filename=unique_name, uploaded_by='system')
        db.session.add(doc)
        db.session.commit()
    except Exception:
        # Seed-Fehler sollen den App-Start nicht verhindern
        pass

# Seed beim App-Start innerhalb des App-Kontexts ausführen
with app.app_context():
    _seed_befragungsbogen_template()

# 📄 Liste der PDFs
@app.route('/api/pdfs', methods=['GET'])
def list_pdfs():
    try:
        if "user" not in session:
            return jsonify({"error": "Nicht eingeloggt"}), 401
        docs = PdfDocument.query.order_by(PdfDocument.id.desc()).limit(500).all()
        return jsonify([d.to_dict() for d in docs])
    except Exception as e:
        print(f"❌ Fehler in /api/pdfs GET: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Fehler beim Laden der PDFs: {str(e)}"}), 500

# 📄 PDF hochladen
@app.route('/api/pdfs', methods=['POST'])
def upload_pdf():
    try:
        if "user" not in session:
            return jsonify({"error": "Nicht eingeloggt"}), 401
        if 'file' not in request.files:
            return jsonify({"error": "Keine Datei übermittelt"}), 400
        f = request.files['file']
        if not f or not f.filename:
            return jsonify({"error": "Ungültige Datei"}), 400
        original = secure_filename(f.filename)
        if not _is_pdf_filename(original):
            return jsonify({"error": "Nur PDF-Dateien sind erlaubt"}), 400
        unique = uuid.uuid4().hex + '.pdf'
        path = os.path.join(UPLOAD_FOLDER, unique)
        f.save(path)
        doc = PdfDocument(filename=original, stored_filename=unique, uploaded_by=session.get('user'))
        db.session.add(doc)
        db.session.commit()
        return jsonify(doc.to_dict()), 201
    except Exception as e:
        print(f"❌ Fehler in /api/pdfs POST: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Fehler beim Hochladen der PDF: {str(e)}"}), 500

# 📄 PDF herunterladen
@app.route('/api/pdfs/<int:doc_id>', methods=['GET'])
def download_pdf(doc_id: int):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    doc = PdfDocument.query.get(doc_id)
    if not doc:
        return jsonify({"error": "Nicht gefunden"}), 404
    path = os.path.join(UPLOAD_FOLDER, doc.stored_filename)
    if not os.path.exists(path):
        return jsonify({"error": "Datei fehlt auf dem Server"}), 410
    return send_file(path, as_attachment=True, download_name=doc.filename, mimetype='application/pdf')

# 📄 PDF löschen (Datei + DB-Eintrag)
@app.route('/api/pdfs/<int:doc_id>', methods=['DELETE'])
def delete_pdf(doc_id: int):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    doc = PdfDocument.query.get(doc_id)
    if not doc:
        return jsonify({"error": "Nicht gefunden"}), 404
    path = os.path.join(UPLOAD_FOLDER, doc.stored_filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        # Datei konnte ggf. nicht gelöscht werden – wir löschen dennoch den DB-Eintrag,
        # um keine Waisen zu behalten. Der Fehler ist nicht kritisch.
        pass
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"success": True})

# 📄 PDF Template (z.B. Befragungsbogen) inline öffnen per Name-Suche
@app.route('/api/pdfs/open-template')
def open_template_pdf():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({"error": "Parameter 'name' erforderlich"}), 400
    # Finde die zuletzt hochgeladene PDF, deren Original-Dateiname den Namen enthält
    q = PdfDocument.query.filter(PdfDocument.filename.ilike(f"%{name}%")).order_by(PdfDocument.id.desc()).first()
    if not q:
        # Fallback: zeige die zuletzt hochgeladene PDF
        q = PdfDocument.query.order_by(PdfDocument.id.desc()).first()
        if not q:
            return jsonify({"error": f"Vorlage '{name}' nicht gefunden"}), 404
    path = os.path.join(UPLOAD_FOLDER, q.stored_filename)
    if not os.path.exists(path):
        return jsonify({"error": "Datei fehlt auf dem Server"}), 410
    # Inline im Browser anzeigen (iframe-kompatibel)
    return send_file(path, as_attachment=False, download_name=q.filename, mimetype='application/pdf')

# 📧 Neueste Befragungsbogen-PDF direkt versenden
@app.route('/api/send-latest-befragungsbogen', methods=['POST'])
def send_latest_befragungsbogen():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    payload = request.get_json() or {}
    to_email = (payload.get('to') or '').strip()
    filename = (payload.get('filename') or 'Befragungsbogen.pdf').strip() or 'Befragungsbogen.pdf'
    if not to_email:
        return jsonify({"error": "Empfänger (to) erforderlich"}), 400

    # Finde neueste PDF, deren Originalname 'Befragungsbogen' enthält, sonst letzte beliebige
    doc = (
        PdfDocument.query
        .filter(PdfDocument.filename.ilike('%Befragungsbogen%'))
        .order_by(PdfDocument.id.desc())
        .first()
    ) or PdfDocument.query.order_by(PdfDocument.id.desc()).first()
    if not doc:
        return jsonify({"error": "Kein Dokument vorhanden"}), 404

    path = os.path.join(UPLOAD_FOLDER, doc.stored_filename)
    if not os.path.exists(path):
        return jsonify({"error": "Datei fehlt auf dem Server"}), 410

    # Datei lesen und base64 enkodieren
    with open(path, 'rb') as f:
        pdf_bytes = f.read()
    pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')

    # Reiche an bestehende Versandlogik weiter (Subject/Body optional aus Payload)
    data = {
        'to': to_email,
        'filename': filename,
        'pdf_base64': f'data:application/pdf;base64,{pdf_b64}',
        'subject': payload.get('subject'),
        'body': payload.get('body'),
        'sms_number': payload.get('sms_number'),
        'sms_name': payload.get('sms_name'),
        'lastName': payload.get('lastName'),
    }

    # Nutze die gleiche Implementierung wie /api/send-offer, aber mit SMTP
    try:
        subject = data.get('subject') or "Befragungsbogen"
        body = data.get('body') or (
            "Sehr geehrte Damen und Herren,\n\n"
            "anbei finden Sie den Bedarfsfragebogen eines neuen Kunden.\n\n"
            "Viele Grüße"
        )
        
        # SMTP-Konfiguration aus Umgebungsvariablen
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
        smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
        smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
        
        if not smtp_username or not smtp_password:
            return jsonify({"error": "SMTP-Credentials nicht konfiguriert. Bitte SMTP_USERNAME und SMTP_PASSWORD in .env setzen."}), 400

        # Signatur für SMTP-Absender abrufen, falls Postfach hinterlegt
        # Versuche zuerst mit smtp_username, dann mit 'kontakt@helpcare.de' als Fallback
        signature = get_signature_for_email(smtp_username)
        if not signature and smtp_username != 'kontakt@helpcare.de':
            print(f"⚠️ Signatur nicht für {smtp_username} gefunden, versuche kontakt@helpcare.de")
            signature = get_signature_for_email('kontakt@helpcare.de')
        print(f"🔍 Signatur-Abruf für {smtp_username}: {'✅ gefunden' if signature else '❌ nicht gefunden'}")
        newline = '\n'
        
        # E-Mail erstellen
        message = MIMEMultipart('mixed')
        message['Subject'] = subject
        message['From'] = f"HelpCare <{smtp_username}>"
        
        # Für Befragungsbogen: BCC an alle Kooperationspartner
        partners = Kooperationspartner.query.all()
        bcc_emails = [partner.email for partner in partners if partner.email]
        
        # Für Befragungsbogen: An team@helpcare.de statt befragungsbogen@helpcare.de senden
        if to_email == 'befragungsbogen@helpcare.de':
            actual_to_email = 'team@helpcare.de'
        else:
            actual_to_email = to_email

        # Prepare text and HTML bodies mit Signatur (OHNE BCC-Info)
        body_text_final = body
        
        # HTML-Tabellen-basiertes Template erstellen
        # Body in Zeilen aufteilen
        body_lines = body.split(newline)
        # Leere Zeilen am Anfang/Ende entfernen, aber innere Leerzeilen behalten
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        
        # HTML-Template mit Tabellen erstellen
        body_html_final = create_html_email_template(body_lines, signature if signature else None)
        
        # Signatur IMMER hinzufügen, wenn vorhanden (für Plain-Text)
        if signature:
            print(f"✅ Füge Signatur hinzu (Länge: {len(signature)} Zeichen)")
            # Für Plain-Text: HTML-Tags entfernen
            import re
            from html import unescape
            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace(newline, ' ').strip()
            body_text_final = f"{body}{newline}{newline}{signature_text}"
            print(f"✅ HTML-Body mit Signatur erstellt (Gesamtlänge: {len(body_html_final)} Zeichen)")
        else:
            print(f"⚠️ Keine Signatur vorhanden, verwende nur Body")

        # Text und HTML Versionen (für alle Empfänger - OHNE BCC-Info)
        text_part = MIMEText(body_text_final, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        
        # Alternative part (text + HTML)
        alternative = MIMEMultipart('alternative')
        alternative.attach(text_part)
        alternative.attach(html_part)
        
        # PDF-Daten vorbereiten
        if pdf_b64.startswith('data:application/pdf;base64,'):
            pdf_b64_clean = pdf_b64.split(',', 1)[1]
        else:
            pdf_b64_clean = pdf_b64
        pdf_data = base64.b64decode(pdf_b64_clean)
        
        # Für Befragungsbogen: Separate E-Mails senden
        if bcc_emails:
            # 1. E-Mail an team@helpcare.de MIT Partner-Liste (intern)
            bcc_info_text = f"\n\n---\nDiese E-Mail wurde an folgende Kooperationspartner gesendet:\n" + "\n".join(f"  • {email}" for email in bcc_emails)
            # BCC-Info als HTML-Tabellen-Struktur hinzufügen
            bcc_info_html = """
                                    <tr>
                                        <td style="padding-top: 24px; border-top: 1px solid #e0e0e0;">
                                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                                <tr>
                                                    <td style="font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 1.4; color: #666666; padding-bottom: 4px; mso-line-height-rule: exactly;">
                                                        Diese E-Mail wurde an folgende Kooperationspartner gesendet:
                                                    </td>
                                                </tr>
"""
            for email in bcc_emails:
                bcc_info_html += f"""
                                                <tr>
                                                    <td style="font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 1.4; color: #666666; padding-left: 16px; padding-bottom: 2px; mso-line-height-rule: exactly;">
                                                        • {email}
                                                    </td>
                                                </tr>
"""
            bcc_info_html += """
                                            </table>
                                        </td>
                                    </tr>
"""
            
            body_team_text = body_text_final + bcc_info_text
            # HTML: BCC-Info vor dem schließenden </table> des Inhalts einfügen
            body_team_html = body_html_final.replace('</table>', bcc_info_html + '</table>', 1)
            
            text_part_team = MIMEText(body_team_text, 'plain', 'utf-8')
            html_part_team = MIMEText(body_team_html, 'html', 'utf-8')
            
            alternative_team = MIMEMultipart('alternative')
            alternative_team.attach(text_part_team)
            alternative_team.attach(html_part_team)
            
            message_team = MIMEMultipart('mixed')
            message_team['Subject'] = subject
            message_team['From'] = f"HelpCare <{smtp_username}>"
            message_team['To'] = actual_to_email
            # KEIN BCC-Feld - nur interne E-Mail an Team
            message_team.attach(alternative_team)
            
            pdf_attachment_team = MIMEBase('application', 'pdf')
            pdf_attachment_team.set_payload(pdf_data)
            encoders.encode_base64(pdf_attachment_team)
            pdf_attachment_team.add_header('Content-Disposition', f'attachment; filename={filename}')
            message_team.attach(pdf_attachment_team)
            
            # SMTP-Verbindung einmal öffnen für alle E-Mails
            if smtp_use_ssl:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
                server.login(smtp_username, smtp_password)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port)
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
            
            # Team-E-Mail senden
            server.send_message(message_team)
            print(f"✅ E-Mail an {actual_to_email} gesendet (mit Liste der {len(bcc_emails)} Partner)")
            
            # 2. Separate E-Mails an jeden Partner (ohne BCC-Info, jeder sieht nur seine eigene)
            for partner_email in bcc_emails:
                message_partner = MIMEMultipart('mixed')
                message_partner['Subject'] = subject
                message_partner['From'] = f"HelpCare <{smtp_username}>"
                message_partner['To'] = partner_email
                # KEIN BCC-Feld - jeder Partner bekommt seine eigene E-Mail
                message_partner.attach(alternative)  # Normale Body ohne BCC-Info
                
                pdf_attachment_partner = MIMEBase('application', 'pdf')
                pdf_attachment_partner.set_payload(pdf_data)
                encoders.encode_base64(pdf_attachment_partner)
                pdf_attachment_partner.add_header('Content-Disposition', f'attachment; filename={filename}')
                message_partner.attach(pdf_attachment_partner)
                
                server.send_message(message_partner)
                print(f"✅ E-Mail an Kooperationspartner {partner_email} gesendet")
            
            server.quit()
            print(f"✅ Insgesamt {len(bcc_emails) + 1} E-Mails gesendet (1 an Team, {len(bcc_emails)} an Partner)")
        else:
            # Normale E-Mail (keine Partner)
            message['To'] = actual_to_email
            message.attach(alternative)
            
            pdf_attachment = MIMEBase('application', 'pdf')
            pdf_attachment.set_payload(pdf_data)
            encoders.encode_base64(pdf_attachment)
            pdf_attachment.add_header('Content-Disposition', f'attachment; filename={filename}')
            message.attach(pdf_attachment)

            # SMTP-Verbindung aufbauen und E-Mail senden
            if smtp_use_ssl:
                # SSL-Verbindung (Port 465)
                with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            else:
                # STARTTLS-Verbindung (Port 587)
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    if smtp_use_tls:
                        server.starttls()
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            
            print(f"✅ E-Mail erfolgreich über SMTP versendet an {actual_to_email}")
        
        # Kunde automatisch speichern mit Befragungsbogen-Daten
        questionnaire_data = {
            'subject': subject,
            'body': body,
            'filename': filename,
            'lastName': data.get('lastName'),
            'sms_name': data.get('sms_name'),
            'sms_number': data.get('sms_number'),
            'sent_at': datetime.datetime.utcnow().isoformat(),
            # In diesem Flow geht der Fragebogen IMMER an alle Partner, daher speichern wir diese explizit
            'bcc_recipients': bcc_emails,
        }
        print(f"DEBUG: Speichere Befragungsbogen-Daten für {to_email}: {questionnaire_data}")
        customer = save_customer_from_email(to_email, questionnaire_data=questionnaire_data)
        print(f"DEBUG: Kunde gespeichert: {customer}")
        
        return jsonify({"success": True})
        
    except smtplib.SMTPAuthenticationError as e:
        error_str = str(e)
        print(f"❌ SMTP-Authentifizierungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Authentifizierung fehlgeschlagen. Bitte SMTP-Credentials (Benutzername/Passwort) überprüfen. Server: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPConnectError as e:
        error_str = str(e)
        print(f"❌ SMTP-Verbindungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Verbindung fehlgeschlagen. Bitte SMTP-Server und Port überprüfen. Versucht: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPDataError as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore')
        print(f"❌ SMTP-Datenfehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except smtplib.SMTPException as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore') if hasattr(e, 'smtp_error') else error_str
        print(f"❌ SMTP-Fehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except Exception as e:
        error_str = str(e)
        print(f"❌ E-Mail-Versand Fehler: {error_str}")
        return jsonify({"error": f"E-Mail-Versand fehlgeschlagen: {error_str}"}), 500

# 🧾 Editor-Seite für Befragungsbogen (pdf.js)
@app.route('/befragungsbogen/editor')
def befragungsbogen_editor():
    if "user" not in session:
        return redirect("/")
    return render_template("befragungsbogen_editor.html")

# 📄 1-Person Bedarfsfragebogen
@app.route('/befragungsbogen/1-person')
def befragungsbogen_1_person():
    if "user" not in session:
        return redirect("/")
    path = os.path.join(os.path.dirname(__file__), 'templates', 'bedarfsfragebogen-1-person.html')
    if not os.path.exists(path):
        return "Datei nicht gefunden", 404
    return send_file(path, mimetype='text/html')


# 📧 Rechnung per E-Mail versenden (PDF Base64)
@app.route('/api/invoices/send-email', methods=['POST'])
def send_invoice_email():
    """
    Versendet eine Rechnung als PDF-Anhang an den Kooperationspartner
    und schickt eine kurze interne Bestätigung an team@helpcare.de.
    """
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    data = request.get_json() or {}
    to_email = (data.get('to') or '').strip()
    invoice_number = (data.get('invoiceNumber') or '').strip()
    pdf_b64 = data.get('pdf_base64') or ''
    partner_name = (data.get('partnerName') or '').strip()
    customer_name = (data.get('customerName') or '').strip()

    if not to_email or not invoice_number or not pdf_b64:
        return jsonify({"error": "to, invoiceNumber und pdf_base64 sind erforderlich"}), 400

    # Externe E-Mail an Rechnungsempfänger
    subject = f"HelpCare | Rechnung Nr. {invoice_number}"
    body = (
        "Sehr geehrte Damen und Herren,\n\n"
        f"anbei finden Sie Ihre Rechnung {invoice_number}\n\n"
        "Viele Grüße"
    )

    # SMTP-Konfiguration aus Umgebungsvariablen (wie bei /api/send-offer)
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
    smtp_port = int(os.getenv('SMTP_PORT', '465'))
    smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
    smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
    smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'

    if not smtp_username or not smtp_password:
        return jsonify({"error": "SMTP-Credentials nicht konfiguriert. Bitte SMTP_USERNAME und SMTP_PASSWORD in .env setzen."}), 400

    try:
        # Signatur für SMTP-Absender abrufen
        signature = get_signature_for_email(smtp_username)
        if not signature and smtp_username != 'kontakt@helpcare.de':
            signature = get_signature_for_email('kontakt@helpcare.de')

        newline = '\n'

        # Body-Zeilen und HTML-Template aufbauen
        body_lines = body.split(newline)
        # Leere Zeilen am Anfang/Ende entfernen
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()

        body_html_final = create_html_email_template(body_lines, signature if signature else None)

        body_text_final = body
        if signature:
            import re
            from html import unescape

            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace(newline, ' ').strip()
            body_text_final = f"{body}{newline}{newline}{signature_text}"

        # PDF-Daten vorbereiten
        if isinstance(pdf_b64, str) and pdf_b64.startswith('data:application/pdf;base64,'):
            pdf_b64_clean = pdf_b64.split(',', 1)[1]
        else:
            pdf_b64_clean = pdf_b64

        pdf_data = base64.b64decode(pdf_b64_clean)
        filename = f"Rechnung-{invoice_number}.pdf"

        # Externe E-Mail an Rechnungsempfänger
        message = MIMEMultipart('mixed')
        message['Subject'] = subject
        message['From'] = f"HelpCare <{smtp_username}>"
        message['To'] = to_email

        alternative = MIMEMultipart('alternative')
        text_part = MIMEText(body_text_final, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        alternative.attach(text_part)
        alternative.attach(html_part)
        message.attach(alternative)

        pdf_attachment = MIMEBase('application', 'pdf')
        pdf_attachment.set_payload(pdf_data)
        encoders.encode_base64(pdf_attachment)
        pdf_attachment.add_header('Content-Disposition', f'attachment; filename={filename}')
        message.attach(pdf_attachment)

        # Interne Bestätigung an team@helpcare.de
        now = datetime.datetime.now()
        sent_at_str = now.strftime('%d.%m.%Y %H:%M:%S')
        internal_to = 'team@helpcare.de'
        internal_subject = f"Rechnung versendet – {invoice_number}"
        internal_body_lines = [
            "Interne Bestätigung:",
            "",
            f"Rechnung {invoice_number} wurde am {sent_at_str} versendet.",
            f"Empfänger: {to_email}",
        ]
        if partner_name:
            internal_body_lines.append(f"Kooperationspartner: {partner_name}")
        if customer_name:
            internal_body_lines.append(f"Kunde: {customer_name}")

        internal_html = create_html_email_template(internal_body_lines, signature if signature else None)
        internal_text = "\n".join(internal_body_lines)
        if signature:
            # Text-Signatur anhängen
            import re
            from html import unescape

            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace('\n', ' ').strip()
            internal_text = f"{internal_text}\n\n{signature_text}"

        internal_message = MIMEMultipart('mixed')
        internal_message['Subject'] = internal_subject
        internal_message['From'] = f"HelpCare <{smtp_username}>"
        internal_message['To'] = internal_to

        internal_alt = MIMEMultipart('alternative')
        internal_alt.attach(MIMEText(internal_text, 'plain', 'utf-8'))
        internal_alt.attach(MIMEText(internal_html, 'html', 'utf-8'))
        internal_message.attach(internal_alt)

        # Beide E-Mails über eine SMTP-Verbindung senden
        if smtp_use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            server.login(smtp_username, smtp_password)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            if smtp_use_tls:
                server.starttls()
            server.login(smtp_username, smtp_password)

        server.send_message(message)
        server.send_message(internal_message)
        server.quit()

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"⚠️ Fehler beim Versand der Rechnungs-E-Mail: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Fehler beim Versand der Rechnung: {str(e)}"}), 500

# 📄 2-Personen Bedarfsfragebogen
@app.route('/befragungsbogen/2-personen')
def befragungsbogen_2_personen():
    if "user" not in session:
        return redirect("/")
    
    # Kunden-ID aus Query-Parameter holen
    customer_id = request.args.get('customer_id', '')
    
    path = os.path.join(os.path.dirname(__file__), 'templates', 'bedarfsfragebogen-2-personen.html')
    if not os.path.exists(path):
        return "Datei nicht gefunden", 404
    
    # Template mit Kunden-ID rendern
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Kunden-ID in den Titel einbetten
    if customer_id:
        content = content.replace(
            '<h1 style="text-align: center;">Bedarfsfragebogen</h1>',
            f'<h1 style="text-align: center;">Bedarfsfragebogen - Kunden-ID: {customer_id}</h1>'
        )
    
    return content

# 📄 Aktueller Bedarfsfragebogen (statisches HTML vom Projektroot)
@app.route('/befragungsbogen/aktueller')
def aktueller_bedarfsfragebogen():
    if "user" not in session:
        return redirect("/")
    path = os.path.join(os.getcwd(), 'aktueller-bedarfsfragebogen.html')
    if not os.path.exists(path):
        return "Datei 'aktueller-bedarfsfragebogen.html' nicht gefunden.", 404
    return send_file(path, mimetype='text/html')

# -----------------
# Betreuungskräfte
# -----------------

@app.route('/api/caregivers', methods=['GET'])
def list_caregivers():
    items = Caregiver.query.order_by(Caregiver.created_at.desc()).all()
    return jsonify([c.to_dict() for c in items])

@app.route('/api/caregivers', methods=['POST'])
def create_caregiver():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()
    if not name or not email:
        return jsonify({'error': 'Name und E-Mail sind erforderlich'}), 400
    c = Caregiver(name=name, email=email, phone=phone)
    db.session.add(c)
    db.session.commit()
    return jsonify(c.to_dict())

@app.route('/api/caregivers/<int:cid>', methods=['PUT'])
def update_caregiver(cid: int):
    c = Caregiver.query.get(cid)
    if not c:
        return jsonify({'error': 'Nicht gefunden'}), 404
    data = request.get_json() or {}
    if 'name' in data: c.name = (data.get('name') or '').strip()
    if 'email' in data: c.email = (data.get('email') or '').strip()
    if 'phone' in data: c.phone = (data.get('phone') or '').strip()
    if 'notes' in data: c.notes = data.get('notes')
    db.session.commit()
    return jsonify(c.to_dict())

@app.route('/api/caregivers/<int:cid>', methods=['DELETE'])
def delete_caregiver(cid: int):
    c = Caregiver.query.get(cid)
    if not c:
        return jsonify({'error': 'Nicht gefunden'}), 404
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})

def refresh_zoho_token():
    """Erneuert den Zoho Access Token mit dem Refresh Token"""
    import requests, json as pyjson
    
    print(f"🔍 DEBUG: refresh_zoho_token aufgerufen")
    
    refresh_token = os.environ.get('ZOHO_SIGN_REFRESH_TOKEN')
    client_id = os.environ.get('ZOHO_CLIENT_ID')
    client_secret = os.environ.get('ZOHO_CLIENT_SECRET')
    
    print(f"🔍 DEBUG: refresh_token: {refresh_token}")
    print(f"🔍 DEBUG: client_id: {client_id}")
    print(f"🔍 DEBUG: client_secret: {client_secret}")
    
    if not all([refresh_token, client_id, client_secret]):
        print(f"🔍 DEBUG: Fehlende Tokens!")
        return None
    
    try:
        url = 'https://accounts.zoho.eu/oauth/v2/token'
        data = {
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'refresh_token'
        }
        
        print(f"🔍 DEBUG: Sende Anfrage an: {url}")
        print(f"🔍 DEBUG: Data: {data}")
        
        resp = requests.post(url, data=data, timeout=10)
        print(f"🔍 DEBUG: Response Status: {resp.status_code}")
        print(f"🔍 DEBUG: Response Text: {resp.text}")
        
        if resp.status_code == 200:
            token_data = resp.json()
            new_access_token = token_data.get('access_token')
            if new_access_token:
                # Token in Umgebungsvariable setzen (für diese Session)
                os.environ['ZOHO_SIGN_ACCESS_TOKEN'] = new_access_token
                print(f"✅ Zoho Token erfolgreich erneuert")
                return new_access_token
        else:
            print(f"❌ Fehler beim Token-Refresh: Status {resp.status_code}")
    except Exception as e:
        print(f"❌ Fehler beim Token-Refresh: {e}")
    
    return None

def get_zoho_access_token():
    """Holt einen gültigen Zoho Access Token (erneuert bei Bedarf)"""
    access_token = os.environ.get('ZOHO_SIGN_ACCESS_TOKEN')
    
    # Wenn kein Token vorhanden, versuche Refresh
    if not access_token:
        access_token = refresh_zoho_token()
    
    return access_token

@app.route('/api/debug/zoho-token')
def debug_zoho_token():
    """Debug-Endpoint für Zoho Token"""
    print(f"🔍 DEBUG: debug_zoho_token aufgerufen")
    
    # Teste refresh_zoho_token direkt
    print(f"🔍 DEBUG: Teste refresh_zoho_token()")
    refreshed_token = refresh_zoho_token()
    print(f"🔍 DEBUG: refresh_zoho_token() Ergebnis: {refreshed_token}")
    
    access_token = get_zoho_access_token()
    print(f"🔍 DEBUG: get_zoho_access_token() Ergebnis: {access_token}")
    
    return jsonify({
        'access_token': access_token,
        'refreshed_token': refreshed_token,
        'has_refresh_token': bool(os.environ.get('ZOHO_SIGN_REFRESH_TOKEN')),
        'has_client_id': bool(os.environ.get('ZOHO_CLIENT_ID')),
        'has_client_secret': bool(os.environ.get('ZOHO_CLIENT_SECRET'))
    })

@app.route('/api/caregivers/<int:cid>/contract', methods=['POST'])
def send_caregiver_contract(cid: int):
    """Sendet einen Testvertrag zur digitalen Signatur über Zoho Sign und speichert die Response am Caregiver."""
    print(f"🔍 DEBUG: send_caregiver_contract aufgerufen mit cid={cid}")
    
    c = Caregiver.query.get(cid)
    if not c:
        print(f"🔍 DEBUG: Betreuungskraft {cid} nicht gefunden")
        return jsonify({'error': 'Betreuungskraft nicht gefunden'}), 404
    
    print(f"🔍 DEBUG: Betreuungskraft gefunden: {c.name} ({c.email})")
    
    payload = request.get_json() or {}
    # Minimaler Testvertrag-Body
    test_subject = payload.get('subject') or 'Testvertrag Betreuungskraft'
    test_message = payload.get('message') or 'Bitte prüfen und digital unterschreiben.'

    # Einfache HTML-Vorlage (kann später ersetzt werden)
    html_content = payload.get('html') or f"""
    <html><body>
      <h2>Betreuungsvertrag ({test_subject})</h2>
      <p>Name: {c.name}</p>
      <p>E-Mail: {c.email}</p>
      <p>Datum: {{today}}</p>
      <p>Bitte unterschreiben Sie unten.</p>
      <p>__________________________</p>
      <p>Unterschrift: __________________________</p>
      <p>Datum: __________________________</p>
    </body></html>
    """

    # Zoho Sign: Erstellung eines Signaturantrags (via API)
    import requests, base64, json as pyjson
    
    # Versuche zuerst Token aus Request, dann automatischen Refresh
    access_token = payload.get('access_token') or get_zoho_access_token()
    
    if not access_token:
        return jsonify({
            'error': 'Zoho Access Token fehlt. Bitte setze folgende Umgebungsvariablen:\n'
                    '- ZOHO_SIGN_REFRESH_TOKEN\n'
                    '- ZOHO_CLIENT_ID\n'
                    '- ZOHO_CLIENT_SECRET\n\n'
                    'Oder gib einen Token im Request-Body an.'
        }), 400

    # Dokument aus HTML als Base64-PDF
    html_b64 = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')

    # Zoho Sign API Request - korrekte Struktur basierend auf offizieller API
    api_url = 'https://sign.zoho.eu/api/v1/requests'
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}',
        'Content-Type': 'application/json'
    }
    
    # Korrekte Struktur für Zoho Sign API (mit requests Array)
    req_body = {
        'requests': [
            {
                'request_name': test_subject,
                'actions': [
                    {
                        'recipient_name': c.name,
                        'recipient_email': c.email,
                        'action_type': 'SIGN'
                    }
                ],
                'documents': [
                    {
                        'document_name': 'Vertrag.html',
                        'document_data': html_b64
                    }
                ]
            }
        ]
    }
    
    print(f"🔍 Debug: Korrekte Struktur: {pyjson.dumps(req_body, indent=2)}")
    
    # SCHRITT 1: Request erstellen mit form-data (nicht JSON!)
    import io
    
    # JSON-Daten für form-data mit Signaturfeldern
    request_data = {
        "requests": {
            "request_name": test_subject,
            "actions": [
                {
                    "action_type": "SIGN",
                    "recipient_email": c.email,
                    "recipient_name": c.name,
                    "signing_order": 1,
                    "verify_recipient": False,
                    "verification_type": "EMAIL",
                    "verification_code": "",
                    "private_notes": test_message,
                }
            ],
            "expiration_days": 30,
            "is_sequential": True,
            "email_reminders": True,
            "reminder_period": 7
        }
    }
    
    print(f"🔍 Debug: Request Data: {pyjson.dumps(request_data, indent=2)}")
    
    # Form-data vorbereiten
    files = {
        'file': ('Vertrag.html', io.BytesIO(html_content.encode('utf-8')), 'text/html')
    }
    
    data = {
        'data': pyjson.dumps(request_data)
    }
    
    # Headers für form-data (nicht JSON!)
    form_headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    
    print(f"🔍 Debug: Erstelle Request mit form-data")
    create_resp = requests.post(api_url, headers=form_headers, data=data, files=files, timeout=30)
    
    try:
        create_json = create_resp.json()
    except Exception:
        create_json = {'status_code': create_resp.status_code, 'text': create_resp.text}
    
    print(f"🔍 Debug: Create Response: {create_json}")
    
    if create_resp.status_code >= 300:
        return jsonify({'error': 'Zoho Sign Request-Erstellung fehlgeschlagen', 'response': create_json}), 502
    
    # SCHRITT 2: Request submiten
    print(f"🔍 Debug: Create Response Structure: {create_json}")
    
    # Extrahiere request_id aus der Zoho Sign Antwort
    request_id = None
    if 'requests' in create_json and isinstance(create_json['requests'], dict):
        request_id = create_json['requests'].get('request_id')
    elif 'requests' in create_json and isinstance(create_json['requests'], list) and len(create_json['requests']) > 0:
        request_id = create_json['requests'][0].get('request_id')
    elif 'request_id' in create_json:
        request_id = create_json['request_id']
    elif 'id' in create_json:
        request_id = create_json['id']
    
    print(f"🔍 Debug: Extrahierte Request ID: {request_id}")
    
    if not request_id:
        return jsonify({'error': 'Request ID nicht erhalten', 'response': create_json}), 502
    
    # SCHRITT 2: Request submiten
    submit_url = f'https://sign.zoho.eu/api/v1/requests/{request_id}/submit'
    print(f"🔍 Debug: Submit URL: {submit_url}")
    
    # Submit-Headers (nur Authorization, kein Content-Type für Submit)
    submit_headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    
    submit_resp = requests.post(submit_url, headers=submit_headers, timeout=30)
    
    try:
        submit_json = submit_resp.json()
    except Exception:
        submit_json = {'status_code': submit_resp.status_code, 'text': submit_resp.text}
    
    print(f"🔍 Debug: Submit Response: {submit_json}")
    
    if submit_resp.status_code >= 300:
        return jsonify({'error': 'Zoho Sign Request-Submit fehlgeschlagen', 'response': submit_json}), 502
    
    # Erfolgreiche Antwort
    resp_json = submit_json

    # Response am Caregiver speichern
    c.contract_data_json = pyjson.dumps(resp_json)
    db.session.commit()
    return jsonify({'success': True, 'response': resp_json, 'caregiver': c.to_dict()})

# 📧 Befragungsbogen mit übergebenen Formularwerten ausfüllen, schreibschützen und versenden
@app.route('/api/send-befragungsbogen-filled', methods=['POST'])
def send_befragungsbogen_filled():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    payload = request.get_json() or {}
    to_email = (payload.get('to') or '').strip()
    filename = (payload.get('filename') or 'Befragungsbogen.pdf').strip() or 'Befragungsbogen.pdf'
    fields = payload.get('fields') or {}
    if not to_email:
        return jsonify({"error": "Empfänger (to) erforderlich"}), 400
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception as e:
        return jsonify({"error": f"pypdf fehlt oder fehlerhaft: {str(e)}"}), 500

    # Vorlage laden (neueste Befragungsbogen)
    doc = (
        PdfDocument.query
        .filter(PdfDocument.filename.ilike('%Befragungsbogen%'))
        .order_by(PdfDocument.id.desc())
        .first()
    ) or PdfDocument.query.order_by(PdfDocument.id.desc()).first()
    if not doc:
        return jsonify({"error": "Kein Dokument vorhanden"}), 404
    path = os.path.join(UPLOAD_FOLDER, doc.stored_filename)
    if not os.path.exists(path):
        return jsonify({"error": "Datei fehlt auf dem Server"}), 410

    # PDF befüllen
    try:
        reader = PdfReader(path)
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        # Form-Felder pro Seite aktualisieren
        for page in writer.pages:
            try:
                writer.update_page_form_field_values(page, fields)
            except Exception:
                pass
        # Felder schreibgeschützt setzen
        try:
            acroform = writer._root_object.get('/AcroForm')
            if acroform:
                fields_array = acroform.get('/Fields') or []
                for fld in fields_array:
                    obj = fld.get_object()
                    # /Ff Bit 1 (ReadOnly) setzen
                    current = obj.get('/Ff', 0)
                    obj.update({ '/Ff': int(current) | 1 })
                # NeedAppearances deaktivieren
                acroform.update({'/NeedAppearances': False})
        except Exception:
            pass
        # In Memory schreiben
        import io
        out_buf = io.BytesIO()
        writer.write(out_buf)
        pdf_bytes = out_buf.getvalue()
        pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')
        # zusätzlich auf Server speichern
        stored_name = uuid.uuid4().hex + '.pdf'
        dest_path = os.path.join(UPLOAD_FOLDER, stored_name)
        with open(dest_path, 'wb') as f:
            f.write(pdf_bytes)
        saved_doc = PdfDocument(filename=filename, stored_filename=stored_name, uploaded_by=session.get('user'))
        db.session.add(saved_doc)
        db.session.commit()
    except Exception as e:
        return jsonify({"error": f"PDF-Befüllung fehlgeschlagen: {str(e)}"}), 500

    # E-Mail senden über SMTP
    try:
        subject = payload.get('subject') or "Befragungsbogen"
        body = payload.get('body') or (
            "Sehr geehrte Damen und Herren,\n\n"
            "anbei finden Sie den Bedarfsfragebogen eines neuen Kunden.\n\n"
            "Viele Grüße"
        )
        
        # SMTP-Konfiguration aus Umgebungsvariablen
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
        smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
        smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
        
        if not smtp_username or not smtp_password:
            return jsonify({"error": "SMTP-Credentials nicht konfiguriert. Bitte SMTP_USERNAME und SMTP_PASSWORD in .env setzen."}), 400

        # Signatur für SMTP-Absender abrufen, falls Postfach hinterlegt
        # Versuche zuerst mit smtp_username, dann mit 'kontakt@helpcare.de' als Fallback
        signature = get_signature_for_email(smtp_username)
        if not signature and smtp_username != 'kontakt@helpcare.de':
            print(f"⚠️ Signatur nicht für {smtp_username} gefunden, versuche kontakt@helpcare.de")
            signature = get_signature_for_email('kontakt@helpcare.de')
        newline = '\n'
        
        # E-Mail erstellen
        message = MIMEMultipart('mixed')
        message['Subject'] = subject
        message['From'] = f"HelpCare <{smtp_username}>"
        
        # Für Befragungsbogen: BCC an ausgewählte Kooperationspartner
        # Prüfe ob Partner explizit übergeben wurden
        partners_data = payload.get('partners', [])
        if partners_data:
            # Verwende übergebene Partner
            bcc_emails = [partner.get('email') for partner in partners_data if partner.get('email')]
        else:
            # Fallback: Alle Partner (für Rückwärtskompatibilität)
            partners = Kooperationspartner.query.all()
            bcc_emails = [partner.email for partner in partners if partner.email]
        
        # Für Befragungsbogen: An team@helpcare.de statt befragungsbogen@helpcare.de senden
        if to_email == 'befragungsbogen@helpcare.de':
            actual_to_email = 'team@helpcare.de'
        else:
            actual_to_email = to_email
        
        # Prepare text and HTML bodies mit Signatur (OHNE BCC-Info)
        body_text_final = body
        body_html_final = body.replace(newline, '<br>')
        
        # Body escapen (bevor Signatur hinzugefügt wird)
        body_html_escaped = body_html_final.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        if signature:
            # Für Plain-Text: HTML-Tags entfernen
            import re
            from html import unescape
            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace(newline, ' ').strip()
            body_text_final = f"{body}{newline}{newline}{signature_text}"
            # Für HTML: Signatur nach dem Escaping hinzufügen (Signatur ist bereits HTML)
            body_html_final = f"{body_html_escaped}<br><br>{signature}"
        else:
            body_html_final = body_html_escaped
        
        body_html_final = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
            body_html_final +
            "</div>"
        )

        # Text und HTML Versionen (für alle Empfänger - OHNE BCC-Info)
        text_part = MIMEText(body_text_final, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        
        # Alternative part (text + HTML)
        alternative = MIMEMultipart('alternative')
        alternative.attach(text_part)
        alternative.attach(html_part)
        
        # PDF-Daten vorbereiten
        pdf_data = base64.b64decode(pdf_b64)
        
        # Für Befragungsbogen: Separate E-Mails senden
        if bcc_emails:
            # 1. E-Mail an team@helpcare.de MIT Partner-Liste (intern)
            bcc_info_text = f"\n\n---\nDiese E-Mail wurde an folgende Kooperationspartner gesendet:\n" + "\n".join(f"  • {email}" for email in bcc_emails)
            # BCC-Info als HTML-Tabellen-Struktur hinzufügen
            bcc_info_html = """
                                    <tr>
                                        <td style="padding-top: 24px; border-top: 1px solid #e0e0e0;">
                                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                                <tr>
                                                    <td style="font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 1.4; color: #666666; padding-bottom: 4px; mso-line-height-rule: exactly;">
                                                        Diese E-Mail wurde an folgende Kooperationspartner gesendet:
                                                    </td>
                                                </tr>
"""
            for email in bcc_emails:
                bcc_info_html += f"""
                                                <tr>
                                                    <td style="font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 1.4; color: #666666; padding-left: 16px; padding-bottom: 2px; mso-line-height-rule: exactly;">
                                                        • {email}
                                                    </td>
                                                </tr>
"""
            bcc_info_html += """
                                            </table>
                                        </td>
                                    </tr>
"""
            
            body_team_text = body_text_final + bcc_info_text
            # HTML: BCC-Info vor dem schließenden </table> des Inhalts einfügen
            body_team_html = body_html_final.replace('</table>', bcc_info_html + '</table>', 1)
            
            text_part_team = MIMEText(body_team_text, 'plain', 'utf-8')
            html_part_team = MIMEText(body_team_html, 'html', 'utf-8')
            
            alternative_team = MIMEMultipart('alternative')
            alternative_team.attach(text_part_team)
            alternative_team.attach(html_part_team)
            
            message_team = MIMEMultipart('mixed')
            message_team['Subject'] = subject
            message_team['From'] = f"HelpCare <{smtp_username}>"
            message_team['To'] = actual_to_email
            # KEIN BCC-Feld - nur interne E-Mail an Team
            message_team.attach(alternative_team)
            
            pdf_attachment_team = MIMEBase('application', 'pdf')
            pdf_attachment_team.set_payload(pdf_data)
            encoders.encode_base64(pdf_attachment_team)
            pdf_attachment_team.add_header('Content-Disposition', f'attachment; filename={filename}')
            message_team.attach(pdf_attachment_team)
            
            # SMTP-Verbindung einmal öffnen für alle E-Mails
            if smtp_use_ssl:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
                server.login(smtp_username, smtp_password)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port)
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
            
            # Team-E-Mail senden
            server.send_message(message_team)
            print(f"✅ E-Mail an {actual_to_email} gesendet (mit Liste der {len(bcc_emails)} Partner)")
            
            # 2. Separate E-Mails an jeden Partner (ohne BCC-Info, jeder sieht nur seine eigene)
            for partner_email in bcc_emails:
                message_partner = MIMEMultipart('mixed')
                message_partner['Subject'] = subject
                message_partner['From'] = f"HelpCare <{smtp_username}>"
                message_partner['To'] = partner_email
                # KEIN BCC-Feld - jeder Partner bekommt seine eigene E-Mail
                message_partner.attach(alternative)  # Normale Body ohne BCC-Info
                
                pdf_attachment_partner = MIMEBase('application', 'pdf')
                pdf_attachment_partner.set_payload(pdf_data)
                encoders.encode_base64(pdf_attachment_partner)
                pdf_attachment_partner.add_header('Content-Disposition', f'attachment; filename={filename}')
                message_partner.attach(pdf_attachment_partner)
                
                server.send_message(message_partner)
                print(f"✅ E-Mail an Kooperationspartner {partner_email} gesendet")
            
            server.quit()
            print(f"✅ Insgesamt {len(bcc_emails) + 1} E-Mails gesendet (1 an Team, {len(bcc_emails)} an Partner)")
        else:
            # Normale E-Mail (keine Partner)
            message['To'] = actual_to_email
            message.attach(alternative)
            
            pdf_attachment = MIMEBase('application', 'pdf')
            pdf_attachment.set_payload(pdf_data)
            encoders.encode_base64(pdf_attachment)
            pdf_attachment.add_header('Content-Disposition', f'attachment; filename={filename}')
            message.attach(pdf_attachment)

            # SMTP-Verbindung aufbauen und E-Mail senden
            if smtp_use_ssl:
                # SSL-Verbindung (Port 465)
                with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            else:
                # STARTTLS-Verbindung (Port 587)
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    if smtp_use_tls:
                        server.starttls()
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            
            print(f"✅ E-Mail erfolgreich über SMTP versendet an {actual_to_email}")
        
        # Kunde automatisch speichern mit Befragungsbogen-Daten (inkl. ausgefüllte Felder)
        questionnaire_data = {
            'subject': subject,
            'body': body,
            'filename': filename,
            'fields': fields,  # Alle ausgefüllten Formularfelder
            'sent_at': datetime.datetime.utcnow().isoformat()
        }
        save_customer_from_email(to_email, questionnaire_data=questionnaire_data)
        
        return jsonify({"success": True})
        
    except smtplib.SMTPAuthenticationError as e:
        error_str = str(e)
        print(f"❌ SMTP-Authentifizierungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Authentifizierung fehlgeschlagen. Bitte SMTP-Credentials (Benutzername/Passwort) überprüfen. Server: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPConnectError as e:
        error_str = str(e)
        print(f"❌ SMTP-Verbindungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Verbindung fehlgeschlagen. Bitte SMTP-Server und Port überprüfen. Versucht: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPDataError as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore')
        print(f"❌ SMTP-Datenfehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except smtplib.SMTPException as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore') if hasattr(e, 'smtp_error') else error_str
        print(f"❌ SMTP-Fehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except Exception as e:
        error_str = str(e)
        print(f"❌ E-Mail-Versand Fehler: {error_str}")
        return jsonify({"error": f"E-Mail-Versand fehlgeschlagen: {error_str}"}), 500

# 📧 E-Mail API (Gmail und Exchange)
@app.route("/api/emails")
def get_emails():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    cred_id_param = request.args.get('cred_id')
    account_type = request.args.get('type', 'gmail')  # 'gmail' oder 'exchange'
    slot_param = request.args.get('slot')

    try:
        if account_type == 'exchange':
            # Exchange/Outlook über IMAP oder Microsoft Graph API
            cred_row = None
            if cred_id_param:
                try:
                    cred_id_int = int(cred_id_param)
                    cred_row = ExchangeCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            else:
                # Neuestes Exchange-Konto
                cred_row = (
                    ExchangeCredential.query
                    .filter_by(username=session['user'])
                    .order_by(ExchangeCredential.id.desc())
                    .first()
                )
            
            if not cred_row:
                return jsonify({"error": "Kein Exchange-Konto verbunden. Bitte Postfach hinzufügen."}), 400
            
            # Prüfe ob IMAP oder OAuth verwendet wird
            if cred_row.imap_server and cred_row.token_json:
                try:
                    token_data = json.loads(cred_row.token_json)
                    if token_data.get('method') == 'imap':
                        # IMAP-Verbindung (IONOS Exchange)
                        password_encrypted = token_data.get('password')
                        if not password_encrypted:
                            return jsonify({"error": "Passwort nicht verfügbar. Bitte Postfach erneut verbinden."}), 400
                        password = base64.b64decode(password_encrypted.encode()).decode()
                    else:
                        # OAuth-Token vorhanden, aber kein IMAP
                        raise ValueError("Kein IMAP-Passwort")
                except:
                    return jsonify({"error": "Passwort nicht verfügbar. Bitte Postfach erneut verbinden."}), 400
                
                try:
                    # IMAP-Verbindung
                    if cred_row.imap_use_ssl:
                        mail = imaplib.IMAP4_SSL(cred_row.imap_server, cred_row.imap_port)
                    else:
                        mail = imaplib.IMAP4(cred_row.imap_server, cred_row.imap_port)
                    
                    mail.login(cred_row.email, password)
                    mail.select('INBOX')
                    
                    # Suche nach ungelesenen E-Mails, dann neueste
                    typ, message_ids = mail.search(None, 'ALL')
                    if typ != 'OK':
                        mail.logout()
                        return jsonify({"error": "Fehler beim Abrufen der E-Mails"}), 500
                    
                    message_ids = message_ids[0].split()
                    # Neueste 10 E-Mails
                    message_ids = message_ids[-10:] if len(message_ids) > 10 else message_ids
                    message_ids.reverse()  # Neueste zuerst
                    
                    email_list = []
                    for msg_id in message_ids:
                        typ, msg_data = mail.fetch(msg_id, '(RFC822)')
                        if typ != 'OK':
                            continue
                        
                        msg = email.message_from_bytes(msg_data[0][1])
                        
                        # Header dekodieren
                        def decode_mime_words(s):
                            if not s:
                                return ''
                            decoded = decode_header(s)
                            return ''.join([str(t[0], t[1] or 'utf-8') if isinstance(t[0], bytes) else t[0] for t in decoded])
                        
                        from_addr = decode_mime_words(msg.get('From', 'Unbekannt'))
                        subject = decode_mime_words(msg.get('Subject', '(Kein Betreff)'))
                        
                        # Datum
                        date_tuple = email.utils.parsedate_tz(msg.get('Date', ''))
                        if date_tuple:
                            dt = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
                            time_str = dt.strftime('%d.%m.%Y – %H:%M')
                        else:
                            time_str = 'Unbekannt'
                        
                        # Snippet (erste Zeilen des Textes)
                        snippet = ''
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == 'text/plain':
                                    try:
                                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                        snippet = body[:200].replace('\n', ' ').strip()
                                    except:
                                        pass
                                    break
                        else:
                            try:
                                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                                snippet = body[:200].replace('\n', ' ').strip()
                            except:
                                pass
                        
                        # Prüfe ob ungelesen
                        flags = mail.fetch(msg_id, '(FLAGS)')[1][0].decode()
                        is_unread = '\\Seen' not in flags
                        
                        email_list.append({
                            "from": from_addr,
                            "subject": subject,
                            "time": time_str,
                            "snippet": snippet,
                            "unread": is_unread,
                            "id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                            "threadId": None,
                        })
                    
                    mail.logout()
                    return jsonify(email_list)
                except imaplib.IMAP4.error as e:
                    return jsonify({"error": f"IMAP-Fehler: {str(e)}"}), 500
                except Exception as e:
                    return jsonify({"error": f"Fehler beim Abrufen der E-Mails: {str(e)}"}), 500
            elif cred_row.token_json:
                # Microsoft Graph API (OAuth)
                token_data = json.loads(cred_row.token_json)
                access_token = token_data.get('access_token')
                
                if not access_token:
                    return jsonify({"error": "Ungültiger Token. Bitte Postfach erneut verbinden."}), 400
                
                # Microsoft Graph API aufrufen
                headers = {'Authorization': f'Bearer {access_token}'}
                graph_url = 'https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages'
                params = {'$top': 10, '$orderby': 'receivedDateTime desc'}
                
                response = requests.get(graph_url, headers=headers, params=params)
                if not response.ok:
                    if response.status_code == 401:
                        return jsonify({"error": "Token abgelaufen. Bitte Postfach erneut verbinden."}), 401
                    return jsonify({"error": f"Fehler bei Microsoft Graph API: {response.text}"}), 500
                
                graph_data = response.json()
                messages = graph_data.get('value', [])
                
                email_list = []
                for msg in messages:
                    from_addr = msg.get('from', {}).get('emailAddress', {}).get('address', 'Unbekannt')
                    from_name = msg.get('from', {}).get('emailAddress', {}).get('name', '')
                    from_display = f"{from_name} <{from_addr}>" if from_name else from_addr
                    
                    received = msg.get('receivedDateTime', '')
                    if received:
                        try:
                            dt = datetime.datetime.fromisoformat(received.replace('Z', '+00:00'))
                            time_str = dt.strftime('%d.%m.%Y – %H:%M')
                        except:
                            time_str = received[:10]
                    else:
                        time_str = 'Unbekannt'
                    
                    email_info = {
                        "from": from_display,
                        "subject": msg.get('subject', '(Kein Betreff)'),
                        "time": time_str,
                        "snippet": msg.get('bodyPreview', '') or msg.get('body', {}).get('content', '')[:200],
                        "unread": not msg.get('isRead', False),
                        "id": msg.get('id'),
                        "threadId": msg.get('conversationId'),
                    }
                    email_list.append(email_info)
                
                return jsonify(email_list)
            else:
                return jsonify({"error": "Keine gültige Verbindungsmethode konfiguriert."}), 400
        else:
            # Gmail (bestehende Logik)
            cred_row = None
            if cred_id_param:
                try:
                    cred_id_int = int(cred_id_param)
                    cred_row = GmailCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            if not cred_row:
                # Fallback auf Slots 1..3
                slot_index = 1
                if slot_param is not None:
                    try:
                        slot_index = int(slot_param)
                    except Exception:
                        slot_index = 1
                slot_index = max(1, min(3, slot_index))
                cred_row = (
                    GmailCredential.query
                    .filter_by(username=session['user'])
                    .order_by(GmailCredential.id.desc())
                    .offset(slot_index - 1)
                    .first()
                )
            if not cred_row:
                return jsonify({"error": "Kein Gmail-Konto verbunden. Bitte Postfach hinzufügen."}), 400
            token_data = json.loads(cred_row.token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            service = build('gmail', 'v1', credentials=creds)
            results = service.users().messages().list(userId='me', maxResults=10).execute()
            messages = results.get('messages', [])

            email_list = []
            for msg in messages:
                msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
                headers = msg_data['payload']['headers']
                email_info = {
                    "from": next((h['value'] for h in headers if h['name'] == 'From'), 'Unbekannt'),
                    "subject": next((h['value'] for h in headers if h['name'] == 'Subject'), '(Kein Betreff)'),
                    "time": datetime.datetime.fromtimestamp(
                        int(msg_data['internalDate']) / 1000).strftime('%d.%m.%Y – %H:%M'),
                    "snippet": msg_data.get('snippet', ''),
                    "unread": 'UNREAD' in (msg_data.get('labelIds') or []),
                    "id": msg_data.get('id'),
                    "threadId": msg_data.get('threadId'),
                }
                email_list.append(email_info)

            return jsonify(email_list)
    except Exception as e:
        return jsonify({"error": f"Fehler bei E-Mail API: {str(e)}"}), 500

# 📧 Vollständige E-Mail abrufen
@app.route('/api/emails/<email_id>/body')
def get_email_body():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    email_id = request.view_args.get('email_id')
    cred_id_param = request.args.get('cred_id')
    account_type = request.args.get('type', 'exchange')
    
    try:
        if account_type == 'exchange':
            cred_row = None
            if cred_id_param:
                try:
                    cred_id_int = int(cred_id_param)
                    cred_row = ExchangeCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            
            if not cred_row:
                return jsonify({"error": "Kein Exchange-Konto verbunden"}), 400
            
            # IMAP-Verbindung
            if cred_row.imap_server and cred_row.token_json:
                try:
                    token_data = json.loads(cred_row.token_json)
                    if token_data.get('method') == 'imap':
                        password_encrypted = token_data.get('password')
                        if not password_encrypted:
                            return jsonify({"error": "Passwort nicht verfügbar"}), 400
                        password = base64.b64decode(password_encrypted.encode()).decode()
                    else:
                        return jsonify({"error": "Kein IMAP-Passwort"}), 400
                except:
                    return jsonify({"error": "Passwort nicht verfügbar"}), 400
                
                try:
                    if cred_row.imap_use_ssl:
                        mail = imaplib.IMAP4_SSL(cred_row.imap_server, cred_row.imap_port)
                    else:
                        mail = imaplib.IMAP4(cred_row.imap_server, cred_row.imap_port)
                    
                    mail.login(cred_row.email, password)
                    mail.select('INBOX')
                    
                    # E-Mail abrufen
                    typ, msg_data = mail.fetch(email_id.encode() if isinstance(email_id, str) else str(email_id).encode(), '(RFC822)')
                    if typ != 'OK':
                        mail.logout()
                        return jsonify({"error": "E-Mail nicht gefunden"}), 404
                    
                    msg = email.message_from_bytes(msg_data[0][1])
                    
                    # Vollständigen Body extrahieren
                    body_text = ''
                    body_html = ''
                    
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type == 'text/plain' and not body_text:
                                try:
                                    body_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                except:
                                    pass
                            elif content_type == 'text/html' and not body_html:
                                try:
                                    body_html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                except:
                                    pass
                    else:
                        content_type = msg.get_content_type()
                        if content_type == 'text/plain':
                            try:
                                body_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                            except:
                                pass
                        elif content_type == 'text/html':
                            try:
                                body_html = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                            except:
                                pass
                    
                    mail.logout()
                    
                    return jsonify({
                        "body": body_html or body_text,
                        "bodyText": body_text,
                        "bodyHtml": body_html
                    })
                except Exception as e:
                    return jsonify({"error": f"Fehler beim Abrufen der E-Mail: {str(e)}"}), 500
            elif cred_row.token_json:
                # Microsoft Graph API
                token_data = json.loads(cred_row.token_json)
                access_token = token_data.get('access_token')
                
                if not access_token:
                    return jsonify({"error": "Ungültiger Token"}), 400
                
                headers = {'Authorization': f'Bearer {access_token}'}
                graph_url = f'https://graph.microsoft.com/v1.0/me/messages/{email_id}'
                
                response = requests.get(graph_url, headers=headers)
                if not response.ok:
                    return jsonify({"error": f"Fehler bei Microsoft Graph API: {response.text}"}), 500
                
                msg_data = response.json()
                body_html = msg_data.get('body', {}).get('content', '')
                body_text = msg_data.get('bodyPreview', '')
                
                return jsonify({
                    "body": body_html or body_text,
                    "bodyText": body_text,
                    "bodyHtml": body_html
                })
            else:
                return jsonify({"error": "Keine gültige Verbindungsmethode"}), 400
        else:
            # Gmail
            cred_row = None
            if cred_id_param:
                try:
                    cred_id_int = int(cred_id_param)
                    cred_row = GmailCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            
            if not cred_row:
                return jsonify({"error": "Kein Gmail-Konto verbunden"}), 400
            
            token_data = json.loads(cred_row.token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            service = build('gmail', 'v1', credentials=creds)
            
            msg_data = service.users().messages().get(userId='me', id=email_id, format='full').execute()
            
            # Body extrahieren
            body_text = ''
            body_html = ''
            
            def extract_body(parts):
                nonlocal body_text, body_html
                for part in parts:
                    mime_type = part.get('mimeType', '')
                    if mime_type == 'text/plain':
                        data = part.get('body', {}).get('data', '')
                        if data:
                            body_text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    elif mime_type == 'text/html':
                        data = part.get('body', {}).get('data', '')
                        if data:
                            body_html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    
                    if 'parts' in part:
                        extract_body(part['parts'])
            
            payload = msg_data.get('payload', {})
            if 'parts' in payload:
                extract_body(payload['parts'])
            else:
                mime_type = payload.get('mimeType', '')
                data = payload.get('body', {}).get('data', '')
                if data:
                    decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    if mime_type == 'text/html':
                        body_html = decoded
                    else:
                        body_text = decoded
            
            return jsonify({
                "body": body_html or body_text,
                "bodyText": body_text,
                "bodyHtml": body_html
            })
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen der E-Mail: {str(e)}"}), 500

# 📧 Ungelesene Nachrichten zählen (pro Slot oder cred_id)
@app.route('/api/emails/unread_count')
def unread_count():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    cred_id_param = request.args.get('cred_id')
    account_type = request.args.get('type', 'gmail')
    slot_param = request.args.get('slot')

    try:
        if account_type == 'exchange':
            cred_row = None
            if cred_id_param:
                try:
                    cred_id_int = int(cred_id_param)
                    cred_row = ExchangeCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    pass
            if not cred_row:
                cred_row = (
                    ExchangeCredential.query
                    .filter_by(username=session['user'])
                    .order_by(ExchangeCredential.id.desc())
                    .first()
                )
            if not cred_row:
                return jsonify({"count": 0, "connected": False})
            
            # Prüfe ob IMAP oder OAuth
            if cred_row.imap_server and cred_row.token_json:
                try:
                    token_data = json.loads(cred_row.token_json)
                    if token_data.get('method') == 'imap':
                        password_encrypted = token_data.get('password')
                        if not password_encrypted:
                            return jsonify({"count": 0, "connected": False})
                        password = base64.b64decode(password_encrypted.encode()).decode()
                        
                        # IMAP-Verbindung
                        if cred_row.imap_use_ssl:
                            mail = imaplib.IMAP4_SSL(cred_row.imap_server, cred_row.imap_port)
                        else:
                            mail = imaplib.IMAP4(cred_row.imap_server, cred_row.imap_port)
                        
                        mail.login(cred_row.email, password)
                        mail.select('INBOX')
                        
                        # Ungelesene E-Mails zählen
                        typ, message_ids = mail.search(None, 'UNSEEN')
                        if typ == 'OK':
                            count = len(message_ids[0].split()) if message_ids[0] else 0
                        else:
                            count = 0
                        
                        mail.logout()
                        return jsonify({"count": int(count), "connected": True})
                except Exception:
                    return jsonify({"count": 0, "connected": False})
            elif cred_row.token_json:
                # OAuth (Microsoft Graph API)
                token_data = json.loads(cred_row.token_json)
                access_token = token_data.get('access_token')
                if not access_token:
                    return jsonify({"count": 0, "connected": False})
                
                headers = {'Authorization': f'Bearer {access_token}'}
                graph_url = 'https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages'
                params = {'$filter': 'isRead eq false', '$count': 'true', '$top': 1}
                response = requests.get(graph_url, headers=headers, params=params)
                if response.ok:
                    data = response.json()
                    count = data.get('@odata.count', len(data.get('value', [])))
                    return jsonify({"count": int(count), "connected": True})
                return jsonify({"count": 0, "connected": False})
            else:
                return jsonify({"count": 0, "connected": False})
        else:
            # Gmail (bestehende Logik)
            cred_row = None
            if cred_id_param:
                try:
                    cred_id_int = int(cred_id_param)
                except Exception:
                    cred_id_int = None
                if cred_id_int:
                    cred_row = GmailCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
            if not cred_row:
                slot_index = 1
                if slot_param is not None:
                    try:
                        slot_index = int(slot_param)
                    except Exception:
                        slot_index = 1
                slot_index = max(1, min(3, slot_index))
                cred_row = (
                    GmailCredential.query
                    .filter_by(username=session['user'])
                    .order_by(GmailCredential.id.desc())
                    .offset(slot_index - 1)
                    .first()
                )
            if not cred_row:
                return jsonify({"count": 0, "connected": False})
            token_data = json.loads(cred_row.token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            service = build('gmail', 'v1', credentials=creds)
            results = service.users().messages().list(userId='me', q='is:unread', maxResults=1).execute() or {}
            count = results.get('resultSizeEstimate', 0)
            return jsonify({"count": int(count), "connected": True})
    except Exception:
        return jsonify({"count": 0, "connected": False})

# Gmail-Account löschen
@app.route('/api/gmail/accounts/<int:cred_id>', methods=['DELETE'])
def delete_gmail_account(cred_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        cred = GmailCredential.query.filter_by(id=cred_id, username=session['user']).first()
        if not cred:
            return jsonify({"error": "Gmail-Account nicht gefunden"}), 404
        
        db.session.delete(cred)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

# 📧 Liste aller verbundenen Gmail-Postfächer (Email + unread)
@app.route('/api/gmail/accounts')
def gmail_accounts():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    rows = (
        GmailCredential.query
        .filter_by(username=session['user'])
        .order_by(GmailCredential.id.desc())
        .all()
    )
    accounts = []
    for r in rows:
        try:
            token_data = json.loads(r.token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            service = build('gmail', 'v1', credentials=creds)
            # Email-Adresse bestimmen: via profile
            email_addr = None
            try:
                prof = service.users().getProfile(userId='me').execute() or {}
                email_addr = prof.get('emailAddress')
            except Exception:
                email_addr = None
            # Ungelesen schätzen
            try:
                res = service.users().messages().list(userId='me', q='is:unread', maxResults=1).execute() or {}
                unread_est = int(res.get('resultSizeEstimate', 0))
            except Exception:
                unread_est = 0
            accounts.append({
                "cred_id": r.id,
                "email": email_addr or "Verbundenes Konto",
                "unread": unread_est,
                "type": "gmail",
            })
        except Exception:
            continue
    return jsonify(accounts)

# 📧 Liste aller verbundenen Postfächer (Gmail + Exchange)
@app.route('/api/mail/accounts')
def mail_accounts():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    accounts = []
    
    # Nur Exchange-Konten (Gmail wurde entfernt)
    # Exchange-Konten
    exchange_rows = (
        ExchangeCredential.query
        .filter_by(username=session['user'])
        .order_by(ExchangeCredential.id.desc())
        .all()
    )
    for r in exchange_rows:
        try:
            email_addr = r.email or "Verbundenes Konto"
            unread_est = 0
            
            # Prüfe ob IMAP oder OAuth
            if r.imap_server and r.token_json:
                try:
                    token_data = json.loads(r.token_json)
                    if token_data.get('method') == 'imap':
                        # IMAP: Ungelesen zählen
                        password_encrypted = token_data.get('password')
                        if password_encrypted:
                            password = base64.b64decode(password_encrypted.encode()).decode()
                            if r.imap_use_ssl:
                                mail = imaplib.IMAP4_SSL(r.imap_server, r.imap_port)
                            else:
                                mail = imaplib.IMAP4(r.imap_server, r.imap_port)
                            mail.login(r.email, password)
                            mail.select('INBOX')
                            typ, message_ids = mail.search(None, 'UNSEEN')
                            if typ == 'OK':
                                unread_est = len(message_ids[0].split()) if message_ids[0] else 0
                            mail.logout()
                except Exception:
                    pass
            elif r.token_json:
                # OAuth (Microsoft Graph API)
                try:
                    token_data = json.loads(r.token_json)
                    access_token = token_data.get('access_token')
                    if access_token:
                        headers = {'Authorization': f'Bearer {access_token}'}
                        graph_url = 'https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages'
                        params = {'$filter': 'isRead eq false', '$count': 'true', '$top': 1}
                        response = requests.get(graph_url, headers=headers, params=params)
                        if response.ok:
                            data = response.json()
                            unread_est = data.get('@odata.count', len(data.get('value', [])))
                except Exception:
                    pass
            
            accounts.append({
                "cred_id": r.id,
                "email": email_addr,
                "unread": unread_est,
                "type": "exchange",
            })
        except Exception:
            continue
    
    return jsonify(accounts)

# 📧 Vollständige E-Mail abrufen (für Antwort)
@app.route('/api/emails/<email_id>/detail')
def get_email_detail():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    cred_id_param = request.args.get('cred_id')
    account_type = request.args.get('type', 'exchange')
    
    try:
        if account_type == 'exchange':
            cred_row = ExchangeCredential.query.filter_by(id=int(cred_id_param), username=session['user']).first()
            if not cred_row or not cred_row.imap_server:
                return jsonify({"error": "Konto nicht gefunden"}), 404
            
            token_data = json.loads(cred_row.token_json)
            if token_data.get('method') != 'imap':
                return jsonify({"error": "Nur IMAP wird unterstützt"}), 400
            
            password = base64.b64decode(token_data.get('password').encode()).decode()
            
            if cred_row.imap_use_ssl:
                mail = imaplib.IMAP4_SSL(cred_row.imap_server, cred_row.imap_port)
            else:
                mail = imaplib.IMAP4(cred_row.imap_server, cred_row.imap_port)
            
            mail.login(cred_row.email, password)
            mail.select('INBOX')
            
            # E-Mail abrufen
            typ, msg_data = mail.fetch(email_id.encode() if isinstance(email_id, str) else str(email_id).encode(), '(RFC822)')
            if typ != 'OK':
                mail.logout()
                return jsonify({"error": "E-Mail nicht gefunden"}), 404
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            def decode_mime_words(s):
                if not s:
                    return ''
                decoded = decode_header(s)
                return ''.join([str(t[0], t[1] or 'utf-8') if isinstance(t[0], bytes) else t[0] for t in decoded])
            
            # E-Mail-Adresse aus From extrahieren
            from_header = decode_mime_words(msg.get('From', ''))
            from_email = from_header
            # Versuche E-Mail-Adresse zu extrahieren (z.B. "Name <email@domain.com>" -> "email@domain.com")
            import re
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
            if email_match:
                from_email = email_match.group(0)
            
            # Vollständiger Body
            full_body = ''
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        try:
                            full_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except:
                            pass
                        break
            else:
                try:
                    full_body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    pass
            
            mail.logout()
            
            return jsonify({
                "from": from_header,
                "from_email": from_email,
                "subject": decode_mime_words(msg.get('Subject', '(Kein Betreff)')),
                "body": full_body,
                "id": email_id
            })
        else:
            return jsonify({"error": "Nur Exchange wird unterstützt"}), 400
    except Exception as e:
        return jsonify({"error": f"Fehler: {str(e)}"}), 500

# Hilfsfunktionen für Kooperationsverträge
def _extract_address_parts(address: str):
    if not address:
        return '', '', ''
    parts = [seg.strip() for seg in address.split(',')]
    street = parts[0] if parts else ''
    plz = ''
    ort = ''
    if len(parts) > 1:
        city_parts = parts[1].split()
        if city_parts:
            plz = city_parts[0]
            if len(city_parts) > 1:
                ort = ' '.join(city_parts[1:])
    return street, plz, ort

def _render_kooperationsvertrag_html(contract, partner: Kooperationspartner):
    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'kooperationsvertrag.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    street, plz, ort = _extract_address_parts(partner.street_address or '')
    replacements = {
        '[Firmenname des Dienstleisters]': partner.company_name or partner.name or '',
        '[Straße]': street,
        '[PLZ]': plz,
        '[Ort]': ort,
        '[Land]': 'Deutschland',
        '[Vertretungsberechtigte]': partner.managing_director or '',
        '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
        '[Provision]': (partner.provision or '').strip()
    }
    
    for placeholder, value in replacements.items():
        html_content = html_content.replace(placeholder, str(value))
    return html_content

def _generate_kooperationsvertrag_pdf_from_html(contract, html_content):
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    
    font_config = FontConfiguration()
    html_doc = HTML(string=html_content)
    css = CSS(string='@page { size: A4; margin: 1.5cm; }', font_config=font_config)
    
    pdf_bytes = html_doc.write_pdf(stylesheets=[css], font_config=font_config)
    
    pdf_filename = f"kooperationsvertrag_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
    
    with open(pdf_path, 'wb') as f:
        f.write(pdf_bytes)
    
    contract.pdf_filename = pdf_filename
    db.session.commit()
    return pdf_filename, f"/uploads/{pdf_filename}"

def _get_dienstleistungsvertrag_replacements(contract, customer: Customer, partner: Kooperationspartner):
    if not customer or not partner:
        raise ValueError("Kunde oder Kooperationspartner nicht gefunden")
    return {
        '[Auftragsnummer]': contract.contract_number,
        '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
        '[Vorname Name]': customer.name,
        '[Straße Hausnummer]': customer.street_address or '',
        '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
        '[Telefon Kunde]': customer.phone or '',
        '[E-Mail Kunde]': customer.email or '',
        '[Firmenname Partner]': partner.company_name or partner.name or '',
        '[Adresse Partner]': partner.street_address or '',
        '[Telefon Partner]': partner.phone or '',
        '[E-Mail Partner]': partner.email or '',
        '[Identifikationsnummer Partner]': partner.identification_number or '',
        '[Handelsregisternummer Partner]': partner.commercial_register or '',
        '[Umsatzsteuer-Identifikationsnummer Partner]': partner.vat_id or '',
        '[Name Geschäftsführer Partner]': partner.managing_director or '',
        '[Notfalltelefon Partner]': partner.emergency_phone or '',
        '[Betrag]': format_currency(contract.monthly_rate) if contract.monthly_rate else '',
        '[Tagessatz]': format_currency(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
        '[Ort]': customer.city or '',
        '[Partnerfirma]': getattr(partner, 'partner_company', None) or partner.company_name or partner.name or ''
    }

def _render_dienstleistungsvertrag_html(contract, customer: Customer = None, partner: Kooperationspartner = None, *, ignore_custom=False):
    if not ignore_custom and getattr(contract, 'custom_html', None):
        return contract.custom_html
    customer = customer or Customer.query.get(contract.customer_id)
    partner = partner or Kooperationspartner.query.get(contract.kooperationspartner_id)
    replacements = _get_dienstleistungsvertrag_replacements(contract, customer, partner)
    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dienstleistungsvertrag.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    for placeholder, value in replacements.items():
        html_content = html_content.replace(placeholder, str(value))
    return html_content

def _generate_dienstleistungsvertrag_pdf_from_html(contract, html_content, preview=False):
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    
    font_config = FontConfiguration()
    html_doc = HTML(string=html_content)
    css = CSS(string='@page { size: A4; margin: 2cm; }', font_config=font_config)
    
    pdf_bytes = html_doc.write_pdf(stylesheets=[css], font_config=font_config)
    suffix = "_Preview" if preview else ""
    pdf_filename = f"dienstleistungsvertrag_{contract.contract_number}{suffix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
    
    # Erstelle Verzeichnis falls nicht vorhanden
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    
    with open(pdf_path, 'wb') as f:
        f.write(pdf_bytes)
    
    # Nur PDF-Filename speichern wenn nicht Preview
    if not preview:
        contract.pdf_filename = pdf_filename
        db.session.commit()
    return pdf_bytes, pdf_filename, pdf_path

# Hilfsfunktion: HTML-Tabellen-basiertes E-Mail-Template erstellen
def create_html_email_template(content_lines, signature_html=None):
    """
    Erstellt ein E-Mail-Client-kompatibles HTML-Template mit Tabellen-Layout.
    
    Args:
        content_lines: Liste von Textzeilen für den E-Mail-Inhalt
        signature_html: Optional HTML-Signatur
    
    Returns:
        HTML-String mit Tabellen-basiertem Layout
    """
    # Tabellen-basiertes Layout für maximale E-Mail-Client-Kompatibilität
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; background-color: #f4f4f4;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f4f4f4;">
            <tr>
                <td align="center" style="padding: 20px 0;">
                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="background-color: #ffffff; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <tr>
                            <td style="padding: 20px 30px;">
                                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
"""
    
    # Inhalt als Tabellen-Zeilen hinzufügen
    for i, line in enumerate(content_lines):
        if line.strip():  # Nur nicht-leere Zeilen
            # Letzte Zeile hat kein padding-bottom
            padding_bottom = "0" if i == len(content_lines) - 1 else "4px"
            html += f"""
                                    <tr>
                                        <td style="font-family: Arial, Helvetica, sans-serif; font-size: 16px; line-height: 1.5; color: #333333; padding-bottom: {padding_bottom}; mso-line-height-rule: exactly;">
                                            {line}
                                        </td>
                                    </tr>
"""
        else:  # Leerzeile
            html += """
                                    <tr>
                                        <td style="padding-bottom: 4px; line-height: 4px; font-size: 4px;">&nbsp;</td>
                                    </tr>
"""
    
    # Signatur hinzufügen, falls vorhanden
    if signature_html:
        html += """
                                    <tr>
                                        <td style="padding-top: 16px;">
                                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                                <tr>
                                                    <td style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.5; color: #666666; mso-line-height-rule: exactly;">
"""
        # Signatur-HTML einfügen (bereits HTML, daher direkt)
        html += signature_html
        html += """
                                                    </td>
                                                </tr>
                                            </table>
                                        </td>
                                    </tr>
"""
    
    html += """
                                </table>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
"""
    return html

# Hilfsfunktion: Signatur für eine E-Mail-Adresse abrufen
def get_signature_for_email(email_address, username=None):
    """Ruft die Signatur für eine E-Mail-Adresse ab, falls ein Postfach dafür hinterlegt ist"""
    try:
        # Normalisiere E-Mail-Adresse (lowercase)
        email_lower = email_address.lower().strip()
        
        if username:
            # Suche case-insensitive mit username
            creds = ExchangeCredential.query.filter(
                db.func.lower(ExchangeCredential.email) == email_lower,
                ExchangeCredential.username == username
            ).all()
        else:
            # Suche nach E-Mail-Adresse, unabhängig vom Benutzer, case-insensitive
            creds = ExchangeCredential.query.filter(
                db.func.lower(ExchangeCredential.email) == email_lower
            ).all()
        
        if creds:
            # Wenn mehrere Credentials gefunden, bevorzuge die mit Signatur
            cred_with_signature = None
            for cred in creds:
                if cred.signature and cred.signature.strip():
                    cred_with_signature = cred
                    break
            
            # Falls keine mit Signatur gefunden, nimm die erste
            if not cred_with_signature:
                cred_with_signature = creds[0]
            
            print(f"✅ ExchangeCredential gefunden für {email_address}: ID={cred_with_signature.id}, signature vorhanden={bool(cred_with_signature.signature)}")
            if cred_with_signature.signature and cred_with_signature.signature.strip():
                print(f"✅ Signatur gefunden (Länge: {len(cred_with_signature.signature)} Zeichen)")
                return cred_with_signature.signature
            else:
                print(f"⚠️ ExchangeCredential gefunden, aber keine Signatur vorhanden")
        else:
            print(f"⚠️ Kein ExchangeCredential gefunden für E-Mail: {email_address}")
            # Debug: Zeige alle vorhandenen E-Mail-Adressen
            all_creds = ExchangeCredential.query.all()
            if all_creds:
                emails = [c.email for c in all_creds]
                print(f"   Verfügbare E-Mail-Adressen in DB: {emails}")
    except Exception as e:
        print(f"⚠️ Fehler beim Abrufen der Signatur für {email_address}: {e}")
        import traceback
        traceback.print_exc()
    return None

# 📧 E-Mail-Antwort senden
@app.route('/api/emails/reply', methods=['POST'])
def reply_email():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    cred_id = data.get('cred_id')
    account_type = data.get('type', 'exchange')
    email_id = data.get('email_id')
    to_email = data.get('to')  # E-Mail-Adresse des Empfängers
    subject = data.get('subject', '').strip()
    body = data.get('body', '').strip()
    
    if not cred_id or not email_id or not to_email or not body:
        return jsonify({"error": "Fehlende Parameter"}), 400
    
    # Betreff mit "Re: " präfixen falls nicht vorhanden
    if not subject.startswith('Re:') and not subject.startswith('RE:'):
        subject = f"Re: {subject}"
    
    # SMTP-Konfiguration aus Umgebungsvariablen
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
    smtp_port = int(os.getenv('SMTP_PORT', '465'))
    smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
    smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
    smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
    
    if not smtp_username or not smtp_password:
        return jsonify({"error": "SMTP-Credentials nicht konfiguriert"}), 400
    
    try:
        # E-Mail erstellen
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = f"HelpCare <{smtp_username}>"
        message['To'] = to_email
        
        # Signatur hinzufügen, falls vorhanden
        cred_row = ExchangeCredential.query.filter_by(id=cred_id, username=session['user']).first()
        signature = cred_row.signature if cred_row and cred_row.signature else ''
        
        # Text und HTML Versionen mit Signatur
        body_with_signature = body
        newline = '\n'
        body_with_signature_html = body.replace(newline, '<br>')
        
        if signature:
            # Signatur ist HTML, füge sie hinzu
            # Für Plain-Text: HTML-Tags entfernen
            import re
            from html import unescape
            signature_text = re.sub(r'<[^>]+>', '', signature)  # HTML-Tags entfernen
            signature_text = unescape(signature_text)  # HTML-Entities dekodieren
            signature_text = signature_text.replace(newline, ' ').strip()  # Zeilenumbrüche normalisieren
            
            body_with_signature = f"{body}{newline}{newline}{signature_text}"
            # Für HTML-Version: Signatur direkt anhängen (bereits HTML)
            body_html_base = body.replace(newline, '<br>')
            body_with_signature_html = f"{body_html_base}<br><br>{signature}"
        
        # Plain-Text Version (für E-Mail-Clients ohne HTML)
        body_text_final = body_with_signature
        
        # HTML Version mit Signatur
        body_html_final = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
            body_with_signature_html +
            "</div>"
        )
        
        text_part = MIMEText(body_text_final, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        
        message.attach(text_part)
        message.attach(html_part)
        
        # SMTP-Verbindung aufbauen und E-Mail senden
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        
        print(f"✅ Antwort erfolgreich über SMTP versendet an {to_email}")
        return jsonify({"success": True, "message": "Antwort erfolgreich gesendet"})
        
    except Exception as e:
        error_str = str(e)
        print(f"❌ Fehler beim Senden der Antwort: {error_str}")
        return jsonify({"error": f"Fehler beim Senden: {error_str}"}), 500

# 📧 Neue E-Mail senden
@app.route('/api/emails/send', methods=['POST'])
def send_email():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    cred_id = data.get('cred_id')
    account_type = data.get('type', 'exchange')
    to_email = data.get('to', '').strip()
    cc_email = data.get('cc', '').strip()
    bcc_email = data.get('bcc', '').strip()
    subject = data.get('subject', '').strip()
    body = data.get('body', '').strip()
    attachments = data.get('attachments', [])
    
    if not cred_id or not to_email or not subject or not body:
        return jsonify({"error": "Fehlende Parameter"}), 400
    
    # SMTP-Konfiguration
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
    smtp_port = int(os.getenv('SMTP_PORT', '465'))
    smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
    smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
    smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
    
    if not smtp_username or not smtp_password:
        return jsonify({"error": "SMTP-Credentials nicht konfiguriert"}), 400
    
    try:
        # E-Mail erstellen
        message = MIMEMultipart('mixed')
        message['Subject'] = subject
        message['From'] = f"HelpCare <{smtp_username}>"
        message['To'] = to_email
        if cc_email:
            message['Cc'] = cc_email
        if bcc_email:
            message['Bcc'] = bcc_email
        
        # Signatur hinzufügen
        cred_row = ExchangeCredential.query.filter_by(id=cred_id, username=session['user']).first() if cred_id else None
        signature = cred_row.signature if cred_row and cred_row.signature else ''
        
        newline = '\n'
        body_with_signature = body
        body_with_signature_html = body.replace(newline, '<br>')
        
        if signature:
            import re
            from html import unescape
            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace(newline, ' ').strip()
            body_with_signature = f"{body}{newline}{newline}{signature_text}"
            body_with_signature_html = f"{body.replace(newline, '<br>')}<br><br>{signature}"
        
        body_html_final = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
            body_with_signature_html +
            "</div>"
        )
        
        # Alternative part (text + HTML)
        alternative = MIMEMultipart('alternative')
        text_part = MIMEText(body_with_signature, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        alternative.attach(text_part)
        alternative.attach(html_part)
        message.attach(alternative)
        
        # Anhänge hinzufügen
        for att in attachments:
            try:
                attachment = MIMEBase('application', 'octet-stream')
                attachment.set_payload(base64.b64decode(att.get('content', '')))
                encoders.encode_base64(attachment)
                attachment.add_header('Content-Disposition', f'attachment; filename={att.get("filename", "attachment")}')
                message.attach(attachment)
            except Exception as e:
                print(f"⚠️ Fehler beim Hinzufügen des Anhangs: {e}")
        
        # SMTP senden
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        
        print(f"✅ E-Mail erfolgreich über SMTP versendet an {to_email}")
        return jsonify({"success": True, "message": "E-Mail erfolgreich gesendet"})
        
    except Exception as e:
        error_str = str(e)
        print(f"❌ Fehler beim Senden der E-Mail: {error_str}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Fehler beim Senden: {error_str}"}), 500

# 📧 E-Mail löschen
@app.route('/api/emails/<email_id>', methods=['DELETE'])
def delete_email(email_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    cred_id = request.args.get('cred_id')
    account_type = request.args.get('type', 'exchange')
    
    try:
        if account_type == 'exchange':
            cred_row = None
            if cred_id:
                try:
                    cred_id_int = int(cred_id)
                    cred_row = ExchangeCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            
            if not cred_row:
                return jsonify({"error": "Kein Exchange-Konto verbunden"}), 400
            
            # IMAP-Verbindung
            if cred_row.imap_server and cred_row.token_json:
                try:
                    token_data = json.loads(cred_row.token_json)
                    if token_data.get('method') == 'imap':
                        password_encrypted = token_data.get('password')
                        if not password_encrypted:
                            return jsonify({"error": "Passwort nicht verfügbar"}), 400
                        password = base64.b64decode(password_encrypted.encode()).decode()
                    else:
                        return jsonify({"error": "Kein IMAP-Passwort"}), 400
                except:
                    return jsonify({"error": "Passwort nicht verfügbar"}), 400
                
                try:
                    if cred_row.imap_use_ssl:
                        mail = imaplib.IMAP4_SSL(cred_row.imap_server, cred_row.imap_port)
                    else:
                        mail = imaplib.IMAP4(cred_row.imap_server, cred_row.imap_port)
                    
                    mail.login(cred_row.email, password)
                    mail.select('INBOX')
                    
                    # E-Mail löschen (als gelöscht markieren)
                    mail.store(email_id.encode() if isinstance(email_id, str) else str(email_id).encode(), '+FLAGS', '\\Deleted')
                    mail.expunge()
                    mail.logout()
                    
                    return jsonify({"success": True, "message": "E-Mail erfolgreich gelöscht"})
                except Exception as e:
                    return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500
            elif cred_row.token_json:
                # Microsoft Graph API
                token_data = json.loads(cred_row.token_json)
                access_token = token_data.get('access_token')
                
                if not access_token:
                    return jsonify({"error": "Ungültiger Token"}), 400
                
                headers = {'Authorization': f'Bearer {access_token}'}
                graph_url = f'https://graph.microsoft.com/v1.0/me/messages/{email_id}'
                
                response = requests.delete(graph_url, headers=headers)
                if not response.ok:
                    return jsonify({"error": f"Fehler bei Microsoft Graph API: {response.text}"}), 500
                
                return jsonify({"success": True, "message": "E-Mail erfolgreich gelöscht"})
            else:
                return jsonify({"error": "Keine gültige Verbindungsmethode"}), 400
        else:
            # Gmail
            cred_row = None
            if cred_id:
                try:
                    cred_id_int = int(cred_id)
                    cred_row = GmailCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            
            if not cred_row:
                return jsonify({"error": "Kein Gmail-Konto verbunden"}), 400
            
            token_data = json.loads(cred_row.token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            service = build('gmail', 'v1', credentials=creds)
            
            service.users().messages().delete(userId='me', id=email_id).execute()
            
            return jsonify({"success": True, "message": "E-Mail erfolgreich gelöscht"})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

# 📧 E-Mail als gelesen/ungelesen markieren
@app.route('/api/emails/<email_id>/read', methods=['POST'])
def mark_email_read(email_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    cred_id = data.get('cred_id')
    account_type = data.get('type', 'exchange')
    mark_as_read = data.get('read', True)
    
    try:
        if account_type == 'exchange':
            cred_row = None
            if cred_id:
                try:
                    cred_id_int = int(cred_id)
                    cred_row = ExchangeCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            
            if not cred_row:
                return jsonify({"error": "Kein Exchange-Konto verbunden"}), 400
            
            # IMAP-Verbindung
            if cred_row.imap_server and cred_row.token_json:
                try:
                    token_data = json.loads(cred_row.token_json)
                    if token_data.get('method') == 'imap':
                        password_encrypted = token_data.get('password')
                        if not password_encrypted:
                            return jsonify({"error": "Passwort nicht verfügbar"}), 400
                        password = base64.b64decode(password_encrypted.encode()).decode()
                    else:
                        return jsonify({"error": "Kein IMAP-Passwort"}), 400
                except:
                    return jsonify({"error": "Passwort nicht verfügbar"}), 400
                
                try:
                    if cred_row.imap_use_ssl:
                        mail = imaplib.IMAP4_SSL(cred_row.imap_server, cred_row.imap_port)
                    else:
                        mail = imaplib.IMAP4(cred_row.imap_server, cred_row.imap_port)
                    
                    mail.login(cred_row.email, password)
                    mail.select('INBOX')
                    
                    # Als gelesen/ungelesen markieren
                    if mark_as_read:
                        mail.store(email_id.encode() if isinstance(email_id, str) else str(email_id).encode(), '+FLAGS', '\\Seen')
                    else:
                        mail.store(email_id.encode() if isinstance(email_id, str) else str(email_id).encode(), '-FLAGS', '\\Seen')
                    
                    mail.logout()
                    return jsonify({"success": True, "message": f"E-Mail als {'gelesen' if mark_as_read else 'ungelesen'} markiert"})
                except Exception as e:
                    return jsonify({"error": f"Fehler beim Markieren: {str(e)}"}), 500
            elif cred_row.token_json:
                # Microsoft Graph API
                token_data = json.loads(cred_row.token_json)
                access_token = token_data.get('access_token')
                
                if not access_token:
                    return jsonify({"error": "Ungültiger Token"}), 400
                
                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                }
                graph_url = f'https://graph.microsoft.com/v1.0/me/messages/{email_id}'
                
                response = requests.patch(graph_url, headers=headers, json={'isRead': mark_as_read})
                if not response.ok:
                    return jsonify({"error": f"Fehler bei Microsoft Graph API: {response.text}"}), 500
                
                return jsonify({"success": True, "message": f"E-Mail als {'gelesen' if mark_as_read else 'ungelesen'} markiert"})
            else:
                return jsonify({"error": "Keine gültige Verbindungsmethode"}), 400
        else:
            # Gmail
            cred_row = None
            if cred_id:
                try:
                    cred_id_int = int(cred_id)
                    cred_row = GmailCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
                except Exception:
                    return jsonify({"error": "Ungültige cred_id"}), 400
            
            if not cred_row:
                return jsonify({"error": "Kein Gmail-Konto verbunden"}), 400
            
            token_data = json.loads(cred_row.token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            service = build('gmail', 'v1', credentials=creds)
            
            if mark_as_read:
                service.users().messages().modify(userId='me', id=email_id, body={'removeLabelIds': ['UNREAD']}).execute()
            else:
                service.users().messages().modify(userId='me', id=email_id, body={'addLabelIds': ['UNREAD']}).execute()
            
            return jsonify({"success": True, "message": f"E-Mail als {'gelesen' if mark_as_read else 'ungelesen'} markiert"})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Markieren: {str(e)}"}), 500

# Exchange-Account löschen
@app.route('/api/exchange/accounts/<int:cred_id>', methods=['DELETE'])
def delete_exchange_account(cred_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        cred = ExchangeCredential.query.filter_by(id=cred_id, username=session['user']).first()
        if not cred:
            return jsonify({"error": "Exchange-Account nicht gefunden"}), 404
        
        db.session.delete(cred)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

# E-Mail-Signatur speichern
@app.route('/api/exchange/accounts/<int:cred_id>/signature', methods=['PUT'])
def update_exchange_signature(cred_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        cred = ExchangeCredential.query.filter_by(id=cred_id, username=session['user']).first()
        if not cred:
            return jsonify({"error": "Exchange-Account nicht gefunden"}), 404
        
        data = request.get_json() or {}
        signature = data.get('signature', '').strip()
        
        cred.signature = signature
        db.session.commit()
        
        return jsonify({"success": True, "message": "Signatur gespeichert"})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Speichern: {str(e)}"}), 500

# E-Mail-Signatur für E-Mail-Adresse speichern (erstellt automatisch Dummy-Postfach falls nicht vorhanden)
@app.route('/api/email-signature', methods=['PUT'])
def update_email_signature():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        data = request.get_json() or {}
        email_addr = data.get('email', '').strip().lower()
        signature = data.get('signature', '').strip()
        
        if not email_addr:
            return jsonify({"error": "E-Mail-Adresse erforderlich"}), 400
        
        # Suche nach vorhandenem Postfach
        cred = ExchangeCredential.query.filter(
            db.func.lower(ExchangeCredential.email) == email_addr
        ).first()
        
        if not cred:
            # Erstelle Dummy-Postfach für Signatur
            cred = ExchangeCredential(
                username=session.get('user'),
                email=email_addr,
                imap_server=None,
                imap_port=None,
                imap_use_ssl=True,
                password=None,
                token_json=None
            )
            db.session.add(cred)
            db.session.flush()  # Um die ID zu bekommen
        
        cred.signature = signature
        db.session.commit()
        
        return jsonify({"success": True, "message": f"Signatur für {email_addr} gespeichert", "cred_id": cred.id})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Speichern: {str(e)}"}), 500

# E-Mail-Signatur abrufen
@app.route('/api/exchange/accounts/<int:cred_id>/signature', methods=['GET'])
def get_exchange_signature(cred_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        cred = ExchangeCredential.query.filter_by(id=cred_id, username=session['user']).first()
        if not cred:
            return jsonify({"error": "Exchange-Account nicht gefunden"}), 404
        
        return jsonify({"signature": cred.signature or ""})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen: {str(e)}"}), 500


# 📧 Angebot per E-Mail versenden (PDF Base64)
@app.route('/api/send-offer', methods=['POST'])
def send_offer():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    data = request.get_json() or {}
    to_email = data.get('to')
    # Subject/Body defaults (keeps your latest wording) with last name interpolation
    name_full = (data.get('sms_name') or '').strip()
    last_name = (data.get('lastName') or (name_full.split()[-1] if name_full else '')).strip()
    
    # Prüfe ob es sich um einen Befragungsbogen handelt (früh definieren)
    filename = data.get('filename') or 'Angebot.pdf'
    subject = data.get('subject') or "Ihr unverbindliches Angebot"
    is_questionnaire = (
        'befragungsbogen' in filename.lower() or 
        'befragungsbogen' in subject.lower() or
        'befragungsbogen' in (data.get('body') or '').lower()
    )
    
    # Für Befragungsbogen: Kunden-ID in den Body einbetten
    if is_questionnaire:
        form_fields = data.get('form_fields', {})
        customer_id = form_fields.get('kunden_id', '')
        if customer_id:
            # Betreff um Kunden-ID ergänzen, damit Partner die E-Mail zuordnen können
            if f"{customer_id}" not in subject:
                subject = f"Bedarfsfragebogen – Kunden-ID: {customer_id}"
            body = data.get('body') or (
                "Sehr geehrte Damen und Herren,\n\n"
                f"anbei finden Sie den Bedarfsfragebogen eines neuen Kunden (Kunden-ID: {customer_id}).\n\n"
                "Viele Grüße"
            )
        else:
            body = data.get('body') or (
                "Sehr geehrte Damen und Herren,\n\n"
                "anbei finden Sie den Bedarfsfragebogen eines neuen Kunden.\n\n"
                "Viele Grüße"
            )
    else:
        body = data.get('body') or (
            f"Sehr geehrte Familie {last_name},\n\n"
            "vielen Dank für das freundliche Gespräch. Wie vereinbart, übersende ich Ihnen im Anhang unser Angebot.\n\n"
            "Sollten Sie noch Fragen haben oder weitere Details benötigen, stehe ich Ihnen gerne zur Verfügung.\n\n"
            "Mit besten Grüßen  \n"
            "Team HelpCare  \n\n"
        )

    pdf_b64 = data.get('pdf_base64')
    sms_number = data.get('sms_number')
    sms_name = data.get('sms_name')
    sms_info_email = to_email
    if not to_email or not pdf_b64:
        return jsonify({"error": "to und pdf_base64 erforderlich"}), 400

    # Prüfe ob es sich um einen Befragungsbogen handelt (vor E-Mail-Versand)
    is_questionnaire = (
        'befragungsbogen' in filename.lower() or 
        'befragungsbogen' in subject.lower() or
        'befragungsbogen' in body.lower()
    )
    
    # Für Befragungsbogen: Dateiname und Betreff anpassen (inkl. Kunden-ID)
    if is_questionnaire:
        form_fields = data.get('form_fields', {})
        customer_id = form_fields.get('kunden_id', '')
        if customer_id:
            filename = f"Bedarfsfragebogen_{customer_id}.pdf"
            # Falls der Betreff noch keine Kunden-ID enthält, ergänzen
            if f"{customer_id}" not in subject:
                subject = f"Bedarfsfragebogen – Kunden-ID: {customer_id}"
        else:
            filename = "Bedarfsfragebogen.pdf"

    # SMTP-Konfiguration aus Umgebungsvariablen
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
    smtp_port = int(os.getenv('SMTP_PORT', '465'))
    smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
    smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
    smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
    
    if not smtp_username or not smtp_password:
        return jsonify({"error": "SMTP-Credentials nicht konfiguriert. Bitte SMTP_USERNAME und SMTP_PASSWORD in .env setzen."}), 400

    try:
        # Signatur für SMTP-Absender abrufen, falls Postfach hinterlegt
        # Versuche zuerst mit smtp_username, dann mit 'kontakt@helpcare.de' als Fallback
        signature = get_signature_for_email(smtp_username)
        if not signature and smtp_username != 'kontakt@helpcare.de':
            print(f"⚠️ Signatur nicht für {smtp_username} gefunden, versuche kontakt@helpcare.de")
            signature = get_signature_for_email('kontakt@helpcare.de')
        print(f"🔍 Signatur-Abruf für {smtp_username}: {'✅ gefunden' if signature else '❌ nicht gefunden'}")
        if signature:
            print(f"✅ Signatur gefunden (Länge: {len(signature)} Zeichen)")
        else:
            print(f"❌ WICHTIG: Keine Signatur gefunden! Bitte prüfen Sie, ob für {smtp_username} oder kontakt@helpcare.de eine Signatur in der Datenbank gespeichert ist.")
        newline = '\n'
        
        # E-Mail erstellen
        message = MIMEMultipart('mixed')
        message['Subject'] = subject
        message['From'] = f"HelpCare <{smtp_username}>"
        
        # Für Befragungsbogen: BCC an ausgewählte Kooperationspartner
        questionnaire_bcc_emails = []
        if is_questionnaire:
            # Prüfe ob Partner explizit übergeben wurden
            partners_data = data.get('partners', [])
            if partners_data:
                # Verwende übergebene Partner
                bcc_emails = [partner.get('email') for partner in partners_data if partner.get('email')]
            else:
                # Fallback: Alle Partner (für Rückwärtskompatibilität)
                partners = Kooperationspartner.query.all()
                bcc_emails = [partner.email for partner in partners if partner.email]
            
            if bcc_emails:
                questionnaire_bcc_emails = bcc_emails
        
        # Für Befragungsbogen: An team@helpcare.de statt befragungsbogen@helpcare.de senden
        if is_questionnaire and to_email == 'befragungsbogen@helpcare.de':
            actual_to_email = 'team@helpcare.de'
        else:
            actual_to_email = to_email
        
        # Prepare text and HTML bodies mit Signatur (OHNE BCC-Info für alle)
        body_text_final = body
        
        # HTML-Tabellen-basiertes Template erstellen
        # Body in Zeilen aufteilen
        body_lines = body.split(newline)
        # Leere Zeilen am Anfang/Ende entfernen, aber innere Leerzeilen behalten
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        
        # HTML-Template mit Tabellen erstellen
        body_html_final = create_html_email_template(body_lines, signature if signature else None)
        
        if signature:
            # Für Plain-Text: HTML-Tags entfernen
            import re
            from html import unescape
            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace(newline, ' ').strip()
            body_text_final = f"{body}{newline}{newline}{signature_text}"
            print(f"✅ Füge Signatur hinzu (Länge: {len(signature)} Zeichen)")
        else:
            print(f"⚠️ Keine Signatur vorhanden, verwende nur Body")
        
        if signature:
            print(f"✅ HTML-Body mit Signatur erstellt (Gesamtlänge: {len(body_html_final)} Zeichen)")

        # Text und HTML Versionen (für alle Empfänger)
        text_part = MIMEText(body_text_final, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        
        # Alternative part (text + HTML) - enthält bereits die Signatur
        alternative = MIMEMultipart('alternative')
        alternative.attach(text_part)
        alternative.attach(html_part)
        print(f"✅ Alternative MIME-Part erstellt (enthält Signatur: {bool(signature)})")
        
        # Für Befragungsbogen: Separate E-Mails senden
        # 1. E-Mail an team@helpcare.de MIT BCC-Liste (intern, OHNE BCC-Feld)
        # 2. Separate E-Mails an jeden Kooperationspartner (jeder sieht nur seine eigene E-Mail)
        if is_questionnaire and questionnaire_bcc_emails:
            # PDF-Daten vorbereiten
            if pdf_b64.startswith('data:application/pdf;base64,'):
                pdf_b64_clean = pdf_b64.split(',', 1)[1]
            else:
                pdf_b64_clean = pdf_b64
            pdf_data = base64.b64decode(pdf_b64_clean)
            
            # 1. E-Mail an team@helpcare.de MIT BCC-Liste (intern)
            bcc_info_text = f"\n\n---\nDiese E-Mail wurde an folgende Kooperationspartner gesendet:\n" + "\n".join(f"  • {email}" for email in questionnaire_bcc_emails)
            
            # BCC-Info als HTML-Tabellen-Struktur hinzufügen
            bcc_info_html = """
                                    <tr>
                                        <td style="padding-top: 24px; border-top: 1px solid #e0e0e0;">
                                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                                <tr>
                                                    <td style="font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 18px; color: #666666; padding-bottom: 8px;">
                                                        Diese E-Mail wurde an folgende Kooperationspartner gesendet:
                                                    </td>
                                                </tr>
"""
            for email in questionnaire_bcc_emails:
                bcc_info_html += f"""
                                                <tr>
                                                    <td style="font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 18px; color: #666666; padding-left: 16px;">
                                                        • {email}
                                                    </td>
                                                </tr>
"""
            bcc_info_html += """
                                            </table>
                                        </td>
                                    </tr>
"""
            
            # BCC-Info in das HTML-Template einfügen (vor dem schließenden </table>)
            body_team_text = body_text_final + bcc_info_text
            # HTML: BCC-Info vor dem schließenden </table> des Inhalts einfügen
            body_team_html = body_html_final.replace('</table>', bcc_info_html + '</table>', 1)
            
            text_part_team = MIMEText(body_team_text, 'plain', 'utf-8')
            html_part_team = MIMEText(body_team_html, 'html', 'utf-8')
            
            alternative_team = MIMEMultipart('alternative')
            alternative_team.attach(text_part_team)
            alternative_team.attach(html_part_team)
            
            message_team = MIMEMultipart('mixed')
            message_team['Subject'] = subject
            message_team['From'] = f"HelpCare <{smtp_username}>"
            message_team['To'] = actual_to_email
            # KEIN BCC-Feld - nur interne E-Mail an Team
            message_team.attach(alternative_team)
            
            pdf_attachment_team = MIMEBase('application', 'pdf')
            pdf_attachment_team.set_payload(pdf_data)
            encoders.encode_base64(pdf_attachment_team)
            pdf_attachment_team.add_header('Content-Disposition', f'attachment; filename={filename}')
            message_team.attach(pdf_attachment_team)
            
            # Zusätzliche PDF-Anhänge für Angebote (nicht für Befragungsbogen)
            if not is_questionnaire:
                additional_pdfs = ['helpcare-flyer.pdf', 'Profilbeispiel.pdf']
                for pdf_filename in additional_pdfs:
                    pdf_path = os.path.join('angebots-additionals', pdf_filename)
                    if os.path.exists(pdf_path):
                        try:
                            with open(pdf_path, 'rb') as f:
                                pdf_content = f.read()
                            additional_attachment = MIMEBase('application', 'pdf')
                            additional_attachment.set_payload(pdf_content)
                            encoders.encode_base64(additional_attachment)
                            additional_attachment.add_header('Content-Disposition', f'attachment; filename={pdf_filename}')
                            message_team.attach(additional_attachment)
                            print(f"✅ Zusätzlicher Anhang hinzugefügt (Team): {pdf_filename}")
                        except Exception as e:
                            print(f"⚠️ Fehler beim Hinzufügen von {pdf_filename} (Team): {e}")
                    else:
                        print(f"⚠️ Datei nicht gefunden: {pdf_path}")
            
            # 2. Separate E-Mails an jeden Kooperationspartner (jeder sieht nur seine eigene)
            # SMTP-Verbindung einmal öffnen für alle E-Mails
            if smtp_use_ssl:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
                server.login(smtp_username, smtp_password)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port)
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
            
            # Team-E-Mail senden
            server.send_message(message_team)
            print(f"✅ E-Mail an {actual_to_email} gesendet (mit Liste der {len(questionnaire_bcc_emails)} Partner)")
            
            # Separate E-Mails an jeden Partner senden (ohne BCC-Info, jeder sieht nur seine eigene)
            for partner_email in questionnaire_bcc_emails:
                message_partner = MIMEMultipart('mixed')
                message_partner['Subject'] = subject
                message_partner['From'] = f"HelpCare <{smtp_username}>"
                message_partner['To'] = partner_email
                # KEIN BCC-Feld - jeder Partner bekommt seine eigene E-Mail
                message_partner.attach(alternative)  # Normale Body ohne BCC-Info
                
                pdf_attachment_partner = MIMEBase('application', 'pdf')
                pdf_attachment_partner.set_payload(pdf_data)
                encoders.encode_base64(pdf_attachment_partner)
                pdf_attachment_partner.add_header('Content-Disposition', f'attachment; filename={filename}')
                message_partner.attach(pdf_attachment_partner)
                
                server.send_message(message_partner)
                print(f"✅ E-Mail an Kooperationspartner {partner_email} gesendet")
            
            server.quit()
            
            print(f"✅ Insgesamt {len(questionnaire_bcc_emails) + 1} E-Mails gesendet (1 an Team, {len(questionnaire_bcc_emails)} an Partner)")
            # Für Befragungsbogen: Keine weitere E-Mail senden, da bereits gesendet
            return_early = True
        else:
            # Normale E-Mail (nicht Befragungsbogen oder keine BCC)
            message['To'] = actual_to_email
            if is_questionnaire and questionnaire_bcc_emails:
                message['Bcc'] = ', '.join(questionnaire_bcc_emails)
            message.attach(alternative)
            return_early = False
        
        # Wenn bereits gesendet (Befragungsbogen mit BCC), überspringe normalen Versand
        if not return_early:
            # PDF-Anhang hinzufügen
            if pdf_b64.startswith('data:application/pdf;base64,'):
                pdf_b64_clean = pdf_b64.split(',', 1)[1]
            else:
                pdf_b64_clean = pdf_b64
            
            pdf_data = base64.b64decode(pdf_b64_clean)
            pdf_attachment = MIMEBase('application', 'pdf')
            pdf_attachment.set_payload(pdf_data)
            encoders.encode_base64(pdf_attachment)
            pdf_attachment.add_header('Content-Disposition', f'attachment; filename={filename}')
            message.attach(pdf_attachment)
            
            # Zusätzliche PDF-Anhänge für Angebote (nicht für Befragungsbogen)
            if not is_questionnaire:
                additional_pdfs = ['helpcare-flyer.pdf', 'Profilbeispiel.pdf']
                for pdf_filename in additional_pdfs:
                    pdf_path = os.path.join('angebots-additionals', pdf_filename)
                    if os.path.exists(pdf_path):
                        try:
                            with open(pdf_path, 'rb') as f:
                                pdf_content = f.read()
                            additional_attachment = MIMEBase('application', 'pdf')
                            additional_attachment.set_payload(pdf_content)
                            encoders.encode_base64(additional_attachment)
                            additional_attachment.add_header('Content-Disposition', f'attachment; filename={pdf_filename}')
                            message.attach(additional_attachment)
                            print(f"✅ Zusätzlicher Anhang hinzugefügt: {pdf_filename}")
                        except Exception as e:
                            print(f"⚠️ Fehler beim Hinzufügen von {pdf_filename}: {e}")
                    else:
                        print(f"⚠️ Datei nicht gefunden: {pdf_path}")

            # SMTP-Verbindung aufbauen und E-Mail senden
            if smtp_use_ssl:
                # SSL-Verbindung (Port 465)
                with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            else:
                # STARTTLS-Verbindung (Port 587)
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    if smtp_use_tls:
                        server.starttls()
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            
            print(f"✅ E-Mail erfolgreich über SMTP versendet an {actual_to_email}")
        
        # Automatisch Kunde speichern - unterscheide zwischen Angebot und Befragungsbogen
        customer_name = sms_name or name_full or None
        
        if is_questionnaire:
            # Befragungsbogen-Daten speichern (inkl. Formularfelder und PDF)
            form_fields = data.get('form_fields', {})
            customer_id = form_fields.get('kunden_id', '')
            
            questionnaire_data = {
                'subject': subject,
                'body': body,
                'filename': filename,
                'sms_number': sms_number,
                'sms_name': sms_name,
                'lastName': last_name,
                'sent_at': datetime.datetime.utcnow().isoformat(),
                'form_fields': form_fields,  # Alle ausgefüllten Formularfelder (inkl. Kunden-ID)
                'pdf_data': data.get('pdf_data', ''),  # Die generierte PDF-Datei (base64)
                'customer_id': customer_id  # Kunden-ID für Kooperationspartner
            }
            print(f"DEBUG: Erkenne Befragungsbogen - speichere questionnaire_data: {questionnaire_data}")
            
            # Speichere die tatsächlich verwendeten BCC-Empfänger (nur die Partner, die den Fragebogen bekommen haben)
            questionnaire_data['bcc_recipients'] = questionnaire_bcc_emails or []
            
            # Wenn eine Kunden-ID ausgewählt ist, Daten zu diesem Kunden hinzufügen
            if customer_id:
                try:
                    # Bestehenden Kunden laden
                    customer_id_int = int(customer_id)
                    
                    # WICHTIG: Session explizit refreshen, um sicherzustellen, dass wir die aktuellen Daten sehen
                    db.session.expire_all()
                    
                    customer = Customer.query.filter_by(id=customer_id_int).first()
                    
                    if customer:
                        # Befragungsbogen-Daten zu bestehendem Kunden hinzufügen
                        customer.questionnaire_data_json = json.dumps(questionnaire_data)
                        db.session.commit()
                        print(f"DEBUG: ✅ Befragungsbogen-Daten zu bestehendem Kunden {customer_id} ({customer.name}) hinzugefügt")
                        # PDF automatisch als Datei exportieren
                        _export_questionnaire_pdf(customer.id, customer.name, questionnaire_data)
                    else:
                        print(f"DEBUG: ⚠️ Kunde {customer_id} nicht gefunden in Datenbank!")
                        print(f"DEBUG: Prüfe ob Kunde mit anderer ID existiert...")
                        # Versuche Kunde über E-Mail zu finden als Fallback
                        if to_email:
                            customer_by_email = Customer.query.filter_by(email=to_email).first()
                            if customer_by_email:
                                print(f"DEBUG: ✅ Kunde gefunden über E-Mail {to_email} (ID: {customer_by_email.id})")
                                customer_by_email.questionnaire_data_json = json.dumps(questionnaire_data)
                                db.session.commit()
                                print(f"DEBUG: ✅ Befragungsbogen-Daten zu Kunde {customer_by_email.id} über E-Mail hinzugefügt")
                                # PDF automatisch als Datei exportieren
                                _export_questionnaire_pdf(customer_by_email.id, customer_by_email.name, questionnaire_data)
                            else:
                                print(f"DEBUG: ⚠️ Kunde auch nicht über E-Mail {to_email} gefunden")
                                print(f"DEBUG: Speichere mit Empfänger-E-Mail: {to_email}")
                                save_customer_from_email(to_email, customer_name, questionnaire_data=questionnaire_data)
                        else:
                            print(f"DEBUG: ⚠️ Keine E-Mail-Adresse verfügbar, speichere unter team@helpcare.de")
                            save_customer_from_email('team@helpcare.de', 'Befragungsbogen', questionnaire_data=questionnaire_data)
                except ValueError as e:
                    print(f"DEBUG: ⚠️ Ungültige Kunden-ID '{customer_id}': {e}")
                    print(f"DEBUG: Speichere mit Empfänger-E-Mail: {to_email}")
                    save_customer_from_email(to_email, customer_name, questionnaire_data=questionnaire_data)
                except Exception as e:
                    print(f"DEBUG: ⚠️ Fehler beim Hinzufügen zu bestehendem Kunden {customer_id}: {e}")
                    print(f"DEBUG: Exception-Typ: {type(e).__name__}")
                    import traceback
                    print(f"DEBUG: Traceback: {traceback.format_exc()}")
                    # Versuche mit der Empfänger-E-Mail zu speichern statt team@helpcare.de
                    save_customer_from_email(to_email, customer_name, questionnaire_data=questionnaire_data)
            else:
                # Kein Kunde ausgewählt - neuen Kunden erstellen
                save_customer_from_email('team@helpcare.de', 'Befragungsbogen', questionnaire_data=questionnaire_data)
        else:
            # Angebot-Daten speichern (inkl. PDF)
            offer_data = {
                'subject': subject,
                'body': body,
                'filename': filename,
                'sms_number': sms_number,
                'sms_name': sms_name,
                'lastName': last_name,
                'sent_at': datetime.datetime.utcnow().isoformat(),
                'pdf_data': data.get('pdf_base64', '')  # Die PDF-Datei (base64)
            }
            print(f"DEBUG: Erkenne Angebot - speichere offer_data: {offer_data}")
            
            # Prüfe ob eine Kunden-ID in form_fields vorhanden ist
            form_fields = data.get('form_fields', {})
            customer_id = form_fields.get('kunden_id', '')
            
            # Wenn eine Kunden-ID ausgewählt ist, Daten zu diesem Kunden hinzufügen
            if customer_id:
                try:
                    # Bestehenden Kunden laden
                    customer_id_int = int(customer_id)
                    
                    # WICHTIG: Session explizit refreshen, um sicherzustellen, dass wir die aktuellen Daten sehen
                    db.session.expire_all()
                    
                    customer = Customer.query.filter_by(id=customer_id_int).first()
                    
                    if customer:
                        # Angebot-Daten zu bestehendem Kunden hinzufügen
                        try:
                            current_offer_data = json.loads(customer.offer_data_json or '{}')
                            current_offer_data.update(offer_data)
                            customer.offer_data_json = json.dumps(current_offer_data)
                        except:
                            customer.offer_data_json = json.dumps(offer_data)
                        
                        # Kontakthistorie-Eintrag hinzufügen
                        customer.add_contact_entry('offer_sent', offer_data)
                        
                        # Letzten Kontakt aktualisieren
                        customer.last_contact = datetime.datetime.utcnow()
                        
                        db.session.commit()
                        print(f"DEBUG: ✅ Angebot-Daten zu bestehendem Kunden {customer_id} ({customer.name}) hinzugefügt")
                        # PDF automatisch als Datei exportieren
                        _export_offer_pdf(customer.id, customer.name, offer_data)
                    else:
                        print(f"DEBUG: ⚠️ Kunde {customer_id} nicht gefunden in Datenbank!")
                        print(f"DEBUG: Speichere mit Empfänger-E-Mail: {to_email}")
                        save_customer_from_email(to_email, customer_name, offer_data)
                except ValueError as e:
                    print(f"DEBUG: ⚠️ Ungültige Kunden-ID '{customer_id}': {e}")
                    print(f"DEBUG: Speichere mit Empfänger-E-Mail: {to_email}")
                    save_customer_from_email(to_email, customer_name, offer_data)
                except Exception as e:
                    print(f"DEBUG: ⚠️ Fehler beim Hinzufügen zu bestehendem Kunden {customer_id}: {e}")
                    print(f"DEBUG: Exception-Typ: {type(e).__name__}")
                    import traceback
                    print(f"DEBUG: Traceback: {traceback.format_exc()}")
                    # Versuche mit der Empfänger-E-Mail zu speichern
                    save_customer_from_email(to_email, customer_name, offer_data)
            else:
                # Kein Kunde ausgewählt - normal nach E-Mail suchen
                save_customer_from_email(to_email, customer_name, offer_data)
        
        # Optional: Send SMS via Link Mobility if number present
        if sms_number:
            try:
                linkmobility_token = os.getenv('LINKMOBILITY_TOKEN') or 'bb2d6280-fbfe-4b73-9421-b2ca7a76c896'
                link_base = os.getenv('LINKMOBILITY_BASE_URL') or 'https://api.linkmobility.eu/rest/smsmessaging/simple'
                # E.164 normalize (Germany default)
                num = ''.join([c for c in (sms_number or '') if c.isdigit() or c=='+'])
                num = num.replace('+','')
                if num.startswith('00'):
                    num = num[2:]
                if num.startswith('0'):
                    num = '49' + num[1:]
                if not num.startswith('49'):
                    # keep as-is or extend mapping for other countries
                    pass
                recipient = '+' + num
                customer_message = (
                    f"Herzlich Willkommen {sms_name or ''},\n\n"
                    "Wir danken Ihnen für Ihr Vertrauen,\n"
                    "dass wir Sie bei Ihrer Suche nach\n"
                    "einer passenden 24 Stunden\n"
                    "Betreuungskraft unterstützen dürfen.\n\n"
                    f"Ihr persönliches Angebot wurde per\nE-Mail an: {sms_info_email}\nzugestellt.\n\n"
                    "Bitte prüfen Sie auch Ihren\n"
                    "Spam-Ordner, falls Sie unsere\n"
                    "E-Mail nicht im Posteingang finden.\n\n"
                    "Für Fragen erreichen Sie uns jederzeit\n"
                    "kostenlos unter 0800 000 9178.\n\n"
                    "Beste Grüße\nIhr HelpCare Team"
                )
                # Sicherstellen, dass der Text sauber als UTF‑8 vorliegt
                customer_message = prepare_sms_utf8(customer_message)
                payload = {
                    'access_token': linkmobility_token,
                    'recipientAddressList': recipient,
                    'messageContent': customer_message,
                }
                import requests as _requests
                _requests.post(link_base, data=payload, headers={'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}, timeout=30)
            except Exception:
                pass
        return jsonify({"success": True})
        
    except smtplib.SMTPAuthenticationError as e:
        error_str = str(e)
        print(f"❌ SMTP-Authentifizierungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Authentifizierung fehlgeschlagen. Bitte SMTP-Credentials (Benutzername/Passwort) überprüfen. Server: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPConnectError as e:
        error_str = str(e)
        print(f"❌ SMTP-Verbindungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Verbindung fehlgeschlagen. Bitte SMTP-Server und Port überprüfen. Versucht: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPDataError as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore')
        print(f"❌ SMTP-Datenfehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except smtplib.SMTPException as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore') if hasattr(e, 'smtp_error') else error_str
        print(f"❌ SMTP-Fehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except Exception as e:
        error_str = str(e)
        print(f"❌ E-Mail-Versand Fehler: {error_str}")
        return jsonify({"error": f"E-Mail-Versand fehlgeschlagen: {error_str}"}), 500

# 📧 Erinnerungsmail an Kooperationspartner senden
@app.route('/api/send-reminder', methods=['POST'])
def send_reminder():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    subject = data.get('subject', '').strip()
    body = data.get('body', '').strip()
    partners = data.get('partners', [])
    
    if not subject:
        return jsonify({"error": "Betreff erforderlich"}), 400
    
    if not partners:
        return jsonify({"error": "Mindestens ein Kooperationspartner erforderlich"}), 400
    
    # SMTP-Konfiguration aus Umgebungsvariablen
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
    smtp_port = int(os.getenv('SMTP_PORT', '465'))
    smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
    smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
    smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
    
    if not smtp_username or not smtp_password:
        return jsonify({"error": "SMTP-Credentials nicht konfiguriert. Bitte SMTP_USERNAME und SMTP_PASSWORD in .env setzen."}), 400
    
    try:
        # Signatur für SMTP-Absender abrufen, falls Postfach hinterlegt
        # Versuche zuerst mit smtp_username, dann mit 'kontakt@helpcare.de' als Fallback
        signature = get_signature_for_email(smtp_username)
        if not signature and smtp_username != 'kontakt@helpcare.de':
            print(f"⚠️ Signatur nicht für {smtp_username} gefunden, versuche kontakt@helpcare.de")
            signature = get_signature_for_email('kontakt@helpcare.de')
        newline = '\n'

        # Fallback-Text, falls kein Body übergeben wurde
        body_fallback = (
            "Hallo,\n\n"
            "hier ist eine Erinnerung von HelpCare.\n\n"
            "Mit besten Grüßen\n"
            "Team HelpCare"
        )
        body_text_base = body or body_fallback

        # Für HTML-Version dieselbe Template-Logik wie bei Rechnungen/Befragungsbogen verwenden
        body_lines = body_text_base.split(newline)
        # Leere Zeilen am Anfang/Ende entfernen
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()

        body_html_final = create_html_email_template(body_lines, signature if signature else None)

        # Plain-Text-Version inkl. Signatur (ohne HTML-Tags)
        body_text_final = body_text_base
        if signature:
            import re
            from html import unescape

            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace(newline, ' ').strip()
            body_text_final = f"{body_text_base}{newline}{newline}{signature_text}"
        
        # Create message
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = f"HelpCare <{smtp_username}>"
        
        # Add BCC recipients
        bcc_emails = [partner['email'] for partner in partners if partner.get('email')]
        if bcc_emails:
            message['Bcc'] = ', '.join(bcc_emails)
        
        # Add text and HTML parts
        text_part = MIMEText(body_text_final, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        
        message.attach(text_part)
        message.attach(html_part)
        
        # SMTP-Verbindung aufbauen und E-Mail senden
        if smtp_use_ssl:
            # SSL-Verbindung (Port 465)
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            # STARTTLS-Verbindung (Port 587)
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        
        print(f"✅ Erinnerungsmail erfolgreich über SMTP versendet an {len(bcc_emails)} Kooperationspartner")
        return jsonify({"success": True, "sent_to": len(bcc_emails)})
        
    except smtplib.SMTPAuthenticationError as e:
        error_str = str(e)
        print(f"❌ SMTP-Authentifizierungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Authentifizierung fehlgeschlagen. Bitte SMTP-Credentials (Benutzername/Passwort) überprüfen. Server: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPConnectError as e:
        error_str = str(e)
        print(f"❌ SMTP-Verbindungsfehler: {error_str}")
        return jsonify({"error": f"SMTP-Verbindung fehlgeschlagen. Bitte SMTP-Server und Port überprüfen. Versucht: {smtp_server}:{smtp_port}"}), 500
    except smtplib.SMTPDataError as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore')
        print(f"❌ SMTP-Datenfehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except smtplib.SMTPException as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore') if hasattr(e, 'smtp_error') else error_str
        print(f"❌ SMTP-Fehler: {error_str} (Code: {error_code})")
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return jsonify({"error": f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"}), 500
        return jsonify({"error": f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"}), 500
    except Exception as e:
        error_str = str(e)
        print(f"❌ E-Mail-Versand Fehler: {error_str}")
        return jsonify({"error": f"E-Mail-Versand fehlgeschlagen: {error_str}"}), 500

# 📲 Webhook von Chatwoot empfangen
@app.route("/webhook/chatwoot", methods=["POST"])
def chatwoot_webhook():
    data = request.get_json()

    # 👉 Zeige alles schön formatiert im Terminal (für Debug)
    print("📦 Webhook-Payload:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

    if data.get("event") != "message_created":
        return "Ignored", 200

    if data.get("message_type") != "incoming":
        return "Ignored", 200

    # Kontakt-Infos extrahieren
    contact = data.get("contact", {})
    contact_id = contact.get("id", "Unbekannt")
    contact_name = contact.get("name", "Unbekannt")
    contact_identifier = contact.get("identifier", "Unbekannt")

    # Du kannst hier z. B. die ID oder Identifier oder beides verwenden
    new_message = {
        "contact": f"{contact_name} ({contact_identifier})",  # oder nur identifier
        "text": data.get("content", "[Leere Nachricht]"),
        "time": data.get("created_at")
    }

    try:
        with open(os.path.join(APP_DATA_DIR, "chatwoot_messages.json"), "r") as f:
            messages = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        messages = []

    messages.insert(0, new_message)
    messages = messages[:100]

    with open(os.path.join(APP_DATA_DIR, "chatwoot_messages.json"), "w") as f:
        json.dump(messages, f, indent=2)

    return jsonify({"success": True})


# 📤 Letzte WhatsApp-Nachrichten abrufen
@app.route("/api/whatsapp-messages")
def whatsapp_messages():
    try:
        with open(os.path.join(APP_DATA_DIR, "chatwoot_messages.json"), "r") as f:
            messages = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        messages = []

    return jsonify(messages[:10])

# 👤 Aktueller Nutzer (Session)
@app.route("/api/me")
def who_am_i():
    if "user" not in session:
        return jsonify({"authenticated": False}), 200
    return jsonify({"authenticated": True, "username": session["user"]})

# 👥 Mitarbeiter-API (DB-gestützt)
@app.route("/api/users", methods=["GET", "POST"])
def users_api():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    if request.method == "GET":
        users = User.query.order_by(User.id.desc()).all()
        return jsonify([u.to_public_dict() for u in users])

    # POST anlegen
    payload = request.get_json() or {}
    name = payload.get("name")
    email = payload.get("email")
    role = payload.get("role") or "employee"
    avatar = payload.get("avatar")

    if not name or not email:
        return jsonify({"error": "name und email sind erforderlich"}), 400

    username = payload.get("username") or name.lower().replace(" ", ".")
    # Generisches Initialpasswort (sollte via Reset-Flow geändert werden)
    initial_password = payload.get("password") or uuid.uuid4().hex[:10]

    user = User(username=username, email=email, role=role, avatar=avatar or (
        "https://ui-avatars.com/api/?name=" + name.replace(" ", "+")
    ))
    user.set_password(initial_password)
    db.session.add(user)
    db.session.commit()

    response = user.to_public_dict()
    response.update({"initial_password": initial_password})
    return jsonify(response), 201

# 🗒️ Teamnotizen API
@app.route('/api/team-notes', methods=['GET', 'POST'])
def team_notes():
    try:
        if request.method == 'GET':
            notes = TeamNote.query.order_by(TeamNote.id.asc()).limit(500).all()
            return jsonify([n.to_dict() for n in notes])

        # JSON-Payload verarbeiten - auch wenn Content-Type fehlt
        try:
            payload = request.get_json(force=True) or {}
        except Exception:
            # Fallback: versuche aus form data zu lesen
            payload = {
                'content': request.form.get('content', ''),
                'parent_id': request.form.get('parent_id')
            }
        
        content = payload.get('content')
        parent_id = payload.get('parent_id')
        if not content:
            return jsonify({"error": "content erforderlich"}), 400
        author = session.get('user') or 'Gast'
        try:
            pid = int(parent_id) if parent_id is not None else None
        except Exception:
            pid = None
        note = TeamNote(content=content, author=author, parent_id=pid)
        db.session.add(note)
        db.session.commit()
        return jsonify(note.to_dict()), 201
    except Exception as e:
        print(f"❌ Fehler in /api/team-notes: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Fehler bei Team-Notes: {str(e)}"}), 500

@app.route('/api/team-notes/<int:note_id>', methods=['DELETE'])
def delete_team_note(note_id: int):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    note = TeamNote.query.get(note_id)
    if not note:
        return jsonify({"error": "Notiz nicht gefunden"}), 404
    # Nur der Autor darf seine eigene Notiz löschen
    current_user = session.get('user')
    if not current_user or (note.author and note.author != current_user):
        return jsonify({"error": "Keine Berechtigung zum Löschen dieser Notiz"}), 403
    db.session.delete(note)
    db.session.commit()
    return jsonify({"success": True})

# Reaktionen setzen/entfernen
@app.route('/api/team-notes/<int:note_id>/react', methods=['POST'])
def react_team_note(note_id: int):
    # Reaktionen auch ohne Login zulassen
    note = TeamNote.query.get(note_id)
    if not note:
        return jsonify({"error": "Notiz nicht gefunden"}), 404
    payload = request.get_json() or {}
    reaction = (payload.get('reaction') or '').strip()
    if not reaction:
        return jsonify({"error": "reaction erforderlich"}), 400
    import json as _json
    try:
        current = _json.loads(note.reactions_json or '[]')
        if not isinstance(current, list):
            current = []
    except Exception:
        current = []
    # Toggle reaction for this user (simple aggregate without user binding for now)
    current.append(reaction)
    note.reactions_json = _json.dumps(current)
    db.session.commit()
    return jsonify(note.to_dict())

# 📊 Kunden-Kennzahlen API
@app.route('/api/customers/stats', methods=['GET'])
def customers_stats():
    """Gibt die Anzahl der Kunden (Im Einsatz) und Anfragen (alle) zurück"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        # Kunden: Status ist "Im Einsatz"
        kunden_count = Customer.query.filter(Customer.status.ilike('Im Einsatz')).count()
        
        # Anfragen: Alle Kunden insgesamt
        anfragen_count = Customer.query.count()
        
        return jsonify({
            "kunden": kunden_count,
            "anfragen": anfragen_count
        })
    except Exception as e:
        print(f"❌ Fehler beim Laden der Kunden-Kennzahlen: {e}")
        return jsonify({"error": str(e)}), 500

# 👥 Kundenverwaltung API
@app.route('/api/customers', methods=['GET', 'POST'])
def customers():
    if request.method == 'GET':
        # Optionale Pagination (default: 50 pro Seite für bessere Performance)
        page = request.args.get('page', type=int, default=1)
        per_page = request.args.get('per_page', type=int, default=50)  # Optimiert für Performance
        
        # Optional: Suchfilter
        search = request.args.get('search', '').strip()
        query = Customer.query
        
        if search:
            # Suche in Name, Email, Company
            search_filter = f'%{search}%'
            query = query.filter(
                db.or_(
                    Customer.name.ilike(search_filter),
                    Customer.email.ilike(search_filter),
                    Customer.company.ilike(search_filter)
                )
            )
        
        # Optional: Kategorien-Filter
        category = request.args.get('category', '').strip().lower()
        if category and category != 'all':
            if category == 'anfrage':
                # Anfrage: Status ist null, "Angebot versendet", "Inaktiv" oder leer
                query = query.filter(
                    db.or_(
                        Customer.status.is_(None),
                        Customer.status == '',
                        Customer.status.ilike('Angebot versendet'),
                        Customer.status.ilike('Inaktiv')
                    )
                )
            elif category == 'kunde':
                # Kunde: Status ist "Im Einsatz"
                query = query.filter(Customer.status.ilike('Im Einsatz'))
            elif category == 'abgesagt':
                # Abgesagt: Status ist "Abgesagt"
                query = query.filter(Customer.status.ilike('Abgesagt'))
            elif category == 'verstorben':
                # Verstorben: Status ist "Verstorben"
                query = query.filter(Customer.status.ilike('Verstorben'))
        
        # Performance-Optimierung: JSON-Spalten nur laden wenn Details benötigt werden
        include_details = request.args.get('include_details', 'false').lower() == 'true'
        
        if include_details:
            # Vollständige Abfrage mit allen Spalten (für Detailansicht)
            pagination = query.order_by(Customer.created_at.desc()).paginate(
                page=page, per_page=per_page, error_out=False
            )
            items = []
            for customer in pagination.items:
                item = customer.to_dict()
                items.append(item)
        else:
            # Optimierte Abfrage: JSON-Spalten AUSLASSEN für bessere Performance
            from sqlalchemy import select
            # Nur die Spalten laden, die für die Liste benötigt werden
            columns = [
                Customer.id,
                Customer.name,
                Customer.email,
                Customer.phone,
                Customer.mobile_phone,
                Customer.company,
                Customer.created_at,
                Customer.last_contact,
                Customer.status,
                Customer.street_address,
                Customer.postal_code,
                Customer.city,
                Customer.contract_number,
                Customer.monthly_rate,
                Customer.daily_rate,
                Customer.notes
            ]
            
            # Optimierte COUNT-Query: Verwende func.count() direkt auf gefilterter Query
            # Dies ist effizienter als query.count() bei großen Tabellen
            from sqlalchemy import func
            # COUNT auf Basis der bereits gefilterten Query
            total = query.with_entities(func.count(Customer.id)).scalar()
            pages = (total + per_page - 1) // per_page if total > 0 else 1
            
            # Lade nur die benötigten Spalten (OHNE JSON-Felder!)
            offset = (page - 1) * per_page
            customers = query.with_entities(*columns)\
                .order_by(Customer.created_at.desc())\
                .offset(offset)\
                .limit(per_page)\
                .all()
            
            items = []
            for customer in customers:
                item = {
                    'id': customer.id,
                    'name': customer.name,
                    'email': customer.email,
                    'phone': customer.phone,
                    'mobile_phone': customer.mobile_phone,
                    'company': customer.company,
                    'created_at': customer.created_at.isoformat() if customer.created_at else None,
                    'last_contact': customer.last_contact.isoformat() if customer.last_contact else None,
                    'status': customer.status,
                    'street_address': customer.street_address,
                    'postal_code': customer.postal_code,
                    'city': customer.city,
                    'contract_number': customer.contract_number,
                    'monthly_rate': customer.monthly_rate,
                    'daily_rate': customer.daily_rate,
                    'notes': customer.notes
                }
                items.append(item)
            
            # Pagination-Objekt für Kompatibilität
            class PaginationObj:
                def __init__(self, items, total, pages, page):
                    self.items = items
                    self.total = total
                    self.pages = pages
                    self.page = page
            
            pagination = PaginationObj(items, total, pages, page)
        
        return jsonify({
            'items': items,
            'total': pagination.total,
            'pages': pagination.pages,
            'page': pagination.page,
            'per_page': per_page
        })
    
    elif request.method == 'POST':
        data = request.get_json()
        
        # Prüfen ob Kunde mit gleichem Namen bereits existiert
        existing_customer = Customer.query.filter_by(name=data.get('name')).first()
        if existing_customer:
            return jsonify({"error": "Kunde mit diesem Namen existiert bereits"}), 400
        
        customer = Customer(
            name=data.get('name'),
            email=data.get('email'),
            phone=data.get('phone'),
            mobile_phone=data.get('mobile_phone'),
            company=data.get('company'),
            notes=data.get('notes'),
            status=data.get('status'),
            street_address=data.get('street_address'),
            postal_code=data.get('postal_code'),
            city=data.get('city'),
            contract_number=data.get('contract_number'),
            monthly_rate=data.get('monthly_rate'),
            daily_rate=data.get('daily_rate')
        )
        
        db.session.add(customer)
        db.session.commit()
        
        return jsonify(customer.to_dict()), 201

@app.route('/api/customers/<int:customer_id>', methods=['GET', 'PUT', 'DELETE'])
def customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'GET':
        # Detail-Ansicht: JSON-Daten nur laden wenn explizit angefragt (Lazy Loading)
        include_json = request.args.get('include_json', 'false').lower() == 'true'
        
        if include_json:
            # Vollständige Daten mit JSON-Feldern
            return jsonify(customer.to_dict())
        else:
            # Optimierte Version ohne große JSON-Felder (für schnelles Laden)
            data = {
                'id': customer.id,
                'name': customer.name,
                'email': customer.email,
                'phone': customer.phone,
                'mobile_phone': customer.mobile_phone,
                'company': customer.company,
                'created_at': customer.created_at.isoformat() if customer.created_at else None,
                'last_contact': customer.last_contact.isoformat() if customer.last_contact else None,
                'notes': customer.notes,
                'status': customer.status,
                'street_address': customer.street_address,
                'postal_code': customer.postal_code,
                'city': customer.city,
                'contract_number': customer.contract_number,
                'monthly_rate': customer.monthly_rate,
                'daily_rate': customer.daily_rate,
                # JSON-Daten als null markieren - werden erst beim Tab-Klick geladen
                'offer_data': None,
                'questionnaire_data': None,
                'profile_data': None,
                'contact_history': None,
                'contract_data': None
            }
            return jsonify(data)
    
    elif request.method == 'PUT':
        data = request.get_json()
        
        customer.name = data.get('name', customer.name)
        customer.email = data.get('email', customer.email)
        customer.phone = data.get('phone', customer.phone)
        customer.mobile_phone = data.get('mobile_phone', customer.mobile_phone)
        customer.company = data.get('company', customer.company)
        customer.notes = data.get('notes', customer.notes)
        # Status-Update zulassen (freie Strings, UI liefert feste Auswahl)
        if 'status' in data:
            customer.status = data.get('status')
        customer.street_address = data.get('street_address', customer.street_address)
        customer.postal_code = data.get('postal_code', customer.postal_code)
        customer.city = data.get('city', customer.city)
        customer.contract_number = data.get('contract_number', customer.contract_number)
        customer.monthly_rate = data.get('monthly_rate', customer.monthly_rate)
        customer.daily_rate = data.get('daily_rate', customer.daily_rate)
        customer.last_contact = datetime.datetime.utcnow()
        
        db.session.commit()
        return jsonify(customer.to_dict())
    
    elif request.method == 'DELETE':
        try:
            from sqlalchemy import text
            
            print(f"🗑️ Lösche Kunde {customer_id} und alle verknüpften Daten...")
            
            # Direkte SQL-Löschungen mit expliziten Commits nach jedem Schritt
            # 1. FollowUps löschen (die zu Notizen gehören, die zu diesem Kunden gehören)
            try:
                result1 = db.session.execute(
                    text("DELETE FROM follow_ups WHERE note_id IN (SELECT id FROM customer_notes WHERE customer_id = :customer_id)"),
                    {"customer_id": customer_id}
                )
                db.session.commit()
                print(f"   ✅ {result1.rowcount} FollowUps (zu Notizen) gelöscht")
            except Exception as e:
                print(f"   ⚠️ Fehler beim Löschen von FollowUps (zu Notizen): {e}")
                db.session.rollback()
            
            # 2. FollowUps löschen (die direkt zu customer_id gehören)
            try:
                result2 = db.session.execute(
                    text("DELETE FROM follow_ups WHERE customer_id = :customer_id"),
                    {"customer_id": customer_id}
                )
                db.session.commit()
                print(f"   ✅ {result2.rowcount} FollowUps (direkt) gelöscht")
            except Exception as e:
                print(f"   ⚠️ Fehler beim Löschen von FollowUps (direkt): {e}")
                db.session.rollback()
            
            # 3. CustomerNotes löschen - WICHTIG: Muss vor dem Kunden gelöscht werden
            # Verwende explizite Parameter-Bindung für PostgreSQL
            try:
                # Zuerst prüfen, ob es Notizen gibt
                check_result = db.session.execute(
                    text("SELECT COUNT(*) FROM customer_notes WHERE customer_id = :customer_id"),
                    {"customer_id": customer_id}
                )
                count = check_result.scalar()
                print(f"   📊 Gefundene CustomerNotes: {count}")
                
                if count > 0:
                    result3 = db.session.execute(
                        text("DELETE FROM customer_notes WHERE customer_id = :customer_id"),
                        {"customer_id": customer_id}
                    )
                    db.session.commit()
                    print(f"   ✅ {result3.rowcount} CustomerNotes gelöscht")
                else:
                    print(f"   ℹ️ Keine CustomerNotes zum Löschen gefunden")
            except Exception as e:
                print(f"   ❌ KRITISCHER FEHLER beim Löschen von CustomerNotes: {e}")
                import traceback
                print(traceback.format_exc())
                db.session.rollback()
                raise  # Wir müssen hier abbrechen, sonst können wir den Kunden nicht löschen
            
            # 4. Dienstleistungsverträge löschen
            try:
                result4 = db.session.execute(
                    text("DELETE FROM dienstleistungsvertraege WHERE customer_id = :customer_id"),
                    {"customer_id": customer_id}
                )
                db.session.commit()
                print(f"   ✅ {result4.rowcount} Dienstleistungsverträge gelöscht")
            except Exception as e:
                print(f"   ⚠️ Fehler beim Löschen von Dienstleistungsverträgen: {e}")
                db.session.rollback()
            
            # 5. Jetzt kann der Kunde gelöscht werden
            db.session.delete(customer)
            db.session.commit()
            print(f"   ✅ Kunde {customer_id} erfolgreich gelöscht")
            
            return jsonify({"success": True})
        except Exception as e:
            db.session.rollback()
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Fehler beim Löschen des Kunden {customer_id}: {e}")
            print(f"Traceback: {error_trace}")
            return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

@app.route('/api/customers/<int:customer_id>/sms', methods=['POST'])
def send_sms_to_customer(customer_id):
    """Sendet eine SMS an einen Kunden über Linkmobility API"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json() or {}
    
    # SMS-Nachricht aus Request
    message = data.get('message', '').strip()
    message = prepare_sms_utf8(message)
    if not message:
        return jsonify({"error": "SMS-Nachricht darf nicht leer sein"}), 400
    
    # Telefonnummer aus Kunden-Daten (mobile_phone hat Priorität, sonst phone)
    mobile_phone = customer.mobile_phone or customer.phone
    if not mobile_phone:
        return jsonify({"error": "Keine Mobiltelefonnummer für diesen Kunden hinterlegt"}), 400
    
    try:
        # Linkmobility Konfiguration
        linkmobility_token = os.getenv('LINKMOBILITY_TOKEN') or 'bb2d6280-fbfe-4b73-9421-b2ca7a76c896'
        linkmobility_base_url = os.getenv('LINKMOBILITY_BASE_URL') or 'https://api.linkmobility.eu/rest/smsmessaging/simple'
        
        # E.164 Normalisierung (basierend auf dem PHP-Beispiel)
        customer_number_clean = re.sub(r'\D+', '', mobile_phone)
        
        if customer_number_clean.startswith('00'):
            customer_number_clean = customer_number_clean[2:]
        if customer_number_clean.startswith('0'):
            customer_number_clean = '49' + customer_number_clean[1:]
        if not customer_number_clean.startswith('49'):
            # Falls nicht mit 49 beginnt, könnte es bereits international sein oder anderer Ländercode
            pass
        
        customer_sms_number = '+' + customer_number_clean
        
        # API-Parameter
        params = {
            'access_token': linkmobility_token,
            'recipientAddressList': customer_sms_number,
            'messageContent': message,
        }
        
        # cURL-äquivalent mit requests
        response = requests.post(
            linkmobility_base_url,
            data=params,
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
            timeout=30
        )
        
        if response.status_code == 200:
            # Erfolgreich versendet
            print(f"✅ SMS erfolgreich versendet an {customer_sms_number}: HTTP {response.status_code} – Antwort: {response.text}")
            return jsonify({
                "success": True,
                "message": "SMS erfolgreich versendet",
                "recipient": customer_sms_number,
                "response": response.text
            })
        else:
            # Fehler beim Versand
            error_msg = f"HTTP {response.status_code} – Antwort: {response.text}"
            print(f"❌ Link Mobility SMS Fehler: {error_msg}")
            return jsonify({
                "error": f"SMS-Versand fehlgeschlagen: {error_msg}",
                "status_code": response.status_code,
                "response": response.text
            }), 500
            
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        print(f"❌ Link Mobility cURL/Request Fehler: {error_msg}")
        return jsonify({
            "error": f"SMS-Versand fehlgeschlagen: {error_msg}"
        }), 500
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Unerwarteter Fehler beim SMS-Versand: {error_msg}")
        return jsonify({
            "error": f"Unerwarteter Fehler: {error_msg}"
        }), 500


# 📄 Rechnungen API – zentrale Synchronisation für das Rechnungsmodul
def _parse_date_yyyy_mm_dd(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _generate_next_invoice_number():
    # Suche nach höchster RE-Nummer in bestehenden Rechnungen
    prefix = "RE-"
    max_num = 1335
    for inv in Invoice.query.with_entities(Invoice.invoice_number).all():
        if inv.invoice_number and inv.invoice_number.startswith(prefix):
            try:
                num = int(inv.invoice_number.replace(prefix, ""))
                if num > max_num:
                    max_num = num
            except Exception:
                continue
    return f"{prefix}{max_num + 1}"


@app.route('/api/invoices', methods=['GET'])
def list_invoices():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    invoices = (
        Invoice.query.filter_by(deleted=False)
        .order_by(Invoice.created_at.desc())
        .all()
    )
    return jsonify([inv.to_dict() for inv in invoices])


@app.route('/api/invoices/<int:invoice_id>', methods=['GET'])
def get_invoice(invoice_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    inv = Invoice.query.get_or_404(invoice_id)
    if inv.deleted:
        return jsonify({"error": "Rechnung wurde gelöscht"}), 404
    return jsonify(inv.to_dict())


@app.route('/api/invoices', methods=['POST'])
def create_invoice():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    data = request.get_json() or {}

    try:
        partner_id = int(data.get("partnerId"))
        customer_id = int(data.get("customerId"))
    except Exception:
        return jsonify({"error": "partnerId und customerId müssen numerisch sein"}), 400

    invoice_number = data.get("invoiceNumber") or _generate_next_invoice_number()

    inv = Invoice(
        invoice_number=invoice_number,
        status=data.get("status") or "entwurf",
        partner_id=partner_id,
        customer_id=customer_id,
        agreed_total_amount=float(data.get("agreedTotalAmount") or 0.0),
        commission_rate=float(data.get("commissionRate") or 0.0),
        commission_mode=data.get("commissionMode") or "percent",
        commission_fixed_amount=(
            float(data.get("commissionFixedAmount"))
            if data.get("commissionFixedAmount") is not None
            else None
        ),
        commission_amount=float(data.get("commissionAmount") or 0.0),
        invoice_date=_parse_date_yyyy_mm_dd(data.get("invoiceDate")),
        performance_period_from=_parse_date_yyyy_mm_dd(
            data.get("performancePeriodFrom")
        ),
        performance_period_to=_parse_date_yyyy_mm_dd(
            data.get("performancePeriodTo")
        ),
        due_date=_parse_date_yyyy_mm_dd(data.get("dueDate")),
        reference_number=data.get("referenceNumber"),
        subject=data.get("subject") or f"Rechnung Nr. {invoice_number} – Vermittlungsprovision",
        header_text=data.get("headerText") or "",
        positions_json=json.dumps(data.get("positions") or []),
        payment_terms_days=int(data.get("paymentTermsDays") or 14),
        reverse_charge=bool(data.get("reverseCharge")),
        is_locked=bool(data.get("isLocked")),
        paid_amount=float(data.get("paidAmount") or 0.0),
    )

    db.session.add(inv)
    db.session.commit()
    return jsonify(inv.to_dict()), 201


@app.route('/api/invoices/<int:invoice_id>', methods=['PUT'])
def update_invoice(invoice_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    inv = Invoice.query.get_or_404(invoice_id)
    if inv.deleted:
        return jsonify({"error": "Rechnung wurde gelöscht"}), 404

    data = request.get_json() or {}

    # Nur Felder überschreiben, die wirklich übergeben wurden
    if "status" in data:
        inv.status = data.get("status") or inv.status
    if "partnerId" in data:
        try:
            inv.partner_id = int(data.get("partnerId"))
        except Exception:
            pass
    if "customerId" in data:
        try:
            inv.customer_id = int(data.get("customerId"))
        except Exception:
            pass
    if "agreedTotalAmount" in data:
        inv.agreed_total_amount = float(data.get("agreedTotalAmount") or 0.0)
    if "commissionRate" in data:
        inv.commission_rate = float(data.get("commissionRate") or 0.0)
    if "commissionMode" in data:
        inv.commission_mode = data.get("commissionMode") or inv.commission_mode
    if "commissionFixedAmount" in data:
        value = data.get("commissionFixedAmount")
        inv.commission_fixed_amount = float(value) if value is not None else None
    if "commissionAmount" in data:
        inv.commission_amount = float(data.get("commissionAmount") or 0.0)
    if "invoiceDate" in data:
        inv.invoice_date = _parse_date_yyyy_mm_dd(data.get("invoiceDate"))
    if "performancePeriodFrom" in data:
        inv.performance_period_from = _parse_date_yyyy_mm_dd(
            data.get("performancePeriodFrom")
        )
    if "performancePeriodTo" in data:
        inv.performance_period_to = _parse_date_yyyy_mm_dd(
            data.get("performancePeriodTo")
        )
    if "dueDate" in data:
        inv.due_date = _parse_date_yyyy_mm_dd(data.get("dueDate"))
    if "referenceNumber" in data:
        inv.reference_number = data.get("referenceNumber")
    if "subject" in data:
        inv.subject = data.get("subject") or inv.subject
    if "headerText" in data:
        inv.header_text = data.get("headerText") or ""
    if "positions" in data:
        inv.positions_json = json.dumps(data.get("positions") or [])
    if "paymentTermsDays" in data:
        inv.payment_terms_days = int(
            data.get("paymentTermsDays") or inv.payment_terms_days
        )
    if "reverseCharge" in data:
        inv.reverse_charge = bool(data.get("reverseCharge"))
    if "isLocked" in data:
        inv.is_locked = bool(data.get("isLocked"))
    if "paidAmount" in data:
        inv.paid_amount = float(data.get("paidAmount") or 0.0)

    db.session.commit()
    return jsonify(inv.to_dict())


@app.route('/api/invoices/<int:invoice_id>', methods=['DELETE'])
def delete_invoice(invoice_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    inv = Invoice.query.get_or_404(invoice_id)
    # Rechnung wirklich aus der Datenbank entfernen (nur den Invoice-Datensatz selbst)
    db.session.delete(inv)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/sms/send', methods=['POST'])
def send_free_sms():
    """Sendet eine SMS an eine frei eingegebene Telefonnummer über Linkmobility API"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    
    # SMS-Nachricht und Telefonnummer aus Request
    message = data.get('message', '').strip()
    message = prepare_sms_utf8(message)
    phone_number = data.get('phone_number', '').strip()
    
    if not message:
        return jsonify({"error": "SMS-Nachricht darf nicht leer sein"}), 400
    
    if not phone_number:
        return jsonify({"error": "Telefonnummer darf nicht leer sein"}), 400
    
    try:
        # Linkmobility Konfiguration
        linkmobility_token = os.getenv('LINKMOBILITY_TOKEN') or 'bb2d6280-fbfe-4b73-9421-b2ca7a76c896'
        linkmobility_base_url = os.getenv('LINKMOBILITY_BASE_URL') or 'https://api.linkmobility.eu/rest/smsmessaging/simple'
        
        # E.164 Normalisierung (basierend auf dem PHP-Beispiel)
        phone_number_clean = re.sub(r'\D+', '', phone_number)
        
        if phone_number_clean.startswith('00'):
            phone_number_clean = phone_number_clean[2:]
        if phone_number_clean.startswith('0'):
            phone_number_clean = '49' + phone_number_clean[1:]
        if not phone_number_clean.startswith('49'):
            # Falls nicht mit 49 beginnt, könnte es bereits international sein oder anderer Ländercode
            pass
        
        sms_number = '+' + phone_number_clean
        
        # API-Parameter
        params = {
            'access_token': linkmobility_token,
            'recipientAddressList': sms_number,
            'messageContent': message,
        }
        
        # cURL-äquivalent mit requests
        response = requests.post(
            linkmobility_base_url,
            data=params,
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
            timeout=30
        )
        
        if response.status_code == 200:
            # Erfolgreich versendet
            print(f"✅ SMS erfolgreich versendet an {sms_number}: HTTP {response.status_code} – Antwort: {response.text}")
            return jsonify({
                "success": True,
                "message": "SMS erfolgreich versendet",
                "recipient": sms_number,
                "response": response.text
            })
        else:
            # Fehler beim Versand
            error_msg = f"HTTP {response.status_code} – Antwort: {response.text}"
            print(f"❌ Link Mobility SMS Fehler: {error_msg}")
            return jsonify({
                "error": f"SMS-Versand fehlgeschlagen: {error_msg}",
                "status_code": response.status_code,
                "response": response.text
            }), 500
            
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        print(f"❌ Link Mobility cURL/Request Fehler: {error_msg}")
        return jsonify({
            "error": f"SMS-Versand fehlgeschlagen: {error_msg}"
        }), 500
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Unerwarteter Fehler beim SMS-Versand: {error_msg}")
        return jsonify({
            "error": f"SMS-Versand fehlgeschlagen: {error_msg}"
        }), 500

# Customer Notes APIs
@app.route('/api/customers/<int:customer_id>/notes', methods=['GET', 'POST'])
def customer_notes(customer_id):
    """API für Notizen pro Kunde"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'GET':
        # Alle Notizen für diesen Kunden laden (mit Follow-ups)
        notes = CustomerNote.query.filter_by(customer_id=customer_id).order_by(CustomerNote.created_at.desc()).all()
        notes_data = []
        for note in notes:
            note_dict = note.to_dict()
            # Follow-up für diese Notiz laden
            follow_up = FollowUp.query.filter_by(note_id=note.id).first()
            if follow_up:
                note_dict['follow_up'] = follow_up.to_dict()
            notes_data.append(note_dict)
        return jsonify(notes_data)
    
    elif request.method == 'POST':
        # Neue Notiz erstellen
        data = request.get_json()
        text = data.get('text', '').strip()
        follow_up_text = data.get('follow_up_text', '').strip()
        follow_up_due_date = data.get('follow_up_due_date')
        
        if not text:
            return jsonify({"error": "Notiz-Text ist erforderlich"}), 400
        
        # Notiz erstellen
        author = session.get('user', 'Unbekannt')
        category = data.get('category', 'Allgemein').strip() or 'Allgemein'
        note = CustomerNote(
            customer_id=customer_id,
            category=category,
            text=text,
            author=author
        )
        db.session.add(note)
        db.session.flush()  # Um note.id zu erhalten
        
        # Follow-up erstellen, falls vorhanden
        if follow_up_text and follow_up_due_date:
            try:
                from datetime import datetime as dt
                due_date = dt.strptime(follow_up_due_date, '%Y-%m-%d').date()
                # Prüfen, ob Datum in der Zukunft liegt
                if due_date <= dt.now().date():
                    return jsonify({"error": "Fälligkeitsdatum muss in der Zukunft liegen"}), 400
                
                follow_up = FollowUp(
                    note_id=note.id,
                    customer_id=customer_id,
                    text=follow_up_text,
                    due_date=due_date
                )
                db.session.add(follow_up)
            except ValueError:
                return jsonify({"error": "Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"}), 400
        
        db.session.commit()
        
        # Vollständige Notiz mit Follow-up zurückgeben
        note_dict = note.to_dict()
        if follow_up_text and follow_up_due_date:
            follow_up = FollowUp.query.filter_by(note_id=note.id).first()
            if follow_up:
                note_dict['follow_up'] = follow_up.to_dict()
        
        return jsonify(note_dict), 201


@app.route('/api/customer-notes/<int:note_id>', methods=['DELETE'])
def delete_customer_note(note_id):
    """Löscht eine Notiz (und zugehöriges Follow-up)"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    note = CustomerNote.query.get_or_404(note_id)
    
    # Follow-up löschen, falls vorhanden
    follow_up = FollowUp.query.filter_by(note_id=note_id).first()
    if follow_up:
        db.session.delete(follow_up)
    
    db.session.delete(note)
    db.session.commit()
    
    return jsonify({"success": True}), 200


# Follow-up APIs
@app.route('/api/follow-ups', methods=['GET', 'POST', 'PUT'])
def follow_ups():
    """API für Follow-ups"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    if request.method == 'GET':
        # Alle Follow-ups für einen bestimmten Kunden (optional)
        customer_id = request.args.get('customer_id', type=int)
        if customer_id:
            follow_ups = FollowUp.query.filter_by(customer_id=customer_id).order_by(FollowUp.due_date.asc()).all()
        else:
            # Alle Follow-ups (global)
            follow_ups = FollowUp.query.order_by(FollowUp.due_date.asc()).all()
        
        return jsonify([f.to_dict() for f in follow_ups])
    
    elif request.method == 'POST':
        # Neues Follow-up erstellen (unabhängig von Notizen)
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "Keine Daten empfangen"}), 400
            
            note_id = data.get('note_id')  # Optional
            customer_id = data.get('customer_id')
            text = data.get('text', '').strip()
            due_date_str = data.get('due_date')
            
            # Debug-Ausgabe
            print(f"DEBUG Follow-up POST: customer_id={customer_id}, text={text[:50]}, due_date={due_date_str}")
            
            if not customer_id:
                return jsonify({"error": "customer_id ist erforderlich"}), 400
            if not text:
                return jsonify({"error": "text ist erforderlich"}), 400
            if not due_date_str:
                return jsonify({"error": "due_date ist erforderlich"}), 400
            
            # Prüfe ob Kunde existiert
            customer = Customer.query.get(customer_id)
            if not customer:
                return jsonify({"error": f"Kunde mit ID {customer_id} nicht gefunden"}), 404
            
            from datetime import datetime as dt
            try:
                due_date = dt.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError as ve:
                return jsonify({"error": f"Ungültiges Datumsformat. Erwartet: YYYY-MM-DD, erhalten: {due_date_str}. Fehler: {str(ve)}"}), 400
            
            # Datum muss heute oder in der Zukunft sein
            today = dt.now().date()
            if due_date < today:
                return jsonify({"error": "Fälligkeitsdatum darf nicht in der Vergangenheit liegen"}), 400
            
            follow_up = FollowUp(
                note_id=note_id if note_id else None,
                customer_id=customer_id,
                text=text,
                due_date=due_date
            )
            db.session.add(follow_up)
            db.session.commit()
            
            print(f"DEBUG Follow-up erstellt: ID={follow_up.id}")
            return jsonify(follow_up.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            import traceback
            error_trace = traceback.format_exc()
            print(f"ERROR beim Erstellen des Follow-ups: {str(e)}")
            print(error_trace)
            return jsonify({"error": f"Fehler beim Erstellen des Follow-ups: {str(e)}"}), 500
    
    elif request.method == 'PUT':
        # Follow-up aktualisieren (z.B. Status ändern)
        data = request.get_json()
        follow_up_id = data.get('id')
        if not follow_up_id:
            return jsonify({"error": "id ist erforderlich"}), 400
        
        follow_up = FollowUp.query.get_or_404(follow_up_id)
        
        if 'is_completed' in data:
            follow_up.is_completed = bool(data.get('is_completed'))
        
        if 'text' in data:
            follow_up.text = data.get('text', '').strip()
        
        if 'due_date' in data:
            try:
                from datetime import datetime as dt
                due_date = dt.strptime(data.get('due_date'), '%Y-%m-%d').date()
                follow_up.due_date = due_date
            except ValueError:
                return jsonify({"error": "Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"}), 400
        
        db.session.commit()
        return jsonify(follow_up.to_dict())


@app.route('/api/follow-ups/open', methods=['GET'])
def open_follow_ups():
    """Gibt alle offenen Follow-ups zurück (kundenübergreifend)"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    # Alle offenen Follow-ups mit Kunden-Informationen
    follow_ups = FollowUp.query.filter_by(is_completed=False).order_by(FollowUp.due_date.asc()).all()
    
    result = []
    for follow_up in follow_ups:
        customer = Customer.query.get(follow_up.customer_id)
        note = CustomerNote.query.get(follow_up.note_id)
        follow_up_dict = follow_up.to_dict()
        follow_up_dict['customer_name'] = customer.name if customer else 'Unbekannt'
        follow_up_dict['note_category'] = note.category if note else None
        result.append(follow_up_dict)
    
    return jsonify(result)


@app.route('/api/follow-ups/<int:follow_up_id>', methods=['PUT', 'DELETE'])
def follow_up_detail(follow_up_id):
    """Einzelnes Follow-up aktualisieren oder löschen"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    follow_up = FollowUp.query.get_or_404(follow_up_id)
    
    if request.method == 'PUT':
        data = request.get_json()
        if 'is_completed' in data:
            follow_up.is_completed = bool(data.get('is_completed'))
        if 'text' in data:
            follow_up.text = data.get('text', '').strip()
        if 'due_date' in data:
            try:
                from datetime import datetime as dt
                due_date = dt.strptime(data.get('due_date'), '%Y-%m-%d').date()
                follow_up.due_date = due_date
            except ValueError:
                return jsonify({"error": "Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"}), 400
        
        db.session.commit()
        return jsonify(follow_up.to_dict())
    
    elif request.method == 'DELETE':
        db.session.delete(follow_up)
        db.session.commit()
        return jsonify({"success": True}), 200

# Hilfsfunktion: PDF automatisch exportieren
def _export_questionnaire_pdf(customer_id, customer_name, questionnaire_data):
    """Exportiert ein Bedarfsfragebogen-PDF automatisch als Datei"""
    try:
        import base64
        from datetime import datetime
        
        if not questionnaire_data:
            print(f"⚠️ Keine questionnaire_data für Kunde {customer_id} - Export übersprungen")
            return
        
        # PDF-Daten finden
        pdf_base64 = questionnaire_data.get('pdf_data') or questionnaire_data.get('pdf_base64')
        if not pdf_base64:
            print(f"⚠️ Keine PDF-Daten in questionnaire_data für Kunde {customer_id} - Export übersprungen")
            return
        
        # Base64-Präfix entfernen, falls vorhanden
        if pdf_base64.startswith('data:'):
            pdf_base64 = pdf_base64.split(',', 1)[1]
        
        # PDF dekodieren
        try:
            pdf_bytes = base64.b64decode(pdf_base64)
        except Exception as e:
            print(f"⚠️ Fehler beim Dekodieren der PDF für Kunde {customer_id}: {e}")
            return
        
        # Dateiname generieren
        safe_name = "".join(c for c in (customer_name or f"Kunde_{customer_id}") if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        
        # Datum aus sent_at oder jetzt
        if questionnaire_data.get('sent_at'):
            try:
                date_str = datetime.fromisoformat(questionnaire_data['sent_at'].replace('Z', '+00:00')).strftime('%Y%m%d')
            except:
                date_str = datetime.now().strftime('%Y%m%d')
        else:
            date_str = datetime.now().strftime('%Y%m%d')
        
        # Dateiname
        if questionnaire_data.get('filename'):
            original_filename = questionnaire_data['filename']
            if not original_filename.endswith('.pdf'):
                original_filename += '.pdf'
            filename = f"{date_str}_{safe_name}_{original_filename}"
        else:
            filename = f"{date_str}_{safe_name}_ID{customer_id}_Bedarfsfragebogen.pdf"
        
        filepath = os.path.join(QUESTIONNAIRE_EXPORT_DIR, filename)
        
        # PDF speichern
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)
        
        print(f"✅ Bedarfsfragebogen-PDF automatisch exportiert: {filename} ({len(pdf_bytes)} Bytes)")
    except Exception as e:
        print(f"⚠️ Fehler beim automatischen Export der Bedarfsfragebogen-PDF für Kunde {customer_id}: {e}")
        import traceback
        traceback.print_exc()

# Hilfsfunktion: Angebots-PDF automatisch exportieren
def _export_offer_pdf(customer_id, customer_name, offer_data):
    """Exportiert ein Angebots-PDF automatisch als Datei"""
    try:
        import base64
        from datetime import datetime
        
        if not offer_data:
            print(f"⚠️ Keine offer_data für Kunde {customer_id} - Export übersprungen")
            return
        
        # PDF-Daten finden
        pdf_base64 = offer_data.get('pdf_data') or offer_data.get('pdf_base64')
        if not pdf_base64:
            print(f"⚠️ Keine PDF-Daten in offer_data für Kunde {customer_id} - Export übersprungen")
            return
        
        # Base64-Präfix entfernen, falls vorhanden
        if pdf_base64.startswith('data:'):
            pdf_base64 = pdf_base64.split(',', 1)[1]
        
        # PDF dekodieren
        try:
            pdf_bytes = base64.b64decode(pdf_base64)
        except Exception as e:
            print(f"⚠️ Fehler beim Dekodieren der Angebots-PDF für Kunde {customer_id}: {e}")
            return
        
        # Dateiname generieren
        safe_name = "".join(c for c in (customer_name or f"Kunde_{customer_id}") if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        
        # Datum aus sent_at oder jetzt
        if offer_data.get('sent_at'):
            try:
                date_str = datetime.fromisoformat(offer_data['sent_at'].replace('Z', '+00:00')).strftime('%Y%m%d')
            except:
                date_str = datetime.now().strftime('%Y%m%d')
        else:
            date_str = datetime.now().strftime('%Y%m%d')
        
        # Dateiname
        if offer_data.get('filename'):
            original_filename = offer_data['filename']
            if not original_filename.endswith('.pdf'):
                original_filename += '.pdf'
            filename = f"{date_str}_{safe_name}_{original_filename}"
        else:
            filename = f"{date_str}_{safe_name}_ID{customer_id}_Angebot.pdf"
        
        filepath = os.path.join(OFFER_EXPORT_DIR, filename)
        
        # PDF speichern
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)
        
        print(f"✅ Angebots-PDF automatisch exportiert: {filename} ({len(pdf_bytes)} Bytes)")
    except Exception as e:
        print(f"⚠️ Fehler beim automatischen Export der Angebots-PDF für Kunde {customer_id}: {e}")
        import traceback
        traceback.print_exc()

# Hilfsfunktion: Kooperationsvertrag-PDF automatisch exportieren
def _export_kooperationsvertrag_pdf(contract_id, contract_number, pdf_path, is_signed=False):
    """Exportiert ein Kooperationsvertrag-PDF automatisch als Datei"""
    try:
        from datetime import datetime
        import shutil
        
        if not os.path.exists(pdf_path):
            print(f"⚠️ PDF-Datei nicht gefunden: {pdf_path}")
            return
        
        # Dateiname generieren
        safe_contract_number = "".join(c for c in (contract_number or f"Vertrag_{contract_id}") if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        date_str = datetime.now().strftime('%Y%m%d')
        
        # Dateiname mit Status
        if is_signed:
            filename = f"{date_str}_{safe_contract_number}_unterschrieben.pdf"
        else:
            filename = f"{date_str}_{safe_contract_number}.pdf"
        
        filepath = os.path.join(KOOPERATIONSVERTRAG_EXPORT_DIR, filename)
        
        # PDF kopieren
        shutil.copy2(pdf_path, filepath)
        
        print(f"✅ Kooperationsvertrag-PDF automatisch exportiert: {filename}")
    except Exception as e:
        print(f"⚠️ Fehler beim automatischen Export der Kooperationsvertrag-PDF für Vertrag {contract_id}: {e}")

# Hilfsfunktion: Profil-PDF automatisch exportieren
def _export_profile_pdf(customer_id, customer_name, profile_data):
    """Exportiert ein Profil-PDF (Profilersteller) automatisch als Datei"""
    try:
        import base64
        from datetime import datetime

        if not profile_data:
            print(f"⚠️ Keine profile_data für Kunde {customer_id} - Export übersprungen")
            return

        pdf_base64 = profile_data.get('pdf_data') or profile_data.get('pdf_base64')
        if not pdf_base64:
            print(f"⚠️ Keine PDF-Daten in profile_data für Kunde {customer_id} - Export übersprungen")
            return

        if pdf_base64.startswith('data:'):
            pdf_base64 = pdf_base64.split(',', 1)[1]

        try:
            pdf_bytes = base64.b64decode(pdf_base64)
        except Exception as e:
            print(f"⚠️ Fehler beim Dekodieren der Profil-PDF für Kunde {customer_id}: {e}")
            return

        safe_name = "".join(
            c for c in (customer_name or f"Kunde_{customer_id}") if c.isalnum() or c in (' ', '-', '_')
        ).strip().replace(' ', '_')

        if profile_data.get('created_at'):
            try:
                date_str = datetime.fromisoformat(profile_data['created_at'].replace('Z', '+00:00')).strftime('%Y%m%d')
            except Exception:
                date_str = datetime.now().strftime('%Y%m%d')
        else:
            date_str = datetime.now().strftime('%Y%m%d')

        if profile_data.get('filename'):
            original_filename = profile_data['filename']
            if not original_filename.endswith('.pdf'):
                original_filename += '.pdf'
            filename = f"{date_str}_{safe_name}_{original_filename}"
        else:
            filename = f"{date_str}_{safe_name}_ID{customer_id}_Profil.pdf"

        filepath = os.path.join(PROFILE_EXPORT_DIR, filename)

        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)

        print(f"✅ Profil-PDF automatisch exportiert: {filename}")
    except Exception as e:
        print(f"⚠️ Fehler beim automatischen Export der Profil-PDF für Kunde {customer_id}: {e}")

# Automatisches Speichern von Kunden beim Angebot versenden
def save_customer_from_email(email_address, customer_name=None, offer_data=None, questionnaire_data=None):
    """Speichert automatisch einen Kunden basierend auf E-Mail-Adresse"""
    print(f"DEBUG: save_customer_from_email aufgerufen mit email={email_address}, questionnaire_data={questionnaire_data}")
    if not email_address:
        print("DEBUG: Keine E-Mail-Adresse, breche ab")
        return None
    
    import json
    
    # Telefonnummer (aus Angebot) extrahieren
    phone_from_offer = None
    try:
        if offer_data and isinstance(offer_data, dict):
            phone_from_offer = (offer_data.get('sms_number') or offer_data.get('phone') or '').strip() or None
    except Exception:
        phone_from_offer = None
    
    # Prüfen ob Kunde bereits existiert
    existing_customer = Customer.query.filter_by(email=email_address).first()
    if existing_customer:
        # Letzten Kontakt aktualisieren
        existing_customer.last_contact = datetime.datetime.utcnow()
        
        # Name auffüllen/aktualisieren, wenn sinnvoll
        try:
            if customer_name:
                # Aktualisiere, falls Name leer ist oder nur der Teil vor @ verwendet wurde
                fallback_name = (email_address.split('@')[0] if email_address else '')
                if not existing_customer.name or existing_customer.name == fallback_name:
                    existing_customer.name = customer_name
        except Exception:
            pass
        
        # Telefonnummer übernehmen/aktualisieren
        try:
            if phone_from_offer:
                existing_customer.phone = phone_from_offer
        except Exception:
            pass
        
        # Angebot-Daten hinzufügen/aktualisieren
        if offer_data:
            try:
                current_offer_data = json.loads(existing_customer.offer_data_json or '{}')
                current_offer_data.update(offer_data)
                existing_customer.offer_data_json = json.dumps(current_offer_data)
            except:
                existing_customer.offer_data_json = json.dumps(offer_data)
            
            # Kontakthistorie-Eintrag hinzufügen
            existing_customer.add_contact_entry('offer_sent', offer_data)
            
            # PDF automatisch als Datei exportieren
            _export_offer_pdf(existing_customer.id, existing_customer.name, offer_data)
        
        # Befragungsbogen-Daten hinzufügen/aktualisieren
        if questionnaire_data:
            try:
                current_questionnaire_data = json.loads(existing_customer.questionnaire_data_json or '{}')
                current_questionnaire_data.update(questionnaire_data)
                existing_customer.questionnaire_data_json = json.dumps(current_questionnaire_data)
            except:
                existing_customer.questionnaire_data_json = json.dumps(questionnaire_data)
            
            # Kontakthistorie-Eintrag hinzufügen
            existing_customer.add_contact_entry('questionnaire_sent', questionnaire_data)
            
            # PDF automatisch als Datei exportieren
            _export_questionnaire_pdf(existing_customer.id, existing_customer.name, questionnaire_data)
        
        db.session.commit()
        return existing_customer
    
    # Neuen Kunden erstellen
    customer = Customer(
        name=customer_name or email_address.split('@')[0],  # Fallback: Teil vor @
        email=email_address,
        phone=phone_from_offer
    )
    
    # Angebot-Daten hinzufügen
    if offer_data:
        customer.offer_data_json = json.dumps(offer_data)
        customer.add_contact_entry('offer_sent', offer_data)
    
    # Befragungsbogen-Daten hinzufügen
    if questionnaire_data:
        customer.questionnaire_data_json = json.dumps(questionnaire_data)
        customer.add_contact_entry('questionnaire_sent', questionnaire_data)
    
    try:
        db.session.add(customer)
        db.session.commit()
        
        # PDFs automatisch als Datei exportieren, falls vorhanden
        if offer_data:
            _export_offer_pdf(customer.id, customer.name, offer_data)
        if questionnaire_data:
            _export_questionnaire_pdf(customer.id, customer.name, questionnaire_data)
        
        return customer
    except Exception as e:
        # Bei Fehler (z.B. Duplicate Key): Rollback und erneut versuchen
        db.session.rollback()
        print(f"DEBUG: Fehler beim Erstellen des Kunden, versuche erneut: {e}")
        # Erneut prüfen ob Kunde inzwischen existiert (Race Condition)
        try:
            existing_customer = Customer.query.filter_by(email=email_address).first()
            if existing_customer:
                # Aktualisiere bestehenden Kunden
                if offer_data:
                    try:
                        current_offer_data = json.loads(existing_customer.offer_data_json or '{}')
                        current_offer_data.update(offer_data)
                        existing_customer.offer_data_json = json.dumps(current_offer_data)
                    except:
                        existing_customer.offer_data_json = json.dumps(offer_data)
                    # PDF automatisch als Datei exportieren
                    if offer_data:
                        _export_offer_pdf(existing_customer.id, existing_customer.name, offer_data)
                if questionnaire_data:
                    try:
                        current_questionnaire_data = json.loads(existing_customer.questionnaire_data_json or '{}')
                        current_questionnaire_data.update(questionnaire_data)
                        existing_customer.questionnaire_data_json = json.dumps(current_questionnaire_data)
                    except:
                        existing_customer.questionnaire_data_json = json.dumps(questionnaire_data)
                    # PDF automatisch als Datei exportieren
                    _export_questionnaire_pdf(existing_customer.id, existing_customer.name, questionnaire_data)
                existing_customer.last_contact = datetime.datetime.utcnow()
                db.session.commit()
                return existing_customer
            else:
                # Unerwarteter Fehler, erneut versuchen
                raise
        except Exception as e2:
            print(f"DEBUG: Fehler beim Retry: {e2}")
            raise

# Befragungsbogen-Daten zu Kunde hinzufügen
@app.route('/api/customers/<int:customer_id>/questionnaire', methods=['POST'])
def add_questionnaire_data(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json()
    
    import json
    
    # Befragungsbogen-Daten hinzufügen/aktualisieren
    try:
        current_data = json.loads(customer.questionnaire_data_json or '{}')
        current_data.update(data)
        customer.questionnaire_data_json = json.dumps(current_data)
    except:
        customer.questionnaire_data_json = json.dumps(data)
    
    # Kontakthistorie-Eintrag hinzufügen
    customer.add_contact_entry('questionnaire_sent', data)
    
    # PDF automatisch als Datei exportieren
    _export_questionnaire_pdf(customer.id, customer.name, data)
    
    db.session.commit()
    return jsonify(customer.to_dict())


# Profil-Daten (Profilersteller) zu Kunde hinzufügen
@app.route('/api/customers/<int:customer_id>/profile', methods=['POST'])
def add_profile_data(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json() or {}

    import json

    # Profil-Daten als Liste verwalten (mehrere Profile pro Kunde)
    try:
        raw = getattr(customer, 'profile_data_json', '[]') or '[]'
        current_list = json.loads(raw)
        if isinstance(current_list, dict):
            current_list = [current_list]
        elif not isinstance(current_list, list):
            current_list = []
    except Exception:
        current_list = []

    # Neues Profil-Objekt mit Zeitstempel anhängen
    from datetime import datetime as dt
    new_profile = dict(data or {})
    if 'created_at' not in new_profile:
        new_profile['created_at'] = dt.utcnow().isoformat()
    current_list.append(new_profile)

    customer.profile_data_json = json.dumps(current_list)

    # Kontakthistorie-Eintrag hinzufügen
    customer.add_contact_entry('profile_created', new_profile)

    # PDF automatisch als Datei exportieren
    _export_profile_pdf(customer.id, customer.name, new_profile)

    db.session.commit()
    return jsonify(customer.to_dict())


@app.route('/api/customers/<int:customer_id>/profile/<int:profile_index>', methods=['DELETE'])
def delete_profile(customer_id, profile_index):
    """Löscht ein einzelnes Profil (nach Index) für einen Kunden"""
    customer = Customer.query.get_or_404(customer_id)

    import json

    try:
        raw = getattr(customer, 'profile_data_json', '[]') or '[]'
        profiles = json.loads(raw)
        if isinstance(profiles, dict):
            profiles = [profiles]
        elif not isinstance(profiles, list):
            profiles = []
    except Exception:
        profiles = []

    if profile_index < 0 or profile_index >= len(profiles):
        return jsonify({"error": "Profil nicht gefunden"}), 404

    deleted_profile = profiles.pop(profile_index)
    customer.profile_data_json = json.dumps(profiles)

    # Optionaler Eintrag in der Kontakthistorie
    try:
        customer.add_contact_entry('profile_deleted', deleted_profile)
    except Exception:
        pass

    db.session.commit()
    return jsonify({"success": True, "remaining": len(profiles)})

# Kooperationspartner API
@app.route('/api/kooperationspartner', methods=['GET'])
def get_kooperationspartner():
    try:
        # Optionale Pagination (default: alle)
        page = request.args.get('page', type=int, default=1)
        per_page = request.args.get('per_page', type=int, default=1000)  # Groß genug für normale Nutzung
        
        pagination = Kooperationspartner.query.order_by(Kooperationspartner.name).paginate(
            page=page, per_page=per_page, error_out=False
        )
        return jsonify({
            'items': [partner.to_dict() for partner in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'page': page
        })
    except Exception as e:
        return jsonify({"error": f"Fehler beim Laden: {str(e)}"}), 500

@app.route('/api/kooperationspartner', methods=['POST'])
def create_kooperationspartner():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    
    if not name or not email:
        return jsonify({"error": "Name und E-Mail sind erforderlich"}), 400
    
    try:
        partner = Kooperationspartner(
            name=name,
            email=email,
            company_name=data.get('company_name', '').strip(),
            street_address=data.get('street_address', '').strip(),
            phone=data.get('phone', '').strip(),
            identification_number=data.get('identification_number', '').strip(),
            commercial_register=data.get('commercial_register', '').strip(),
            vat_id=data.get('vat_id', '').strip(),
            managing_director=data.get('managing_director', '').strip(),
            emergency_phone=data.get('emergency_phone', '').strip(),
            provision=data.get('provision', '').strip() or None,
            notes=(data.get('notes') or '').strip() or None
        )
        db.session.add(partner)
        db.session.commit()
        return jsonify(partner.to_dict())
    except Exception as e:
        return jsonify({"error": f"Fehler beim Erstellen: {str(e)}"}), 500

@app.route('/api/kooperationspartner/<int:partner_id>', methods=['GET', 'PUT', 'DELETE'])
def kooperationspartner_detail(partner_id):
    partner = Kooperationspartner.query.get_or_404(partner_id)
    
    if request.method == 'GET':
        return jsonify(partner.to_dict())
    
    elif request.method == 'PUT':
        data = request.get_json() or {}
        
        try:
            if 'name' in data:
                partner.name = data['name'].strip()
            if 'email' in data:
                partner.email = data['email'].strip()
            if 'company_name' in data:
                partner.company_name = data['company_name'].strip()
            if 'street_address' in data:
                partner.street_address = data['street_address'].strip()
            if 'phone' in data:
                partner.phone = data['phone'].strip()
            if 'identification_number' in data:
                partner.identification_number = data['identification_number'].strip()
            if 'commercial_register' in data:
                partner.commercial_register = data['commercial_register'].strip()
            if 'vat_id' in data:
                partner.vat_id = data['vat_id'].strip()
            if 'managing_director' in data:
                partner.managing_director = data['managing_director'].strip()
            if 'emergency_phone' in data:
                partner.emergency_phone = data['emergency_phone'].strip()
            if 'provision' in data:
                provision_value = str(data['provision']).strip()
                # Nur aktualisieren, wenn ein Wert vorhanden ist
                # Leere Werte werden ignoriert, um vorhandene Werte nicht zu überschreiben
                if provision_value:
                    partner.provision = provision_value
                # Wenn explizit leer gesetzt werden soll, dann auf None setzen
                # Aber nur wenn es wirklich leer ist (nicht nur Whitespace)
                elif provision_value == '':
                    partner.provision = None
            if 'notes' in data:
                notes_value = data.get('notes')
                if notes_value is None:
                    partner.notes = None
                else:
                    partner.notes = notes_value.strip() if isinstance(notes_value, str) else notes_value
            
            db.session.commit()
            return jsonify(partner.to_dict())
        except Exception as e:
            return jsonify({"error": f"Fehler beim Aktualisieren: {str(e)}"}), 500
    
    elif request.method == 'DELETE':
        try:
            # Prüfen, ob der Partner noch in Verträgen referenziert wird
            from models import Kooperationsvertrag, Dienstleistungsvertrag
            
            # Kooperationsverträge prüfen (als Sender oder Empfänger)
            kooperationsvertraege = Kooperationsvertrag.query.filter(
                (Kooperationsvertrag.sender_partner_id == partner_id) |
                (Kooperationsvertrag.receiver_partner_id == partner_id)
            ).all()
            
            # Dienstleistungsverträge prüfen
            dienstleistungsvertraege = Dienstleistungsvertrag.query.filter(
                Dienstleistungsvertrag.kooperationspartner_id == partner_id
            ).all()
            
            deleted_count = 0
            
            # Wenn Verträge vorhanden sind, diese zuerst löschen
            if kooperationsvertraege:
                for vertrag in kooperationsvertraege:
                    try:
                        db.session.delete(vertrag)
                        deleted_count += 1
                    except Exception as e:
                        print(f"Fehler beim Löschen von Kooperationsvertrag {vertrag.id}: {e}")
                        db.session.rollback()
                        return jsonify({"error": f"Fehler beim Löschen von Kooperationsvertrag {vertrag.id}: {str(e)}"}), 500
            
            if dienstleistungsvertraege:
                for vertrag in dienstleistungsvertraege:
                    try:
                        db.session.delete(vertrag)
                        deleted_count += 1
                    except Exception as e:
                        print(f"Fehler beim Löschen von Dienstleistungsvertrag {vertrag.id}: {e}")
                        db.session.rollback()
                        return jsonify({"error": f"Fehler beim Löschen von Dienstleistungsvertrag {vertrag.id}: {str(e)}"}), 500
            
            # Alle Verträge-Löschungen committen, bevor der Partner gelöscht wird
            if deleted_count > 0:
                db.session.commit()
            
            # Partner löschen
            try:
                db.session.delete(partner)
                db.session.commit()
                return jsonify({"success": True, "deleted_contracts": deleted_count})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": f"Fehler beim Löschen des Partners: {str(e)}"}), 500
        except Exception as e:
            db.session.rollback()
            print(f"Fehler beim Löschen des Partners {partner_id}: {e}")
            return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

@app.route('/api/kooperationspartner/<int:partner_id>/update', methods=['PUT'])
def update_kooperationspartner(partner_id):
    partner = Kooperationspartner.query.get_or_404(partner_id)
    data = request.get_json() or {}
    
    try:
        if 'name' in data:
            partner.name = data['name'].strip()
        if 'email' in data:
            partner.email = data['email'].strip()
        if 'company_name' in data:
            partner.company_name = data['company_name'].strip()
        if 'street_address' in data:
            partner.street_address = data['street_address'].strip()
        if 'phone' in data:
            partner.phone = data['phone'].strip()
        if 'identification_number' in data:
            partner.identification_number = data['identification_number'].strip()
        if 'commercial_register' in data:
            partner.commercial_register = data['commercial_register'].strip()
        if 'vat_id' in data:
            partner.vat_id = data['vat_id'].strip()
        if 'managing_director' in data:
            partner.managing_director = data['managing_director'].strip()
        if 'emergency_phone' in data:
            partner.emergency_phone = data['emergency_phone'].strip()
        if 'provision' in data:
            partner.provision = str(data['provision']).strip()
        
        db.session.commit()
        return jsonify(partner.to_dict())
    except Exception as e:
        return jsonify({"error": f"Fehler beim Aktualisieren: {str(e)}"}), 500

@app.route('/api/kooperationspartner/<int:partner_id>/delete', methods=['DELETE'])
def delete_kooperationspartner(partner_id):
    partner = Kooperationspartner.query.get_or_404(partner_id)
    
    try:
        db.session.delete(partner)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

@app.route('/api/kooperationspartner/<int:partner_id>/kooperationsvertraege', methods=['GET'])
def get_partner_kooperationsvertraege(partner_id):
    """Holt alle Kooperationsverträge für einen spezifischen Partner (als Sender oder Receiver)"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        # Nur Verträge holen, bei denen der Partner der Receiver ist
        # (denn HelpCare ist immer der Sender)
        contracts = Kooperationsvertrag.query.filter(
            Kooperationsvertrag.receiver_partner_id == partner_id
        ).order_by(Kooperationsvertrag.created_at.desc()).all()
        
        return jsonify([contract.to_dict() for contract in contracts])
    except Exception as e:
        return jsonify({"error": f"Fehler beim Laden: {str(e)}"}), 500

@app.route('/api/kooperationspartner/<int:partner_id>/kooperationsvertraege', methods=['POST'])
def create_partner_kooperationsvertrag(partner_id):
    """Erstellt einen neuen Kooperationsvertrag mit HelpCare als Sender und dem Partner als Receiver"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    contract_number = data.get('contract_number')
    
    if not contract_number:
        return jsonify({"error": "Vertragsnummer ist erforderlich"}), 400
    
    try:
        # HelpCare als Sender-Partner finden (oder erstellen)
        helpcare_partner = Kooperationspartner.query.filter_by(name='HelpCare').first()
        if not helpcare_partner:
            # HelpCare-Partner erstellen falls nicht vorhanden
            helpcare_partner = Kooperationspartner(
                name='HelpCare',
                email='info@helpcare.de',
                company_name='HelpCare GmbH',
                street_address='HelpCare Straße 1, 12345 HelpCare Stadt',
                phone='+49 123 456789',
                managing_director='HelpCare Geschäftsführung'
            )
            db.session.add(helpcare_partner)
            db.session.commit()
        
        # Receiver-Partner laden
        receiver_partner = Kooperationspartner.query.get_or_404(partner_id)
        
        contract = Kooperationsvertrag(
            sender_partner_id=helpcare_partner.id,  # HelpCare ist immer der Sender
            receiver_partner_id=partner_id,         # Der Partner ist der Receiver
            contract_number=contract_number,
            contract_location=helpcare_partner.street_address.split(',')[1].strip().split(' ')[1] if helpcare_partner.street_address and ',' in helpcare_partner.street_address and len(helpcare_partner.street_address.split(',')[1].strip().split(' ')) > 1 else 'HelpCare Stadt',
            contract_data_json=json.dumps(data.get('contract_data', {}))
        )
        db.session.add(contract)
        db.session.commit()
        return jsonify(contract.to_dict()), 201
    except Exception as e:
        return jsonify({"error": f"Fehler beim Erstellen: {str(e)}"}), 500

@app.route('/api/kooperationspartner/<int:partner_id>/upload-contract', methods=['POST'])
def upload_partner_kooperationsvertrag(partner_id):
    """Lädt einen Kooperationsvertrag als PDF hoch und erstellt einen neuen Vertragseintrag"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei übermittelt"}), 400
    
    f = request.files['file']
    if not f or not f.filename:
        return jsonify({"error": "Ungültige Datei"}), 400
    
    original = secure_filename(f.filename)
    if not _is_pdf_filename(original):
        return jsonify({"error": "Nur PDF-Dateien sind erlaubt"}), 400
    
    contract_number = request.form.get('contract_number', '').strip()
    if not contract_number:
        # Fallback: Verwende Dateinamen ohne Erweiterung als Vertragsnummer
        contract_number = original.rsplit('.', 1)[0] if '.' in original else original
    
    try:
        # HelpCare als Sender-Partner finden (oder erstellen)
        helpcare_partner = Kooperationspartner.query.filter_by(name='HelpCare').first()
        if not helpcare_partner:
            helpcare_partner = Kooperationspartner(
                name='HelpCare',
                email='info@helpcare.de',
                company_name='HelpCare GmbH',
                street_address='HelpCare Straße 1, 12345 HelpCare Stadt',
                phone='+49 123 456789',
                managing_director='HelpCare Geschäftsführung'
            )
            db.session.add(helpcare_partner)
            db.session.commit()
        
        # Receiver-Partner laden
        receiver_partner = Kooperationspartner.query.get_or_404(partner_id)
        
        # PDF speichern (als unterschriebenes PDF, da es bereits unterschrieben ist)
        unique = uuid.uuid4().hex + '.pdf'
        path = os.path.join(UPLOAD_FOLDER, unique)
        f.save(path)
        
        # Kooperationsvertrag erstellen
        # Da das hochgeladene PDF bereits unterschrieben ist, speichern wir es als signed_pdf_filename
        # und setzen den Status auf 'signed'
        contract = Kooperationsvertrag(
            sender_partner_id=helpcare_partner.id,
            receiver_partner_id=partner_id,
            contract_number=contract_number,
            contract_location=helpcare_partner.street_address.split(',')[1].strip().split(' ')[1] if helpcare_partner.street_address and ',' in helpcare_partner.street_address and len(helpcare_partner.street_address.split(',')[1].strip().split(' ')) > 1 else 'HelpCare Stadt',
            signed_pdf_filename=unique,  # Als unterschriebenes PDF speichern
            status='signed'  # Status auf 'signed' setzen, da das hochgeladene PDF bereits unterschrieben ist
        )
        db.session.add(contract)
        db.session.commit()
        
        # PDF automatisch exportieren
        _export_kooperationsvertrag_pdf(contract.id, contract.contract_number, path, is_signed=True)
        
        return jsonify(contract.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        print(f"❌ Fehler beim Hochladen des Kooperationsvertrags: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Fehler beim Hochladen: {str(e)}"}), 500

# 📋 Kooperationsvertrag API
@app.route('/api/kooperationsvertraege', methods=['GET', 'POST'])
def kooperationsvertraege():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    if request.method == 'GET':
        # Optionale Pagination (default: alle)
        page = request.args.get('page', type=int, default=1)
        per_page = request.args.get('per_page', type=int, default=1000)  # Groß genug für normale Nutzung
        
        pagination = Kooperationsvertrag.query.order_by(Kooperationsvertrag.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        return jsonify({
            'items': [contract.to_dict() for contract in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'page': page
        })
    
    elif request.method == 'POST':
        data = request.get_json() or {}
        
        sender_partner_id = data.get('sender_partner_id')
        receiver_partner_id = data.get('receiver_partner_id')
        contract_number = data.get('contract_number')
        
        if not all([sender_partner_id, receiver_partner_id, contract_number]):
            return jsonify({"error": "Sender-Partner-ID, Receiver-Partner-ID und Vertragsnummer sind erforderlich"}), 400
        
        try:
            # Sender-Partner laden für Ort
            sender_partner = Kooperationspartner.query.get(sender_partner_id)
            
            contract = Kooperationsvertrag(
                sender_partner_id=sender_partner_id,
                receiver_partner_id=receiver_partner_id,
                contract_number=contract_number,
                contract_location=sender_partner.city if sender_partner and sender_partner.street_address else None,
                contract_data_json=json.dumps(data.get('contract_data', {}))
            )
            db.session.add(contract)
            db.session.commit()
            return jsonify(contract.to_dict()), 201
        except Exception as e:
            return jsonify({"error": f"Fehler beim Erstellen: {str(e)}"}), 500

@app.route('/api/kooperationsvertraege/<int:contract_id>', methods=['GET', 'PUT', 'DELETE'])
def kooperationsvertrag_detail(contract_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    
    if request.method == 'GET':
        return jsonify(contract.to_dict())
    
    elif request.method == 'PUT':
        data = request.get_json() or {}
        
        try:
            if 'contract_number' in data:
                contract.contract_number = data['contract_number']
            if 'contract_location' in data:
                contract.contract_location = data['contract_location']
            if 'status' in data:
                contract.status = data['status']
            if 'contract_data' in data:
                contract.contract_data_json = json.dumps(data['contract_data'])
            
            db.session.commit()
            return jsonify(contract.to_dict())
        except Exception as e:
            return jsonify({"error": f"Fehler beim Aktualisieren: {str(e)}"}), 500
    
    elif request.method == 'DELETE':
        try:
            db.session.delete(contract)
            db.session.commit()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

@app.route('/api/kooperationsvertraege/<int:contract_id>/generate-pdf', methods=['POST'])
def generate_kooperationsvertrag_pdf(contract_id):
    """Generiert eine PDF aus dem Kooperationsvertrag-Template mit den Daten"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    sender_partner = Kooperationspartner.query.get(contract.sender_partner_id)
    receiver_partner = Kooperationspartner.query.get(contract.receiver_partner_id)
    
    if not sender_partner or not receiver_partner:
        return jsonify({"error": "Sender oder Receiver Partner nicht gefunden"}), 404
    
    try:
        html_content = _render_kooperationsvertrag_html(contract, receiver_partner)
        try:
            pdf_filename, pdf_url = _generate_kooperationsvertrag_pdf_from_html(contract, html_content)
            
            # PDF automatisch exportieren
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
            _export_kooperationsvertrag_pdf(contract.id, contract.contract_number, pdf_path, is_signed=False)
            
            return jsonify({
                "success": True,
                "pdf_filename": pdf_filename,
                "pdf_url": pdf_url
            })
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Fehler beim Laden des Templates: {str(e)}"}), 500

@app.route('/api/kooperationsvertraege/<int:contract_id>/preview')
def preview_kooperationsvertrag(contract_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    receiver_partner = Kooperationspartner.query.get(contract.receiver_partner_id)
    if not receiver_partner:
        return jsonify({"error": "Kooperationspartner nicht gefunden"}), 404
    
    try:
        html_content = contract.custom_html or _render_kooperationsvertrag_html(contract, receiver_partner)
        return jsonify({"success": True, "html": html_content})
    except Exception as e:
        return jsonify({"error": f"Preview konnte nicht erstellt werden: {str(e)}"}), 500

@app.route('/api/kooperationsvertraege/<int:contract_id>/send-docuseal', methods=['POST'])
def send_kooperationsvertrag_docuseal(contract_id):
    """Kooperationsvertrag zur Signatur per E-Mail senden"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    
    # Debug-Ausgabe
    print(f"🔍 DEBUG: Kooperationsvertrag {contract_id}")
    print(f"   Sender Partner ID: {contract.sender_partner_id}")
    print(f"   Receiver Partner ID: {contract.receiver_partner_id}")
    
    # Partner laden - mit get_or_404 für bessere Fehlermeldung
    try:
        sender_partner = Kooperationspartner.query.get_or_404(contract.sender_partner_id)
        print(f"✅ Sender Partner gefunden: {sender_partner.name}")
    except Exception as e:
        print(f"❌ Fehler beim Laden des Sender Partners: {e}")
        return jsonify({"error": f"Sender Partner (ID: {contract.sender_partner_id}) nicht gefunden"}), 404
    
    try:
        receiver_partner = Kooperationspartner.query.get_or_404(contract.receiver_partner_id)
        print(f"✅ Receiver Partner gefunden: {receiver_partner.name}")
    except Exception as e:
        print(f"❌ Fehler beim Laden des Receiver Partners: {e}")
        return jsonify({"error": f"Receiver Partner (ID: {contract.receiver_partner_id}) nicht gefunden"}), 404

    data = request.get_json(silent=True) or {}
    custom_html = data.get('html_content')
    if custom_html:
        contract.custom_html = custom_html
    
    try:
        html_content = custom_html or contract.custom_html or _render_kooperationsvertrag_html(contract, receiver_partner)
    except Exception as e:
        return jsonify({"error": f"Template konnte nicht erstellt werden: {str(e)}"}), 500
    
    if custom_html or not contract.pdf_filename:
        try:
            _generate_kooperationsvertrag_pdf_from_html(contract, html_content)
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500

    try:
        # E-Mail mit Signatur-Link senden
        signature_url = f"{request.host_url}api/kooperationsvertraege/{contract_id}/sign"
        success, error_msg = send_signature_email(
            contract_id=contract.id,
            customer_email=receiver_partner.email,
            customer_name=receiver_partner.name,
            contract_type="kooperationsvertrag",
            signature_url=signature_url
        )

        if not success:
            return jsonify({"error": f"E-Mail-Versand Fehler: {error_msg}"}), 500
        
        # Contract Status aktualisieren
        contract.status = 'sent'
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Kooperationsvertrag erfolgreich zur Signatur per E-Mail gesendet"
        })

    except Exception as e:
        return jsonify({"error": f"E-Mail-Versand Fehler: {str(e)}"}), 500

@app.route('/api/kooperationsvertraege/<int:contract_id>/check-status', methods=['POST'])
def check_kooperationsvertrag_status(contract_id):
    """Prüft den Status eines Kooperationsvertrags"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    
    # Einfache Status-Rückgabe (kein DocuSign mehr)
    return jsonify({
        "success": True,
        "status": contract.status,
        "message": f"Status: {contract.status}"
    })

@app.route('/api/kooperationsvertraege/<int:contract_id>/download-pdf', methods=['GET'])
def download_kooperationsvertrag_pdf(contract_id):
    """Lädt das ursprüngliche PDF eines Kooperationsvertrags herunter"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    
    if not contract.pdf_filename:
        return jsonify({"error": "PDF nicht gefunden"}), 404
    
    try:
        pdf_path = os.path.join(UPLOAD_FOLDER, contract.pdf_filename)
        return send_file(pdf_path, as_attachment=True, download_name=f"kooperationsvertrag_{contract.contract_number}.pdf")
    except Exception as e:
        return jsonify({"error": f"Fehler beim Download: {str(e)}"}), 500

@app.route('/api/kooperationsvertraege/<int:contract_id>/sign', methods=['GET'])
def sign_kooperationsvertrag(contract_id):
    """Zeigt den Kooperationsvertrag zur Signatur an"""
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    # Für die Anzeige müssen die Daten des Dienstleisters (Empfänger) verwendet werden
    receiver_partner = Kooperationspartner.query.get(contract.receiver_partner_id)
    
    if not receiver_partner:
        return jsonify({"error": "Kooperationspartner nicht gefunden"}), 404
    
    html_content = contract.custom_html or _render_kooperationsvertrag_html(contract, receiver_partner)
    
    # Prüfe ob bereits signiert (wie in SignaturApp) - WICHTIG: NACH Variablen ersetzung
    if contract.status == 'signed' and contract.signature_data:
        # Vertrag bereits signiert - ersetze placeholder durch Signatur-Bild
        signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{contract.signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder"></div>', signature_img)
    
    # Füge Signatur-Skript hinzu (von SignaturApp) mit contract_id
    html_content = add_signature_script(html_content, contract_id, "kooperationsvertraege")
    
    return html_content

@app.route('/api/kooperationsvertraege/<int:contract_id>/download-signed', methods=['GET'])
def download_signed_kooperationsvertrag_pdf(contract_id):
    """Lädt das unterschriebene PDF eines Kooperationsvertrags herunter"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    
    if not contract.signed_pdf_filename:
        return jsonify({"error": "Unterschriebenes PDF nicht gefunden"}), 404
    
    try:
        pdf_path = os.path.join(UPLOAD_FOLDER, contract.signed_pdf_filename)
        return send_file(pdf_path, as_attachment=True, download_name=f"kooperationsvertrag_{contract.contract_number}_signed.pdf")
    except Exception as e:
        return jsonify({"error": f"Fehler beim Download: {str(e)}"}), 500

# 📋 Dienstleistungsvertrag API
@app.route('/api/dienstleistungsvertraege', methods=['GET', 'POST'])
def dienstleistungsvertraege():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    if request.method == 'GET':
        # Optionale Pagination (default: alle)
        page = request.args.get('page', type=int, default=1)
        per_page = request.args.get('per_page', type=int, default=1000)  # Groß genug für normale Nutzung
        
        pagination = Dienstleistungsvertrag.query.order_by(Dienstleistungsvertrag.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        return jsonify({
            'items': [contract.to_dict() for contract in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'page': page
        })
    
    elif request.method == 'POST':
        data = request.get_json() or {}
        
        customer_id = data.get('customer_id')
        kooperationspartner_id = data.get('kooperationspartner_id')
        contract_number = data.get('contract_number')
        contract_date_str = data.get('contract_date')
        
        if not all([customer_id, kooperationspartner_id, contract_number]):
            return jsonify({"error": "Kunden-ID, Kooperationspartner-ID und Vertragsnummer sind erforderlich"}), 400
        
        try:
            # Kunde laden für Ort
            customer = Customer.query.get(customer_id)
            if not customer:
                return jsonify({"error": "Kunde nicht gefunden"}), 404
            
            # Partner validieren
            partner = Kooperationspartner.query.get(kooperationspartner_id)
            if not partner:
                return jsonify({"error": f"Kooperationspartner mit ID {kooperationspartner_id} nicht gefunden. Bitte einen gültigen Partner auswählen."}), 404
            
            # Vertragsdatum parsen (Format: YYYY-MM-DD)
            contract_date = None
            if contract_date_str:
                try:
                    contract_date = datetime.datetime.strptime(contract_date_str, '%Y-%m-%d')
                except ValueError:
                    return jsonify({"error": "Ungültiges Datumsformat. Bitte verwenden Sie das Format YYYY-MM-DD."}), 400
            
            contract = Dienstleistungsvertrag(
                customer_id=customer_id,
                kooperationspartner_id=kooperationspartner_id,
                contract_number=contract_number,
                contract_date=contract_date,  # Datum vom Benutzer oder None (dann wird default verwendet)
                monthly_rate=data.get('monthly_rate'),
                contract_location=customer.city if customer else None,  # Ort vom Kunden übernehmen
                contract_data_json=json.dumps(data.get('contract_data', {}))
            )
            db.session.add(contract)
            db.session.commit()
            return jsonify(contract.to_dict()), 201
        except Exception as e:
            return jsonify({"error": f"Fehler beim Erstellen: {str(e)}"}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>', methods=['GET', 'PUT', 'DELETE'])
def dienstleistungsvertrag_detail(contract_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    
    if request.method == 'GET':
        return jsonify(contract.to_dict())
    
    elif request.method == 'PUT':
        data = request.get_json() or {}
        
        try:
            if 'contract_number' in data:
                contract.contract_number = data['contract_number']
            if 'monthly_rate' in data:
                contract.monthly_rate = data['monthly_rate']
            if 'daily_rate' in data:
                contract.daily_rate = data['daily_rate']
            if 'contract_location' in data:
                contract.contract_location = data['contract_location']
            if 'status' in data:
                contract.status = data['status']
            if 'contract_data' in data:
                contract.contract_data_json = json.dumps(data['contract_data'])
            
            contract.updated_at = datetime.datetime.utcnow()
            db.session.commit()
            return jsonify(contract.to_dict())
        except Exception as e:
            return jsonify({"error": f"Fehler beim Aktualisieren: {str(e)}"}), 500
    
    elif request.method == 'DELETE':
        try:
            db.session.delete(contract)
            db.session.commit()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": f"Fehler beim Löschen: {str(e)}"}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/generate-pdf', methods=['POST'])
def generate_contract_pdf(contract_id):
    """Generiert eine PDF aus dem Dienstleistungsvertrag-Template mit den Daten"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer or not partner:
        return jsonify({"error": "Kunde oder Kooperationspartner nicht gefunden"}), 404
    
    try:
        html_content = _render_dienstleistungsvertrag_html(contract, customer, partner)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Fehler beim Laden des Templates: {str(e)}"}), 500
    
    try:
        pdf_bytes, pdf_filename, _ = _generate_dienstleistungsvertrag_pdf_from_html(contract, html_content)
    except ImportError:
        return jsonify({"error": "weasyprint ist nicht installiert. Bitte installieren Sie es mit: pip install weasyprint"}), 500
    except Exception as e:
        return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
    
    pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')
    return jsonify({
        "success": True,
        "pdf_base64": f"data:application/pdf;base64,{pdf_b64}",
        "filename": pdf_filename
    })

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/preview')
def preview_dienstleistungsvertrag(contract_id):
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    try:
        html_content = _render_dienstleistungsvertrag_html(contract)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Preview konnte nicht erstellt werden: {str(e)}"}), 500
    
    return jsonify({"success": True, "html": html_content})

@app.route('/api/dienstleistungsvertraege/send-preview', methods=['POST'])
def send_contract_preview_new():
    """Sendet eine Preview-Version des Dienstleistungsvertrags mit Platzhalterwerten per E-Mail (ohne existierenden Vertrag)"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    data = request.get_json() or {}
    contract_id = data.get('contract_id')
    
    # Wenn contract_id vorhanden, verwende existierenden Vertrag
    if contract_id:
        contract = Dienstleistungsvertrag.query.get(contract_id)
        if not contract:
            return jsonify({"error": "Vertrag nicht gefunden"}), 404
        customer = Customer.query.get(contract.customer_id)
        coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
        contract_number = contract.contract_number
        contract_date = contract.contract_date
        monthly_rate = contract.monthly_rate
        daily_rate = contract.daily_rate
    else:
        # Standard-Preview mit Beispielwerten (keine Formulardaten nötig)
        customer_id = data.get('customer_id')
        
        if not customer_id:
            return jsonify({"error": "customer_id ist erforderlich"}), 400
        
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({"error": "Kunde nicht gefunden"}), 404
        
        # Standard-Beispielwerte für Vertrag (kein Partner nötig)
        contract_number = f"DLV-PREVIEW-{datetime.datetime.now().strftime('%Y%m%d')}"
        contract_date = datetime.datetime.utcnow()
        monthly_rate = 2500.0  # Standard-Beispielwert
        daily_rate = 83.33  # 2500 / 30
        
        # Erstelle temporäres Contract-Objekt
        from types import SimpleNamespace
        contract = SimpleNamespace(
            contract_number=contract_number,
            contract_date=contract_date,
            monthly_rate=monthly_rate,
            daily_rate=daily_rate,
            custom_html=None
        )
        
        # Erstelle Beispielpartner (immer Standardwerte)
        coop_partner = SimpleNamespace(
            name="Muster Partner GmbH",
            company_name="Muster Partner GmbH",
            email="partner@example.com",
            phone="030 98765432",
            address="Partnerstraße 456",
            street_address="Partnerstraße 456",
            identification_number="DE123456789",
            commercial_register="HRB 12345 B",
            vat_id="DE123456789",
            managing_director="Max Mustermann",
            emergency_phone="030 98765433",
            partner_company="Muster Partner GmbH"
        )
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not customer.email:
        return jsonify({"error": "Kunde hat keine E-Mail-Adresse"}), 400
    
    try:
        # Erstelle Platzhalter-Kunden und Partner für Preview
        from types import SimpleNamespace
        
        preview_customer = SimpleNamespace(
            name="Max Mustermann",
            email=customer.email,  # Echte E-Mail für Versand
            phone="030 12345678",
            mobile_phone="0176 12345678",
            street_address="Musterstraße 123",
            postal_code="12345",
            city="Berlin",
            company=None
        )
        
        preview_partner = SimpleNamespace(
            name="Muster Partner GmbH",
            company_name="Muster Partner GmbH",
            email="partner@example.com",
            phone="030 98765432",
            street_address="Partnerstraße 456",
            postal_code="54321",
            city="Berlin",
            identification_number="DE123456789",
            commercial_register="HRB 12345 B",
            vat_id="DE123456789",
            managing_director="Max Mustermann",
            emergency_phone="030 98765433",
            partner_company="Muster Partner GmbH"
        )
        
        # Rendere HTML mit Platzhalterwerten
        html_content = _render_dienstleistungsvertrag_html(contract, preview_customer, preview_partner)
        
        # Generiere PDF
        try:
            pdf_bytes, pdf_filename, pdf_path = _generate_dienstleistungsvertrag_pdf_from_html(contract, html_content, preview=True)
        except ImportError:
            return jsonify({"error": "weasyprint ist nicht installiert"}), 500
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
        
        # Verwende die bereits generierten PDF-Bytes
        pdf_data = pdf_bytes
        
        # E-Mail mit PDF-Anhang versenden
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders
        
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
        smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
        smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
        
        message = MIMEMultipart('alternative')
        message['Subject'] = f'Dienstleistungsvertrag {contract.contract_number} - Preview'
        message['From'] = f"HelpCare <{smtp_username}>"
        message['To'] = customer.email
        
        # E-Mail-Body
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #f58060;">Dienstleistungsvertrag - Preview</h2>
                <p>Guten Tag {customer.name},</p>
                <p>anbei erhalten Sie eine <strong>Preview-Version</strong> des Dienstleistungsvertrags {contract.contract_number}.</p>
                <p><strong>Hinweis:</strong> Diese Version enthält Platzhalterwerte (z.B. "Max Mustermann") und dient nur zur Ansicht. 
                Bitte beachten Sie, dass dies <strong>keine gültige Unterschrift</strong> erfordert.</p>
                <p>Sie können sich den Vertrag in Ruhe anschauen. Bei Fragen stehen wir Ihnen gerne zur Verfügung.</p>
                <p style="margin-top: 30px;">
                    Mit freundlichen Grüßen,<br>
                    <strong style="color: #f58060;">Ihr HelpCare Team</strong>
                </p>
                <p style="margin-top: 20px; font-size: 12px; color: #666;">
                    HelpCare GmbH | Kurfürstendamm 14 | 10719 Berlin<br>
                    team@helpcare.de | 030 - 232 53 57 100
                </p>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""Guten Tag {customer.name},

anbei erhalten Sie eine Preview-Version des Dienstleistungsvertrags {contract.contract_number}.

Hinweis: Diese Version enthält Platzhalterwerte (z.B. "Max Mustermann") und dient nur zur Ansicht. 
Bitte beachten Sie, dass dies keine gültige Unterschrift erfordert.

Sie können sich den Vertrag in Ruhe anschauen. Bei Fragen stehen wir Ihnen gerne zur Verfügung.

Mit freundlichen Grüßen,
Ihr HelpCare Team

HelpCare GmbH | Kurfürstendamm 14 | 10719 Berlin
team@helpcare.de | 030 - 232 53 57 100"""
        
        text_part = MIMEText(text_body, 'plain', 'utf-8')
        html_part = MIMEText(html_body, 'html', 'utf-8')
        message.attach(text_part)
        message.attach(html_part)
        
        # PDF als Anhang
        attachment = MIMEBase('application', 'pdf')
        attachment.set_payload(pdf_data)
        encoders.encode_base64(attachment)
        attachment.add_header(
            'Content-Disposition',
            f'attachment; filename=Dienstleistungsvertrag_{contract.contract_number}_Preview.pdf'
        )
        message.attach(attachment)
        
        # E-Mail senden
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        
        print(f"✅ Preview-Version erfolgreich per E-Mail an {customer.email} versendet")
        
        return jsonify({
            "success": True,
            "message": f"Preview-Version erfolgreich an {customer.email} gesendet"
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Fehler beim Versenden der Preview: {e}")
        print(f"Traceback: {error_trace}")
        return jsonify({"error": f"Fehler beim Versenden: {str(e)}"}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/send-preview', methods=['POST'])
def send_contract_preview(contract_id):
    """Sendet eine Preview-Version des Dienstleistungsvertrags mit Platzhalterwerten per E-Mail"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not customer.email:
        return jsonify({"error": "Kunde hat keine E-Mail-Adresse"}), 400
    
    try:
        # Erstelle Platzhalter-Kunden und Partner für Preview
        from types import SimpleNamespace
        
        preview_customer = SimpleNamespace(
            name="Max Mustermann",
            email=customer.email,  # Echte E-Mail für Versand
            phone="030 12345678",
            mobile_phone="0176 12345678",
            street_address="Musterstraße 123",
            postal_code="12345",
            city="Berlin",
            company=None
        )
        
        # Erstelle Beispielpartner-Daten (immer Standardwerte für Preview)
        preview_partner = SimpleNamespace(
            name="Muster Partner GmbH",
            company_name="Muster Partner GmbH",
            email="partner@example.com",
            phone="030 98765432",
            street_address="Partnerstraße 456",
            postal_code="54321",
            city="Berlin",
            identification_number="DE123456789",
            commercial_register="HRB 12345 B",
            vat_id="DE123456789",
            managing_director="Max Mustermann",
            emergency_phone="030 98765433",
            partner_company="Muster Partner GmbH"
        )
        
        # Rendere HTML mit Platzhalterwerten
        html_content = _render_dienstleistungsvertrag_html(contract, preview_customer, preview_partner)
        
        # Generiere PDF
        try:
            pdf_bytes, pdf_filename, pdf_path = _generate_dienstleistungsvertrag_pdf_from_html(contract, html_content, preview=True)
        except ImportError:
            return jsonify({"error": "weasyprint ist nicht installiert"}), 500
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
        
        # Verwende die bereits generierten PDF-Bytes
        pdf_data = pdf_bytes
        
        # E-Mail mit PDF-Anhang versenden
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders
        
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
        smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
        smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
        
        message = MIMEMultipart('alternative')
        message['Subject'] = f'Dienstleistungsvertrag {contract.contract_number} - Preview'
        message['From'] = f"HelpCare <{smtp_username}>"
        message['To'] = customer.email
        
        # E-Mail-Body
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #f58060;">Dienstleistungsvertrag - Preview</h2>
                <p>Guten Tag {customer.name},</p>
                <p>anbei erhalten Sie eine <strong>Preview-Version</strong> des Dienstleistungsvertrags {contract.contract_number}.</p>
                <p><strong>Hinweis:</strong> Diese Version enthält Platzhalterwerte (z.B. "Max Mustermann") und dient nur zur Ansicht. 
                Bitte beachten Sie, dass dies <strong>keine gültige Unterschrift</strong> erfordert.</p>
                <p>Sie können sich den Vertrag in Ruhe anschauen. Bei Fragen stehen wir Ihnen gerne zur Verfügung.</p>
                <p style="margin-top: 30px;">
                    Mit freundlichen Grüßen,<br>
                    <strong style="color: #f58060;">Ihr HelpCare Team</strong>
                </p>
                <p style="margin-top: 20px; font-size: 12px; color: #666;">
                    HelpCare GmbH | Kurfürstendamm 14 | 10719 Berlin<br>
                    team@helpcare.de | 030 - 232 53 57 100
                </p>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""Guten Tag {customer.name},

anbei erhalten Sie eine Preview-Version des Dienstleistungsvertrags {contract.contract_number}.

Hinweis: Diese Version enthält Platzhalterwerte (z.B. "Max Mustermann") und dient nur zur Ansicht. 
Bitte beachten Sie, dass dies keine gültige Unterschrift erfordert.

Sie können sich den Vertrag in Ruhe anschauen. Bei Fragen stehen wir Ihnen gerne zur Verfügung.

Mit freundlichen Grüßen,
Ihr HelpCare Team

HelpCare GmbH | Kurfürstendamm 14 | 10719 Berlin
team@helpcare.de | 030 - 232 53 57 100"""
        
        text_part = MIMEText(text_body, 'plain', 'utf-8')
        html_part = MIMEText(html_body, 'html', 'utf-8')
        message.attach(text_part)
        message.attach(html_part)
        
        # PDF als Anhang
        attachment = MIMEBase('application', 'pdf')
        attachment.set_payload(pdf_data)
        encoders.encode_base64(attachment)
        attachment.add_header(
            'Content-Disposition',
            f'attachment; filename=Dienstleistungsvertrag_{contract.contract_number}_Preview.pdf'
        )
        message.attach(attachment)
        
        # E-Mail senden
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        
        print(f"✅ Preview-Version erfolgreich per E-Mail an {customer.email} versendet")
        
        return jsonify({
            "success": True,
            "message": f"Preview-Version erfolgreich an {customer.email} gesendet"
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Fehler beim Versenden der Preview: {e}")
        print(f"Traceback: {error_trace}")
        return jsonify({"error": f"Fehler beim Versenden: {str(e)}"}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/send-for-signature', methods=['POST'])
def send_contract_for_signature(contract_id):
    """Sendet den Dienstleistungsvertrag zur digitalen Signatur per E-Mail (wie in SignaturApp)"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not coop_partner:
        return jsonify({"error": "Kooperationspartner nicht gefunden"}), 404
    
    data = request.get_json(silent=True) or {}
    custom_html = data.get('html_content')
    if custom_html:
        contract.custom_html = custom_html
    
    try:
        html_content = custom_html or _render_dienstleistungsvertrag_html(contract, customer, coop_partner)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Template konnte nicht erstellt werden: {str(e)}"}), 500
    
    pdf_generated = False
    if custom_html or not contract.pdf_filename:
        try:
            _generate_dienstleistungsvertrag_pdf_from_html(contract, html_content)
            pdf_generated = True
        except ImportError:
            return jsonify({"error": "weasyprint ist nicht installiert. Bitte installieren Sie es mit: pip install weasyprint"}), 500
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
    elif custom_html:
        db.session.commit()
    
    # E-Mail an KUNDE senden
    customer_signature_url = f"{request.host_url}api/dienstleistungsvertraege/{contract_id}/sign/customer"
    success, error_msg = send_signature_email(
        contract_id=contract_id,
        customer_email=customer.email,
        customer_name=customer.name,
        contract_type="dienstleistungsvertrag",
        signature_url=customer_signature_url
    )
    
    if not success:
        return jsonify({"error": f"E-Mail-Versand an Kunde Fehler: {error_msg}"}), 500
    
    # E-Mail an PARTNER senden
    partner_signature_url = f"{request.host_url}api/dienstleistungsvertraege/{contract_id}/sign/partner"
    success, error_msg = send_signature_email(
        contract_id=contract_id,
        customer_email=coop_partner.email,
        customer_name=coop_partner.name or coop_partner.company_name,
        contract_type="dienstleistungsvertrag",
        signature_url=partner_signature_url
    )
    
    if not success:
        return jsonify({"error": f"E-Mail-Versand an Partner Fehler: {error_msg}"}), 500
    
    # Status aktualisieren
    contract.status = 'sent'
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Vertrag erfolgreich zur Signatur an beide Parteien gesendet"
    })

@app.route('/docusign-test')
def docusign_test_page():
    """Test-Seite für DocuSign API"""
    return render_template('zoho_test.html')

# Test-Funktion für Zoho Sign (ohne Authentifizierung für Tests)
@app.route('/api/test-zoho-sign', methods=['GET'])
def test_zoho_sign():
    """Test-Funktion für Zoho Sign API"""
    # Temporär ohne Authentifizierung für Tests
    # if "user" not in session:
    #     return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        # Token testen
        access_token = get_zoho_access_token()
        if not access_token:
            return jsonify({"error": "Zoho Access Token fehlt"}), 400
        
        # Einfacher API-Test mit multipart/form-data
        api_url = 'https://sign.zoho.eu/api/v1/requests'
        headers = {
            'Authorization': f'Zoho-oauthtoken {access_token}'
        }
        
        test_data = {}
        
        # Test mit echter Datei
        test_file_content = b"Test PDF Content for Zoho Sign API"
        test_files = {
            'file': ('test.pdf', test_file_content, 'application/pdf')
        }
        
        print(f"🔍 DEBUG: Teste Zoho Sign API...")
        print(f"🔍 DEBUG: URL: {api_url}")
        print(f"🔍 DEBUG: Headers: {headers}")
        print(f"🔍 DEBUG: Data: {test_data}")
        print(f"🔍 DEBUG: Files: test.pdf ({len(test_file_content)} bytes)")
        
        # Test mit Datei-Upload
        response = requests.post(api_url, headers=headers, data=test_data, files=test_files, timeout=30)
        
        print(f"🔍 DEBUG: Response Status: {response.status_code}")
        print(f"🔍 DEBUG: Response Text: {response.text}")
        
        return jsonify({
            "status": response.status_code,
            "response": response.text,
            "success": response.status_code < 300,
            "test_data": test_data
        })
        
    except Exception as e:
        return jsonify({"error": f"Test fehlgeschlagen: {str(e)}"}), 500

# DocuSign Konfiguration (als Fallback)
DOCUSIGN_CONFIG = {
    'base_url': 'https://demo.docusign.net/restapi',  # Sandbox URL
    'client_id': '122f860d-a239-4b1f-a19d-e121cc2ea4d3',
    'client_secret': 'aeb3de31-5ceb-416f-a206-545c4ce9df1e',
    'private_key': '',  # Muss noch generiert werden
    'user_id': 'f30c4cc4-6f8a-4d87-9fd6-157d26a3aece',
    'account_id': 'a7f2e024-efbc-4ba5-ada3-c2961f78b7e3',
    'access_token': 'eyJ0eXAiOiJNVCIsImFsZyI6IlJTMjU2Iiwia2lkIjoiNjgxODVmZjEtNGU1MS00Y2U5LWFmMWMtNjg5ODEyMjAzMzE3In0.AQsAAAABAAUABwAAzYjGmBPeSAgAAA2s1NsT3kgCAMRMDPOKb4dNn9YVfSajrs4VAAEAAAAYAAEAAAAFAAAADQAkAAAAMTIyZjg2MGQtYTIzOS00YjFmLWExOWQtZTEyMWNjMmVhNGQzIgAkAAAAMTIyZjg2MGQtYTIzOS00YjFmLWExOWQtZTEyMWNjMmVhNGQzEgABAAAACwAAAGludGVyYWN0aXZlMACANvDFmBPeSDcAro1EaYGAwEu2WuRzG7Z-Zg.aeRB-j6zDQpD1PS5UmjhtA43YQSZa27rMA4Hxr0DiHIaYWOe7-dGZMW3RV_8_iJfQ_2MdKR9ocjcCuWl1P655aNyXrLOVIjFQ3HYoik9dkuN1n04NRmsM4gmaYVejl-rNaDsgAuvYQb7OoMOyX5uG99E69wp_ooKtVLhHSkjUfDFtNAIRKyI-_nMlS53nZb7ZjU4SgrgNPZKoJeFWZ14SFSjQASHoT-tV0oG8CaAFgdG6JMTM0pnmaOPc-5FSxoGNk02hN9AgQ0CX2oCnEujIg-WsqBhV5jYnc935klA0htgkHGkjzjmiF9xq9TW2dpuyKst1utxs3GIrclsZzckHA'
}

def get_docusign_token():
    """DocuSign Access Token abrufen"""
    try:
        # Prüfe ob Token in Session vorhanden ist
        if 'docusign_token' in session:
            return session['docusign_token']
        
        # Verwende konfigurierten Token
        if DOCUSIGN_CONFIG.get('access_token'):
            return DOCUSIGN_CONFIG['access_token']
        
        # Falls kein Token vorhanden, zeige Setup-Anleitung
        print("⚠️ DocuSign: Kein Access Token vorhanden")
        print("📋 DocuSign Setup-Anleitung:")
        print("1. Gehen Sie zu: http://localhost:8000/auth/docusign")
        print("2. Autorieren Sie die Anwendung")
        print("3. Sie werden zurückgeleitet und erhalten einen Token")
        
        return None
        
    except Exception as e:
        print(f"❌ DocuSign Token-Fehler: {str(e)}")
        return None

# DocuSign OAuth Flow (für zukünftige Implementierung)
@app.route('/auth/docusign')
def docusign_auth():
    """DocuSign OAuth Authorization"""
    auth_url = f"https://account-d.docusign.com/oauth/auth?response_type=code&scope=signature&client_id={DOCUSIGN_CONFIG['client_id']}&redirect_uri=http://localhost:8000/auth/docusign/callback"
    return redirect(auth_url)

@app.route('/auth/docusign/callback')
def docusign_callback():
    """DocuSign OAuth Callback"""
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization Code nicht erhalten"}), 400
    
    try:
        # Token gegen Authorization Code tauschen
        token_url = "https://account-d.docusign.com/oauth/token"
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': DOCUSIGN_CONFIG['client_id'],
            'client_secret': DOCUSIGN_CONFIG['client_secret'],
            'redirect_uri': 'http://localhost:8000/auth/docusign/callback'
        }
        
        response = requests.post(token_url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            # Token in Session speichern
            session['docusign_token'] = token_data.get('access_token')
            session['docusign_refresh_token'] = token_data.get('refresh_token')
            
            return jsonify({
                "success": True,
                "message": "DocuSign erfolgreich authentifiziert!",
                "access_token": token_data.get('access_token')
            })
        else:
            return jsonify({"error": f"Token-Austausch fehlgeschlagen: {response.text}"}), 400
            
    except Exception as e:
        return jsonify({"error": f"OAuth Callback Fehler: {str(e)}"}), 500

def create_docusign_envelope(contract_id, customer_email, customer_name, contract_type="dienstleistungsvertrag"):
    """DocuSign Envelope erstellen mit REST API"""
    try:
        # Access Token abrufen
        access_token = get_docusign_token()
        if not access_token:
            return None, "DocuSign Token konnte nicht abgerufen werden"
        
        # Vertrag laden basierend auf Typ
        if contract_type == "kooperationsvertrag":
            contract = Kooperationsvertrag.query.get(contract_id)
            anchor_string = "Unterschrift Partner"
            contract_type_name = "Kooperationsvertrag"
        else:
            contract = Dienstleistungsvertrag.query.get(contract_id)
            anchor_string = "Unterschrift Auftraggeber"
            contract_type_name = "Dienstleistungsvertrag"
        
        if not contract:
            return None, "Vertrag nicht gefunden"
        
        if not contract.pdf_filename:
            return None, "PDF nicht gefunden"
        
        # PDF laden
        pdf_path = os.path.join(UPLOAD_FOLDER, contract.pdf_filename)
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        # Envelope JSON erstellen
        envelope_data = {
            "emailSubject": f"{contract_type_name} {contract.contract_number} zur Unterschrift",
            "documents": [
                {
                    "documentBase64": base64.b64encode(pdf_bytes).decode('utf-8'),
                    "name": f"{contract_type_name} {contract.contract_number}",
                    "fileExtension": "pdf",
                    "documentId": "1"
                }
            ],
            "recipients": {
                "signers": [
                    {
                        "email": customer_email,
                        "name": customer_name,
                        "recipientId": "1",
                        "routingOrder": "1",
                        "tabs": {
                            "signHereTabs": [
                                {
                                    "documentId": "1",
                                    "pageNumber": "1",
                                    "recipientId": "1",
                                    "xPosition": "200",
                                    "yPosition": "600",
                                    "tabLabel": "SignHereTab",
                                    "anchorString": anchor_string,
                                    "anchorXOffset": "0",
                                    "anchorYOffset": "-20"
                                }
                            ]
                        }
                    }
                ]
            },
            "status": "sent"
        }
        
        # Envelope erstellen
        url = f"{DOCUSIGN_CONFIG['base_url']}/v2.1/accounts/{DOCUSIGN_CONFIG['account_id']}/envelopes"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, json=envelope_data, headers=headers)
        
        if response.status_code == 201:
            result = response.json()
            return result.get('envelopeId'), None
        else:
            return None, f"DocuSign API Fehler: {response.status_code} - {response.text}"
        
    except Exception as e:
        print(f"❌ DocuSign Envelope-Fehler: {str(e)}")
        return None, str(e)

def send_signature_email_smtp(contract_id, customer_email, customer_name, contract_type="dienstleistungsvertrag", signature_url=None):
    """Sendet E-Mail mit Signatur-Link über SMTP (Ionos/Outlook)"""
    try:
        # Vertrag laden basierend auf Typ
        if contract_type == "kooperationsvertrag":
            contract = Kooperationsvertrag.query.get(contract_id)
            contract_type_name = "Kooperationsvertrag"
        else:
            contract = Dienstleistungsvertrag.query.get(contract_id)
            contract_type_name = "Dienstleistungsvertrag"
        
        if not contract:
            return False, "Vertrag nicht gefunden"
        
        # SMTP-Konfiguration aus Umgebungsvariablen
        # Unterstützte Provider:
        # - Ionos Exchange: smtp.exchange.ionos.eu (Port 587, TLS) - für Microsoft Exchange über Ionos
        # - Ionos: smtp.ionos.de (Port 587, STARTTLS) oder smtp.ionos.de (Port 465, SSL)
        # - Outlook/Office 365: smtp.office365.com (Port 587, TLS)
        # - Gmail: smtp.gmail.com (Port 587, TLS) - benötigt App-Passwort
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')  # Ionos SMTP-Server
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
        smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
        smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
        
        if not smtp_username or not smtp_password:
            return False, "SMTP-Credentials nicht konfiguriert. Bitte SMTP_USERNAME und SMTP_PASSWORD in .env setzen."
        
        # Signatur-URL generieren (falls nicht angegeben)
        if not signature_url:
            if contract_type == "kooperationsvertrag":
                signature_url = f"{request.host_url}api/kooperationsvertraege/{contract_id}/sign"
            else:
                signature_url = f"{request.host_url}api/{contract_type}s/{contract_id}/sign"
        
        # HTML-E-Mail mit schönem Design erstellen (gleicher Inhalt wie Gmail-Version)
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@300;400;500;600;700&display=swap');
    </style>
</head>
<body style="margin: 0; padding: 0; font-family: 'Quicksand', sans-serif; background-color: #fef6f2;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #fef6f2; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-radius: 15px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1); position: relative;">
                    <!-- Header mit Logo -->
                    <tr>
                        <td align="center" style="padding: 50px 30px; background: linear-gradient(135deg, #f58060 0%, #ff9d6e 100%);">
                            <h1 style="color: #ffffff; font-size: 28px; font-weight: 700; margin: 0;">HelpCare</h1>
                            <p style="margin: 20px 0 0 0; color: #ffffff; font-size: 18px; font-weight: 500; opacity: 0.95;">Digitale Vertragsunterschriften</p>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 50px 40px;">
                            <h2 style="color: #f58060; font-size: 26px; font-weight: 600; margin: 0 0 20px 0;">Guten Tag {customer_name},</h2>
                            <p style="color: #333; line-height: 1.8; margin: 0 0 20px 0; font-size: 16px;">
                                anbei erhalten Sie Ihren {contract_type_name} zur elektronischen Unterschrift.
                            </p>
                            <p style="color: #333; line-height: 1.8; margin: 0 0 35px 0; font-size: 16px;">
                                Bitte klicken Sie auf den Button unten, um den Vertrag zu signieren:
                            </p>
                            
                            <!-- CTA Button -->
                            <div style="text-align: center; margin: 45px 0;">
                                <a href="{signature_url}" style="background-color: #f58060; color: #ffffff; padding: 20px 45px; text-decoration: none; border-radius: 12px; display: inline-block; font-weight: 600; font-size: 18px; box-shadow: 0 6px 20px rgba(247, 128, 96, 0.35); letter-spacing: 0.5px;">
                                    DOKUMENT EINSEHEN
                                </a>
                            </div>
                            
                            <!-- Vertragsdetails -->
                            <div style="background-color: #fef6f2; padding: 25px; border-radius: 10px; margin: 40px 0; border-left: 4px solid #f58060;">
                                <p style="margin: 0 0 8px 0; font-size: 14px; color: #666; font-weight: 500;">Vertragsdetails:</p>
                                <p style="margin: 0 0 5px 0; font-size: 13px; color: #333;">
                                    <strong>Vertragsnummer:</strong> {contract.contract_number}
                                </p>
                                <p style="margin: 5px 0 0 0; font-size: 13px; color: #333;">
                                    <strong>Typ:</strong> {contract_type_name}
                                </p>
                            </div>
                            
                            <!-- Fallback Link -->
                            <div style="background-color: #fef6f2; padding: 25px; border-radius: 10px; margin: 40px 0; border-left: 4px solid #f58060;">
                                <p style="margin: 0 0 12px 0; font-size: 14px; color: #666; font-weight: 500;">Falls der Button nicht funktioniert:</p>
                                <p style="margin: 0; font-size: 13px; color: #f58060; word-break: break-all; font-family: 'Courier New', monospace; background-color: #ffffff; padding: 10px; border-radius: 5px;">
                                    {signature_url}
                                </p>
                            </div>
                            
                            <p style="color: #666; line-height: 1.6; margin: 35px 0 0 0; font-size: 14px;">
                                Bei Fragen sind wir jederzeit für Sie erreichbar.<br>
                                <a href="mailto:team@helpcare.de" style="color: #f58060; font-weight: 600; text-decoration: none;">team@helpcare.de</a> | 
                                <span style="color: #f58060; font-weight: 600;">030 - 232 53 57 100</span>
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 40px; background-color: #fef6f2; text-align: center; border-top: 1px solid #fdeae1;">
                            <p style="margin: 0 0 15px 0; color: #666; font-size: 15px; line-height: 1.6;">
                                Mit freundlichen Grüßen,<br>
                                <strong style="color: #f58060; font-weight: 600; font-size: 16px;">Ihr HelpCare Team</strong>
                            </p>
                            <div style="margin: 25px 0; padding-top: 20px; border-top: 1px solid #fdeae1;">
                                <p style="margin: 0 0 8px 0; font-size: 12px; color: #999;">
                                    HelpCare GmbH | Kurfürstendamm 14 | 10719 Berlin
                                </p>
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""
        
        # E-Mail erstellen
        message = MIMEMultipart('alternative')
        message['Subject'] = f"{contract_type_name} {contract.contract_number} zur Unterschrift"
        message['From'] = f"HelpCare <{smtp_username}>"
        message['To'] = customer_email
        
        # HTML und Plain-Text Versionen
        text_part = MIMEText(f"""Guten Tag {customer_name},

anbei erhalten Sie Ihren {contract_type_name} zur elektronischen Unterschrift.

Bitte klicken Sie auf den folgenden Link, um den Vertrag zu signieren:
{signature_url}

Vertragsdetails:
- Vertragsnummer: {contract.contract_number}
- Typ: {contract_type_name}

Bei Fragen sind wir jederzeit für Sie erreichbar.
team@helpcare.de | 030 - 232 53 57 100

Mit freundlichen Grüßen,
Ihr HelpCare Team

HelpCare GmbH | Kurfürstendamm 14 | 10719 Berlin""", 'plain', 'utf-8')
        html_part = MIMEText(html_body, 'html', 'utf-8')
        
        message.attach(text_part)
        message.attach(html_part)
        
        # SMTP-Verbindung aufbauen und E-Mail senden
        if smtp_use_ssl:
            # SSL-Verbindung (Port 465)
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            # STARTTLS-Verbindung (Port 587)
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        
        print(f"✅ E-Mail erfolgreich über SMTP versendet an {customer_email}")
        
        return True, None
        
    except smtplib.SMTPAuthenticationError as e:
        error_str = str(e)
        print(f"❌ SMTP-Authentifizierungsfehler: {error_str}")
        return False, f"SMTP-Authentifizierung fehlgeschlagen. Bitte SMTP-Credentials (Benutzername/Passwort) überprüfen. Server: {smtp_server}:{smtp_port}"
    except smtplib.SMTPConnectError as e:
        error_str = str(e)
        print(f"❌ SMTP-Verbindungsfehler: {error_str}")
        return False, f"SMTP-Verbindung fehlgeschlagen. Bitte SMTP-Server und Port überprüfen. Versucht: {smtp_server}:{smtp_port}"
    except smtplib.SMTPDataError as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore')
        print(f"❌ SMTP-Datenfehler: {error_str} (Code: {error_code})")
        # Rate-Limit-Erkennung
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return False, f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"
        return False, f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"
    except smtplib.SMTPException as e:
        error_str = str(e)
        error_code = getattr(e, 'smtp_code', None)
        error_msg = getattr(e, 'smtp_error', b'').decode('utf-8', errors='ignore') if hasattr(e, 'smtp_error') else error_str
        print(f"❌ SMTP-Fehler: {error_str} (Code: {error_code})")
        # Rate-Limit-Erkennung auch hier
        if error_code == 421 or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            return False, f"SMTP-Rate-Limit erreicht: Zu viele E-Mails in kurzer Zeit gesendet. Bitte warten Sie einige Minuten und versuchen Sie es erneut. (Fehler: {error_msg})"
        return False, f"SMTP-Versand fehlgeschlagen: {error_msg or error_str}"
    except Exception as e:
        error_str = str(e)
        print(f"❌ E-Mail-Versand Fehler: {error_str}")
        return False, f"E-Mail-Versand fehlgeschlagen: {error_str}"

def send_signature_email(contract_id, customer_email, customer_name, contract_type="dienstleistungsvertrag", signature_url=None):
    """Sendet E-Mail mit Signatur-Link im schönen HTML-Design über SMTP (Ionos/Outlook)"""
    # Verwende SMTP (Ionos/Outlook)
    smtp_result, smtp_error = send_signature_email_smtp(contract_id, customer_email, customer_name, contract_type, signature_url)
    if smtp_result:
        return smtp_result, smtp_error
    # Falls SMTP fehlschlägt, gib den SMTP-Fehler zurück
    print(f"❌ SMTP-Versand fehlgeschlagen: {smtp_error}")
    return False, f"SMTP-Versand fehlgeschlagen: {smtp_error}"

def send_signed_contract_email(contract):
    """Sendet das unterschriebene Dokument per E-Mail an Kunde und Kooperationspartner"""
    try:
        if not contract.signed_pdf_filename:
            print("⚠️ Unterschriebenes Dokument nicht gefunden, E-Mail wird nicht versendet")
            return
        
        # Lade Kunde und Partner
        customer = Customer.query.get(contract.customer_id)
        partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
        
        if not customer or not partner:
            print("⚠️ Kunde oder Partner nicht gefunden, E-Mail wird nicht versendet")
            return
        
        # Liste der Empfänger
        recipients = []
        if customer.email:
            recipients.append((customer.email, customer.name))
        if partner.email:
            recipients.append((partner.email, partner.name))
        
        if not recipients:
            print("⚠️ Keine E-Mail-Adressen gefunden, E-Mail wird nicht versendet")
            return
        
        # SMTP-Konfiguration
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
        smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
        smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'
        
        if not smtp_username or not smtp_password:
            print("⚠️ SMTP-Credentials nicht konfiguriert, E-Mail wird nicht versendet")
            return
        
        # Lade das unterschriebene PDF
        pdf_path = os.path.join(UPLOAD_FOLDER, contract.signed_pdf_filename)
        if not os.path.exists(pdf_path):
            print(f"⚠️ PDF-Datei nicht gefunden: {pdf_path}")
            return
        
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()
        
        # Signatur abrufen
        signature = get_signature_for_email(smtp_username)
        if not signature and smtp_username != 'team@helpcare.de':
            print(f"⚠️ Signatur nicht für {smtp_username} gefunden, versuche team@helpcare.de")
            signature = get_signature_for_email('team@helpcare.de')
        print(f"🔍 Signatur-Abruf für {smtp_username}: {'✅ gefunden' if signature else '❌ nicht gefunden'}")
        newline = '\n'
        
        # Versende E-Mail an jeden Empfänger
        for recipient_email, recipient_name in recipients:
            try:
                message = MIMEMultipart('mixed')
                message['Subject'] = f'Unterschriebener Dienstleistungsvertrag - {contract.contract_number}'
                message['From'] = f"HelpCare <{smtp_username}>"
                message['To'] = recipient_email
                
                # Einfacher E-Mail-Text wie gewünscht
                email_body = f"""Guten Tag {recipient_name},

anbei erhalten Sie den unterschriebenen Dienstleistungsvertrag.

Viele Grüße"""
                
                # Body für Plain-Text und HTML vorbereiten
                body_text_final = email_body
                # Für HTML: Zeilenumbrüche zu <br> konvertieren, aber NACH dem Escaping
                body_html_escaped = email_body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                body_html_final = body_html_escaped.replace(newline, '<br>')
                
                # Signatur hinzufügen, wenn vorhanden
                if signature:
                    print(f"✅ Füge Signatur hinzu (Länge: {len(signature)} Zeichen)")
                    # Für Plain-Text: HTML-Tags entfernen
                    import re
                    from html import unescape
                    signature_text = re.sub(r'<[^>]+>', '', signature)
                    signature_text = unescape(signature_text)
                    signature_text = signature_text.replace(newline, ' ').strip()
                    body_text_final = f"{email_body}{newline}{newline}{signature_text}"
                    # Für HTML: Signatur nach dem Escaping hinzufügen (Signatur ist bereits HTML)
                    body_html_final = f"{body_html_final}<br><br>{signature}"
                    print(f"✅ HTML-Body mit Signatur erstellt (Gesamtlänge: {len(body_html_final)} Zeichen)")
                else:
                    print(f"⚠️ Keine Signatur vorhanden, verwende nur Body")
                    # body_html_final ist bereits korrekt gesetzt
                
                body_html_final = (
                    "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
                    body_html_final +
                    "</div>"
                )
                
                # Text und HTML Versionen
                text_part = MIMEText(body_text_final, 'plain', 'utf-8')
                html_part = MIMEText(body_html_final, 'html', 'utf-8')
                
                # Alternative part (text + HTML)
                alternative = MIMEMultipart('alternative')
                alternative.attach(text_part)
                alternative.attach(html_part)
                message.attach(alternative)
                
                # PDF als Anhang
                attachment = MIMEBase('application', 'pdf')
                attachment.set_payload(pdf_data)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition',
                    f'attachment; filename= Dienstleistungsvertrag_{contract.contract_number}_unterschrieben.pdf'
                )
                message.attach(attachment)
                
                # SMTP-Versand
                if smtp_use_ssl:
                    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                        server.login(smtp_username, smtp_password)
                        server.send_message(message)
                else:
                    with smtplib.SMTP(smtp_server, smtp_port) as server:
                        if smtp_use_tls:
                            server.starttls()
                        server.login(smtp_username, smtp_password)
                        server.send_message(message)
                
                print(f"✅ E-Mail mit unterschriebenem Vertrag erfolgreich an {recipient_email} versendet!")
            except Exception as e:
                print(f"⚠️ Fehler beim Versenden der E-Mail an {recipient_email}: {e}")
    except Exception as e:
        print(f"⚠️ Fehler beim Versenden der E-Mail mit unterschriebenem Vertrag: {e}")
    

def _notify_other_partners_on_contract_completed(contract: Dienstleistungsvertrag):
    """
    Benachrichtigt alle Kooperationspartner, die den Bedarfsfragebogen für diesen Kunden erhalten haben,
    sobald ein Dienstleistungsvertrag vollständig unterzeichnet ('completed') ist.
    Der ausgewählte Vertragspartner selbst wird NICHT benachrichtigt.
    Mehrfachversand wird über ein Flag in contract_data_json verhindert.
    """
    try:
        # Sicherstellen, dass nur bei 'completed' Benachrichtigungen verschickt werden
        if not contract or contract.status != 'completed':
            return

        # Vertragsdaten-JSON laden/initialisieren
        try:
            contract_data = json.loads(contract.contract_data_json or '{}')
        except Exception:
            contract_data = {}

        # Wurde bereits benachrichtigt? -> dann nichts tun
        if contract_data.get('partners_notified_on_completion'):
            return

        customer = Customer.query.get(contract.customer_id)
        winner_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)

        if not customer:
            return

        # Fragebogen-Daten des Kunden laden
        try:
            questionnaire_data = json.loads(customer.questionnaire_data_json or '{}')
        except Exception:
            questionnaire_data = {}

        bcc_recipients = questionnaire_data.get('bcc_recipients') or []
        if not bcc_recipients:
            # Keine bekannten Empfänger des Bedarfsfragebogens – nichts zu tun
            return

        # Alle Partner, die den Fragebogen erhalten haben
        partners = Kooperationspartner.query.filter(Kooperationspartner.email.in_(bcc_recipients)).all()
        if not partners:
            return

        winner_email = winner_partner.email if winner_partner and winner_partner.email else None
        recipient_emails = [
            p.email for p in partners
            if p.email and p.email != winner_email
        ]

        if not recipient_emails:
            return

        # SMTP-Konfiguration wiederverwenden
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.ionos.de')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_username = os.getenv('SMTP_USERNAME', 'kontakt@helpcare.de')
        smtp_password = os.getenv('SMTP_PASSWORD', '!dashboardE1#')
        smtp_use_tls = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'False').lower() == 'true'

        if not smtp_username or not smtp_password:
            print("⚠️ SMTP-Credentials nicht konfiguriert – Partner-Benachrichtigungen werden übersprungen.")
            return

        subject = f"Auftrag besetzt – Kunden-ID: {customer.id}"
        body_text = (
            "Sehr geehrte Damen und Herren,\n\n"
            f"der Auftrag mit der Kunden-ID: {customer.id} wurde soeben besetzt.\n\n"
            "Viele Grüße\n"
            "Ihr HelpCare-Team"
        )
        body_html = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">"
            "Sehr geehrte Damen und Herren,<br><br>"
            f"der Auftrag mit der Kunden-ID: {customer.id} wurde soeben besetzt.<br><br>"
            "Viele Grüße<br>"
            "Ihr HelpCare-Team"
            "</div>"
        )

        # Optional: Signatur für SMTP-Absender anhängen
        try:
            # Versuche zuerst smtp_username, dann 'team@helpcare.de' als Fallback
            signature = get_signature_for_email(smtp_username)
            if not signature and smtp_username != 'team@helpcare.de':
                print(f"⚠️ Signatur nicht für {smtp_username} gefunden, versuche team@helpcare.de")
                signature = get_signature_for_email('team@helpcare.de')
        except Exception:
            signature = None

        if signature:
            import re
            from html import unescape
            newline = '\n'
            signature_text = re.sub(r'<[^>]+>', '', signature)
            signature_text = unescape(signature_text)
            signature_text = signature_text.replace(newline, ' ').strip()
            body_text = f"{body_text}\n\n{signature_text}"
            body_html = f"{body_html}<br><br>{signature}"

        # Eine E-Mail pro Partner schicken (klare Zuordnung beim Partner)
        for email_addr in recipient_emails:
            try:
                message = MIMEMultipart('alternative')
                message['Subject'] = subject
                message['From'] = f"HelpCare <{smtp_username}>"
                message['To'] = email_addr

                text_part = MIMEText(body_text, 'plain', 'utf-8')
                html_part = MIMEText(body_html, 'html', 'utf-8')
                message.attach(text_part)
                message.attach(html_part)

                if smtp_use_ssl:
                    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                        server.login(smtp_username, smtp_password)
                        server.send_message(message)
                else:
                    with smtplib.SMTP(smtp_server, smtp_port) as server:
                        if smtp_use_tls:
                            server.starttls()
                        server.login(smtp_username, smtp_password)
                        server.send_message(message)

                print(f"✅ Benachrichtigungs-E-Mail zum besetzten Auftrag an {email_addr} gesendet.")
            except Exception as e:
                print(f"❌ Fehler beim Senden der Benachrichtigungs-E-Mail an {email_addr}: {e}")

        # Flag setzen, damit nicht mehrfach benachrichtigt wird
        contract_data['partners_notified_on_completion'] = True
        contract.contract_data_json = json.dumps(contract_data)
    except Exception as e:
        # Fehler dürfen den eigentlichen Signatur-Flow nicht blockieren
        print(f"⚠️ Fehler bei Partner-Benachrichtigung nach Vertragsabschluss: {e}")
    

# Manuelle Status-Aktualisierung
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/check-status', methods=['POST'])
def check_dienstleistungsvertrag_status(contract_id):
    """Prüft den Status eines Dienstleistungsvertrags"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    
    # Prüfe ob beide unterschrieben haben
    if contract.status not in ['completed', 'sent', 'customer_signed', 'partner_signed']:
        # Status basierend auf Signaturen aktualisieren
        if contract.signature_data and contract.partner_signature_data:
            old_status = contract.status
            contract.status = 'completed'
            # Erstelle finales PDF mit BEIDEN Signaturen falls noch nicht vorhanden
            if not contract.signed_pdf_filename:
                signed_pdf_filename = create_signed_contract_pdf_complete(contract)
                if signed_pdf_filename:
                    contract.signed_pdf_filename = signed_pdf_filename
            # Partner über den besetzten Auftrag informieren
            _notify_other_partners_on_contract_completed(contract)
            db.session.commit()
            # Versende unterschriebenes Dokument per E-Mail, wenn Status gerade auf completed gesetzt wurde
            if old_status != 'completed':
                send_signed_contract_email(contract)
        elif contract.signature_data:
            contract.status = 'customer_signed'
            db.session.commit()
        elif contract.partner_signature_data:
            contract.status = 'partner_signed'
            db.session.commit()
    
    # Einfache Status-Rückgabe
    return jsonify({
        "success": True,
        "status": contract.status,
        "message": f"Status: {contract.status}"
    })

# E-Mail Signatur-Versand Integration
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/send-docuseal', methods=['POST'])
def send_docuseal_signature(contract_id):
    """Dienstleistungsvertrag zur Signatur per E-Mail senden"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not coop_partner:
        return jsonify({"error": "Kooperationspartner nicht gefunden"}), 404
    
    data = request.get_json(silent=True) or {}
    custom_html = data.get('html_content')
    if custom_html:
        contract.custom_html = custom_html
    
    try:
        html_content = custom_html or _render_dienstleistungsvertrag_html(contract, customer, coop_partner)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Template konnte nicht erstellt werden: {str(e)}"}), 500
    
    pdf_generated = False
    if custom_html or not contract.pdf_filename:
        try:
            _generate_dienstleistungsvertrag_pdf_from_html(contract, html_content)
            pdf_generated = True
        except ImportError:
            return jsonify({"error": "weasyprint ist nicht installiert. Bitte installieren Sie es mit: pip install weasyprint"}), 500
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
    elif custom_html:
        db.session.commit()
    
    # E-Mail an KUNDE senden
    customer_signature_url = f"{request.host_url}api/dienstleistungsvertraege/{contract_id}/sign/customer"
    success, error_msg = send_signature_email(
        contract_id=contract_id,
        customer_email=customer.email,
        customer_name=customer.name,
        contract_type="dienstleistungsvertrag",
        signature_url=customer_signature_url
    )
    
    if not success:
        return jsonify({"error": f"E-Mail-Versand an Kunde Fehler: {error_msg}"}), 500
    
    # E-Mail an PARTNER senden
    partner_signature_url = f"{request.host_url}api/dienstleistungsvertraege/{contract_id}/sign/partner"
    success, error_msg = send_signature_email(
        contract_id=contract_id,
        customer_email=coop_partner.email,
        customer_name=coop_partner.name or coop_partner.company_name,
        contract_type="dienstleistungsvertrag",
        signature_url=partner_signature_url
    )
    
    if not success:
        return jsonify({"error": f"E-Mail-Versand an Partner Fehler: {error_msg}"}), 500
    
    # Status aktualisieren
    contract.status = 'sent'
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Vertrag erfolgreich zur Signatur an beide Parteien gesendet"
    })

# DocuSign Webhook
@app.route('/webhook/docusign', methods=['POST'])
def docusign_webhook():
    """Webhook für DocuSign Status-Updates"""
    try:
        data = request.get_json()
        print(f"📦 DocuSign Webhook: {json.dumps(data, indent=2)}")
        
        # Envelope ID extrahieren
        envelope_id = data.get('data', {}).get('envelopeId')
        status = data.get('data', {}).get('status')
        
        if envelope_id and status:
            # Vertrag finden - sowohl Dienstleistungsvertrag als auch Kooperationsvertrag
            contract = Dienstleistungsvertrag.query.filter_by(zoho_request_id=envelope_id).first()
            contract_type = "dienstleistungsvertrag"
            
            if not contract:
                contract = Kooperationsvertrag.query.filter_by(envelope_id=envelope_id).first()
                contract_type = "kooperationsvertrag"
            
            if contract:
                # Status aktualisieren
                if status == 'completed':
                    contract.status = 'signed'
                    
                    # Unterschriebenes Dokument herunterladen
                    try:
                        signed_pdf_filename = download_signed_document(envelope_id, contract.contract_number, contract_type)
                        if signed_pdf_filename:
                            contract.signed_pdf_filename = signed_pdf_filename
                            print(f"✅ Unterschriebenes Dokument heruntergeladen ({contract_type}): {signed_pdf_filename}")
                    except Exception as e:
                        print(f"⚠️ Fehler beim Herunterladen des unterschriebenen Dokuments ({contract_type}): {str(e)}")
                        
                elif status == 'declined':
                    contract.status = 'declined'
                elif status == 'expired':
                    contract.status = 'expired'
                
                db.session.commit()
                print(f"✅ {contract_type.title()} {contract.id} Status aktualisiert: {status}")
        
        return jsonify({"success": True})
        
    except Exception as e:
        print(f"❌ DocuSign Webhook-Fehler: {str(e)}")
        return jsonify({"error": str(e)}), 500

def download_signed_document(envelope_id, contract_number, contract_type="dienstleistungsvertrag"):
    """Unterschriebenes Dokument von DocuSign herunterladen"""
    try:
        # Token direkt aus der Konfiguration verwenden (für Webhook/Background-Tasks)
        access_token = DOCUSIGN_CONFIG.get('access_token')
        if not access_token:
            # Fallback: Versuche get_docusign_token() (funktioniert nur im Request-Context)
            try:
                access_token = get_docusign_token()
            except:
                access_token = None
        
        if not access_token:
            print("❌ Kein DocuSign Token verfügbar")
            return None
        
        # Zuerst Dokumentenliste abrufen
        documents_url = f"{DOCUSIGN_CONFIG['base_url']}/v2.1/accounts/{DOCUSIGN_CONFIG['account_id']}/envelopes/{envelope_id}/documents"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        documents_response = requests.get(documents_url, headers=headers)
        
        if documents_response.status_code == 200:
            documents_data = documents_response.json()
            print(f"📄 Verfügbare Dokumente: {documents_data}")
            
            # Erstes Dokument herunterladen
            if documents_data.get('envelopeDocuments'):
                document_id = documents_data['envelopeDocuments'][0]['documentId']
                
                # Dokument als PDF herunterladen
                download_url = f"{DOCUSIGN_CONFIG['base_url']}/v2.1/accounts/{DOCUSIGN_CONFIG['account_id']}/envelopes/{envelope_id}/documents/{document_id}"
                download_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/pdf"
                }
                
                pdf_response = requests.get(download_url, headers=download_headers)
                
                if pdf_response.status_code == 200:
                    # PDF speichern
                    pdf_filename = f"{contract_type}_unterschrieben_{contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
                    
                    with open(pdf_path, 'wb') as f:
                        f.write(pdf_response.content)
                    
                    print(f"✅ Unterschriebenes Dokument gespeichert: {pdf_filename}")
                    return pdf_filename
                else:
                    print(f"❌ PDF-Download Fehler: {pdf_response.status_code} - {pdf_response.text}")
                    return None
            else:
                print("❌ Keine Dokumente im Envelope gefunden")
                return None
        else:
            print(f"❌ Dokumentenliste Fehler: {documents_response.status_code} - {documents_response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Fehler beim Herunterladen des unterschriebenen Dokuments: {str(e)}")
        return None

# DocuSign Test-Funktion (ohne Authentifizierung für Tests)
@app.route('/api/test-docusign', methods=['GET'])
def test_docusign():
    """Test-Funktion für DocuSign API"""
    # Temporär ohne Authentifizierung für Tests
    # if "user" not in session:
    #     return jsonify({"error": "Nicht eingeloggt"}), 401
    
    try:
        # Token testen
        access_token = get_docusign_token()
        if not access_token:
            return jsonify({"error": "DocuSign Token konnte nicht abgerufen werden"}), 400
        
        return jsonify({
            "success": True,
            "message": "DocuSign API-Verbindung erfolgreich",
            "token_length": len(access_token),
            "token_preview": access_token[:20] + "..." if len(access_token) > 20 else access_token
        })
        
    except Exception as e:
        return jsonify({"error": f"DocuSign Test fehlgeschlagen: {str(e)}"}), 500

# Alternative: PDF mit Signatur-Feldern und E-Mail-Versand
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/send-for-signature-alt', methods=['POST'])
def send_contract_for_signature_alternative(contract_id):
    """Vertrag als PDF mit Signatur-Feldern generieren und per E-Mail senden"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not coop_partner:
        return jsonify({"error": "Kooperationspartner nicht gefunden"}), 404
    
    try:
        # PDF mit Signatur-Feldern generieren
        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dienstleistungsvertrag.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Signatur-Felder hinzufügen
        signature_fields = """
        <div style="page-break-before: always; margin-top: 50px;">
            <h3>Unterschriften</h3>
            <div style="display: flex; justify-content: space-between; margin-top: 100px;">
                <div style="width: 45%; text-align: center;">
                    <div style="border-bottom: 1px solid black; height: 50px; margin-bottom: 10px;"></div>
                    <p><strong>Unterschrift Kunde</strong></p>
                    <p>""" + customer.name + """</p>
                    <p>Datum: _______________</p>
                </div>
                <div style="width: 45%; text-align: center;">
                    <div style="border-bottom: 1px solid black; height: 50px; margin-bottom: 10px;"></div>
                    <p><strong>Unterschrift Kooperationspartner</strong></p>
                    <p>""" + (coop_partner.company_name or coop_partner.name) + """</p>
                    <p>Datum: _______________</p>
                </div>
            </div>
        </div>
        """
        
        # Signatur-Felder vor </body> einfügen
        html_content = html_content.replace('</body>', signature_fields + '</body>')
        
        # Variablen ersetzen
        replacements = {
            '[Auftragsnummer]': contract.contract_number,
            '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
            '[Vorname Name]': customer.name,
            '[Straße Hausnummer]': customer.street_address or '',
            '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
            '[Telefon Kunde]': customer.phone or '',
            '[E-Mail Kunde]': customer.email or '',
            '[Firmenname Partner]': coop_partner.company_name or coop_partner.name or '',
            '[Adresse Partner]': coop_partner.street_address or '',
            '[Telefon Partner]': coop_partner.phone or '',
            '[E-Mail Partner]': coop_partner.email or '',
            '[Identifikationsnummer Partner]': coop_partner.identification_number or '',
            '[Handelsregisternummer Partner]': coop_partner.commercial_register or '',
            '[Umsatzsteuer-Identifikationsnummer Partner]': coop_partner.vat_id or '',
            '[Name Geschäftsführer Partner]': coop_partner.managing_director or '',
            '[Notfalltelefon Partner]': coop_partner.emergency_phone or '',
            '[Betrag]': format_currency(contract.monthly_rate) if contract.monthly_rate else '',
            '[Tagessatz]': format_currency(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
            '[Ort]': customer.city or '',
            '[Partnerfirma]': coop_partner.partner_company or coop_partner.name
        }
        
        # Alle Variablen ersetzen
        for placeholder, value in replacements.items():
            html_content = html_content.replace(placeholder, str(value))
        
        # PDF generieren
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
        
        font_config = FontConfiguration()
        html_doc = HTML(string=html_content)
        css = CSS(string='@page { size: A4; margin: 2cm; }', font_config=font_config)
        
        pdf_bytes = html_doc.write_pdf(stylesheets=[css], font_config=font_config)
        
        # PDF speichern
        pdf_filename = f"dienstleistungsvertrag_mit_signaturen_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
        
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        
        # In Datenbank speichern
        contract.pdf_filename = pdf_filename
        contract.status = 'ready_for_signature'
        db.session.commit()
        
        # PDF als Base64 zurückgeben
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        return jsonify({
            "success": True,
            "message": "PDF mit Signatur-Feldern erfolgreich generiert! Sie können es herunterladen und per E-Mail an den Kunden senden.",
            "pdf_base64": pdf_base64,
            "filename": pdf_filename,
            "download_url": f"/api/dienstleistungsvertraege/{contract_id}/download-pdf",
            "customer_email": customer.email,
            "instructions": "Das PDF wurde generiert. Sie können es herunterladen und per E-Mail an den Kunden senden. Der Kunde kann es ausdrucken, unterschreiben und zurücksenden."
        })
        
    except Exception as e:
        return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/generate-signed-pdf', methods=['POST'])
def generate_signed_pdf(contract_id):
    """Generiert ein PDF mit Signatur-Feldern für manuelle Unterschrift"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer or not coop_partner:
        return jsonify({"error": "Kunde oder Kooperationspartner nicht gefunden"}), 404
    
    try:
        # PDF mit Signatur-Feldern generieren
        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dienstleistungsvertrag.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Signatur-Felder hinzufügen
        signature_fields = """
        <div style="page-break-before: always; margin-top: 50px;">
            <h3>Unterschriften</h3>
            <div style="display: flex; justify-content: space-between; margin-top: 100px;">
                <div style="width: 45%; text-align: center;">
                    <div style="border-bottom: 1px solid black; height: 50px; margin-bottom: 10px;"></div>
                    <p><strong>Unterschrift Kunde</strong></p>
                    <p>""" + customer.name + """</p>
                    <p>Datum: _______________</p>
                </div>
                <div style="width: 45%; text-align: center;">
                    <div style="border-bottom: 1px solid black; height: 50px; margin-bottom: 10px;"></div>
                    <p><strong>Unterschrift Kooperationspartner</strong></p>
                    <p>""" + (coop_partner.company_name or coop_partner.name) + """</p>
                    <p>Datum: _______________</p>
                </div>
            </div>
        </div>
        """
        
        # Signatur-Felder vor </body> einfügen
        html_content = html_content.replace('</body>', signature_fields + '</body>')
        
        # Variablen ersetzen
        replacements = {
            '[Auftragsnummer]': contract.contract_number,
            '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
            '[Vorname Name]': customer.name,
            '[Straße Hausnummer]': customer.street_address or '',
            '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
            '[Telefon Kunde]': customer.phone or '',
            '[E-Mail Kunde]': customer.email or '',
            '[Firmenname Partner]': coop_partner.company_name or coop_partner.name or '',
            '[Adresse Partner]': coop_partner.street_address or '',
            '[Telefon Partner]': coop_partner.phone or '',
            '[E-Mail Partner]': coop_partner.email or '',
            '[Identifikationsnummer Partner]': coop_partner.identification_number or '',
            '[Handelsregisternummer Partner]': coop_partner.commercial_register or '',
            '[Umsatzsteuer-Identifikationsnummer Partner]': coop_partner.vat_id or '',
            '[Name Geschäftsführer Partner]': coop_partner.managing_director or '',
            '[Notfalltelefon Partner]': coop_partner.emergency_phone or '',
            '[Betrag]': format_currency(contract.monthly_rate) if contract.monthly_rate else '',
            '[Tagessatz]': format_currency(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
            '[Ort]': customer.city or '',
            '[Partnerfirma]': coop_partner.partner_company or coop_partner.name
        }
        
        # Alle Variablen ersetzen
        for placeholder, value in replacements.items():
            html_content = html_content.replace(placeholder, str(value))
        
        # PDF generieren
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
        
        font_config = FontConfiguration()
        html_doc = HTML(string=html_content)
        css = CSS(string='@page { size: A4; margin: 2cm; }', font_config=font_config)
        
        pdf_bytes = html_doc.write_pdf(stylesheets=[css], font_config=font_config)
        
        # PDF speichern
        pdf_filename = f"dienstleistungsvertrag_mit_signaturen_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
        
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        
        # In Datenbank speichern
        contract.pdf_filename = pdf_filename
        contract.status = 'ready_for_signature'
        db.session.commit()
        
        # PDF als Base64 zurückgeben
        import base64
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        return jsonify({
            "success": True,
            "message": "PDF mit Signatur-Feldern erfolgreich generiert",
            "pdf_base64": pdf_base64,
            "filename": pdf_filename,
            "download_url": f"/api/dienstleistungsvertraege/{contract_id}/download-pdf"
        })
        
    except Exception as e:
        return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500

# PDF Download
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/download-pdf')
def download_contract_pdf(contract_id):
    """Download des generierten PDFs"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    
    if not contract.pdf_filename:
        return jsonify({"error": "PDF nicht gefunden"}), 404
    
    pdf_path = os.path.join(UPLOAD_FOLDER, contract.pdf_filename)
    
    if not os.path.exists(pdf_path):
        return jsonify({"error": "PDF-Datei nicht gefunden"}), 404
    
    return send_file(pdf_path, as_attachment=True, download_name=contract.pdf_filename)

def add_signature_script(html, contract_id=None, contract_type=None, signer_type=None):
    """Fügt JavaScript für Signatur-Funktionalität hinzu"""
    
    # API-URLs
    if contract_id and contract_type:
        if signer_type:
            api_url = f'/api/{contract_type}/{contract_id}/save-signature/{signer_type}'
        else:
            api_url = f'/api/{contract_type}/{contract_id}/save-signature'
    else:
        api_url = '/api/save-signature'
    
    # Konvertiere contract_id zu int oder null
    contract_id_js = contract_id if contract_id else 'null'
    
    # Bestimme den Platzhalter basierend auf signer_type
    placeholder_id = 'signature-placeholder'
    if signer_type == 'partner':
        placeholder_id = 'signature-placeholder-partner'
    elif signer_type == 'customer':
        placeholder_id = 'signature-placeholder'
    
    # Verwende normale String-Konkatenation statt f-string
    signature_script = """
    <script>
        const CONTRACT_ID = """ + str(contract_id_js) + """;
        const CONTRACT_TYPE = '""" + (contract_type or '') + """';
        const API_URL = '""" + api_url + """';
        const PLACEHOLDER_ID = '""" + placeholder_id + """';
        function initSignature() {
            const placeholder = document.getElementById(PLACEHOLDER_ID);
            if (!placeholder) return;
            
            // Prüfe ob bereits signiert wurde - wenn ja, zeige Download-Button und Meldung
            // Warte kurz, um sicherzustellen, dass das Bild geladen ist
            setTimeout(() => {
                const img = placeholder.querySelector('img');
                if (img) {
                    showDownloadButton();
                    showSignedMessage();
                    return; // KEIN Button anzeigen
                }
                
                // Nur wenn NOCH NICHT signiert, Button anzeigen
                const observer = new IntersectionObserver((entries) => {
                    entries.forEach(entry => {
                        if (entry.isIntersecting) {
                            // Prüfe NOCHMAL ob bereits signiert wurde (sicherheitshalber)
                            if (!entry.target.querySelector('img')) {
                                showSignatureButton(entry.target);
                            }
                        }
                    });
                }, { threshold: 0.5 });
                
                observer.observe(placeholder);
            }, 100);
        }
        
        function showDownloadButton() {
            if (document.querySelector('.download-btn')) return;
            
            const button = document.createElement('button');
            button.className = 'download-btn';
            button.innerHTML = '<i class="fas fa-download"></i> PDF herunterladen';
            button.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #f58060; color: white; padding: 15px 30px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; z-index: 9999;';
            button.onclick = function() {
                window.print();
            };
            document.body.appendChild(button);
        }
        
        function showSignedMessage() {
            const message = document.createElement('div');
            message.style.cssText = 'position: fixed; top: 80px; right: 30px; background: #fff3cd; border: 2px solid #ffc107; padding: 15px 20px; border-radius: 8px; z-index: 9998; box-shadow: 0 4px 12px rgba(0,0,0,0.2); max-width: 350px;';
            message.innerHTML = '<strong style="color: #856404;">✓ Vertrag bereits signiert</strong><br><p style="margin: 8px 0 0 0; color: #856404; font-size: 14px;">Dieser Vertrag wurde bereits von Ihnen unterschrieben. Sie können das Dokument oben rechts herunterladen.</p>';
            document.body.appendChild(message);
            
            setTimeout(() => {
                message.style.transition = 'opacity 0.5s';
                message.style.opacity = '0';
                setTimeout(() => message.remove(), 500);
            }, 8000);
        }
        
        function showSignatureButton(placeholder) {
            if (placeholder.querySelector('.sign-button')) return;
            if (placeholder.querySelector('img')) return;
            
            const button = document.createElement('button');
            button.className = 'sign-button';
            button.textContent = 'Jetzt unterschreiben';
            button.style.cssText = 'background-color: #f58060; color: white; padding: 15px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold;';
            button.onclick = function() {
                const img = placeholder.querySelector('img');
                if (img) {
                    alert('Dieser Vertrag wurde bereits signiert!');
                    return;
                }
                openSignatureModal();
            };
            
            placeholder.innerHTML = '';
            placeholder.appendChild(button);
        }
        
        function openSignatureModal() {
            const modal = document.createElement('div');
            modal.id = 'signature-modal';
            modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 10000; display: flex; justify-content: center; align-items: center;';
            
            const modalContent = document.createElement('div');
            modalContent.style.cssText = 'background: white; padding: 30px; border-radius: 15px; width: 90%; max-width: 600px; box-shadow: 0 10px 40px rgba(0,0,0,0.2);';
            
            modalContent.innerHTML = `
                <h2 style="margin-top: 0; color: #f58060;">Bitte signieren Sie hier</h2>
                <canvas id="signature-canvas" style="border: 3px solid #f58060; border-radius: 8px; cursor: crosshair; width: 100%; height: 200px; touch-action: none;"></canvas>
                <div style="margin-top: 25px; text-align: right;">
                    <button onclick="clearSignature()" style="padding: 12px 24px; margin-right: 10px; background: #f44336; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">Löschen</button>
                    <button onclick="saveSignature()" style="padding: 12px 24px; background: #f58060; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">Speichern</button>
                </div>
            `;
            
            modal.appendChild(modalContent);
            document.body.appendChild(modal);
            setupCanvas();
        }
        
        function setupCanvas() {
            const canvas = document.getElementById('signature-canvas');
            const ctx = canvas.getContext('2d');
            
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width;
            canvas.height = rect.height;
            
            ctx.strokeStyle = '#000000';
            ctx.lineWidth = 2;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            
            let isDrawing = false;
            
            function getCoords(e) {
                const rect = canvas.getBoundingClientRect();
                return {
                    x: (e.touches ? e.touches[0].clientX : e.clientX) - rect.left,
                    y: (e.touches ? e.touches[0].clientY : e.clientY) - rect.top
                };
            }
            
            function startDrawing(e) {
                isDrawing = true;
                const coords = getCoords(e);
                ctx.beginPath();
                ctx.moveTo(coords.x, coords.y);
            }
            
            function draw(e) {
                if (!isDrawing) return;
                const coords = getCoords(e);
                ctx.lineTo(coords.x, coords.y);
                ctx.stroke();
            }
            
            function stopDrawing() {
                isDrawing = false;
            }
            
            canvas.addEventListener('mousedown', startDrawing);
            canvas.addEventListener('mousemove', draw);
            canvas.addEventListener('mouseup', stopDrawing);
            canvas.addEventListener('touchstart', startDrawing);
            canvas.addEventListener('touchmove', draw);
            canvas.addEventListener('touchend', stopDrawing);
        }
        
        function clearSignature() {
            const canvas = document.getElementById('signature-canvas');
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
        
        async function saveSignature() {
            const canvas = document.getElementById('signature-canvas');
            const signatureData = canvas.toDataURL('image/png');
            
            // Speichere Signatur im Backend
            try {
                const response = await fetch(API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ signature: signatureData })
                });
                
                const result = await response.json();
                
                if (!response.ok) {
                    alert('Fehler: ' + (result.error || 'Unbekannter Fehler'));
                    console.error('Signatur konnte nicht gespeichert werden:', result);
                    document.getElementById('signature-modal').remove();
                    return;
                }
            } catch (e) {
                console.error('Signatur konnte nicht gespeichert werden:', e);
                alert('Fehler beim Speichern der Signatur. Bitte versuchen Sie es erneut.');
                document.getElementById('signature-modal').remove();
                return;
            }
            
            const placeholder = document.getElementById('signature-placeholder');
            const img = document.createElement('img');
            img.src = signatureData;
            img.style.maxWidth = '300px';
            img.style.height = 'auto';
            img.style.display = 'block';
            img.style.margin = '10px auto';
            
            placeholder.innerHTML = '';
            placeholder.appendChild(img);
            
            document.getElementById('signature-modal').remove();
            
            // Entferne Signatur-Button wenn vorhanden
            const signButton = document.querySelector('.sign-button');
            if (signButton) {
                signButton.remove();
            }
            
            // Zeige Download-Button
            showDownloadButton();
            
            alert('Danke für die Unterschrift! Sie können das Dokument jetzt herunterladen.');
        }
        
        window.addEventListener('DOMContentLoaded', initSignature);
    </script>
"""
    
    if '</body>' in html:
        html = html.replace('</body>', signature_script + '</body>')
    else:
        html += signature_script
    
    return html

# Download des unterschriebenen PDFs
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/sign/customer', methods=['GET'])
def sign_dienstleistungsvertrag_customer(contract_id):
    """Zeigt den Dienstleistungsvertrag zur Signatur für den KUNDEN an"""
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    try:
        html_content = _render_dienstleistungsvertrag_html(contract, customer, coop_partner)
    except ValueError as e:
        return f"Fehler: {str(e)}", 404
    except Exception as e:
        return f"Fehler beim Laden des Templates: {str(e)}", 500
    
    # Füge CSS hinzu um Partner-Unterschrifts-Spalte zu verstecken und Kunden-Unterschrift zu zentrieren
    hide_partner_style = '''<style>
        td:has(#signature-placeholder-partner) { display: none !important; }
        table.email-table:has(#signature-placeholder) tr td:nth-child(1) { width: 60% !important; text-align: center !important; }
        table.email-table:has(#signature-placeholder) tr td:nth-child(2) { width: 10% !important; }
        table.email-table:has(#signature-placeholder) tr td:nth-child(3) { width: 30% !important; }
    </style>'''
    if '</head>' in html_content:
        html_content = html_content.replace('</head>', hide_partner_style + '</head>', 1)
    else:
        html_content = hide_partner_style + html_content
    
    # Prüfe ob KUNDE bereits signiert hat
    if contract.status in ['customer_signed', 'partner_signed', 'completed'] and contract.signature_data:
        signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{contract.signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder"></div>', signature_img)
    
    # Füge Signatur-Skript hinzu
    html_content = add_signature_script(html_content, contract_id, "dienstleistungsvertraege", signer_type="customer")
    
    return html_content

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/sign/partner', methods=['GET'])
def sign_dienstleistungsvertrag_partner(contract_id):
    """Zeigt den Dienstleistungsvertrag zur Signatur für den PARTNER an"""
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    try:
        html_content = _render_dienstleistungsvertrag_html(contract, customer, coop_partner)
    except ValueError as e:
        return f"Fehler: {str(e)}", 404
    except Exception as e:
        return f"Fehler beim Laden des Templates: {str(e)}", 500
    
    # Verstecke Kunden-Unterschrifts-Spalte für den Partner und zentriere Partner-Unterschrift
    hide_customer_style = '''<style>
        td:has(#signature-placeholder) { display: none !important; }
        table.email-table:has(#signature-placeholder-partner) tr td:nth-child(1) { width: 30% !important; }
        table.email-table:has(#signature-placeholder-partner) tr td:nth-child(2) { width: 10% !important; }
        table.email-table:has(#signature-placeholder-partner) tr td:nth-child(3) { width: 60% !important; text-align: center !important; }
    </style>'''
    if '</head>' in html_content:
        html_content = html_content.replace('</head>', hide_customer_style + '</head>', 1)
    else:
        html_content = hide_customer_style + html_content
    
    # Prüfe ob PARTNER bereits signiert hat
    if contract.status in ['partner_signed', 'completed'] and contract.partner_signature_data:
        signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{contract.partner_signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder-partner"></div>', signature_img)
    
    # Füge Signatur-Skript hinzu
    html_content = add_signature_script(html_content, contract_id, "dienstleistungsvertraege", signer_type="partner")
    
    return html_content

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/sign', methods=['GET'])
def sign_dienstleistungsvertrag(contract_id):
    """Zeigt den Dienstleistungsvertrag zur Signatur an"""
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    try:
        html_content = _render_dienstleistungsvertrag_html(contract, customer, coop_partner)
    except ValueError as e:
        return f"Fehler: {str(e)}", 404
    except Exception as e:
        return f"Fehler beim Laden des Templates: {str(e)}", 500
    
    # Prüfe ob bereits signiert (wie in SignaturApp) - WICHTIG: NACH Variablen ersetzung
    if contract.status == 'signed' and contract.signature_data:
        # Vertrag bereits signiert - ersetze placeholder durch Signatur-Bild
        signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{contract.signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder"></div>', signature_img)
    
    # Füge Signatur-Skript hinzu (von SignaturApp) mit contract_id
    html_content = add_signature_script(html_content, contract_id, "dienstleistungsvertraege")
    
    return html_content

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/save-signature/customer', methods=['POST'])
def save_dienstleistungsvertrag_signature_customer(contract_id):
    """Speichert die Signatur des KUNDEN"""
    try:
        contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
        
        # Prüfe ob Kunde bereits signiert hat
        if contract.status in ['customer_signed', 'completed']:
            return jsonify({'error': 'Der Kunde hat bereits signiert!'}), 400
        
        data = request.get_json()
        signature_data = data.get('signature')
        
        # Speichere Kunden-Signatur
        contract.signature_data = signature_data
        
        # Status basierend auf Partner-Signatur
        if contract.status == 'partner_signed':
            # Beide haben signiert
            contract.status = 'completed'
            # Erstelle finales PDF mit BEIDEN Signaturen
            signed_pdf_filename = create_signed_contract_pdf_complete(contract)
            if signed_pdf_filename:
                contract.signed_pdf_filename = signed_pdf_filename
            # Partner über den besetzten Auftrag informieren
            _notify_other_partners_on_contract_completed(contract)
            # Versende unterschriebenes Dokument per E-Mail
            db.session.commit()  # Commit vor E-Mail-Versand, damit PDF verfügbar ist
            send_signed_contract_email(contract)
        else:
            # Nur Kunde hat signiert
            contract.status = 'customer_signed'
        
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/save-signature/partner', methods=['POST'])
def save_dienstleistungsvertrag_signature_partner(contract_id):
    """Speichert die Signatur des PARTNERS"""
    try:
        contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
        
        # Prüfe ob Partner bereits signiert hat
        if contract.status in ['partner_signed', 'completed']:
            return jsonify({'error': 'Der Partner hat bereits signiert!'}), 400
        
        data = request.get_json()
        signature_data = data.get('signature')
        
        # Speichere Partner-Signatur
        contract.partner_signature_data = signature_data
        
        # Status basierend auf Kunden-Signatur
        if contract.status == 'customer_signed':
            # Beide haben signiert
            contract.status = 'completed'
            # Erstelle finales PDF mit BEIDEN Signaturen
            signed_pdf_filename = create_signed_contract_pdf_complete(contract)
            if signed_pdf_filename:
                contract.signed_pdf_filename = signed_pdf_filename
            # Partner über den besetzten Auftrag informieren
            _notify_other_partners_on_contract_completed(contract)
            # Versende unterschriebenes Dokument per E-Mail
            db.session.commit()  # Commit vor E-Mail-Versand, damit PDF verfügbar ist
            send_signed_contract_email(contract)
        else:
            # Nur Partner hat signiert
            contract.status = 'partner_signed'
        
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/save-signature', methods=['POST'])
def save_dienstleistungsvertrag_signature(contract_id):
    """Legacy: Speichert die Signatur eines Dienstleistungsvertrags (falls noch verwendet)"""
    try:
        contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
        
        # Verhindere mehrfache Signatur (wie in SignaturApp)
        if contract.status == 'signed':
            return jsonify({'error': 'Dieser Vertrag wurde bereits signiert!'}), 400
        
        data = request.get_json()
        signature_data = data.get('signature')
        
        # Speichere Signatur
        contract.signature_data = signature_data
        contract.status = 'signed'
        
        # Erstelle PDF mit Signatur
        signed_pdf_filename = create_signed_contract_pdf(contract, signature_data, "dienstleistungsvertrag")
        if signed_pdf_filename:
            contract.signed_pdf_filename = signed_pdf_filename
        
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def create_signed_contract_pdf_complete(contract):
    """Erstellt ein finales PDF mit BEIDEN Signaturen (Kunde + Partner)"""
    try:
        print(f"🔍 Erstelle PDF mit beiden Signaturen für Vertrag {contract.id}")
        
        # Prüfe ob beide Signaturen vorhanden sind
        if not contract.signature_data:
            print("❌ Keine Kunden-Signatur vorhanden")
            return None
        if not contract.partner_signature_data:
            print("❌ Keine Partner-Signatur vorhanden")
            return None
            
        print(f"✅ Beide Signaturen vorhanden")
        
        try:
            html_content = _render_dienstleistungsvertrag_html(contract)
        except ValueError as e:
            print(f"❌ Fehler: {e}")
            return None
        except Exception as e:
            print(f"❌ Fehler beim Laden des Templates: {str(e)}")
            return None
        
        print(f"✅ Variablen ersetzt")
        
        # Füge BEIDE Signaturen in die existierenden Felder ein
        # Kunden-Signatur
        customer_signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{contract.signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder"></div>', customer_signature_img)
        print(f"✅ Kunden-Signatur eingefügt")
        
        # Partner-Signatur
        partner_signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{contract.partner_signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder-partner"></div>', partner_signature_img)
        print(f"✅ Partner-Signatur eingefügt")
        
        # Entferne JavaScript und CSS-Verstecke
        import re
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        # Erstelle PDF
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
        
        font_config = FontConfiguration()
        html_doc = HTML(string=html_content)
        css = CSS(string='@page { size: A4; margin: 2cm; }', font_config=font_config)
        
        pdf_filename = f"signed_complete_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
        
        print(f"🔍 Erstelle PDF: {pdf_path}")
        pdf_bytes = html_doc.write_pdf(stylesheets=[css], font_config=font_config)
        
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        
        print(f"✅ PDF erfolgreich erstellt: {pdf_filename}")
        return pdf_filename
        
    except Exception as e:
        print(f"❌ Fehler beim Erstellen des finalen PDFs: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def create_signed_contract_pdf(contract, signature_data, contract_type):
    """Erstellt ein PDF mit eingefügter Signatur (Legacy)"""
    try:
        # Lade Template
        template_name = "dienstleistungsvertrag.html" if contract_type == "dienstleistungsvertrag" else "kooperationsvertrag.html"
        template_path = os.path.join(os.path.dirname(__file__), 'templates', template_name)
        
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Variablen ersetzen
        if contract_type == "dienstleistungsvertrag":
            customer = Customer.query.get(contract.customer_id)
            coop_partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
            try:
                html_content = contract.custom_html or _render_dienstleistungsvertrag_html(
                    contract,
                    customer,
                    coop_partner,
                    ignore_custom=True
                )
            except Exception as e:
                print(f"❌ Fehler beim Rendern des Dienstleistungsvertrags: {str(e)}")
                return None
        else:
            # Kooperationsvertrag - WICHTIG: receiver_partner ist der Dienstleister!
            receiver_partner = Kooperationspartner.query.get(contract.receiver_partner_id)
            
            if receiver_partner:
                replacements = {
                    '[Firmenname des Dienstleisters]': receiver_partner.company_name or receiver_partner.name,
                    '[Straße]': receiver_partner.street_address.split(',')[0] if receiver_partner.street_address else '',
                    '[PLZ]': receiver_partner.street_address.split(',')[1].strip().split(' ')[0] if receiver_partner.street_address and ',' in receiver_partner.street_address else '',
                    '[Ort]': receiver_partner.street_address.split(',')[1].strip().split(' ')[1] if receiver_partner.street_address and ',' in receiver_partner.street_address and len(receiver_partner.street_address.split(',')[1].strip().split(' ')) > 1 else '',
                    '[Land]': 'Deutschland',
                    '[Vertretungsberechtigte]': receiver_partner.managing_director or '',
                    '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
                    '[Provision]': (receiver_partner.provision or '').strip()
                }
                
                for placeholder, value in replacements.items():
                    html_content = html_content.replace(placeholder, str(value))
        
        # Füge Signatur ein
        signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder"></div>', signature_img)
        
        # Entferne JavaScript
        import re
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        # Erstelle PDF mit weasyprint
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
        
        font_config = FontConfiguration()
        html_doc = HTML(string=html_content)
        
        pdf_filename = f"signed_{contract_type}_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
        
        css = CSS(string='@page { size: A4; margin: 2cm; }', font_config=font_config)
        pdf_bytes = html_doc.write_pdf(stylesheets=[css], font_config=font_config)
        
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        
        return pdf_filename
        
    except Exception as e:
        print(f"Fehler beim Erstellen des signierten PDFs: {str(e)}")
        return None

@app.route('/api/kooperationsvertraege/<int:contract_id>/save-signature', methods=['POST'])
def save_kooperationsvertrag_signature(contract_id):
    """Speichert die Signatur eines Kooperationsvertrags und erstellt PDF"""
    try:
        contract = Kooperationsvertrag.query.get_or_404(contract_id)
        
        # Verhindere mehrfache Signatur (wie in SignaturApp)
        if contract.status == 'signed':
            return jsonify({'error': 'Dieser Vertrag wurde bereits signiert!'}), 400
        
        data = request.get_json()
        signature_data = data.get('signature')
        
        # Speichere Signatur
        contract.signature_data = signature_data
        contract.status = 'signed'
        
        # Erstelle PDF mit Signatur
        signed_pdf_filename = create_signed_contract_pdf(contract, signature_data, "kooperationsvertrag")
        if signed_pdf_filename:
            contract.signed_pdf_filename = signed_pdf_filename
            
            # PDF automatisch exportieren
            pdf_path = os.path.join(UPLOAD_FOLDER, signed_pdf_filename)
            _export_kooperationsvertrag_pdf(contract.id, contract.contract_number, pdf_path, is_signed=True)
        
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/download-signed-pdf')
def download_signed_contract_pdf(contract_id):
    """Download des unterschriebenen PDFs"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    
    if not contract.signed_pdf_filename:
        return jsonify({"error": "Unterschriebenes PDF nicht gefunden"}), 404
    
    pdf_path = os.path.join(UPLOAD_FOLDER, contract.signed_pdf_filename)
    
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Unterschriebene PDF-Datei nicht gefunden"}), 404
    
    return send_file(pdf_path, as_attachment=True, download_name="Dienstleistungsvertrag.pdf")

@app.route('/webhook/zoho-sign', methods=['POST'])
def zoho_sign_webhook():
    """Webhook für Zoho Sign Status-Updates"""
    try:
        data = request.get_json()
        print(f"📦 Zoho Sign Webhook: {json.dumps(data, indent=2)}")
        
        # Status-Update verarbeiten
        request_id = data.get('request_id')
        status = data.get('status')
        
        if request_id and status:
            # Vertrag mit dieser Zoho Request ID finden
            contract = Dienstleistungsvertrag.query.filter_by(zoho_request_id=request_id).first()
            if contract:
                if status == 'COMPLETED':
                    contract.status = 'signed'
                    # Hier könnte man das signierte PDF von Zoho Sign herunterladen
                    # und in signed_pdf_filename speichern
                elif status == 'EXPIRED':
                    contract.status = 'expired'
                elif status == 'DECLINED':
                    contract.status = 'declined'
                
                contract.updated_at = datetime.datetime.utcnow()
                db.session.commit()
                print(f"✅ Vertrag {contract.id} Status aktualisiert: {status}")
        
        return jsonify({"success": True})
    except Exception as e:
        print(f"❌ Zoho Sign Webhook Fehler: {e}")
        return jsonify({"error": str(e)}), 500

# 🔓 Logout
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

def _mask(value: str, show: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= show:
        return value
    return value[:show] + "…"

@app.route("/debug/oauth")
def debug_oauth():
    if "user" not in session:
        return redirect("/")
    redirect_uri = url_for('gmail_callback', _external=True)
    info = {"redirect_uri": redirect_uri}

    # Try env JSON
    src = None
    raw = os.getenv('GOOGLE_CLIENT_CONFIG_JSON')
    if raw:
        txt = raw.strip()
        try:
            cfg = json.loads(txt)
            src = "env_json"
        except Exception:
            try:
                if (txt.startswith('"') and txt.endswith('"')) or (txt.startswith("'") and txt.endswith("'")):
                    txt = txt[1:-1]
                txt = txt.replace('\\"', '"')
                cfg = json.loads(txt)
                src = "env_json_unquoted"
            except Exception:
                cfg = None
        if cfg:
            web = cfg.get('web', {})
            info.update({
                "source": src,
                "client_id": _mask(web.get('client_id', '')),
                "has_client_secret": bool(web.get('client_secret')),
                "authorized_redirect_uris": web.get('redirect_uris', [])
            })
            return jsonify(info)

    # Try file
    path = os.getenv('GOOGLE_CLIENT_CONFIG_PATH') or 'credentials.json'
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                cfg = json.load(f)
            web = cfg.get('web', {})
            info.update({
                "source": f"file:{path}",
                "client_id": _mask(web.get('client_id', '')),
                "has_client_secret": bool(web.get('client_secret')),
                "authorized_redirect_uris": web.get('redirect_uris', [])
            })
            return jsonify(info)
        except Exception as e:
            info.update({"source": f"file:{path}", "error": str(e)})
            return jsonify(info), 200

    # Fallback to id/secret
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    if client_id and client_secret:
        info.update({
            "source": "env_id_secret",
            "client_id": _mask(client_id),
            "has_client_secret": True,
            "authorized_redirect_uris": ["(configured in Google Cloud console)"]
        })
        return jsonify(info)

    info.update({
        "source": "none",
        "error": "No Google OAuth config found"
    })
    return jsonify(info), 200

# ▶️ Nur lokal öffnen
if __name__ == "__main__":
    import webbrowser, threading
    threading.Timer(1.5, lambda: webbrowser.open_new("http://127.0.0.1:5000")).start()
    app.run(debug=True)
