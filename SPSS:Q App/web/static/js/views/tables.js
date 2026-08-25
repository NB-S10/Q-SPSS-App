import { api, get, post } from '../api.js';
import { getContext, setContext } from '../state.js';
import { makeReorderable } from '../components/reorder.js';
import { SCOPES, buildShader, legendFor } from '../components/heatmap.js';

const $ = (id) => document.getElementById(id);
const output = $('table-output');
const notices = $('table-notices');

// A matrix or multi-punch parent is offered alongside its individual items, so
// you can tabulate one option on its own or the whole question at once.
const PARENT_KINDS = new Set(['single', 'multi', 'matrix_group', 'numeric']);
const CHILD_KINDS = new Set(['multi_item', 'matrix_item']);

let variables = [];
let byKey = {};
let dataset = null;
const openGroups = new Set();

const scopeSelect = $('heat-scope');
for (const [value, label] of Object.entries(SCOPES)) {
  scopeSelect.append(new Option(label, value));
}

// rowCategories maps a row variable to the categories to SHOW. Hiding a
// category here is presentation only -- the base is untouched, so the visible
// rows can legitimately sum to less than 100%. Excluding a category from the
// base is a different act and lives on the Variables screen.
// Two ways of taking a row category out, following Excel:
//   'remove'  the category goes and the question rebases without it. This is
//             what a pivot does when you untick an item, and the default.
//   'hide'    the category is not shown but stays in the base, so the rows kept
//             sum to under 100%. Excel's "include filtered items in totals",
//             which is opt-in there too and flags affected totals.
const spec = {
  rows: [], banner: [], filters: [],
  rowCategories: {},   // hide mode: which categories to display
  rowExclusions: {},   // remove mode: which categories to drop and rebase
  rowMode: {},         // var_key -> 'remove' | 'hide'
};
// Which chip's category list is open, e.g. { side: 'rows', key: 'single:377' }.
let picking = null;
// How rows are ordered: the question's own order, or by a column's values.
// columnIndex 0 is the Total column.
const sort = { mode: 'question', columnIndex: 0 };
const num = (n) => Number(n).toLocaleString('en-GB');

// ---------------------------------------------------------------- loading

async function loadDatasets() {
  const { projectId, datasetId } = getContext();
  if (!projectId) {
    output.innerHTML = '<div class="empty"><strong>No project open</strong>Choose one on the Data screen.</div>';
    return;
  }
  const project = await get(`/api/projects/${projectId}`);
  const select = $('dataset-select');
  select.innerHTML = '';
  if (!project.datasets.length) {
    output.innerHTML = '<div class="empty"><strong>No dataset</strong>Upload one on the Data screen.</div>';
    return;
  }
  for (const d of project.datasets) {
    const opt = new Option(d.name, String(d.id));
    if (String(d.id) === String(datasetId)) opt.selected = true;
    select.append(opt);
  }
  await loadDataset(Number(select.value));
}

async function loadDataset(id) {
  dataset = await get(`/api/datasets/${id}`);
  setContext({ datasetId: dataset.id, datasetName: dataset.name, nRows: dataset.n_rows });
  variables = dataset.variables.filter(
    (v) => PARENT_KINDS.has(v.kind) || CHILD_KINDS.has(v.kind));
  byKey = Object.fromEntries(dataset.variables.map((v) => [v.var_key, v]));
  spec.rows = [];
  spec.banner = [];
  spec.filters = [];
  spec.rowCategories = {};
  spec.rowExclusions = {};
  spec.rowMode = {};
  picking = null;
  openGroups.clear();
  sort.mode = 'question';
  sort.columnIndex = 0;
  $('sort-select').value = 'question';
  $('weight-select').options[0].text =
    dataset.weight_column ? `Weighted (${dataset.weight_column})` : 'Weighted (none in file)';
  renderTree();
  renderChips();
  renderSetup();
  refresh();
}

// ---------------------------------------------------------------- variable picker

function childrenOf(key) {
  return variables.filter((v) => v.parent_key === key);
}

