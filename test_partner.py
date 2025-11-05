from app import app, db, Kooperationspartner, Dienstleistungsvertrag

with app.app_context():
    contract = Dienstleistungsvertrag.query.first()
    if contract:
        print(f'Vertrag verwendet Partner ID: {contract.kooperationspartner_id}')
        partner = Kooperationspartner.query.get(contract.kooperationspartner_id)
        if partner:
            print(f'\nPartner Daten für ID {partner.id}:')
            print(f'name: {partner.name}')
            print(f'email: {partner.email}')
            print(f'company_name: {partner.company_name or partner.name}')
            print(f'street_address: {partner.street_address or ""}')
            print(f'phone: {partner.phone or ""}')
            print(f'identification_number: {partner.identification_number or ""}')
            print(f'commercial_register: {partner.commercial_register or ""}')
            print(f'vat_id: {partner.vat_id or ""}')
            print(f'managing_director: {partner.managing_director or ""}')
            print(f'emergency_phone: {partner.emergency_phone or ""}')
        else:
            print('Partner nicht gefunden')
    else:
        print('Kein Vertrag gefunden')


