from flask import Flask, render_template, request, redirect, session, jsonify, url_for, send_file
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
import os
import datetime
from dotenv import load_dotenv
import json
import requests

# DocuSign imports (vereinfacht - nur für Typen)
# from docusign_esign import ApiClient, EnvelopesApi, EnvelopeDefinition, Document, Signer, SignHere, Tabs, Recipients
import uuid
from models import db, User, Anfrage, TeamNote, GmailCredential, PdfDocument, Customer, Kooperationspartner, Caregiver, Dienstleistungsvertrag, Kooperationsvertrag
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

# 🔃 .env laden (lokal)
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback")

# 📦 Persistente Ablage – Basisverzeichnis (standard: ./data)
APP_DATA_DIR = os.getenv('APP_DATA_DIR') or os.path.join(os.getcwd(), 'data')
os.makedirs(APP_DATA_DIR, exist_ok=True)

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

CORS(app)

db.init_app(app)

with app.app_context():
    db.create_all()
    # Leichtgewichtige Migration: fehlende Spalten zu team_notes hinzufügen (SQLite)
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            # Team notes migration
            insp = conn.execute(text("PRAGMA table_info(team_notes)")).fetchall()
            cols = [row[1] for row in insp]
            if 'parent_id' not in cols:
                conn.execute(text("ALTER TABLE team_notes ADD COLUMN parent_id INTEGER"))
            if 'reactions_json' not in cols:
                conn.execute(text("ALTER TABLE team_notes ADD COLUMN reactions_json TEXT DEFAULT '[]'"))
            
            # Signature data migration für beide Vertrags-Tabellen
            insp = conn.execute(text("PRAGMA table_info(kooperationsvertraege)")).fetchall()
            koop_cols = [row[1] for row in insp]
            if 'signature_data' not in koop_cols:
                conn.execute(text("ALTER TABLE kooperationsvertraege ADD COLUMN signature_data TEXT"))
                conn.commit()
            
            insp = conn.execute(text("PRAGMA table_info(dienstleistungsvertraege)")).fetchall()
            dlv_cols = [row[1] for row in insp]
            if 'signature_data' not in dlv_cols:
                conn.execute(text("ALTER TABLE dienstleistungsvertraege ADD COLUMN signature_data TEXT"))
                conn.commit()
    except Exception as e:
        print(f"Migration-Fehler: {e}")
        pass
    
    # Migration für Customer-Tabelle: Neue Spalten hinzufügen (falls nicht vorhanden)
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            insp = conn.execute(text("PRAGMA table_info(customers)")).fetchall()
            cols = [row[1] for row in insp]
            if 'offer_data_json' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN offer_data_json TEXT DEFAULT '{}'"))
            if 'questionnaire_data_json' not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN questionnaire_data_json TEXT DEFAULT '{}'"))
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
            
            # Kooperationspartner-Tabelle erstellen falls nicht vorhanden
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='kooperationspartner'"))
            if not result.fetchone():
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
                insp_partner = conn.execute(text("PRAGMA table_info(kooperationspartner)")).fetchall()
                partner_cols = [row[1] for row in insp_partner]
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
            
            # Kooperationsvertrag-Tabelle erstellen falls nicht vorhanden
            result_coop = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='kooperationsvertraege'"))
            if not result_coop.fetchone():
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
            
            # Dienstleistungsvertrag-Tabelle erstellen falls nicht vorhanden
            result_contract = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='dienstleistungsvertraege'"))
            if not result_contract.fetchone():
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

# 📥 Anfrage empfangen (extern)
@app.route("/api/externe-anfrage", methods=["POST"])
def externe_anfrage():
    data = request.get_json() or {}
    name = data.get("name")
    tel = data.get("tel")
    if not name:
        return jsonify({"error": "Ungültige Daten"}), 400
    anfrage = Anfrage(name=name, tel=tel)
    db.session.add(anfrage)
    db.session.commit()
    return jsonify({"success": True, "id": anfrage.id})

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
    anfragen = Anfrage.query.order_by(Anfrage.id.desc()).limit(100).all()
    return jsonify([a.to_dict() for a in anfragen])

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
    aktuelles_datum = datetime.datetime.now().strftime('%A, %d. %B %Y')
    username = session.get("user")
    return render_template("index.html", aktuelles_datum=aktuelles_datum, username=username)

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
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    docs = PdfDocument.query.order_by(PdfDocument.id.desc()).limit(500).all()
    return jsonify([d.to_dict() for d in docs])