function renderTree() {
  const term = $('var-search').value.trim().toLowerCase();
  const matches = (v) =>
    v.label.toLowerCase().includes(term) || v.code.toLowerCase().includes(term);

  const parents = variables.filter((v) => PARENT_KINDS.has(v.kind));
  const shown = term
    ? parents.filter((p) => matches(p) || childrenOf(p.var_key).some(matches))
    : parents;

  const html = shown.slice(0, 300).map((p) => {
    const kids = childrenOf(p.var_key);
    const open = openGroups.has(p.var_key);
    const rows = [row(p, false, kids.length, open)];
    if (open) rows.push(...kids.map((k) => row(k, true, 0, false)));
    return rows.join('');
  }).join('');

  $('var-tree').innerHTML = html || '<p class="note">Nothing matches.</p>';
  wireTree();
}

function row(v, isChild, childCount, open) {
  const expand = childCount
    ? `<button class="expand" data-expand="${esc(v.var_key)}">${open ? '▾' : '▸'} ${childCount}</button>`
    : '';
  return `<div class="item ${isChild ? 'child' : ''} ${childCount && open ? 'group-head' : ''}">
    <span class="c">${esc(v.code || '')}</span>
    <span class="l" title="${esc(v.label)}">${esc(v.label)}</span>
    ${expand}
    <span class="assign">
      <button data-add-row="${esc(v.var_key)}" title="Show this down the side of the table">Rows</button>
      <button data-add-banner="${esc(v.var_key)}" title="Break the table down by this">Columns</button>
      <button data-add-filter="${esc(v.var_key)}" title="Restrict the whole table to certain answers">Filter</button>
    </span>
  </div>`;
}

function wireTree() {
  const tree = $('var-tree');
  tree.querySelectorAll('[data-expand]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.expand;
      openGroups.has(key) ? openGroups.delete(key) : openGroups.add(key);
      renderTree();
    }));
  tree.querySelectorAll('[data-add-row]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.addRow;
      if (!spec.rows.includes(key)) spec.rows.push(key);
      renderChips(); refresh();
    }));
  tree.querySelectorAll('[data-add-banner]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.addBanner;
      if (!spec.banner.some((g) => g.var_key === key)) {
        spec.banner.push({ var_key: key, categories: [] });
      }
      renderChips(); refresh();
    }));
  tree.querySelectorAll('[data-add-filter]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.addFilter;
      const categories = Object.keys(byKey[key]?.value_labels ?? {});
      if (!categories.length) {
        notices.innerHTML =
          '<p class="note bad">That variable has no categories to filter on.</p>';
        return;
      }
      if (!spec.filters.some((f) => f.var_key === key)) {
        // Starts with everything kept, which changes nothing, and the picker
        // opens straight away so the user can untick what they don't want.
        spec.filters.push({ var_key: key, categories: [...categories] });
      }
      picking = { side: 'filter', key };
      renderChips(); refresh();
    }));
}

// ---------------------------------------------------------------- chips

function renderChips({ keepPicker = false } = {}) {
  const label = (k) => byKey[k]?.label ?? k;

  $('row-chips').innerHTML = spec.rows.length
    ? spec.rows.map((k) => chip('rows', k, label(k), 46, spec.rowCategories[k])).join('')
    : '<span class="note">Pick a question on the left</span>';

  $('banner-chips').innerHTML = spec.banner.length
    ? spec.banner.map((g) =>
        chip('columns', g.var_key, label(g.var_key), 34, g.categories)).join('')
    : '<span class="note">Total only</span>';

  $('filter-chips').innerHTML = spec.filters.length
    ? spec.filters.map((f) => chip('filter', f.var_key, label(f.var_key), 30, f.categories)).join('')
    : '<span class="note">None — add one from the Filter button on a question</span>';

  document.querySelectorAll('[data-drop-row]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.dropRow;
      spec.rows = spec.rows.filter((k) => k !== key);
      delete spec.rowCategories[key];
      delete spec.rowExclusions[key];
      delete spec.rowMode[key];
      if (picking?.key === key) picking = null;
      renderChips(); refresh();
    }));
  document.querySelectorAll('[data-drop-banner]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.dropBanner;
      spec.banner = spec.banner.filter((g) => g.var_key !== key);
      if (picking?.key === key) picking = null;
      renderChips(); refresh();
    }));
  document.querySelectorAll('[data-pick]').forEach((b) =>
    b.addEventListener('click', () => {
      const [side, key] = b.dataset.pick.split('|');
      picking = picking && picking.key === key && picking.side === side
        ? null : { side, key };
      renderChips();
    }));
  document.querySelectorAll('[data-drop-filter]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.dropFilter;
      spec.filters = spec.filters.filter((f) => f.var_key !== key);
      if (picking?.key === key) picking = null;
      renderChips(); refresh();
    }));

  wireChipReordering();

  // Rebuilding the picker while the user is ticking would drop the checkboxes
  // out from under them, so callers mid-selection pass keepPicker.
  if (!keepPicker) renderCategoryPicker();
}

