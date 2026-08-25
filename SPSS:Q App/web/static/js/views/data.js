import { api, get, post } from '../api.js';
import { getContext, setContext } from '../state.js';

const $ = (id) => document.getElementById(id);
const select = $('project-select');
const nameInput = $('new-project-name');
const createBtn = $('create-project');
const dropZone = $('drop-zone');
const fileInput = $('file-input');
const status = $('upload-status');
const sheetRow = $('sheet-row');
const sheetSelect = $('sheet-select');

let pendingFile = null;

const num = (n) => Number(n).toLocaleString('en-GB');

async function refreshProjects() {
  const projects = await get('/api/projects');
  const current = getContext().projectId;
  select.innerHTML = '';
  select.append(new Option(projects.length ? 'Choose a project…' : 'No projects yet', ''));
  for (const p of projects) {
    const opt = new Option(p.name, String(p.id));
    if (String(p.id) === String(current)) opt.selected = true;
    select.append(opt);
  }
  if (getContext().projectId) await refreshDatasets();
}

async function refreshDatasets() {
  const { projectId } = getContext();
  if (!projectId) return;
  const project = await get(`/api/projects/${projectId}`);
  const card = $('datasets-card');
  const list = $('dataset-list');
  if (!project.datasets.length) {
    card.classList.add('hidden');
    return;
  }
  card.classList.remove('hidden');
  list.innerHTML = '';
  for (const d of project.datasets) {
    const row = document.createElement('div');
    row.className = 'var';
    row.innerHTML = `<div class="head">
      <span class="name">${d.name}</span>
      <span class="note">${num(d.n_rows)} rows · ${num(d.n_columns)} columns · ${d.header_style}</span>
      <button class="secondary use-btn" data-id="${d.id}" data-name="${d.name}"
              data-rows="${d.n_rows}">Use this</button></div>`;
    list.append(row);
  }
  list.querySelectorAll('.use-btn').forEach((b) =>
    b.addEventListener('click', () => {
      setContext({
        datasetId: Number(b.dataset.id),
        datasetName: b.dataset.name,
        nRows: Number(b.dataset.rows),
      });
      status.textContent = `Using "${b.dataset.name}".`;
    }));
}

select.addEventListener('change', () => {
  const id = select.value;
  setContext({
    projectId: id ? Number(id) : null,
    projectName: id ? select.options[select.selectedIndex].text : null,
    datasetId: null, datasetName: null, nRows: null,
  });
  refreshDatasets();
});

createBtn.addEventListener('click', async () => {
  const name = nameInput.value.trim();
  if (!name) return nameInput.focus();
  createBtn.disabled = true;
  try {
    const created = await post('/api/projects', { name });
    nameInput.value = '';
    await refreshProjects();
    select.value = String(created.id);
    select.dispatchEvent(new Event('change'));
  } catch (err) {
    status.textContent = err.message;
  } finally {
    createBtn.disabled = false;
  }
});

// ---- upload ----

$('browse').addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => fileInput.files[0] && handleFile(fileInput.files[0]));

['dragenter', 'dragover'].forEach((e) =>
  dropZone.addEventListener(e, (ev) => { ev.preventDefault(); dropZone.classList.add('over'); }));
['dragleave', 'drop'].forEach((e) =>
  dropZone.addEventListener(e, (ev) => { ev.preventDefault(); dropZone.classList.remove('over'); }));
dropZone.addEventListener('drop', (ev) => {
  const file = ev.dataTransfer?.files?.[0];
  if (file) handleFile(file);
});

async function handleFile(file) {
  if (!getContext().projectId) {
    status.textContent = 'Choose or create a project first.';
    return;
  }
  pendingFile = file;
  sheetRow.classList.add('hidden');

  // Excel workbooks often carry the data on a sheet other than the first.
  if (/\.xlsx?$/i.test(file.name)) {
    status.textContent = 'Reading worksheet names…';
    const form = new FormData();
    form.append('file', file);
    try {
      const { sheets } = await api('/api/datasets/sheets', { method: 'POST', body: form });
      if (sheets.length > 1) {
        sheetSelect.innerHTML = '';
        sheets.forEach((s) => sheetSelect.append(new Option(s, s)));
        sheetRow.classList.remove('hidden');
        status.textContent = `${file.name} has ${sheets.length} worksheets. Pick one.`;
        return;
      }
    } catch (err) {
      status.textContent = err.message;
      return;
    }
  }
  upload(pendingFile, '');
}

$('confirm-upload').addEventListener('click', () => upload(pendingFile, sheetSelect.value));

async function upload(file, sheet) {
  if (!file) return;
  status.textContent = `Reading ${file.name}…`;
  sheetRow.classList.add('hidden');
  const form = new FormData();
  form.append('project_id', String(getContext().projectId));
  form.append('name', file.name.replace(/\.[^.]+$/, ''));
  form.append('sheet', sheet);
  form.append('file', file);
  try {
    const info = await api('/api/datasets/upload', { method: 'POST', body: form });
    setContext({ datasetId: info.id, datasetName: info.name, nRows: info.n_rows });
    status.textContent = '';
    renderSummary(info);
    await refreshDatasets();
  } catch (err) {
    status.textContent = err.message;
  }
}

function renderSummary(info) {
  $('summary-card').classList.remove('hidden');
  const stats = [
    ['Respondents', num(info.n_rows)],
    ['Columns', num(info.n_columns)],
    ['Questions', num(info.n_questions)],
    ['Headers', info.header_style === 'alchemer' ? 'Alchemer' : 'Generic'],
  ];
  $('summary-stats').innerHTML = stats
    .map(([l, v]) => `<div class="stat"><div class="label">${l}</div><div class="value">${v}</div></div>`)
    .join('');

  const LABELS = {
    single: 'single response', multi: 'multi-punch', matrix_group: 'matrix',
    matrix_item: 'matrix item', numeric: 'numeric', text: 'free text',
    meta: 'metadata', weight: 'weight', empty: 'empty',
  };
  $('summary-kinds').innerHTML = Object.entries(info.by_kind)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `<span class="pill">${LABELS[k] ?? k} <strong>${v}</strong></span>`)
    .join(' ');

  const flags = $('summary-flags');
  if (!info.flagged.length) {
    flags.innerHTML = '<span class="note good">Nothing needed flagging.</span>';
    return;
  }
  flags.innerHTML = `<p class="note warn">${info.flagged.length} variable(s) worth a look:</p>` +
    info.flagged.slice(0, 10).map((f) =>
      `<div class="note">· <strong>${f.label.slice(0, 70)}</strong> — ${f.notes.join('; ')}</div>`
    ).join('');
}

refreshProjects().catch((err) => { status.textContent = err.message; });
