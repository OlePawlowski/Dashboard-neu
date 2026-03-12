-- SQL-Query für pgAdmin: PDF-Daten aus questionnaire_data_json extrahieren
-- Diese Query zeigt die Base64-Daten, die du dann manuell dekodieren kannst

SELECT 
    id,
    name,
    email,
    created_at,
    questionnaire_data_json::jsonb->>'filename' as pdf_filename,
    questionnaire_data_json::jsonb->>'sent_at' as sent_at,
    -- Base64-PDF-Daten extrahieren (kann sehr lang sein!)
    questionnaire_data_json::jsonb->>'pdf_data' as pdf_base64,
    -- Länge der PDF-Daten (um zu sehen, ob PDF vorhanden ist)
    length(questionnaire_data_json::jsonb->>'pdf_data') as pdf_size
FROM customers
WHERE questionnaire_data_json IS NOT NULL 
  AND questionnaire_data_json != '{}'
  AND questionnaire_data_json != ''
  AND questionnaire_data_json::jsonb->>'pdf_data' IS NOT NULL
ORDER BY created_at DESC;