/* Dragging a chip changes the order the row blocks are stacked in, or the order
   the banner's column groups sit left to right. */
function wireChipReordering() {
  const setups = [
    ['row-chips', (order) => { spec.rows = order; }],
    ['banner-chips', (order) => {
      const byVar = new Map(spec.banner.map((g) => [g.var_key, g]));
      spec.banner = order.map((k) => byVar.get(k)).filter(Boolean);
    }],
  ];
  for (const [id, apply] of setups) {
    const container = $(id);
    if (!container.querySelector('.chip')) continue;
    container.dataset.reorderAxis = 'x';
    makeReorderable(container, {
      itemSelector: '.chip',
      handleSelector: '.grip',
      onReorder: (order) => {
        apply(order);
        renderChips({ keepPicker: true });
        refresh();
      },
    });
  }
}

function chip(side, key, text, cut, selection) {
  const all = Object.keys(byKey[key]?.value_labels ?? {});
  const kept = side === 'rows' ? keptRowCategories(key, all) : (selection ?? all);
  const chosen = kept.length;
  const partial = chosen < all.length;
  const open = picking?.side === side && picking?.key === key;
  const counter = all.length > 1
    ? `<span class="count" title="${partial ? 'Some categories hidden' : 'All categories shown'}">${chosen}/${all.length}</span>`
    : '';
  const dropAttr = side === 'rows' ? 'data-drop-row'
    : side === 'filter' ? 'data-drop-filter' : 'data-drop-banner';
  const grip = side === 'filter'
    ? ''   // Filters combine with AND, so their order changes nothing.
    : `<span class="grip" tabindex="0" aria-label="Reorder"
             title="Drag to reorder, or Alt+Left / Alt+Right">⠿</span>`;
  return `<span class="chip ${side === 'columns' ? 'columns' : ''} ${open ? 'open' : ''}"
                data-reorder-item data-value="${esc(key)}">
    ${grip}<button class="pick" data-pick="${esc(side)}|${esc(key)}"
            title="Choose which categories to show">${esc(text.slice(0, cut))}</button>
    ${counter}<button ${dropAttr}="${esc(key)}" title="Remove">&times;</button></span>`;
}

/* Which categories a row block is currently showing, whichever mechanism is in
   use. */
function keptRowCategories(key, all) {
  if (rowMode(key) === 'hide') {
    return spec.rowCategories[key]?.length ? spec.rowCategories[key] : all;
  }
  const dropped = new Set(spec.rowExclusions[key] ?? []);
  return all.filter((c) => !dropped.has(c));
}

function rowMode(key) {
  return spec.rowMode[key] ?? 'remove';
}

