const form = document.getElementById("profileForm");
const pdfButton = document.getElementById("pdfButton");
const resetButton = document.getElementById("resetButton");
const customerSelect = document.getElementById("customerSelect");
const photoInput = document.getElementById("photoInput");
const photoPreview = document.getElementById("photoPreview");
const photoPlaceholder = document.getElementById("photoPlaceholder");
const editableFields = Array.from(form.querySelectorAll("[contenteditable='true']"));
const checkboxFields = Array.from(form.querySelectorAll('input[type="checkbox"]'));
const defaultPdfButtonLabel = pdfButton.textContent;
let isExportingPdf = false;
let selectedCustomerId = null;

async function loadCustomersForProfilersteller() {
  if (!customerSelect) return;
  try {
    const res = await fetch("/api/customers?per_page=500");
    if (!res.ok) throw new Error("Fehler beim Laden der Kunden");
    const data = await res.json();
    const items = Array.isArray(data) ? data : (data.items || []);
    customerSelect.innerHTML = '<option value="">Bitte Kunden wählen…</option>';
    items.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name ? `${c.name} (${c.email || "Keine E-Mail"})` : `Kunde #${c.id}`;
      customerSelect.appendChild(opt);
    });
  } catch (e) {
    console.error("Fehler beim Laden der Kunden für Profilersteller:", e);
  }
}

if (customerSelect) {
  loadCustomersForProfilersteller();
  customerSelect.addEventListener("change", () => {
    selectedCustomerId = customerSelect.value || null;
  });
}

function syncCloneState(sourceRoot, cloneRoot) {
  const sourceCheckboxes = sourceRoot.querySelectorAll('input[type="checkbox"]');
  const cloneCheckboxes = cloneRoot.querySelectorAll('input[type="checkbox"]');
  const sourcePhoto = sourceRoot.querySelector("#photoPreview");
  const clonePhoto = cloneRoot.querySelector("#photoPreview");
  const clonePlaceholder = cloneRoot.querySelector("#photoPlaceholder");

  sourceCheckboxes.forEach((checkbox, index) => {
    const cloneCheckbox = cloneCheckboxes[index];

    if (cloneCheckbox) {
      cloneCheckbox.checked = checkbox.checked;
    }
  });

  if (sourcePhoto && clonePhoto) {
    clonePhoto.src = sourcePhoto.src;
    clonePhoto.className = sourcePhoto.className;
  }

  if (clonePlaceholder) {
    clonePlaceholder.classList.toggle(
      "is-hidden",
      Boolean(sourcePhoto && sourcePhoto.classList.contains("is-visible"))
    );
  }
}

function setPlainTextContent(element, value) {
  element.textContent = value;
}

function resetEditableFields() {
  editableFields.forEach((field) => {
    setPlainTextContent(field, field.dataset.default || "");
  });
}

function resetCheckboxes() {
  checkboxFields.forEach((checkbox) => {
    checkbox.checked = true;
  });
}

function clearPhoto() {
  photoPreview.removeAttribute("src");
  photoPreview.classList.remove("is-visible");
  photoPlaceholder.classList.remove("is-hidden");
  photoInput.value = "";
}

function updatePhotoPreview(dataUrl) {
  // Original-Bild verwenden, Rahmen passt sich dem Seitenverhältnis an
  photoPreview.src = dataUrl;
  photoPreview.classList.add("is-visible");
  photoPlaceholder.classList.add("is-hidden");
}

function sanitizeFileName(value) {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/\s+/g, "-");
  const safe = normalized.replace(/[^a-z0-9-]/g, "");

  return safe || "profil";
}

function setPdfButtonState(isBusy) {
  pdfButton.disabled = isBusy;
  pdfButton.textContent = isBusy ? "PDF wird erstellt..." : defaultPdfButtonLabel;
}

async function waitForImages(root) {
  const images = Array.from(root.querySelectorAll("img"));

  await Promise.all(
    images.map((image) => new Promise((resolve) => {
      if (image.complete) {
        resolve();
        return;
      }

      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", resolve, { once: true });
    }))
  );
}

