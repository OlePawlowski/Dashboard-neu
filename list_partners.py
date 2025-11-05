from app import app, db, Kooperationspartner

with app.app_context():
    partners = Kooperationspartner.query.all()
    print('Alle Partner:')
    for partner in partners:
        print(f'\nPartner ID: {partner.id}')
        print(f'name: {partner.name}')
        print(f'email: {partner.email}')
        print(f'company_name: {partner.company_name}')
        print(f'street_address: {partner.street_address}')
        print(f'phone: {partner.phone}')
        print(f'emergency_phone: {partner.emergency_phone}')
        print(f'identification_number: {partner.identification_number}')
        print(f'commercial_register: {partner.commercial_register}')
        print(f'vat_id: {partner.vat_id}')
        print(f'managing_director: {partner.managing_director}')