function renderCategoryPicker() {
  const box = $('cat-picker');
  if (!picking) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  const variable = byKey[picking.key];
  const all = variable?.category_order?.length
    ? variable.category_order
    : Object.keys(variable?.value_labels ?? {});
  if (!all.length) {
    box.classList.add('hidden');
    return;
  }
  const isFilter = picking.side === 'filter';
  const isRows = picking.side === 'rows';
  const chosen = new Set(
    isRows ? keptRowCategories(picking.key, all) : (selectionFor(picking) ?? all));
  const excluded = new Set(variable.missing_codes ?? []);

  box.classList.remove('hidden');
  box.innerHTML = `
    <div class="head">
      <strong>${isFilter ? 'Keep only these answers:'
        : `Show in ${picking.side === 'rows' ? 'rows' : 'columns'}:`}</strong>
      <span class="note">${esc(variable.label.slice(0, 60))}</span>
      <span class="spacer"></span>
      <button class="secondary" data-cat-all>All</button>
      <button class="secondary" data-cat-none>None</button>
      <button class="secondary" data-cat-close>Done</button>
    </div>
    ${isRows ? `<div class="mode-row">
      <label><input type="radio" name="cat-mode" value="remove"
        ${rowMode(picking.key) === 'remove' ? 'checked' : ''}>
        Remove and rebase</label>
      <label><input type="radio" name="cat-mode" value="hide"
        ${rowMode(picking.key) === 'hide' ? 'checked' : ''}>
        Hide but keep in the base</label>
    </div>` : ''}
    <div class="list">
      ${all.map((c) => `<label>
        <input type="checkbox" data-cat="${esc(c)}" ${chosen.has(c) ? 'checked' : ''}>
        <span>${esc(c)}${excluded.has(c) ? ' <em class="note">(not in base)</em>' : ''}</span>
      </label>`).join('')}
    </div>
    <p class="note" style="margin:8px 0 0;font-size:0.7188rem">
      ${isFilter
        ? `A filter drops respondents from the whole table, so every base and
           every percentage changes. Filters combine with AND.`
        : isRows
        ? (rowMode(picking.key) === 'remove'
            ? `Unticked answers disappear and this question rebases without them,
               so the rows left still add up to 100%. Same as unticking an item
               in an Excel pivot.`
            : `Unticked answers disappear from view but stay in the base, so the
               rows left add up to less than 100%. Use this to keep the base
               comparable with other tables.`)
        : `Unticked answers drop out as columns. The Total column still covers
           everyone — to rebase it too, add a Filter on this question instead.`}
    </p>`;

  const apply = (categories) => {
    // An empty selection means "all", so a table is never left with no rows.
    const complete = categories.length === all.length || categories.length === 0;
    if (picking.side === 'rows') {
      const key = picking.key;
      delete spec.rowCategories[key];
      delete spec.rowExclusions[key];
      if (!complete) {
        if (rowMode(key) === 'hide') spec.rowCategories[key] = categories;
        else spec.rowExclusions[key] = all.filter((c) => !categories.includes(c));
      }
    } else if (picking.side === 'filter') {
      // A filter always sends its categories explicitly; an empty list would
      // silently keep everybody, which the engine refuses outright.
      const clause = spec.filters.find((f) => f.var_key === picking.key);
      if (clause) clause.categories = categories.length ? categories : all;
    } else {
      const group = spec.banner.find((g) => g.var_key === picking.key);
      if (group) group.categories = complete ? [] : categories;
    }
    // Only the chip counts change, so the picker's own checkboxes are left
    // alone. Rebuilding them mid-tick drops the boxes the user is clicking.
    renderChips({ keepPicker: true });
    refresh();
  };

  box.querySelectorAll('[data-cat]').forEach((input) =>
    input.addEventListener('change', () => {
      const ticked = [...box.querySelectorAll('[data-cat]')]
        .filter((i) => i.checked).map((i) => i.dataset.cat);
      if (!ticked.length) {
        // Refuse rather than sending an empty table request.
        input.checked = true;
        return;
      }
      apply(all.filter((c) => ticked.includes(c)));
    }));
  box.querySelectorAll('[name="cat-mode"]').forEach((radio) =>
    radio.addEventListener('change', () => {
      // Switching mode keeps the same categories showing, and only changes
      // whether the base rebases.
      const keeping = keptRowCategories(picking.key, all);
      spec.rowMode[picking.key] = radio.value;
      apply(keeping);
      renderCategoryPicker();
    }));
  box.querySelector('[data-cat-all]').addEventListener('click', () => apply(all));
  box.querySelector('[data-cat-none]').addEventListener('click', () => apply([all[0]]));
  box.querySelector('[data-cat-close]').addEventListener('click', () => {
    picking = null;
    renderChips();
  });
}

