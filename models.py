from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='employee', nullable=False)  # 'admin' | 'manager' | 'employee'
    avatar = db.Column(db.String(512), nullable=True)
    must_reset_password = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def to_public_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'avatar': self.avatar,
            'created_at': self.created_at.isoformat()
        }


class Anfrage(db.Model):
    __tablename__ = 'anfragen'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    tel = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'tel': self.tel,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TeamNote(db.Model):
    __tablename__ = 'team_notes'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(120), nullable=True)  # optional: Nutzername aus Session
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Neu: Threading & Reaktionen
    parent_id = db.Column(db.Integer, db.ForeignKey('team_notes.id'), nullable=True)
    reactions_json = db.Column(db.Text, nullable=True, default='[]')

    def to_dict(self):
        data = {
            'id': self.id,
            'content': self.content,
            'author': self.author,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        # Optional-Felder sicher anhängen (falls Spalten in älteren DBs fehlen)
        try:
            data['parent_id'] = getattr(self, 'parent_id', None)
        except Exception:
            data['parent_id'] = None
        try:
            data['reactions'] = getattr(self, 'reactions_json', '[]')
        except Exception:
            data['reactions'] = '[]'
        return data


class GmailCredential(db.Model):
    __tablename__ = 'gmail_credentials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username = db.Column(db.String(80), nullable=True, index=True)
    token_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExchangeCredential(db.Model):
    __tablename__ = 'exchange_credentials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username = db.Column(db.String(80), nullable=True, index=True)
    token_json = db.Column(db.Text, nullable=True)  # OAuth-Token für Microsoft Graph API (optional)
    email = db.Column(db.String(255), nullable=False)  # E-Mail-Adresse des Kontos
    imap_server = db.Column(db.String(255), nullable=True)  # IMAP-Server (z.B. imap.exchange.ionos.eu)
    imap_port = db.Column(db.Integer, nullable=True, default=993)  # IMAP-Port
    imap_use_ssl = db.Column(db.Boolean, default=True)  # SSL verwenden
    password = db.Column(db.String(255), nullable=True)  # Passwort für IMAP (verschlüsselt gespeichert)
    signature = db.Column(db.Text, nullable=True)  # E-Mail-Signatur
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Kooperationspartner(db.Model):
    __tablename__ = 'kooperationspartner'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Dienstleistungsvertrag-spezifische Felder
    company_name = db.Column(db.String(255), nullable=True)  # Firmenname
    street_address = db.Column(db.String(255), nullable=True)  # Straße, PLZ, Ort
    phone = db.Column(db.String(64), nullable=True)  # Telefon
    identification_number = db.Column(db.String(100), nullable=True)  # Identifikationsnummer
    commercial_register = db.Column(db.String(100), nullable=True)  # Handelsregisternummer
    vat_id = db.Column(db.String(100), nullable=True)  # USt-IdNr.
    managing_director = db.Column(db.String(255), nullable=True)  # Name Geschäftsführer
    emergency_phone = db.Column(db.String(64), nullable=True)  # Notfalltelefon (24 Stunden)
    
    # Neue Variable: Provision (z. B. "10.5%" oder "10,5 %")
    provision = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Vertragsdaten (JSON für Flexibilität)
    contract_data_json = db.Column(db.Text, nullable=True, default='{}')
    
    def to_dict(self):
        import json
        data = {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'company_name': self.company_name,
            'street_address': self.street_address,
            'phone': self.phone,
            'identification_number': self.identification_number,
            'commercial_register': self.commercial_register,
            'vat_id': self.vat_id,
            'managing_director': self.managing_director,
            'emergency_phone': self.emergency_phone,
            'provision': self.provision,
            'notes': self.notes
        }
        
        # JSON-Felder sicher parsen
        try:
            data['contract_data'] = json.loads(self.contract_data_json or '{}')
        except:
            data['contract_data'] = {}
            
        return data

class Kooperationsvertrag(db.Model):
    __tablename__ = 'kooperationsvertraege'
    
    id = db.Column(db.Integer, primary_key=True)
    sender_partner_id = db.Column(db.Integer, db.ForeignKey('kooperationspartner.id'), nullable=False, index=True)  # Partner der den Vertrag sendet
    receiver_partner_id = db.Column(db.Integer, db.ForeignKey('kooperationspartner.id'), nullable=False, index=True)  # Partner der den Vertrag erhält
    contract_number = db.Column(db.String(100), nullable=False)
    contract_date = db.Column(db.DateTime, default=datetime.utcnow)
    contract_location = db.Column(db.String(255), nullable=True)  # Ort des Vertrags
    custom_html = db.Column(db.Text, nullable=True)  # Benutzerdefinierter Vertragsinhalt
    
    # Status des Vertrags
    status = db.Column(db.String(50), default='draft', index=True)  # draft, sent, signed, completed
    
    # DocuSign Integration
    envelope_id = db.Column(db.String(255), nullable=True)  # DocuSign Envelope ID
    
    # PDF-Dateien
    pdf_filename = db.Column(db.String(255), nullable=True)  # Generiertes PDF
    signed_pdf_filename = db.Column(db.String(255), nullable=True)  # Unterschriebenes PDF
    signature_data = db.Column(db.Text, nullable=True)  # Signatur als Base64
    
    # Vertragsdaten (JSON für Flexibilität)
    contract_data_json = db.Column(db.Text, nullable=True, default='{}')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        import json
        data = {
            'id': self.id,
            'sender_partner_id': self.sender_partner_id,
            'receiver_partner_id': self.receiver_partner_id,
            'contract_number': self.contract_number,
            'contract_date': self.contract_date.isoformat() if self.contract_date else None,
            'contract_location': self.contract_location,
            'custom_html': self.custom_html,
            'status': self.status,
            'envelope_id': self.envelope_id,
            'pdf_filename': self.pdf_filename,
            'signed_pdf_filename': self.signed_pdf_filename,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        # JSON-Felder sicher parsen
        try:
            data['contract_data'] = json.loads(self.contract_data_json or '{}')
        except:
            data['contract_data'] = {}
            
        return data

class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    mobile_phone = db.Column(db.String(64), nullable=True)
    company = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    last_contact = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    notes = db.Column(db.Text, nullable=True)
    # Kundenstatus (z. B. "Angebot versendet", "Abgesagt", "Im Einsatz", "Inaktiv")
    status = db.Column(db.String(50), nullable=True, index=True)
    
    # Angebot-Variablen (JSON für Flexibilität)
    offer_data_json = db.Column(db.Text, nullable=True, default='{}')
    
    # Befragungsbogen-Daten
    questionnaire_data_json = db.Column(db.Text, nullable=True, default='{}')
    
    # Profilersteller-Daten (Betreuungskraft-Profile)
    profile_data_json = db.Column(db.Text, nullable=True, default='{}')
    
    # Kontakthistorie
    contact_history_json = db.Column(db.Text, nullable=True, default='[]')
    
    # Dienstleistungsvertrag-Daten
    contract_data_json = db.Column(db.Text, nullable=True, default='{}')
    
    # Vertragsspezifische Felder für einfacheren Zugriff
    street_address = db.Column(db.String(255), nullable=True)
    postal_code = db.Column(db.String(20), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    contract_number = db.Column(db.String(100), nullable=True)
    monthly_rate = db.Column(db.Float, nullable=True)
    daily_rate = db.Column(db.Float, nullable=True)

    def to_dict(self):
        import json
        data = {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'mobile_phone': self.mobile_phone,
            'company': self.company,
            'created_at': self.created_at.isoformat(),
            'last_contact': self.last_contact.isoformat(),
            'notes': self.notes,
            'status': getattr(self, 'status', None),
            'street_address': self.street_address,
            'postal_code': self.postal_code,
            'city': self.city,
            'contract_number': self.contract_number,
            'monthly_rate': self.monthly_rate,
            'daily_rate': self.daily_rate
        }
        
        # JSON-Felder sicher parsen
        try:
            offer_data = json.loads(self.offer_data_json or '{}')
            # Base64-PDF-Daten in Data-URL umwandeln für Frontend-Anzeige
            if offer_data.get('pdf_base64') and not offer_data.get('pdf_data'):
                # Wenn nur pdf_base64 vorhanden ist, in pdf_data als Data-URL umwandeln
                pdf_base64 = offer_data['pdf_base64']
                if not pdf_base64.startswith('data:'):
                    offer_data['pdf_data'] = f"data:application/pdf;base64,{pdf_base64}"
            elif offer_data.get('pdf_data') and not offer_data['pdf_data'].startswith('data:'):
                # Wenn pdf_data vorhanden ist, aber keine Data-URL, dann als Base64 behandeln
                offer_data['pdf_data'] = f"data:application/pdf;base64,{offer_data['pdf_data']}"
            data['offer_data'] = offer_data
        except Exception as e:
            print(f"⚠️ Fehler beim Parsen von offer_data_json für Kunde {self.id}: {e}")
            data['offer_data'] = {}
            
        try:
            questionnaire_data = json.loads(self.questionnaire_data_json or '{}')
            # Base64-PDF-Daten in Data-URL umwandeln für Frontend-Anzeige
            if questionnaire_data.get('pdf_base64') and not questionnaire_data.get('pdf_data'):
                # Wenn nur pdf_base64 vorhanden ist, in pdf_data als Data-URL umwandeln
                pdf_base64 = questionnaire_data['pdf_base64']
                if not pdf_base64.startswith('data:'):
                    questionnaire_data['pdf_data'] = f"data:application/pdf;base64,{pdf_base64}"
            elif questionnaire_data.get('pdf_data') and not questionnaire_data['pdf_data'].startswith('data:'):
                # Wenn pdf_data vorhanden ist, aber keine Data-URL, dann als Base64 behandeln
                questionnaire_data['pdf_data'] = f"data:application/pdf;base64,{questionnaire_data['pdf_data']}"
            data['questionnaire_data'] = questionnaire_data
        except Exception as e:
            print(f"⚠️ Fehler beim Parsen von questionnaire_data_json für Kunde {self.id}: {e}")
            data['questionnaire_data'] = {}
        
        # Profile-Daten (Liste von Profilen, analog zu Angebot/Befragungsbogen)
        try:
            raw_profile = getattr(self, 'profile_data_json', '[]') or '[]'
            parsed = json.loads(raw_profile)
            # Backwards-Kompatibilität: falls früher ein einzelnes Objekt gespeichert wurde
            if isinstance(parsed, dict):
                profiles = [parsed]
            elif isinstance(parsed, list):
                profiles = parsed
            else:
                profiles = []

            normalized_profiles = []
            for p in profiles:
                if not isinstance(p, dict):
                    continue
                profile = dict(p)
                # Base64-PDF-Daten in Data-URL umwandeln für Frontend-Anzeige
                if profile.get('pdf_base64') and not profile.get('pdf_data'):
                    pdf_base64 = profile['pdf_base64']
                    if not pdf_base64.startswith('data:'):
                        profile['pdf_data'] = f"data:application/pdf;base64,{pdf_base64}"
                elif profile.get('pdf_data') and not str(profile['pdf_data']).startswith('data:'):
                    profile['pdf_data'] = f"data:application/pdf;base64,{profile['pdf_data']}"
                normalized_profiles.append(profile)

            data['profile_data'] = normalized_profiles
        except Exception as e:
            print(f"⚠️ Fehler beim Parsen von profile_data_json für Kunde {self.id}: {e}")
            data['profile_data'] = []
            
        try:
            data['contact_history'] = json.loads(self.contact_history_json or '[]')
        except:
            data['contact_history'] = []
            
        try:
            data['contract_data'] = json.loads(self.contract_data_json or '{}')
        except:
            data['contract_data'] = {}
            
        return data
    
    def add_contact_entry(self, contact_type, details=None):
        """Fügt einen neuen Kontakteintrag hinzu"""
        import json
        try:
            history = json.loads(self.contact_history_json or '[]')
        except:
            history = []
            
        entry = {
            'type': contact_type,  # 'offer_sent', 'questionnaire_sent', 'manual_note'
            'timestamp': datetime.utcnow().isoformat(),
            'details': details or {}
        }
        
        history.append(entry)
        self.contact_history_json = json.dumps(history)
        self.last_contact = datetime.utcnow()


class Invoice(db.Model):
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False, default='entwurf', index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('kooperationspartner.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    agreed_total_amount = db.Column(db.Float, nullable=False, default=0.0)
    commission_rate = db.Column(db.Float, nullable=False, default=0.0)
    commission_mode = db.Column(db.String(20), nullable=True)  # 'percent' | 'fixed'
    commission_fixed_amount = db.Column(db.Float, nullable=True)
    commission_amount = db.Column(db.Float, nullable=False, default=0.0)
    invoice_date = db.Column(db.Date, nullable=False)
    performance_period_from = db.Column(db.Date, nullable=False)
    performance_period_to = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    reference_number = db.Column(db.String(100), nullable=True)
    subject = db.Column(db.String(255), nullable=False)
    header_text = db.Column(db.Text, nullable=True)
    positions_json = db.Column(db.Text, nullable=True, default='[]')
    payment_terms_days = db.Column(db.Integer, nullable=False, default=14)
    reverse_charge = db.Column(db.Boolean, nullable=False, default=False)
    is_locked = db.Column(db.Boolean, nullable=False, default=False)
    paid_amount = db.Column(db.Float, nullable=False, default=0.0)
    deleted = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        def _date_to_str(d):
            return d.isoformat() if d else None

        return {
            "id": str(self.id),
            "invoiceNumber": self.invoice_number,
            "status": self.status,
            "partnerId": str(self.partner_id) if self.partner_id is not None else "",
            "customerId": str(self.customer_id) if self.customer_id is not None else "",
            "agreedTotalAmount": self.agreed_total_amount or 0.0,
            "commissionRate": self.commission_rate or 0.0,
            "commissionMode": self.commission_mode,
            "commissionFixedAmount": self.commission_fixed_amount,
            "commissionAmount": self.commission_amount or 0.0,
            "invoiceDate": _date_to_str(self.invoice_date),
            "performancePeriodFrom": _date_to_str(self.performance_period_from),
            "performancePeriodTo": _date_to_str(self.performance_period_to),
            "dueDate": _date_to_str(self.due_date),
            "referenceNumber": self.reference_number,
            "subject": self.subject,
            "headerText": self.header_text or "",
            "positions": [],
            "paymentTermsDays": self.payment_terms_days,
            "reverseCharge": self.reverse_charge,
            "isLocked": self.is_locked,
            "paidAmount": self.paid_amount,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class PdfDocument(db.Model):
    __tablename__ = 'pdf_documents'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), unique=True, nullable=False)
    uploaded_by = db.Column(db.String(80), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat()
        }


class Caregiver(db.Model):
    __tablename__ = 'caregivers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    # Signierte Verträge (letzter/aktueller) – flexibel per JSON
    contract_data_json = db.Column(db.Text, nullable=True, default='{}')

    def to_dict(self):
        import json
        try:
            contract_data = json.loads(self.contract_data_json or '{}')
        except Exception:
            contract_data = {}
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'notes': self.notes,
            'contract_data': contract_data,
        }


class CustomerProposal(db.Model):
    __tablename__ = 'customer_proposals'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('kooperationspartner.id'), nullable=False, index=True)
    upload_token = db.Column(db.String(128), nullable=False, index=True, unique=True)
    original_filename = db.Column(db.String(255), nullable=True)
    stored_filename = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    uploaded_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'partner_id': self.partner_id,
            'upload_token': self.upload_token,
            'original_filename': self.original_filename,
            'stored_filename': self.stored_filename,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

class Dienstleistungsvertrag(db.Model):
    __tablename__ = 'dienstleistungsvertraege'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    kooperationspartner_id = db.Column(db.Integer, db.ForeignKey('kooperationspartner.id'), nullable=False, index=True)
    
    # Vertragsdaten
    contract_number = db.Column(db.String(100), nullable=False)
    contract_date = db.Column(db.DateTime, default=datetime.utcnow)
    monthly_rate = db.Column(db.Float, nullable=True)
    daily_rate = db.Column(db.Float, nullable=True)
    contract_location = db.Column(db.String(100), nullable=True)  # Ort der Unterschrift
    
    # Status
    status = db.Column(db.String(50), default='draft', index=True)  # draft, sent, customer_signed, partner_signed, completed
    zoho_request_id = db.Column(db.String(255), nullable=True)  # Zoho Sign Request ID
    
    # Dokumente
    pdf_filename = db.Column(db.String(255), nullable=True)
    signed_pdf_filename = db.Column(db.String(255), nullable=True)
    signature_data = db.Column(db.Text, nullable=True)  # Signatur des Kunden als Base64
    partner_signature_data = db.Column(db.Text, nullable=True)  # Signatur des Partners als Base64
    custom_html = db.Column(db.Text, nullable=True)  # Benutzerdefinierter Vertragsinhalt
    
    # Zusätzliche Daten (JSON)
    contract_data_json = db.Column(db.Text, nullable=True, default='{}')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        import json
        try:
            contract_data = json.loads(self.contract_data_json or '{}')
        except Exception:
            contract_data = {}
            
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'kooperationspartner_id': self.kooperationspartner_id,
            'contract_number': self.contract_number,
            'contract_date': self.contract_date.isoformat() if self.contract_date else None,
            'monthly_rate': self.monthly_rate,
            'daily_rate': self.daily_rate,
            'contract_location': self.contract_location,
            'status': self.status,
            'zoho_request_id': self.zoho_request_id,
            'pdf_filename': self.pdf_filename,
            'signed_pdf_filename': self.signed_pdf_filename,
            'partner_signature_data': self.partner_signature_data,
            'custom_html': self.custom_html,
            'contract_data': contract_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class CustomerNote(db.Model):
    __tablename__ = 'customer_notes'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False)  # Pflege / Gesundheit, Angehörige / Kommunikation, etc.
    text = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(120), nullable=True)  # Nutzername aus Session
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'category': self.category,
            'text': self.text,
            'author': self.author,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class FollowUp(db.Model):
    __tablename__ = 'follow_ups'
    
    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey('customer_notes.id'), nullable=True, index=True)  # Optional: kann auch ohne Notiz existieren
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)  # Für globale Abfrage
    text = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'note_id': self.note_id,
            'customer_id': self.customer_id,
            'text': self.text,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'is_completed': self.is_completed,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }