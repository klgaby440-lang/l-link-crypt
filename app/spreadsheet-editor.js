(() => {
  "use strict";

  const MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const SCRIPT_URL = "https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js";
  const PAGE_ROWS = 100;
  const MAX_COLUMNS = 40;
  let loader = null;

  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);

  function loadSheetJS() {
    if (window.XLSX?.read && window.XLSX?.write) return Promise.resolve(window.XLSX);
    if (loader) return loader;
    loader = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = SCRIPT_URL;
      script.async = true;
      script.onload = () => window.XLSX?.read && window.XLSX?.write
        ? resolve(window.XLSX)
        : reject(new Error("La bibliothèque Excel est chargée, mais ses fonctions sont indisponibles."));
      script.onerror = () => reject(new Error("Impossible de charger le moteur Excel. Vérifie la connexion Internet puis réessaie."));
      document.head.appendChild(script);
    }).catch(error => {
      loader = null;
      throw error;
    });
    return loader;
  }

  function cellText(cell) {
    if (!cell) return "";
    if (typeof cell.f === "string") return "=" + cell.f;
    if (cell.w !== undefined && cell.w !== null) return String(cell.w);
    if (cell.v === undefined || cell.v === null) return "";
    if (cell.v instanceof Date) return cell.v.toISOString().slice(0, 10);
    return String(cell.v);
  }

  function extendRange(XLSX, sheet, row, column) {
    const current = sheet["!ref"] ? XLSX.utils.decode_range(sheet["!ref"]) : {
      s: { r: 0, c: 0 }, e: { r: 0, c: 0 }
    };
    current.s.r = Math.min(current.s.r, row);
    current.s.c = Math.min(current.s.c, column);
    current.e.r = Math.max(current.e.r, row);
    current.e.c = Math.max(current.e.c, column);
    sheet["!ref"] = XLSX.utils.encode_range(current);
  }

  function updateCell(XLSX, sheet, address, value) {
    const previous = sheet[address];
    const cell = previous ? { ...previous } : {};
    delete cell.v;
    delete cell.w;
    delete cell.f;
    delete cell.t;

    if (value === "") {
      if (Object.keys(cell).some(key => !["s", "z"].includes(key))) sheet[address] = cell;
      else delete sheet[address];
      return;
    }

    if (value.startsWith("=") && value.length > 1) {
      cell.f = value.slice(1);
      sheet[address] = cell;
      return;
    }

    if (previous?.t === "n" && Number.isFinite(Number(value.trim()))) {
      cell.t = "n";
      cell.v = Number(value);
    } else if (previous?.t === "b" && /^(true|false)$/i.test(value.trim())) {
      cell.t = "b";
      cell.v = value.trim().toLowerCase() === "true";
    } else {
      cell.t = "s";
      cell.v = value;
    }
    sheet[address] = cell;
  }

  function workbookController(host, workbook, XLSX, onChange) {
    let selected = workbook.SheetNames[0];
    let page = 0;
    let destroyed = false;

    const selectedSheet = () => workbook.Sheets[selected];
    const rangeOf = sheet => sheet?.["!ref"]
      ? XLSX.utils.decode_range(sheet["!ref"])
      : { s: { r: 0, c: 0 }, e: { r: 0, c: 0 } };

    function markDirty() {
      if (!destroyed && typeof onChange === "function") onChange();
    }

    function render() {
      if (destroyed) return;
      const sheet = selectedSheet();
      if (!sheet) {
        host.innerHTML = '<div class="work-empty-editor"><b>Feuille introuvable</b><span>Choisis une autre feuille ou recharge le classeur.</span></div>';
        return;
      }

      const range = rangeOf(sheet);
      const totalRows = Math.max(1, range.e.r - range.s.r + 1);
      const totalColumns = Math.max(1, range.e.c - range.s.c + 1);
      const startRow = range.s.r + page * PAGE_ROWS;
      const endRow = Math.min(range.e.r, startRow + PAGE_ROWS - 1);
      const endColumn = Math.min(range.e.c, range.s.c + MAX_COLUMNS - 1);
      const visibleColumns = Math.max(1, endColumn - range.s.c + 1);
      const pageCount = Math.max(1, Math.ceil(totalRows / PAGE_ROWS));

      const options = workbook.SheetNames.map(name =>
        '<option value="' + escapeHtml(name) + '"' + (name === selected ? " selected" : "") + '>' + escapeHtml(name) + "</option>"
      ).join("");

      let html = '<div class="work-spreadsheet">';
      html += '<div class="work-sheet-toolbar">';
      html += '<label class="work-sheet-picker"><span>Feuille</span><select data-xlsx-sheet>' + options + "</select></label>";
      html += '<button type="button" class="work-file-action" data-xlsx-action="row">+ Ligne</button>';
      html += '<button type="button" class="work-file-action" data-xlsx-action="column">+ Colonne</button>';
      html += '<button type="button" class="work-file-action" data-xlsx-action="sheet">+ Feuille</button>';
      html += '<span class="work-sheet-count">' + totalRows + " lignes · " + totalColumns + " colonnes</span>";
      html += "</div>";
      html += '<div class="work-sheet-grid-wrap"><table class="work-sheet-grid"><thead><tr><th class="work-sheet-corner">#</th>';

      for (let column = range.s.c; column <= endColumn; column += 1) {
        html += "<th>" + escapeHtml(XLSX.utils.encode_col(column)) + "</th>";
      }

      html += "</tr></thead><tbody>";
      for (let row = startRow; row <= endRow; row += 1) {
        html += '<tr><th class="work-sheet-row-number">' + (row + 1) + "</th>";
        for (let column = range.s.c; column <= endColumn; column += 1) {
          const address = XLSX.utils.encode_cell({ r: row, c: column });
          const value = cellText(sheet[address]);
          html += '<td><input class="work-sheet-cell" data-xlsx-cell="' + address +
            '" aria-label="' + escapeHtml("Cellule " + address) +
            '" value="' + escapeHtml(value) + '" spellcheck="false" autocomplete="off"></td>';
        }
        html += "</tr>";
      }
      html += "</tbody></table></div>";
      html += '<div class="work-sheet-footer"><button type="button" class="work-file-action" data-xlsx-action="previous"' +
        (page === 0 ? " disabled" : "") + '>← Précédent</button>';
      html += '<span>Lignes ' + (startRow + 1) + "–" + (endRow + 1) + " / " + (range.e.r + 1) +
        " · Page " + (page + 1) + " / " + pageCount + "</span>";
      html += '<button type="button" class="work-file-action" data-xlsx-action="next"' +
        (page + 1 >= pageCount ? " disabled" : "") + '>Suivant →</button></div>';
      if (totalColumns > MAX_COLUMNS) {
        html += '<p class="work-sheet-notice">Seules les ' + MAX_COLUMNS + " premières colonnes sont affichées dans cet éditeur.</p>";
      } else {
        html += '<p class="work-sheet-notice">Les cellules modifiées restent locales jusqu’à Enregistrer ou Exporter. Les formules sont conservées ; Excel recalculera les formules à l’ouverture.</p>';
      }
      html += "</div>";
      host.innerHTML = html;
    }

    host.addEventListener("input", handleInput);
    host.addEventListener("change", handleChange);
    host.addEventListener("click", handleClick);

    function handleInput(event) {
      const input = event.target.closest("[data-xlsx-cell]");
      if (!input) return;
      const sheet = selectedSheet();
      const address = input.dataset.xlsxCell;
      const decoded = XLSX.utils.decode_cell(address);
      updateCell(XLSX, sheet, address, input.value);
      extendRange(XLSX, sheet, decoded.r, decoded.c);
      markDirty();
    }

    function handleChange(event) {
      const select = event.target.closest("[data-xlsx-sheet]");
      if (!select) return;
      if (!workbook.Sheets[select.value]) return;
      selected = select.value;
      page = 0;
      render();
    }

    function handleClick(event) {
      const button = event.target.closest("[data-xlsx-action]");
      if (!button || button.disabled) return;
      const sheet = selectedSheet();
      const range = rangeOf(sheet);
      switch (button.dataset.xlsxAction) {
        case "row":
          range.e.r += 1;
          sheet["!ref"] = XLSX.utils.encode_range(range);
          page = Math.max(0, Math.ceil((range.e.r - range.s.r + 1) / PAGE_ROWS) - 1);
          markDirty();
          render();
          break;
        case "column":
          range.e.c += 1;
          sheet["!ref"] = XLSX.utils.encode_range(range);
          markDirty();
          render();
          break;
        case "sheet": {
          let number = workbook.SheetNames.length + 1;
          let name = "Feuille " + number;
          while (workbook.Sheets[name]) {
            number += 1;
            name = "Feuille " + number;
          }
          workbook.SheetNames.push(name);
          workbook.Sheets[name] = XLSX.utils.aoa_to_sheet([[""]]);
          selected = name;
          page = 0;
          markDirty();
          render();
          break;
        }
        case "previous":
          page = Math.max(0, page - 1);
          render();
          break;
        case "next":
          page += 1;
          render();
          break;
      }
    }

    return {
      async toBlob() {
        workbook.Workbook = workbook.Workbook || {};
        workbook.Workbook.CalcPr = { fullCalcOnLoad: true, forceFullCalc: true };
        const output = XLSX.write(workbook, { bookType: "xlsx", type: "array", compression: true, cellStyles: true });
        return new Blob([output], { type: MIME });
      },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        host.removeEventListener("input", handleInput);
        host.removeEventListener("change", handleChange);
        host.removeEventListener("click", handleClick);
        host.innerHTML = "";
      }
    };
  }

  async function open(host, blob, options = {}) {
    if (!(blob instanceof Blob)) throw new Error("Le contenu du classeur Excel est indisponible.");
    const XLSX = await loadSheetJS();
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const workbook = XLSX.read(bytes, { type: "array", cellFormula: true, cellStyles: true, cellNF: true, cellDates: true });
    if (!workbook || !Array.isArray(workbook.SheetNames) || !workbook.SheetNames.length) {
      throw new Error("Ce fichier Excel ne contient aucune feuille lisible.");
    }
    return workbookController(host, workbook, XLSX, options.onChange);
  }

  window.LlinkSpreadsheetEditor = { open, version: "0.20.3" };
})();