function selectionFor({ side, key }) {
  if (side === 'rows') return keptRowCategories(key, Object.keys(byKey[key]?.value_labels ?? {}));
  if (side === 'filter') return spec.filters.find((f) => f.var_key === key)?.categories;
  const group = spec.banner.find((g) => g.var_key === key);
  return group?.categories?.length ? group.categories : null;
}

function renderSetup() {
  if (!dataset) return;
  $('setup-summary').innerHTML = `
    <div class="stat"><div class="label">Respondents</div>
      <div class="value">${num(dataset.n_rows)}</div></div>`;
}

// ---------------------------------------------------------------- compute

let latest = null;
let pending = null;

function refresh() {
  if (!spec.rows.length) {
    notices.innerHTML = '';
    output.innerHTML = '<div class="empty"><strong>No table yet</strong>Choose a row variable to begin.</div>';
    return;
  }
  clearTimeout(pending);
  pending = setTimeout(compute, 120);
}

async function compute() {
  try {
    latest = await post('/api/tables/compute', {
      dataset_id: dataset.id,
      rows: spec.rows,
      banner: spec.banner,
      filters: spec.filters,
      row_categories: spec.rowCategories,
      row_exclusions: spec.rowExclusions,
      weight_mode: $('weight-select').value,
      base_rule: $('base-select').value,
    });
    render(latest);
  } catch (err) {
    notices.innerHTML = '';
    output.innerHTML = `<div class="empty"><strong>Couldn't build that table</strong>${esc(err.message)}</div>`;
  }
}

// ---------------------------------------------------------------- rendering

function render(table) {
  const stat = $('stat-select').value;
  const scope = scopeSelect.value;
  $('heat-key').innerHTML = legendFor(scope);

  const messages = [...(table.notices ?? [])];
  if (table.filter?.length) messages.push(`Filtered to ${table.filter.join('; ')}.`);
  notices.innerHTML = messages.map((m) => `<p class="note warn">${esc(m)}</p>`).join('');

  const cols = table.columns;
  const spans = [];
  for (const c of cols) {
    const last = spans[spans.length - 1];
    if (last && last.group === c.group) last.n += 1;
    else spans.push({ group: c.group, n: 1 });
  }

  const head = `<thead>
      <tr><th></th>${spans.map((s) =>
        `<th class="group" colspan="${s.n}">${esc(s.group)}</th>`).join('')}</tr>
      <tr class="col-heads" data-reorder-axis="x"><th></th>${cols.map((c, i) => {
        const active = sort.mode !== 'question' && i === sort.columnIndex;
        const arrow = active ? `<span class="dir">${sort.mode === 'desc' ? '▼' : '▲'}</span>` : '';
        // The Total column is a fixed reference and never moves.
        const movable = c.key !== 'total'
          ? `data-reorder-item data-value="${esc(c.label)}" data-group="${esc(c.group)}"`
          : '';
        const grip = c.key !== 'total'
          ? `<span class="grip" tabindex="0" title="Drag to reorder, or Alt+Left / Alt+Right">⠿</span>`
          : '';
        return `<th class="col ${active ? 'sorted' : ''}" data-sort-col="${i}" ${movable}
                    title="Click to sort rows on this column">${grip}${esc(c.label)}${arrow}${
          c.letter ? `<br><span class="note">(${c.letter})</span>` : ''}</th>`;
      }).join('')}</tr>
    </thead>`;

  const body = table.blocks
    .map((b) => renderBlock(b, cols, stat, table, scope))
    .join('');
  output.innerHTML = `<div class="xtab-wrap"><table class="xtab">${head}<tbody>${body}</tbody></table></div>`;
  wireSortHeaders();
  wireRowDragging(table);
  wireColumnDragging(table);
}

/* Dragging a column heading reorders the categories within its own group, and
   saves that order against the variable -- the same act as reordering rows or
   reordering on the Variables screen. Columns cannot leave their group: a
   banner group is one question, and interleaving two questions' columns would
   produce a heading row that lies about what it is showing. */
