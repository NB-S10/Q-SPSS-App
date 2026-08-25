import { api, get } from '../api.js';
import { getContext, setContext } from '../state.js';
import { makeReorderable } from '../components/reorder.js';

const $ = (id) => document.getElementById(id);
const body = $('vars-body');
const datasetSelect = $('dataset-select');
const kindFilter = $('kind-filter');
const search = $('search');

const KIND_LABEL = {
  single: 'single', multi: 'multi-punch', matrix_group: 'matrix',
  matrix_item: 'item', numeric: 'numeric', text: 'free text',
  meta: 'metadata', weight: 'weight', empty: 'empty',
};
const ANALYSABLE = new Set(['single', 'multi', 'matrix_group', 'matrix_item', 'numeric']);

const RULE_NOTE = {
  scale: 'Ordered from the scale wording. Check it.',
  numeric: 'Ordered by the numbers in the labels.',
  data: "Couldn't infer an order, so this is the order the answers first appeared in the data. Drag to set your own.",
  user: 'You set this order.',
};

let variables = [];
const expanded = new Set();

async function loadProjectDatasets() {
  const { projectId, datasetId } = getContext();
  if (!projectId) return;
  const project = await get(`/api/projects/${projectId}`);
  datasetSelect.innerHTML = '';
  if (!project.datasets.length) return;
  for (const d of project.datasets) {
    const opt = new Option(`${d.name} (${d.n_rows.toLocaleString('en-GB')} rows)`, String(d.id));
    if (String(d.id) === String(datasetId)) opt.selected = true;
    datasetSelect.append(opt);
  }
  await loadVariables(Number(datasetSelect.value));
}

async function loadVariables(datasetId) {
  if (!datasetId) return;
  const ds = await get(`/api/datasets/${datasetId}`);
  setContext({ datasetId: ds.id, datasetName: ds.name, nRows: ds.n_rows });
  variables = ds.variables;
  render();
}

function visible() {
  const mode = kindFilter.value;
  const term = search.value.trim().toLowerCase();
  let shown = variables;
  if (mode === 'analysable') shown = shown.filter((v) => ANALYSABLE.has(v.kind));
  if (mode === 'flagged') shown = shown.filter((v) => v.notes?.length);
  if (mode === 'unordered') shown = shown.filter((v) => v.order_rule === 'data' && v.n_categories > 2);
  if (term) {
    const hit = (v) =>
      v.label.toLowerCase().includes(term) || v.code.toLowerCase().includes(term);
    // Matrix items are labelled with their row, not the question, so matching a
    // parent has to bring its children along.
    const parents = new Set(shown.filter(hit).map((v) => v.var_key));
    shown = shown.filter((v) => hit(v) || parents.has(v.parent_key));
  }
  return shown;
}

function render() {
  const shown = visible();
  const needsOrder = variables.filter(
    (v) => v.order_rule === 'data' && Object.keys(v.value_labels ?? {}).length > 2).length;
  $('var-count').innerHTML =
    `${shown.length} of ${variables.length} variables` +
    (needsOrder ? ` · <span class="warn">${needsOrder} need an order</span>` : '');

  if (!shown.length) {
    body.innerHTML = '<div class="empty"><strong>Nothing matches</strong>Try a different filter.</div>';
    return;
  }
  body.innerHTML = shown.map(renderVar).join('');
  wireUp();
}