# 📄 PDF hochladen
@app.route('/api/pdfs', methods=['POST'])
def upload_pdf():
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

    # Nutze die gleiche Implementierung wie /api/send-offer, ohne HTTP-Hop
    request_ctx_backup = request
    try:
        # Minimaler Inline-Aufruf der Logik aus send_offer
        # (kopiert die Kernteile, um keine Request-Kontext-Probleme zu erzeugen)
        creds = load_user_gmail_credentials(session['user'])
        if not creds:
            return jsonify({"error": "Kein Gmail-Konto verbunden."}), 400
        service = build('gmail', 'v1', credentials=creds)

        subject = data.get('subject') or "Befragungsbogen"
        body = data.get('body') or (
            "Hallo,\n\n" 
            "anbei befindet sich der Befragungsbogen.\n\n"
            "Mit besten Grüßen"
        )
        body_html_final = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
            (body or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') +
            "</div>"
        )
        body_text_final = body

        mixed_boundary = 'mixed_boundary'
        alt_boundary = 'alt_boundary'
        parts = []
        parts.append(f"Content-Type: multipart/mixed; boundary={mixed_boundary}\r\n")
        parts.append("MIME-Version: 1.0\r\n")
        parts.append(f"to: {to_email}\r\n")
        parts.append(f"subject: {subject}\r\n\r\n")
        parts.append(f"--{mixed_boundary}\r\n")
        parts.append(f"Content-Type: multipart/alternative; boundary={alt_boundary}\r\n\r\n")
        parts.append(f"--{alt_boundary}\r\n")
        parts.append("Content-Type: text/plain; charset=UTF-8\r\n\r\n")
        parts.append(body_text_final + "\r\n\r\n")
        parts.append(f"--{alt_boundary}\r\n")
        parts.append("Content-Type: text/html; charset=UTF-8\r\n\r\n")
        parts.append(body_html_final + "\r\n\r\n")
        parts.append(f"--{alt_boundary}--\r\n")
        parts.append(f"--{mixed_boundary}\r\n")
        parts.append(f"Content-Type: application/pdf; name={filename}\r\n")
        parts.append("Content-Transfer-Encoding: base64\r\n")
        parts.append(f"Content-Disposition: attachment; filename={filename}\r\n\r\n")
        parts.append(pdf_b64 + "\r\n")
        parts.append(f"--{mixed_boundary}--")
        raw_message = ''.join(parts).encode('utf-8')
        raw = urlsafe_b64encode(raw_message).decode('utf-8')
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        
        # Kunde automatisch speichern mit Befragungsbogen-Daten
        questionnaire_data = {
            'subject': subject,
            'body': body,
            'filename': filename,
            'lastName': data.get('lastName'),
            'sms_name': data.get('sms_name'),
            'sms_number': data.get('sms_number'),
            'sent_at': datetime.datetime.utcnow().isoformat()
        }
        print(f"DEBUG: Speichere Befragungsbogen-Daten für {to_email}: {questionnaire_data}")
        customer = save_customer_from_email(to_email, questionnaire_data=questionnaire_data)
        print(f"DEBUG: Kunde gespeichert: {customer}")
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Senden fehlgeschlagen: {str(e)}"}), 500

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

    # E-Mail senden (bestehende Logik wiederverwenden)
    try:
        creds = load_user_gmail_credentials(session['user'])
        if not creds:
            return jsonify({"error": "Kein Gmail-Konto verbunden."}), 400
        service = build('gmail', 'v1', credentials=creds)
        subject = payload.get('subject') or "Befragungsbogen"
        body = payload.get('body') or (
            "Hallo,\n\n" 
            "anbei befindet sich der Befragungsbogen.\n\n"
            "Mit besten Grüßen"
        )
        # HTML/TXT
        body_html_final = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
            (body or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') +
            "</div>"
        )
        body_text_final = body
        mixed_boundary = 'mixed_boundary'
        alt_boundary = 'alt_boundary'
        parts = []
        parts.append(f"Content-Type: multipart/mixed; boundary={mixed_boundary}\r\n")
        parts.append("MIME-Version: 1.0\r\n")
        parts.append(f"to: {to_email}\r\n")
        parts.append(f"subject: {subject}\r\n\r\n")
        parts.append(f"--{mixed_boundary}\r\n")
        parts.append(f"Content-Type: multipart/alternative; boundary={alt_boundary}\r\n\r\n")
        parts.append(f"--{alt_boundary}\r\n")
        parts.append("Content-Type: text/plain; charset=UTF-8\r\n\r\n")
        parts.append(body_text_final + "\r\n\r\n")
        parts.append(f"--{alt_boundary}\r\n")
        parts.append("Content-Type: text/html; charset=UTF-8\r\n\r\n")
        parts.append(body_html_final + "\r\n\r\n")
        parts.append(f"--{alt_boundary}--\r\n")
        parts.append(f"--{mixed_boundary}\r\n")
        parts.append(f"Content-Type: application/pdf; name={filename}\r\n")
        parts.append("Content-Transfer-Encoding: base64\r\n")
        parts.append(f"Content-Disposition: attachment; filename={filename}\r\n\r\n")
        parts.append(pdf_b64 + "\r\n")
        parts.append(f"--{mixed_boundary}--")
        raw_message = ''.join(parts).encode('utf-8')
        raw = urlsafe_b64encode(raw_message).decode('utf-8')
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        
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
    except Exception as e:
        return jsonify({"error": f"Senden fehlgeschlagen: {str(e)}"}), 500

# 📧 Gmail API
@app.route("/api/emails")
def get_emails():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    # Backward-compat: support either cred_id (preferred) or 1..3 slot index
    cred_id_param = request.args.get('cred_id')
    slot_param = request.args.get('slot')

    try:
        cred_row = None
        if cred_id_param:
            try:
                cred_id_int = int(cred_id_param)
            except Exception:
                return jsonify({"error": "Ungültige cred_id"}), 400
            cred_row = GmailCredential.query.filter_by(id=cred_id_int, username=session['user']).first()
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
    except Exception as e:
        return jsonify({"error": f"Fehler bei Gmail API: {str(e)}"}), 500

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

