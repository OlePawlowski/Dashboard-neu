from app import app, db, Kooperationspartner, Dienstleistungsvertrag

with app.app_context():
    contract = Dienstleistungsvertrag.query.first()
    if contract:
        print(f'Vertrag ID {contract.id} verwendet Partner ID {contract.kooperationspartner_id}')
        
        # Finde Partner mit den richtigen Daten
        # Laut User: o.pawlowski@helpcare.de, phone: 948545948
        correct_partner = Kooperationspartner.query.filter_by(email='o.pawlowski@helpcare.de').first()
        
        if correct_partner:
            print(f'\n✅ Partner mit Email "o.pawlowski@helpcare.de" gefunden!')
            print(f'Partner ID: {correct_partner.id}')
            print(f'Name: {correct_partner.name}')
            print(f'Company Name: {correct_partner.company_name}')
            print(f'Street Address: {correct_partner.street_address}')
            print(f'Phone: {correct_partner.phone}')
            print(f'\n🔧 Update Vertrag auf Partner ID {correct_partner.id}...')
            
            contract.kooperationspartner_id = correct_partner.id
            db.session.commit()
            
            print('✅ Vertrag erfolgreich aktualisiert!')
        else:
            print('❌ Kein Partner mit der Email gefunden')
            
            # Zeige alle Partner
            print('\nAlle Partner:')
            for p in Kooperationspartner.query.all():
                print(f'  ID {p.id}: {p.name} ({p.email})')