function wireColumnDragging(table) {
  const head = document.querySelector('tr.col-heads');
  if (!head || !head.querySelector('[data-reorder-item]')) return;

  makeReorderable(head, {
    itemSelector: 'th[data-reorder-item]',
    handleSelector: '.grip',
    canDrop: (dragged, other) => dragged.dataset.group === other.dataset.group,
    onReorder: async () => {
      const moved = [...head.querySelectorAll('th[data-reorder-item]')];
      const group = moved[0]?.dataset.group;
      // Group every heading by its banner variable and persist each order.
      const byGroup = new Map();
      for (const th of moved) {
        if (!byGroup.has(th.dataset.group)) byGroup.set(th.dataset.group, []);
        byGroup.get(th.dataset.group).push(th.dataset.value);
      }
      for (const [groupLabel, order] of byGroup) {
        const bannerGroup = spec.banner.find(
          (g) => byKey[g.var_key]?.label === groupLabel);
        if (!bannerGroup) continue;
        const variable = byKey[bannerGroup.var_key];
        if (!variable?.id) continue;

        // Only a full set can be saved as the variable's order. With a subset
        // shown, remember the order on the banner group instead.
        const all = Object.keys(variable.value_labels ?? {});
        if (order.length === all.length) {
          try {
            const res = await api(`/api/variables/${variable.id}/order`, {
              method: 'PATCH', body: JSON.stringify({ category_order: order }),
            });
            variable.category_order = res.category_order;
            variable.order_rule = res.order_rule;
            bannerGroup.categories = [];
          } catch (err) {
            notices.innerHTML =
              `<p class="note bad">Couldn't save that column order: ${esc(err.message)}</p>`;
            return;
          }
        } else {
          bannerGroup.categories = order;
        }
      }
      void group;
      refresh();
    },
  });
}

/* Clicking a heading cycles that column: highest first, lowest first, then back
   to the question's own order. */
function wireSortHeaders() {
  document.querySelectorAll('[data-sort-col]').forEach((th) =>
    th.addEventListener('click', () => {
      const index = Number(th.dataset.sortCol);
      if (sort.columnIndex !== index) {
        sort.columnIndex = index;
        sort.mode = 'desc';
      } else {
        sort.mode = sort.mode === 'desc' ? 'asc' : sort.mode === 'asc' ? 'question' : 'desc';
      }
      $('sort-select').value = sort.mode;
      if (latest) render(latest);
    }));
}

function renderBlock(block, cols, stat, table, scope) {
  const weighted = table.weight.mode === 'column';
  const hasTotal = cols.length > 0 && cols[0].key === 'total';
  const shade = buildShader(block, { stat, scope, hasTotal });

  const removed = block.dropped_categories?.length
    ? `<div class="note">Rebased without ${esc(block.dropped_categories.join(', '))}.</div>`
    : '';
  // Excel flags totals that include filtered-out items with an asterisk; the
  // same warning is warranted here, since the rows shown won't sum to 100%.
  const hidden = block.hidden_categories?.length
    ? `<div class="note warn">* ${esc(block.hidden_categories.join(', '))} hidden but still in the base, so the rows below sum to less than 100%.</div>`
    : '';
  const title = `<tr><td class="block-title row-label" colspan="${cols.length + 1}">
      ${esc(block.label)}${block.is_multi ? ' <span class="note">(multi-punch — columns can sum past 100%)</span>' : ''}
      ${removed}${hidden}
    </td></tr>`;

  const baseRows = `
    <tr class="base"><td class="row-label">Base (unweighted)</td>
      ${block.bases_unweighted.map((v) => `<td>${num(Math.round(v))}</td>`).join('')}</tr>
    ${weighted ? `<tr class="base"><td class="row-label">Base (weighted)</td>
      ${block.bases_weighted.map((v) => `<td>${num(Math.round(v))}</td>`).join('')}</tr>` : ''}`;

  const rows = sortRows(block.rows, stat).map((r) => {
    // Sorting reorders what is displayed, so the shader is asked about the row's
    // original index -- its scale was built from the unsorted block.
    const rowIndex = block.rows.indexOf(r);
    const cells = r.cells.map((c, i) => {
      const attrs = shade ? shade(c, rowIndex, i) : '';
      return `<td ${attrs}>${fmt(c, stat)}</td>`;
    }).join('');
    return `<tr class="${r.excluded ? 'excluded' : ''}" data-reorder-item data-value="${esc(r.label)}">
      <td class="row-label drag-handle" tabindex="0"
          title="${esc(r.label)} — drag to reorder">${esc(r.label)}${r.excluded ? ' (excluded from base)' : ''}</td>
      ${cells}</tr>`;
  }).join('');

  const empty = block.bases_unweighted[0] === 0
    ? `<tr><td class="row-label note warn" colspan="${cols.length + 1}">Nobody answered this question.</td></tr>`
    : '';

  return title + baseRows + empty + rows;
}