# 📧 Ungelesene Nachrichten zählen (pro Slot oder cred_id)
@app.route('/api/emails/unread_count')
def unread_count():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    cred_id_param = request.args.get('cred_id')
    slot_param = request.args.get('slot')

    try:
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
            })
        except Exception:
            continue
    return jsonify(accounts)


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
            body = data.get('body') or (
                f"Hallo,\n\n"
                f"anbei befindet sich der Befragungsbogen für Kunden-ID: {customer_id}\n\n"
                f"Mit besten Grüßen"
            )
        else:
            body = data.get('body') or (
                "Hallo,\n\n" 
                "anbei befindet sich der Befragungsbogen.\n\n"
                "Mit besten Grüßen"
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

    # Load credentials with send scope if possible
    creds = load_user_gmail_credentials(session['user'])
    if not creds:
        return jsonify({"error": "Kein Gmail-Konto verbunden."}), 400
    try:
        service = build('gmail', 'v1', credentials=creds)

        # Try to fetch Gmail signature (HTML) and append to message
        signature_html = None
        try:
            settings = service.users().settings().sendAs().list(userId='me').execute() or {}
            send_as_list = settings.get('sendAs', []) or []
            primary = None
            for sa in send_as_list:
                if sa.get('isPrimary') or sa.get('isDefault'):
                    primary = sa
                    break
            if not primary and send_as_list:
                primary = send_as_list[0]
            if primary:
                signature_html = (primary.get('signature') or '').strip() or None
        except Exception:
            signature_html = None

        # Prepare text and HTML bodies
        def html_to_text(html:str) -> str:
            try:
                # basic tag replacement for line breaks
                repl = html.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
                import re
                repl = re.sub(r'<[^>]+>', '', repl)
                # unescape common entities
                repl = repl.replace('&nbsp;', ' ').replace('&amp;', '&')
                return repl
            except Exception:
                return ''

        body_text_final = body
        body_html_final = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
            (body or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') +
            "</div>"
        )
        if signature_html:
            sig_text = html_to_text(signature_html).strip()
            if sig_text:
                body_text_final = body_text_final.rstrip() + "\n\n" + sig_text
            body_html_final = body_html_final + "<div>" + signature_html + "</div>"

        # Prüfe ob es sich um einen Befragungsbogen handelt (vor E-Mail-Versand)
        is_questionnaire = (
            'befragungsbogen' in filename.lower() or 
            'befragungsbogen' in subject.lower() or
            'befragungsbogen' in body.lower()
        )

        # Build MIME message with multipart/alternative (text + HTML) and PDF attachment
        mixed_boundary = 'mixed_boundary'
        alt_boundary = 'alt_boundary'
        message_parts = []
        message_parts.append(f"Content-Type: multipart/mixed; boundary={mixed_boundary}\r\n")
        message_parts.append(f"MIME-Version: 1.0\r\n")
        
        # Für Befragungsbogen: BCC an alle Kooperationspartner
        if is_questionnaire:
            partners = Kooperationspartner.query.all()
            bcc_emails = [partner.email for partner in partners]
            if bcc_emails:
                message_parts.append(f"bcc: {', '.join(bcc_emails)}\r\n")
                print(f"DEBUG: Sende Befragungsbogen per BCC an: {bcc_emails}")
        
        message_parts.append(f"to: {to_email}\r\n")
        message_parts.append(f"subject: {subject}\r\n\r\n")
        # Alternative part (text + HTML)
        message_parts.append(f"--{mixed_boundary}\r\n")
        message_parts.append(f"Content-Type: multipart/alternative; boundary={alt_boundary}\r\n\r\n")
        # Text
        message_parts.append(f"--{alt_boundary}\r\n")
        message_parts.append("Content-Type: text/plain; charset=UTF-8\r\n\r\n")
        message_parts.append(body_text_final + "\r\n\r\n")
        # HTML
        message_parts.append(f"--{alt_boundary}\r\n")
        message_parts.append("Content-Type: text/html; charset=UTF-8\r\n\r\n")
        message_parts.append(body_html_final + "\r\n\r\n")
        # End alternative
        message_parts.append(f"--{alt_boundary}--\r\n")
        # Attachment part
        message_parts.append(f"--{mixed_boundary}\r\n")
        message_parts.append(f"Content-Type: application/pdf; name={filename}\r\n")
        message_parts.append("Content-Transfer-Encoding: base64\r\n")
        message_parts.append(f"Content-Disposition: attachment; filename={filename}\r\n\r\n")
        # Strip header if present
        if pdf_b64.startswith('data:application/pdf;base64,'):
            pdf_b64 = pdf_b64.split(',', 1)[1]
        message_parts.append(pdf_b64 + "\r\n")
        message_parts.append(f"--{mixed_boundary}--")
        raw_message = ''.join(message_parts).encode('utf-8')
        raw = urlsafe_b64encode(raw_message).decode('utf-8')
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        
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
            
            # Für Befragungsbogen: Speichere ohne spezifische E-Mail (da per BCC versendet)
            # Lade alle Kooperationspartner für BCC
            partners = Kooperationspartner.query.all()
            bcc_emails = [partner.email for partner in partners]
            print(f"DEBUG: BCC an Kooperationspartner: {bcc_emails}")
            
            # Speichere mit BCC-Information
            questionnaire_data['bcc_recipients'] = bcc_emails
            
            # Wenn eine Kunden-ID ausgewählt ist, Daten zu diesem Kunden hinzufügen
            if customer_id:
                try:
                    # Bestehenden Kunden laden
                    customer = Customer.query.filter_by(id=int(customer_id)).first()
                    if customer:
                        # Befragungsbogen-Daten zu bestehendem Kunden hinzufügen
                        customer.questionnaire_data_json = json.dumps(questionnaire_data)
                        db.session.commit()
                        print(f"DEBUG: Befragungsbogen-Daten zu bestehendem Kunden {customer_id} hinzugefügt")
                    else:
                        print(f"DEBUG: Kunde {customer_id} nicht gefunden, erstelle neuen Kunden")
                        save_customer_from_email('befragungsbogen@helpcare.de', 'Befragungsbogen', questionnaire_data=questionnaire_data)
                except Exception as e:
                    print(f"DEBUG: Fehler beim Hinzufügen zu bestehendem Kunden: {e}")
                    save_customer_from_email('befragungsbogen@helpcare.de', 'Befragungsbogen', questionnaire_data=questionnaire_data)
            else:
                # Kein Kunde ausgewählt - neuen Kunden erstellen
                save_customer_from_email('befragungsbogen@helpcare.de', 'Befragungsbogen', questionnaire_data=questionnaire_data)
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
    except Exception as e:
        return jsonify({"error": f"Senden fehlgeschlagen: {str(e)}"}), 500

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
    
    # Load credentials
    creds = load_user_gmail_credentials(session['user'])
    if not creds:
        return jsonify({"error": "Kein Gmail-Konto verbunden."}), 400
    
    try:
        service = build('gmail', 'v1', credentials=creds)
        
        # Prepare email content
        body_text_final = body or "Hallo,\n\nhier ist eine Erinnerung von HelpCare.\n\nMit besten Grüßen\nTeam HelpCare"
        body_html_final = (
            "<div style=\"font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap\">" +
            (body_text_final or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') +
            "</div>"
        )
        
        # Try to get signature
        try:
            settings = service.users().settings().sendAs().list(userId='me').execute() or {}
            send_as_list = settings.get('sendAs', []) or []
            primary = None
            for sa in send_as_list:
                if sa.get('isPrimary') or sa.get('isDefault'):
                    primary = sa
                    break
            if not primary and send_as_list:
                primary = send_as_list[0]
            if primary:
                signature_html = (primary.get('signature') or '').strip() or None
                if signature_html:
                    body_html_final += signature_html
        except Exception:
            pass
        
        # Create message
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        
        # Für Kooperationspartner immer team@helpcare.de verwenden
        message['From'] = 'team@helpcare.de'
        
        # Add BCC recipients
        bcc_emails = [partner['email'] for partner in partners]
        message['Bcc'] = ', '.join(bcc_emails)
        
        # Add text and HTML parts
        text_part = MIMEText(body_text_final, 'plain', 'utf-8')
        html_part = MIMEText(body_html_final, 'html', 'utf-8')
        
        message.attach(text_part)
        message.attach(html_part)
        
        # Send email
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        return jsonify({"success": True, "sent_to": len(partners)})
        
    except Exception as e:
        return jsonify({"error": f"Senden fehlgeschlagen: {str(e)}"}), 500

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

    if request.method == 'GET':
        notes = TeamNote.query.order_by(TeamNote.id.asc()).limit(500).all()
        return jsonify([n.to_dict() for n in notes])

    payload = request.get_json() or {}
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

# 👥 Kundenverwaltung API
@app.route('/api/customers', methods=['GET', 'POST'])
def customers():
    if request.method == 'GET':
        customers = Customer.query.order_by(Customer.created_at.desc()).all()
        return jsonify([customer.to_dict() for customer in customers])
    
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
            company=data.get('company'),
            notes=data.get('notes'),
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
        return jsonify(customer.to_dict())
    
    elif request.method == 'PUT':
        data = request.get_json()
        
        customer.name = data.get('name', customer.name)
        customer.email = data.get('email', customer.email)
        customer.phone = data.get('phone', customer.phone)
        customer.company = data.get('company', customer.company)
        customer.notes = data.get('notes', customer.notes)
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
        db.session.delete(customer)
        db.session.commit()
        return jsonify({"success": True})

# Automatisches Speichern von Kunden beim Angebot versenden
def save_customer_from_email(email_address, customer_name=None, offer_data=None, questionnaire_data=None):
    """Speichert automatisch einen Kunden basierend auf E-Mail-Adresse"""
    print(f"DEBUG: save_customer_from_email aufgerufen mit email={email_address}, questionnaire_data={questionnaire_data}")
    if not email_address:
        print("DEBUG: Keine E-Mail-Adresse, breche ab")
        return None
    
    import json
    
    # Prüfen ob Kunde bereits existiert
    existing_customer = Customer.query.filter_by(email=email_address).first()
    if existing_customer:
        # Letzten Kontakt aktualisieren
        existing_customer.last_contact = datetime.datetime.utcnow()
        
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
        
        db.session.commit()
        return existing_customer
    
    # Neuen Kunden erstellen
    customer = Customer(
        name=customer_name or email_address.split('@')[0],  # Fallback: Teil vor @
        email=email_address
    )
    
    # Angebot-Daten hinzufügen
    if offer_data:
        customer.offer_data_json = json.dumps(offer_data)
        customer.add_contact_entry('offer_sent', offer_data)
    
    # Befragungsbogen-Daten hinzufügen
    if questionnaire_data:
        customer.questionnaire_data_json = json.dumps(questionnaire_data)
        customer.add_contact_entry('questionnaire_sent', questionnaire_data)
    
    db.session.add(customer)
    db.session.commit()
    return customer

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
    
    db.session.commit()
    return jsonify(customer.to_dict())

# Kooperationspartner API
@app.route('/api/kooperationspartner', methods=['GET'])
def get_kooperationspartner():
    try:
        partners = Kooperationspartner.query.order_by(Kooperationspartner.name).all()
        return jsonify([partner.to_dict() for partner in partners])
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
            emergency_phone=data.get('emergency_phone', '').strip()
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
            
            db.session.commit()
            return jsonify(partner.to_dict())
        except Exception as e:
            return jsonify({"error": f"Fehler beim Aktualisieren: {str(e)}"}), 500
    
    elif request.method == 'DELETE':
        try:
            db.session.delete(partner)
            db.session.commit()
            return jsonify({"success": True})
        except Exception as e:
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
        # Alle Verträge holen, bei denen der Partner entweder Sender oder Receiver ist
        contracts = Kooperationsvertrag.query.filter(
            (Kooperationsvertrag.sender_partner_id == partner_id) | 
            (Kooperationsvertrag.receiver_partner_id == partner_id)
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

# 📋 Kooperationsvertrag API
@app.route('/api/kooperationsvertraege', methods=['GET', 'POST'])
def kooperationsvertraege():
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    if request.method == 'GET':
        contracts = Kooperationsvertrag.query.order_by(Kooperationsvertrag.created_at.desc()).all()
        return jsonify([contract.to_dict() for contract in contracts])
    
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
        # Template laden
        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'kooperationsvertrag.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Variablen ersetzen
        replacements = {
            '[Firmenname des Dienstleisters]': sender_partner.company_name or sender_partner.name,
            '[Straße]': sender_partner.street_address.split(',')[0] if sender_partner.street_address else '',
            '[PLZ]': sender_partner.street_address.split(',')[1].strip().split(' ')[0] if sender_partner.street_address and ',' in sender_partner.street_address else '',
            '[Ort]': sender_partner.street_address.split(',')[1].strip().split(' ')[1] if sender_partner.street_address and ',' in sender_partner.street_address and len(sender_partner.street_address.split(',')[1].strip().split(' ')) > 1 else '',
            '[Land]': 'Deutschland',
            '[Vertretungsberechtigte]': sender_partner.managing_director or '',
            '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y')
        }
        
        # Alle Variablen ersetzen
        for placeholder, value in replacements.items():
            html_content = html_content.replace(placeholder, str(value))
        
        # PDF generieren mit weasyprint
        try:
            from weasyprint import HTML, CSS
            from weasyprint.text.fonts import FontConfiguration
            
            font_config = FontConfiguration()
            html_doc = HTML(string=html_content)
            css = CSS(string='@page { size: A4; margin: 1.5cm; }', font_config=font_config)
            
            # PDF-Dateiname generieren
            pdf_filename = f"kooperationsvertrag_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
            
            html_doc.write_pdf(pdf_path, stylesheets=[css], font_config=font_config)
            
            # Contract aktualisieren
            contract.pdf_filename = pdf_filename
            db.session.commit()
            
            return jsonify({
                "success": True,
                "pdf_filename": pdf_filename,
                "pdf_url": f"/uploads/{pdf_filename}"
            })
            
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
            
    except Exception as e:
        return jsonify({"error": f"Fehler beim Laden des Templates: {str(e)}"}), 500

@app.route('/api/kooperationsvertraege/<int:contract_id>/send-docuseal', methods=['POST'])
def send_kooperationsvertrag_docuseal(contract_id):
    """Kooperationsvertrag zur Signatur per E-Mail senden"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Kooperationsvertrag.query.get_or_404(contract_id)
    sender_partner = Kooperationspartner.query.get(contract.sender_partner_id)
    receiver_partner = Kooperationspartner.query.get(contract.receiver_partner_id)
    
    if not sender_partner or not receiver_partner:
        return jsonify({"error": "Sender oder Receiver Partner nicht gefunden"}), 404

    if not contract.pdf_filename:
        try:
            # PDF generieren durch direkten Aufruf der Logik
            template_path = os.path.join(os.path.dirname(__file__), 'templates', 'kooperationsvertrag.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Variablen ersetzen
            replacements = {
                '[Firmenname des Dienstleisters]': sender_partner.company_name or sender_partner.name,
                '[Straße]': sender_partner.street_address.split(',')[0] if sender_partner.street_address else '',
                '[PLZ]': sender_partner.street_address.split(',')[1].strip().split(' ')[0] if sender_partner.street_address and ',' in sender_partner.street_address else '',
                '[Ort]': sender_partner.street_address.split(',')[1].strip().split(' ')[1] if sender_partner.street_address and ',' in sender_partner.street_address and len(sender_partner.street_address.split(',')[1].strip().split(' ')) > 1 else '',
                '[Land]': 'Deutschland',
                '[Vertretungsberechtigte]': sender_partner.managing_director or '',
                '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y')
            }
            
            # Alle Variablen ersetzen
            for placeholder, value in replacements.items():
                html_content = html_content.replace(placeholder, str(value))
            
            # PDF generieren
            from weasyprint import HTML, CSS
            from weasyprint.text.fonts import FontConfiguration
            
            font_config = FontConfiguration()
            html_doc = HTML(string=html_content)
            css = CSS(string='@page { size: A4; margin: 1.5cm; }', font_config=font_config)
            
            # PDF-Dateiname generieren
            pdf_filename = f"kooperationsvertrag_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
            
            html_doc.write_pdf(pdf_path, stylesheets=[css], font_config=font_config)
            
            # Contract aktualisieren
            contract.pdf_filename = pdf_filename
            db.session.commit()
            
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
    sender_partner = Kooperationspartner.query.get(contract.sender_partner_id)
    
    # Lade Template
    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'kooperationsvertrag.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Ersetze Variablen
    if sender_partner:
        replacements = {
            '[Firmenname des Dienstleisters]': sender_partner.company_name or sender_partner.name,
            '[Straße]': sender_partner.street_address.split(',')[0] if sender_partner.street_address else '',
            '[PLZ]': sender_partner.street_address.split(',')[1].strip().split(' ')[0] if sender_partner.street_address and ',' in sender_partner.street_address else '',
            '[Ort]': sender_partner.street_address.split(',')[1].strip().split(' ')[1] if sender_partner.street_address and ',' in sender_partner.street_address and len(sender_partner.street_address.split(',')[1].strip().split(' ')) > 1 else '',
            '[Land]': 'Deutschland',
            '[Vertretungsberechtigte]': sender_partner.managing_director or '',
            '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y')
        }
        
        for placeholder, value in replacements.items():
            html_content = html_content.replace(placeholder, str(value))
    
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
        contracts = Dienstleistungsvertrag.query.order_by(Dienstleistungsvertrag.created_at.desc()).all()
        return jsonify([contract.to_dict() for contract in contracts])
    
    elif request.method == 'POST':
        data = request.get_json() or {}
        
        customer_id = data.get('customer_id')
        kooperationspartner_id = data.get('kooperationspartner_id')
        contract_number = data.get('contract_number')
        
        if not all([customer_id, kooperationspartner_id, contract_number]):
            return jsonify({"error": "Kunden-ID, Kooperationspartner-ID und Vertragsnummer sind erforderlich"}), 400
        
        try:
            # Kunde laden für Ort
            customer = Customer.query.get(customer_id)
            
            contract = Dienstleistungsvertrag(
                customer_id=customer_id,
                kooperationspartner_id=kooperationspartner_id,
                contract_number=contract_number,
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
        # Template laden
        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dienstleistungsvertrag.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Variablen ersetzen
        replacements = {
            '[Auftragsnummer]': contract.contract_number,
            '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
            '[Vorname Name]': customer.name,
            '[Straße Hausnummer]': customer.street_address or '',
            '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
            '[Telefon]': customer.phone or '',
            '[E-Mail]': customer.email or '',
            '[Firmenname]': partner.company_name or partner.name,
            '[Adresse]': partner.street_address or '',
            '[Telefon]': partner.phone or '',
            '[E-Mail]': partner.email or '',
            '[Identifikationsnummer]': partner.identification_number or '',
            '[Handelsregisternummer]': partner.commercial_register or '',
            '[Umsatzsteuer-Identifikationsnummer]': partner.vat_id or '',
            '[Name Geschäftsführer]': partner.managing_director or '',
            '[Notfalltelefon]': partner.emergency_phone or '',
            '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
            '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
            '[Ort]': customer.city or '',
            '[Partnerfirma]': partner.partner_company or partner.name
        }
        
        # Alle Variablen ersetzen
        for placeholder, value in replacements.items():
            html_content = html_content.replace(placeholder, str(value))
        
        # PDF generieren mit weasyprint
        try:
            from weasyprint import HTML, CSS
            from weasyprint.text.fonts import FontConfiguration
            
            font_config = FontConfiguration()
            html_doc = HTML(string=html_content)
            css = CSS(string='@page { size: A4; margin: 2cm; }', font_config=font_config)
            
            pdf_bytes = html_doc.write_pdf(stylesheets=[css], font_config=font_config)
            
            # PDF speichern
            pdf_filename = f"dienstleistungsvertrag_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            
            # In Datenbank speichern
            contract.pdf_filename = pdf_filename
            db.session.commit()
            
            # PDF als Base64 zurückgeben
            pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')
            
            return jsonify({
                "success": True,
                "pdf_base64": f"data:application/pdf;base64,{pdf_b64}",
                "filename": pdf_filename
            })
            
        except ImportError:
            return jsonify({"error": "weasyprint ist nicht installiert. Bitte installieren Sie es mit: pip install weasyprint"}), 500
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
            
    except Exception as e:
        return jsonify({"error": f"Fehler beim Laden des Templates: {str(e)}"}), 500

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/send-for-signature', methods=['POST'])
def send_contract_for_signature(contract_id):
    """Sendet den Dienstleistungsvertrag zur digitalen Signatur per E-Mail (wie in SignaturApp)"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not partner:
        return jsonify({"error": "Kooperationspartner nicht gefunden"}), 404
    
    # Wende die send_docuseal_signature Logik an (ohne die Funktion zu duplizieren)
    # Zuerst PDF generieren falls noch nicht vorhanden
    if not contract.pdf_filename:
        try:
            # PDF generieren durch direkten Aufruf der Logik
            template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dienstleistungsvertrag.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Variablen ersetzen
            replacements = {
                '[Auftragsnummer]': contract.contract_number,
                '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
                '[Vorname Name]': customer.name,
                '[Straße Hausnummer]': customer.street_address or '',
                '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
                '[Telefon]': customer.phone or '',
                '[E-Mail]': customer.email or '',
                '[Firmenname]': partner.company_name or partner.name,
                '[Straße, PLZ, Ort]': partner.street_address or '',
                '[Telefon]': partner.phone or '',
                '[E-Mail]': partner.email or '',
                '[Identifikationsnummer]': partner.identification_number or '',
                '[Handelsregister]': partner.commercial_register or '',
                '[USt-IdNr.]': partner.vat_id or '',
                '[Vertr. durch den Geschäftsführer]': partner.managing_director or '',
                '[Notfallkontakt]': partner.emergency_phone or '',
                '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
                '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
                '[Ort]': customer.city or ''
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
            pdf_filename = f"dienstleistungsvertrag_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            
            # In Datenbank speichern
            contract.pdf_filename = pdf_filename
            db.session.commit()
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
    
    # E-Mail mit Signatur-Link senden
    signature_url = f"{request.host_url}api/dienstleistungsvertraege/{contract_id}/sign"
    success, error_msg = send_signature_email(
        contract_id=contract_id,
        customer_email=customer.email,
        customer_name=customer.name,
        contract_type="dienstleistungsvertrag",
        signature_url=signature_url
    )
    
    if not success:
        return jsonify({"error": f"E-Mail-Versand Fehler: {error_msg}"}), 500
    
    # Status aktualisieren
    contract.status = 'sent'
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Vertrag erfolgreich zur Signatur per E-Mail gesendet"
    })

@app.route('/docusign-test')
def docusign_test_page():
    """Test-Seite für DocuSign API"""
    return render_template('zoho_test.html')

# Test-Funktion für Zoho Sign (ohne Authentifizierung für Tests)
@app.route('/api/test-zoho-sign', methods=['GET'])
def test_zoho_sign():
    """Test-Funktion für Zoho Sign API"""
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

# Variable replacements für Dienstleistungsvertrag
def get_dienstleistungsvertrag_replacements(contract, customer, partner):
    """Generiert alle Platzhalter-Ersetzungen für Dienstleistungsvertrag"""
    return {
                '[Auftragsnummer]': contract.contract_number,
                '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
                '[Vorname Name]': customer.name,
                '[Straße Hausnummer]': customer.street_address or '',
                '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
                '[Telefon]': customer.phone or '',
                '[E-Mail]': customer.email or '',
                '[Firmenname]': partner.company_name or partner.name,
                '[Straße, PLZ, Ort]': partner.street_address or '',
                '[Telefon]': partner.phone or '',
                '[E-Mail]': partner.email or '',
                '[Identifikationsnummer]': partner.identification_number or '',
                '[Handelsregister]': partner.commercial_register or '',
                '[USt-IdNr.]': partner.vat_id or '',
                '[Vertr. durch den Geschäftsführer]': partner.managing_director or '',
                '[Notfallkontakt]': partner.emergency_phone or '',
                '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
                '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
                '[Ort]': customer.city or ''
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
            pdf_filename = f"dienstleistungsvertrag_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            
            # In Datenbank speichern
            contract.pdf_filename = pdf_filename
            db.session.commit()
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
    
    try:
        # PDF-Datei laden
        pdf_path = os.path.join(UPLOAD_FOLDER, contract.pdf_filename)
        if not os.path.exists(pdf_path):
            return jsonify({"error": "PDF-Datei nicht gefunden"}), 404
        
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        # Zoho Sign API - Korrekte multipart/form-data Implementierung
        access_token = get_zoho_access_token()
        if not access_token:
            return jsonify({"error": "Zoho Access Token fehlt"}), 400
            
        api_url = 'https://sign.zoho.eu/api/v1/requests'
        headers = {
            'Authorization': f'Zoho-oauthtoken {access_token}'
            # Content-Type wird automatisch für multipart/form-data gesetzt
        }
        
        # Request-Daten für Zoho Sign (nur Datei-Upload)
        request_data = {}
        
        # Datei für Upload
        files = {
            'file': (contract.pdf_filename, pdf_bytes, 'application/pdf')
        }
        
        print(f"🔍 DEBUG: Zoho Sign API Request")
        print(f"🔍 DEBUG: URL: {api_url}")
        print(f"🔍 DEBUG: Headers: {headers}")
        print(f"🔍 DEBUG: Request Data: {request_data}")
        print(f"🔍 DEBUG: File: {contract.pdf_filename} ({len(pdf_bytes)} bytes)")
        
        # Request senden
        create_resp = requests.post(api_url, headers=headers, data=request_data, files=files, timeout=30)
        
        print(f"🔍 DEBUG: Response Status: {create_resp.status_code}")
        print(f"🔍 DEBUG: Response Headers: {dict(create_resp.headers)}")
        print(f"🔍 DEBUG: Response Text: {create_resp.text}")
        
        if create_resp.status_code >= 300:
            return jsonify({
                "error": f"Zoho Sign Request-Erstellung fehlgeschlagen (Status: {create_resp.status_code})", 
                "response": create_resp.text,
                "request_data": request_data
            }), 502
        
        create_json = create_resp.json()
        
        # Request ID extrahieren
        request_id = None
        if 'requests' in create_json and isinstance(create_json['requests'], dict):
            request_id = create_json['requests'].get('request_id')
        
        if not request_id:
            return jsonify({
                "error": "Request ID nicht erhalten", 
                "response": create_json,
                "success": False
            }), 502
        
        # Request submiten
        submit_url = f'https://sign.zoho.eu/api/v1/requests/{request_id}/submit'
        submit_resp = requests.post(submit_url, headers=headers, timeout=30)
        
        if submit_resp.status_code >= 300:
            return jsonify({"error": "Zoho Sign Request-Submit fehlgeschlagen", "response": submit_resp.text}), 502
        
        submit_json = submit_resp.json()
        
        # Status aktualisieren
        contract.status = 'sent'
        contract.zoho_request_id = request_id
        contract.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            "success": True,
            "zoho_request_id": request_id,
            "response": submit_json,
            "contract": contract.to_dict()
        })
        
    except Exception as e:
        return jsonify({"error": f"Fehler beim Senden zur Signatur: {str(e)}"}), 500

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

