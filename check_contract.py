from app import app, db, Kooperationspartner, Dienstleistungsvertrag

with app.app_context():
    contract = Dienstleistungsvertrag.query.first()
    if contract:
        print(f'Vertrag ID: {contract.id}')
        print(f'Contract Number: {contract.contract_number}')
        print(f'Kooperationspartner ID: {contract.kooperationspartner_id}')
        print(f'Customer ID: {contract.customer_id}')
        
        partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
        if partner:
            print(f'\n=== Partner Daten ===')
            print(f'Name: {partner.name}')
            print(f'Email: {partner.email}')
            print(f'Company Name: {partner.company_name or partner.name}')
            print(f'Street Address: {partner.street_address or ""}')
            print(f'Phone: {partner.phone or ""}')
            print(f'Emergency Phone: {partner.emergency_phone or ""}')
            print(f'Identification Number: {partner.identification_number or ""}')
            print(f'Commercial Register: {partner.commercial_register or ""}')
            print(f'VAT ID: {partner.vat_id or ""}')
            print(f'Managing Director: {partner.managing_director or ""}')
        else:
            print(f'\n❌ Partner ID {contract.kooperationspartner_id} existiert nicht!')
            
            # Zeige den neuesten Partner
            latest_partner = Kooperationspartner.query.order_by(Kooperationspartner.id.desc()).first()
            if latest_partner:
                print(f'\nNeuester Partner ist ID {latest_partner.id}: {latest_partner.name}')
                print(f'Würde vermutlich dieser Partner verwendet werden soll')