function renderVar(v) {
  const cats = v.category_order?.length ? v.category_order : Object.keys(v.value_labels ?? {});
  const orderable = cats.length > 1;
  const open = expanded.has(v.var_key);

  const summary = cats.length
    ? `<div class="values">${cats.length} categories · ${cats.slice(0, 6).map(esc).join(' · ')}${cats.length > 6 ? ' …' : ''}</div>`
    : '';
  const flags = (v.notes ?? []).map((n) => `<div class="flag">${esc(n)}</div>`).join('');
  const cols = v.n_columns > 1 ? `<span class="note">${v.n_columns} columns</span>` : '';
  const rule = orderable
    ? `<span class="rule-tag rule-${v.order_rule}">${v.order_rule === 'data' ? 'no order' : v.order_rule}</span>`
    : '';
  const toggle = orderable
    ? `<button class="expander" data-toggle="${esc(v.var_key)}">${open ? 'Done' : 'Set order'}</button>`
    : '';

  return `<div class="var ${v.kind === 'matrix_item' ? 'child' : ''}" data-var="${esc(v.var_key)}">
    <div class="head">
      <span class="code">${esc(v.code || '—')}</span>
      <span class="name">${esc(v.label)}</span>
      ${cols}${rule}
      <span class="pill">${KIND_LABEL[v.kind] ?? v.kind}</span>
      ${toggle}
    </div>
    ${open ? editor(v, cats) : summary}${flags}</div>`;
}

function editor(v, cats) {
  const rows = cats.map((c, i) => {
    const excluded = (v.missing_codes ?? []).includes(c);
    return `<div class="cat ${excluded ? 'excluded' : ''}" data-reorder-item
                 data-value="${esc(c)}" tabindex="0"
                 title="Drag, or press Alt+Up / Alt+Down">
      <span class="handle" aria-hidden="true">⠿</span>
      <span class="pos">${i + 1}</span>
      <span class="txt">${esc(c)}</span>
    </div>`;
  }).join('');

  return `<div class="cat-editor" data-editor="${esc(v.var_key)}" data-id="${v.id}">
    <div class="cat-head">
      <span>Drag to reorder, or focus a row and press Alt+Up / Alt+Down.</span>
      <span class="spacer"></span>
      <button class="secondary" data-resuggest="${v.id}"
              style="font-size:0.75rem;padding:3px 9px">Auto-order</button>
    </div>
    <div class="cat-list">${rows}</div>
    <div class="note" style="margin-top:6px" data-status="${v.id}">${RULE_NOTE[v.order_rule] ?? ''}</div>
  </div>`;
}

function wireUp() {
  body.querySelectorAll('[data-toggle]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.toggle;
      expanded.has(key) ? expanded.delete(key) : expanded.add(key);
      render();
    }));

  body.querySelectorAll('[data-resuggest]').forEach((b) =>
    b.addEventListener('click', async () => {
      const id = Number(b.dataset.resuggest);
      try {
        const res = await api(`/api/variables/${id}/order/suggest`, { method: 'POST' });
        applyUpdate(id, res);
      } catch (err) {
        status(id, err.message, true);
      }
    }));

  body.querySelectorAll('[data-editor]').forEach((container) => {
    const id = Number(container.dataset.id);
    makeReorderable(container.querySelector('.cat-list'), {
      onReorder: (order) => save(id, order, container),
      itemSelector: '.cat',
    });
  });
}

let saveTimer = null;
function save(id, order, container) {
  // Renumber immediately so the positions track the drag, then persist.
  container.querySelectorAll('.cat').forEach((n, i) => {
    n.querySelector('.pos').textContent = String(i + 1);
  });
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      const res = await api(`/api/variables/${id}/order`, {
        method: 'PATCH',
        body: JSON.stringify({ category_order: order }),
      });
      applyUpdate(id, res, false);
      status(id, 'Order saved.');
    } catch (err) {
      status(id, err.message, true);
    }
  }, 350);
}

function applyUpdate(id, res, rerender = true) {
  const v = variables.find((x) => x.id === id);
  if (!v) return;
  v.category_order = res.category_order;
  v.order_rule = res.order_rule;
  if (rerender) render();
}

function status(id, text, bad = false) {
  const el = body.querySelector(`[data-status="${id}"]`);
  if (el) {
    el.textContent = text;
    el.className = `note ${bad ? 'bad' : 'good'}`;
  }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
}

datasetSelect.addEventListener('change', () => loadVariables(Number(datasetSelect.value)));
kindFilter.addEventListener('change', render);
search.addEventListener('input', render);

loadProjectDatasets().catch((err) => {
  body.innerHTML = `<div class="empty"><strong>Couldn't load</strong>${err.message}</div>`;
});