def send_signature_email(contract_id, customer_email, customer_name, contract_type="dienstleistungsvertrag", signature_url=None):
    """Sendet E-Mail mit Signatur-Link im schönen HTML-Design"""
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
        
        # Gmail Credentials laden
        username = session.get('user') if 'user' in session else None
        if not username:
            return False, "Keine Gmail-Credentials gefunden"
        
        gmail_cred = GmailCredential.query.filter_by(username=username).first()
        if not gmail_cred:
            return False, "Keine Gmail-Credentials gefunden"
        
        # Gmail Service aufbauen
        credentials_data = json.loads(gmail_cred.token_json)
        credentials = Credentials.from_authorized_user_info(credentials_data)
        
        service = build('gmail', 'v1', credentials=credentials)
        
        # Signatur-URL generieren (falls nicht angegeben)
        if not signature_url:
            signature_url = f"{request.host_url}api/{contract_type}s/{contract_id}/sign"
        
        # HTML-E-Mail mit schönem Design erstellen
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
        message = MIMEText(html_body, 'html')
        message['to'] = customer_email
        message['subject'] = f"{contract_type_name} {contract.contract_number} zur Unterschrift"
        message['from'] = f"HelpCare <{credentials_data.get('email', 'team@helpcare.de')}>"
        
        # E-Mail als Raw senden
        raw_message = urlsafe_b64encode(message.as_bytes()).decode()
        
        send_result = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        print(f"✅ E-Mail erfolgreich versendet an {customer_email}")
        print(f"   Message ID: {send_result['id']}")
        
        return True, None
        
    except Exception as e:
        print(f"❌ E-Mail-Versand Fehler: {str(e)}")
        return False, str(e)

