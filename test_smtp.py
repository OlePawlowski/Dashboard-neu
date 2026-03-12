#!/usr/bin/env python3
"""
Test-Skript zum Testen verschiedener SMTP-Konfigurationen für Ionos
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# SMTP-Konfiguration
smtp_server = 'smtp.ionos.de'
smtp_username = 'kontakt@helpcare.de'
smtp_password = '!dashboardE1#'
test_email = 'kontakt@helpcare.de'  # Test-E-Mail an sich selbst senden

# Verschiedene Konfigurationen zum Testen
configs = [
    {
        'name': 'Port 587 mit STARTTLS',
        'port': 587,
        'use_ssl': False,
        'use_tls': True
    },
    {
        'name': 'Port 465 mit SSL',
        'port': 465,
        'use_ssl': True,
        'use_tls': False
    },
    {
        'name': 'Port 587 ohne TLS/SSL',
        'port': 587,
        'use_ssl': False,
        'use_tls': False
    },
    {
        'name': 'Port 25 (Standard SMTP)',
        'port': 25,
        'use_ssl': False,
        'use_tls': False
    },
    {
        'name': 'Port 2525 (Alternativer Port)',
        'port': 2525,
        'use_ssl': False,
        'use_tls': True
    },
]

def test_smtp_config(config):
    """Testet eine SMTP-Konfiguration"""
    print(f"\n{'='*60}")
    print(f"Teste: {config['name']}")
    print(f"Server: {smtp_server}:{config['port']}")
    print(f"SSL: {config['use_ssl']}, TLS: {config['use_tls']}")
    print(f"{'='*60}")
    
    try:
        # E-Mail erstellen
        message = MIMEMultipart('alternative')
        message['Subject'] = f"SMTP Test - {config['name']}"
        message['From'] = smtp_username
        message['To'] = test_email
        
        text = f"Dies ist ein Test-E-Mail mit der Konfiguration:\n{config['name']}\nPort: {config['port']}\nSSL: {config['use_ssl']}\nTLS: {config['use_tls']}"
        html = f"<html><body><p>Dies ist ein Test-E-Mail mit der Konfiguration:<br><strong>{config['name']}</strong><br>Port: {config['port']}<br>SSL: {config['use_ssl']}<br>TLS: {config['use_tls']}</p></body></html>"
        
        message.attach(MIMEText(text, 'plain', 'utf-8'))
        message.attach(MIMEText(html, 'html', 'utf-8'))
        
        # SMTP-Verbindung testen
        if config['use_ssl']:
            print(f"Versuche SSL-Verbindung...")
            server = smtplib.SMTP_SSL(smtp_server, config['port'], timeout=10)
        else:
            print(f"Versuche normale Verbindung...")
            server = smtplib.SMTP(smtp_server, config['port'], timeout=10)
            if config['use_tls']:
                print(f"Starte STARTTLS...")
                server.starttls()
        
        print(f"Verbunden! Versuche Login...")
        server.login(smtp_username, smtp_password)
        print(f"Eingeloggt! Versuche E-Mail zu senden...")
        
        server.send_message(message)
        server.quit()
        
        print(f"✅ ERFOLG! E-Mail wurde erfolgreich versendet!")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Authentifizierungsfehler: {e}")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"❌ Verbindungsfehler: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"❌ SMTP-Fehler: {e}")
        return False
    except Exception as e:
        print(f"❌ Allgemeiner Fehler: {type(e).__name__}: {e}")
        return False

if __name__ == '__main__':
    print("="*60)
    print("SMTP-Konfigurationstest für Ionos")
    print("="*60)
    print(f"Server: {smtp_server}")
    print(f"Benutzername: {smtp_username}")
    print(f"Test-E-Mail an: {test_email}")
    print("="*60)
    
    successful_configs = []
    
    for config in configs:
        if test_smtp_config(config):
            successful_configs.append(config)
    
    print(f"\n{'='*60}")
    print("ZUSAMMENFASSUNG")
    print(f"{'='*60}")
    
    if successful_configs:
        print(f"\n✅ Erfolgreiche Konfigurationen ({len(successful_configs)}):")
        for config in successful_configs:
            print(f"  - {config['name']} (Port {config['port']}, SSL: {config['use_ssl']}, TLS: {config['use_tls']})")
    else:
        print("\n❌ Keine erfolgreiche Konfiguration gefunden!")
    
    print(f"\n{'='*60}")
