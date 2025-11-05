// Navigation
function showSection(section) {
    // Update active nav button
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.textContent.trim() === (section === 'templates' ? 'Templates' : 'Verträge')) {
            btn.classList.add('active');
        }
    });
    
    // Show/hide sections
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById(section + '-section').classList.add('active');
    
    // Load data
    if (section === 'templates') {
        loadTemplates();
    } else if (section === 'contracts') {
        loadContracts();
    }
}

// Load Templates
function loadTemplates() {
    fetch('/api/templates')
        .then(response => response.json())
        .then(data => {
            const container = document.getElementById('templates-list');
            container.innerHTML = '';
            
            if (data.length === 0) {
                container.innerHTML = '<p style="text-align: center; color: #666;">Keine Templates vorhanden</p>';
                return;
            }
            
            data.forEach(template => {
                const card = document.createElement('div');
                card.className = 'template-card';
                card.innerHTML = `
                    <h3>${template.name}</h3>
                    <p>Erstellt: ${new Date(template.created_at).toLocaleDateString('de-DE')}</p>
                `;
                container.appendChild(card);
            });
        })
        .catch(error => console.error('Fehler beim Laden der Templates:', error));
}

// Load Contracts
function loadContracts() {
    fetch('/api/contracts')
        .then(response => response.json())
        .then(data => {
            // Update Stats
            const total = data.length;
            const signed = data.filter(c => c.status === 'signed').length;
            document.getElementById('total-contracts').textContent = `${total} Verträge`;
            document.getElementById('signed-contracts').textContent = `${signed} unterschrieben`;
            
            const container = document.getElementById('contracts-list');
            container.innerHTML = '';
            
            if (data.length === 0) {
                container.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #666;">Keine Verträge vorhanden</td></tr>';
                return;
            }
            
            // Sortiere: Unterschriebene zuerst
            data.sort((a, b) => {
                if (a.status === 'signed' && b.status !== 'signed') return -1;
                if (a.status !== 'signed' && b.status === 'signed') return 1;
                return new Date(b.created_at) - new Date(a.created_at);
            });
            
            data.forEach(contract => {
                const row = document.createElement('tr');
                const downloadLink = contract.download_url 
                    ? `<a href="${contract.download_url}" class="btn btn-primary" style="padding: 5px 10px; font-size: 12px; text-decoration: none;">📥 Herunterladen</a>`
                    : '-';
                
                row.innerHTML = `
                    <td>${contract.customer_name}</td>
                    <td>${contract.customer_email}</td>
                    <td><span class="status-badge status-${contract.status}">${contract.status}</span></td>
                    <td>${new Date(contract.created_at).toLocaleDateString('de-DE')}</td>
                    <td>${contract.signed_at ? new Date(contract.signed_at).toLocaleDateString('de-DE') : '-'}</td>
                    <td>${downloadLink}</td>
                `;
                container.appendChild(row);
            });
        })
        .catch(error => console.error('Fehler beim Laden der Verträge:', error));
}

// Template Modal
function openTemplateModal() {
    document.getElementById('template-modal').style.display = 'block';
}

function closeTemplateModal() {
    document.getElementById('template-modal').style.display = 'none';
    document.getElementById('template-form').reset();
}

// Contract Modal
function openContractModal() {
    // Load templates for dropdown
    fetch('/api/templates')
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById('contract-template');
            select.innerHTML = '<option value="">Template auswählen...</option>';
            
            data.forEach(template => {
                const option = document.createElement('option');
                option.value = template.id;
                option.textContent = template.name;
                select.appendChild(option);
            });
        });
    
    document.getElementById('contract-modal').style.display = 'block';
}

function closeContractModal() {
    document.getElementById('contract-modal').style.display = 'none';
    document.getElementById('contract-form').reset();
}

// Close modal on outside click
window.onclick = function(event) {
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
        if (event.target === modal) {
            modal.style.display = 'none';
        }
    });
}

// Template Form Submit
document.getElementById('template-form').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const formData = new FormData();
    formData.append('name', document.getElementById('template-name').value);
    formData.append('file', document.getElementById('template-file').files[0]);
    
    fetch('/api/templates', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert('Fehler: ' + data.error);
        } else {
            alert('Template erfolgreich hochgeladen!');
            closeTemplateModal();
            loadTemplates();
        }
    })
    .catch(error => {
        console.error('Fehler:', error);
        alert('Fehler beim Hochladen des Templates');
    });
});

// Contract Form Submit
document.getElementById('contract-form').addEventListener('submit', function(e) {
    e.preventDefault();
    
    let variables;
    try {
        variables = JSON.parse(document.getElementById('variables').value);
    } catch (error) {
        alert('Ungültiges JSON-Format');
        return;
    }
    
    const data = {
        template_id: parseInt(document.getElementById('contract-template').value),
        customer_name: document.getElementById('customer-name').value,
        customer_email: document.getElementById('customer-email').value,
        variables: variables
    };
    
    fetch('/api/contracts', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert('Fehler: ' + data.error);
        } else {
            alert('Vertrag erfolgreich erstellt und versendet!');
            closeContractModal();
            loadContracts();
        }
    })
    .catch(error => {
        console.error('Fehler:', error);
        alert('Fehler beim Erstellen des Vertrags');
    });
});

// Load templates on page load
document.addEventListener('DOMContentLoaded', function() {
    loadTemplates();
});