# Manuelle Status-Aktualisierung für DocuSign
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/check-status', methods=['POST'])
def check_docusign_status(contract_id):
    """Prüft den Status eines DocuSign Envelopes manuell"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    
    if not contract.zoho_request_id:
        return jsonify({"error": "Keine DocuSign ID gefunden"}), 400
    
    try:
        access_token = get_docusign_token()
        if not access_token:
            return jsonify({"error": "DocuSign Token nicht verfügbar"}), 400
        
        # Envelope Status abrufen
        url = f"{DOCUSIGN_CONFIG['base_url']}/v2.1/accounts/{DOCUSIGN_CONFIG['account_id']}/envelopes/{contract.zoho_request_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            envelope_data = response.json()
            status = envelope_data.get('status')
            
            # Status aktualisieren
            if status == 'completed' and contract.status != 'signed':
                contract.status = 'signed'
                
                # Unterschriebenes Dokument herunterladen
                try:
                    signed_pdf_filename = download_signed_document(contract.zoho_request_id, contract.contract_number, "dienstleistungsvertrag")
                    if signed_pdf_filename:
                        contract.signed_pdf_filename = signed_pdf_filename
                except Exception as e:
                    print(f"⚠️ Fehler beim Herunterladen: {str(e)}")
                    
            elif status == 'declined':
                contract.status = 'declined'
            elif status == 'expired':
                contract.status = 'expired'
            
            db.session.commit()
            
            return jsonify({
                "success": True,
                "status": status,
                "message": f"Status aktualisiert: {status}"
            })
        else:
            return jsonify({"error": f"DocuSign API Fehler: {response.status_code}"}), 400
            
    except Exception as e:
        return jsonify({"error": f"Status-Prüfung fehlgeschlagen: {str(e)}"}), 500

# E-Mail Signatur-Versand Integration
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/send-docuseal', methods=['POST'])
def send_docuseal_signature(contract_id):
    """Dienstleistungsvertrag zur Signatur per E-Mail senden"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not partner:
        return jsonify({"error": "Kooperationspartner nicht gefunden"}), 404
    
    # Zuerst PDF generieren falls noch nicht vorhanden
    if not contract.pdf_filename:
        try:
            # PDF generieren durch direkten Aufruf der Logik
            template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dienstleistungsvertrag.html')
            with open(template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Variablen ersetzen
            replacements = {
                '[Auftragsnummer]': contract.contract_number,
                '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
                '[Vorname Name]': customer.name,
                '[Straße Hausnummer]': customer.street_address or '',
                '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
                '[Telefon]': customer.phone or '',
                '[E-Mail]': customer.email or '',
                '[Firmenname]': partner.company_name or partner.name,
                '[Straße, PLZ, Ort]': partner.street_address or '',
                '[Telefon]': partner.phone or '',
                '[E-Mail]': partner.email or '',
                '[Identifikationsnummer]': partner.identification_number or '',
                '[Handelsregister]': partner.commercial_register or '',
                '[USt-IdNr.]': partner.vat_id or '',
                '[Vertr. durch den Geschäftsführer]': partner.managing_director or '',
                '[Notfallkontakt]': partner.emergency_phone or '',
                '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
                '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
                '[Ort]': customer.city or ''
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
            pdf_filename = f"dienstleistungsvertrag_{contract.contract_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            
            # In Datenbank speichern
            contract.pdf_filename = pdf_filename
            db.session.commit()
        except Exception as e:
            return jsonify({"error": f"PDF-Generierung fehlgeschlagen: {str(e)}"}), 500
    
    # E-Mail mit Signatur-Link senden
    signature_url = f"{request.host_url}api/dienstleistungsvertraege/{contract_id}/sign"
    success, error_msg = send_signature_email(
        contract_id=contract_id,
        customer_email=customer.email,
        customer_name=customer.name,
        contract_type="dienstleistungsvertrag",
        signature_url=signature_url
    )
    
    if not success:
        return jsonify({"error": f"E-Mail-Versand Fehler: {error_msg}"}), 500
    
    # Status aktualisieren
    contract.status = 'sent'
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Vertrag erfolgreich zur Signatur per E-Mail gesendet"
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
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/send-for-signature', methods=['POST'])
def send_contract_for_signature_alternative(contract_id):
    """Vertrag als PDF mit Signatur-Feldern generieren und per E-Mail senden"""
    if "user" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401
    
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer:
        return jsonify({"error": "Kunde nicht gefunden"}), 404
    
    if not partner:
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
                    <p>""" + (partner.company_name or partner.name) + """</p>
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
            '[Telefon]': customer.phone or '',
            '[E-Mail]': customer.email or '',
            '[Firmenname]': partner.company_name or partner.name,
            '[Adresse]': partner.street_address or '',
            '[Telefon]': partner.phone or '',
            '[E-Mail]': partner.email or '',
            '[Identifikationsnummer]': partner.identification_number or '',
            '[Handelsregisternummer]': partner.commercial_register or '',
            '[Umsatzsteuer-Identifikationsnummer]': partner.vat_id or '',
            '[Name Geschäftsführer]': partner.managing_director or '',
            '[Notfalltelefon]': partner.emergency_phone or '',
            '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
            '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
            '[Ort]': customer.city or '',
            '[Partnerfirma]': partner.partner_company or partner.name
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
    partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    if not customer or not partner:
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
                    <p>""" + (partner.company_name or partner.name) + """</p>
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
            '[Telefon]': customer.phone or '',
            '[E-Mail]': customer.email or '',
            '[Firmenname]': partner.company_name or partner.name,
            '[Adresse]': partner.street_address or '',
            '[Telefon]': partner.phone or '',
            '[E-Mail]': partner.email or '',
            '[Identifikationsnummer]': partner.identification_number or '',
            '[Handelsregisternummer]': partner.commercial_register or '',
            '[Umsatzsteuer-Identifikationsnummer]': partner.vat_id or '',
            '[Name Geschäftsführer]': partner.managing_director or '',
            '[Notfalltelefon]': partner.emergency_phone or '',
            '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
            '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
            '[Ort]': customer.city or '',
            '[Partnerfirma]': partner.partner_company or partner.name
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

def add_signature_script(html, contract_id=None, contract_type=None):
    """Fügt JavaScript für Signatur-Funktionalität hinzu"""
    
    # API-URLs
    if contract_id and contract_type:
        api_url = f'/api/{contract_type}/{contract_id}/save-signature'
    else:
        api_url = '/api/save-signature'
    
    # Konvertiere contract_id zu int oder null
    contract_id_js = contract_id if contract_id else 'null'
    
    # Verwende normale String-Konkatenation statt f-string
    signature_script = """
    <script>
        const CONTRACT_ID = """ + str(contract_id_js) + """;
        const CONTRACT_TYPE = '""" + (contract_type or '') + """';
        const API_URL = '""" + api_url + """';
        function initSignature() {
            const placeholder = document.getElementById('signature-placeholder');
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
@app.route('/api/dienstleistungsvertraege/<int:contract_id>/sign', methods=['GET'])
def sign_dienstleistungsvertrag(contract_id):
    """Zeigt den Dienstleistungsvertrag zur Signatur an"""
    contract = Dienstleistungsvertrag.query.get_or_404(contract_id)
    customer = Customer.query.get(contract.customer_id)
    partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
    
    # Lade Template
    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dienstleistungsvertrag.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Ersetze Variablen
    if customer and partner:
        replacements = {
            '[Auftragsnummer]': contract.contract_number,
            '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
            '[Vorname Name]': customer.name,
            '[Straße Hausnummer]': customer.street_address or '',
            '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
            '[Telefon]': customer.phone or '',
            '[E-Mail]': customer.email or '',
            '[Firmenname]': partner.company_name or partner.name,
            '[Straße, PLZ, Ort]': partner.street_address or '',
            '[Telefon]': partner.phone or '',
            '[E-Mail]': partner.email or '',
            '[Identifikationsnummer]': partner.identification_number or '',
            '[Handelsregister]': partner.commercial_register or '',
            '[USt-IdNr.]': partner.vat_id or '',
            '[Vertr. durch den Geschäftsführer]': partner.managing_director or '',
            '[Notfallkontakt]': partner.emergency_phone or '',
            '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
            '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
            '[Ort]': customer.city or ''
        }
        
        for placeholder, value in replacements.items():
            html_content = html_content.replace(placeholder, str(value))
    
    # Prüfe ob bereits signiert (wie in SignaturApp) - WICHTIG: NACH Variablen ersetzung
    if contract.status == 'signed' and contract.signature_data:
        # Vertrag bereits signiert - ersetze placeholder durch Signatur-Bild
        signature_img = f'<div style="margin-top: 20px; text-align: center;"><img src="{contract.signature_data}" style="max-width: 300px; height: auto; display: block; margin: 10px auto;" /></div>'
        html_content = html_content.replace('<div id="signature-placeholder"></div>', signature_img)
    
    # Füge Signatur-Skript hinzu (von SignaturApp) mit contract_id
    html_content = add_signature_script(html_content, contract_id, "dienstleistungsvertraege")
    
    return html_content

@app.route('/api/dienstleistungsvertraege/<int:contract_id>/save-signature', methods=['POST'])
def save_dienstleistungsvertrag_signature(contract_id):
    """Speichert die Signatur eines Dienstleistungsvertrags und erstellt PDF"""
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

def create_signed_contract_pdf(contract, signature_data, contract_type):
    """Erstellt ein PDF mit eingefügter Signatur"""
    try:
        # Lade Template
        template_name = "dienstleistungsvertrag.html" if contract_type == "dienstleistungsvertrag" else "kooperationsvertrag.html"
        template_path = os.path.join(os.path.dirname(__file__), 'templates', template_name)
        
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Variablen ersetzen
        if contract_type == "dienstleistungsvertrag":
            customer = Customer.query.get(contract.customer_id)
            partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
            
            if customer and partner:
                replacements = {
                    '[Auftragsnummer]': contract.contract_number,
                    '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y'),
                    '[Vorname Name]': customer.name,
                    '[Straße Hausnummer]': customer.street_address or '',
                    '[PLZ Ort]': f"{customer.postal_code or ''} {customer.city or ''}".strip(),
                    '[Telefon]': customer.phone or '',
                    '[E-Mail]': customer.email or '',
                    '[Firmenname]': partner.company_name or partner.name,
                    '[Straße, PLZ, Ort]': partner.street_address or '',
                    '[Telefon]': partner.phone or '',
                    '[E-Mail]': partner.email or '',
                    '[Identifikationsnummer]': partner.identification_number or '',
                    '[Handelsregister]': partner.commercial_register or '',
                    '[USt-IdNr.]': partner.vat_id or '',
                    '[Vertr. durch den Geschäftsführer]': partner.managing_director or '',
                    '[Notfallkontakt]': partner.emergency_phone or '',
                    '[Betrag]': str(contract.monthly_rate) if contract.monthly_rate else '',
                    '[Tagessatz]': str(round(contract.monthly_rate / 30, 2)) if contract.monthly_rate else '',
                    '[Ort]': customer.city or ''
                }
                
                for placeholder, value in replacements.items():
                    html_content = html_content.replace(placeholder, str(value))
        else:
            # Kooperationsvertrag
            sender_partner = Kooperationspartner.query.get(contract.sender_partner_id)
            
            if sender_partner:
                replacements = {
                    '[Firmenname des Dienstleisters]': sender_partner.company_name or sender_partner.name,
                    '[Straße]': sender_partner.street_address.split(',')[0] if sender_partner.street_address else '',
                    '[PLZ]': sender_partner.street_address.split(',')[1].strip().split(' ')[0] if sender_partner.street_address and ',' in sender_partner.street_address else '',
                    '[Ort]': sender_partner.street_address.split(',')[1].strip().split(' ')[1] if sender_partner.street_address and ',' in sender_partner.street_address and len(sender_partner.street_address.split(',')[1].strip().split(' ')) > 1 else '',
                    '[Land]': 'Deutschland',
                    '[Vertretungsberechtigte]': sender_partner.managing_director or '',
                    '[Datum]': contract.contract_date.strftime('%d.%m.%Y') if contract.contract_date else datetime.datetime.now().strftime('%d.%m.%Y')
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
        html_doc.write_pdf(pdf_path, stylesheets=[css], font_config=font_config)
        
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
    
    return send_file(pdf_path, as_attachment=True, download_name=contract.signed_pdf_filename)

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