/* Row order. "question" keeps the order set on the Variables screen; otherwise
   rows are ranked on one column's values. Categories excluded from the base sink
   to the bottom either way -- ranking a "Don't know" row that isn't in the base
   alongside ones that are would be misleading. Rows with no value (an empty
   subgroup) also sink, rather than counting as zero. */
function sortRows(rows, stat) {
  if (sort.mode === 'question') return rows;
  const direction = sort.mode === 'desc' ? -1 : 1;
  const value = (r) => r.cells[sort.columnIndex]?.[stat];
  return [...rows].sort((a, b) => {
    if (a.excluded !== b.excluded) return a.excluded ? 1 : -1;
    const va = value(a);
    const vb = value(b);
    const aMissing = va === null || va === undefined;
    const bMissing = vb === null || vb === undefined;
    if (aMissing || bMissing) return aMissing === bMissing ? 0 : (aMissing ? 1 : -1);
    return (va - vb) * direction;
  });
}

/* Dragging a row label sets that question's category order for good, so it is
   saved against the variable exactly as the Variables screen would. */
function wireRowDragging(table) {
  document.querySelectorAll('table.xtab tbody').forEach((body, index) => {
    const block = table.blocks[index];
    if (!block) return;
    const variable = byKey[block.var_key];
    if (!variable?.id || !Object.keys(variable.value_labels ?? {}).length) return;

    makeReorderable(body, {
      itemSelector: 'tr[data-reorder-item]',
      handleSelector: 'td.drag-handle',
      onReorder: async (order) => {
        const wanted = order.filter((v) => v in (variable.value_labels ?? {}));
        if (wanted.length !== Object.keys(variable.value_labels).length) return;
        try {
          const res = await api(`/api/variables/${variable.id}/order`, {
            method: 'PATCH',
            body: JSON.stringify({ category_order: wanted }),
          });
          variable.category_order = res.category_order;
          variable.order_rule = res.order_rule;
          // A hand order only means something in question order.
          sort.mode = 'question';
          $('sort-select').value = 'question';
          refresh();
        } catch (err) {
          notices.innerHTML = `<p class="note bad">Couldn't save that order: ${esc(err.message)}</p>`;
        }
      },
    });
  });
}

function fmt(cell, stat) {
  const v = cell[stat];
  if (v === null || v === undefined) return '–';
  if (stat === 'col_pct' || stat === 'row_pct') return `${(v * 100).toFixed(1)}%`;
  if (stat === 'index') return String(v);
  return num(Math.round(v));
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
}

// ---------------------------------------------------------------- wiring

$('var-search').addEventListener('input', renderTree);
$('dataset-select').addEventListener('change', (e) => loadDataset(Number(e.target.value)));
['weight-select', 'base-select'].forEach((id) => $(id).addEventListener('change', refresh));
// Statistic and heat map only change presentation, so re-render rather than
// asking the server for the same numbers again.
['stat-select', 'heat-scope'].forEach((id) =>
  $(id).addEventListener('change', () => latest && render(latest)));
$('sort-select').addEventListener('change', (e) => {
  sort.mode = e.target.value;
  if (sort.mode !== 'question' && sort.columnIndex == null) sort.columnIndex = 0;
  if (latest) render(latest);
});

loadDatasets().catch((err) => {
  output.innerHTML = `<div class="empty"><strong>Couldn't load</strong>${esc(err.message)}</div>`;
});