async function exportPdf() {
  if (isExportingPdf) {
    return;
  }

  if (!selectedCustomerId) {
    window.alert("Bitte zuerst einen Kunden im Dropdown auswählen, bevor ein Profil erstellt wird.");
    return;
  }

  const jsPdfConstructor = window.jspdf?.jsPDF || window.jsPDF;

  if (typeof html2canvas === "undefined" || typeof jsPdfConstructor !== "function") {
    window.alert("PDF-Export ist aktuell nicht verfügbar.");
    return;
  }

  isExportingPdf = true;
  setPdfButtonState(true);

  const exportNameElement = form.querySelector("[data-export-name='true']");
  const fileName = sanitizeFileName(exportNameElement?.textContent || "profil");
  const a4WidthPx = 794;
  const a4HeightPx = 1123;

  try {
    if (document.fonts?.ready) {
      await document.fonts.ready;
    }

    // Warten, bis Bilder im sichtbaren Formular geladen sind
    await waitForImages(form);

    // Direkt das sichtbare Formular (Preview) rendern, damit Bild und Layout
    // exakt so aussehen wie auf dem Bildschirm.
    const canvas = await html2canvas(form, {
      scale: 2,
      useCORS: true,
      backgroundColor: "#f2ebe3",
    });

    const pdf = new jsPdfConstructor({
      unit: "mm",
      format: "a4",
      orientation: "portrait",
    });

    const imageData = canvas.toDataURL("image/jpeg", 0.98);
    // Seitenverhältnis des Canvas beibehalten, damit nichts verzerrt wird
    const pageWidth = 210;
    const pageHeight = 297;
    const canvasRatio = canvas.width / canvas.height;
    const pageRatio = pageWidth / pageHeight;

    let renderWidth = pageWidth;
    let renderHeight = pageHeight;

    if (canvasRatio > pageRatio) {
      // Canvas breiter als A4-Verhältnis: an Breite ausrichten
      renderWidth = pageWidth;
      renderHeight = pageWidth / canvasRatio;
    } else {
      // Canvas höher als A4-Verhältnis: an Höhe ausrichten
      renderHeight = pageHeight;
      renderWidth = pageHeight * canvasRatio;
    }

    const offsetX = (pageWidth - renderWidth) / 2;
    const offsetY = (pageHeight - renderHeight) / 2;

    pdf.addImage(imageData, "JPEG", offsetX, offsetY, renderWidth, renderHeight);
    const blob = pdf.output("blob");
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = downloadUrl;
    link.download = `betreuungskraftprofil-${fileName}.pdf`;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();

    window.setTimeout(() => {
      URL.revokeObjectURL(downloadUrl);
      link.remove();
    }, 1000);

    // Profil gleichzeitig beim Kunden speichern
    try {
      const dataUrl = pdf.output("datauristring");
      const profilePayload = {
        filename: `betreuungskraftprofil-${fileName}.pdf`,
        pdf_data: dataUrl,
        created_at: new Date().toISOString()
      };
      fetch(`/api/customers/${selectedCustomerId}/profile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profilePayload)
      }).catch((err) => {
        console.error("Fehler beim Speichern des Profil-PDF beim Kunden:", err);
      });
    } catch (e) {
      console.error("Fehler beim Senden der Profil-Daten an das Dashboard:", e);
    }
  } catch (error) {
    console.error("PDF-Export fehlgeschlagen", error);
    window.alert("Beim Erstellen der PDF ist ein Fehler aufgetreten.");
  } finally {
    setPdfButtonState(false);
    isExportingPdf = false;
  }
}

function resetForm() {
  resetEditableFields();
  resetCheckboxes();
  clearPhoto();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
});

form.addEventListener("keydown", (event) => {
  const target = event.target;

  if (!(target instanceof HTMLElement)) {
    return;
  }

  if (target.matches("[contenteditable='true'][data-inline='true']") && event.key === "Enter") {
    event.preventDefault();
  }
});

form.addEventListener("paste", (event) => {
  const target = event.target;

  if (!(target instanceof HTMLElement) || !target.matches("[contenteditable='true']")) {
    return;
  }

  event.preventDefault();
  const text = event.clipboardData?.getData("text/plain") || "";
  document.execCommand("insertText", false, text);
});

form.addEventListener("click", (event) => {
  const target = event.target;

  if (!(target instanceof HTMLElement) || !target.matches("[contenteditable='true']")) {
    return;
  }

  event.stopPropagation();
});

form.addEventListener("mousedown", (event) => {
  const target = event.target;

  if (!(target instanceof HTMLElement) || !target.matches("[contenteditable='true']")) {
    return;
  }

  event.stopPropagation();
});

photoInput.addEventListener("change", () => {
  const file = photoInput.files?.[0];

  if (!file) {
    clearPhoto();
    return;
  }

  const reader = new FileReader();
  reader.addEventListener("load", () => {
    if (typeof reader.result === "string") {
      updatePhotoPreview(reader.result);
    }
  });
  reader.readAsDataURL(file);
});

pdfButton.addEventListener("click", exportPdf);
resetButton.addEventListener("click", resetForm);
