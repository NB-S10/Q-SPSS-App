import { get } from '../api.js';
import { getContext, setContext } from '../state.js';

const $ = (id) => document.getElementById(id);
const body = $('weight-body');
const datasetSelect = $('dataset-select');

const num = (n, dp = 0) =>
  Number(n).toLocaleString('en-GB', { minimumFractionDigits: dp, maximumFractionDigits: dp });

const BAND_CLASS = {
  Excellent: 'good', Good: 'good', Acceptable: '', Poor: 'warn', 'Very poor': 'bad',
};

async function loadDatasets() {
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
  await load(Number(datasetSelect.value));
}

async function load(datasetId) {
  if (!datasetId) return;
  const w = await get(`/api/datasets/${datasetId}/weights`);
  setContext({ datasetId: w.dataset_id, datasetName: w.dataset_name, nRows: w.n_rows });
  render(w);
}

function render(w) {
  if (!w.has_weight) {
    body.innerHTML = `
      <div class="empty">
        <strong>This dataset has no weight column</strong>
        Tables will run unweighted, with every respondent counting 1.
      </div>
      <div class="card" style="margin-top:16px">
        <h2>Calculate weights</h2>
        <p class="note">RIM weighting (raking to population targets) isn't built yet.
        Until it is, either weight the file in the existing weighting wizard and
        re-upload it with a <code>weight_demog</code> column, or run the tables
        unweighted.</p>
        <p><button disabled>Set up targets and rake</button>
          <span class="note">Not built yet</span></p>
      </div>`;
    return;
  }

  const d = w.diagnostics ?? {};
  const bandClass = BAND_CLASS[w.band] ?? '';

  const stats = [
    ['Weight column', w.weight_column],
    ['Respondents', num(w.n_rows)],
    ['Effective base', num(d.effective_base)],
    ['Efficiency', `${num(d.efficiency_percent, 1)}%`],
    ['Design effect', num(d.design_effect, 3)],
  ];

  body.innerHTML = `
    <p class="note">
      This dataset arrived already weighted, so there's nothing to calculate.
      Tables will use <strong>${esc(w.weight_column)}</strong> unless you pick
      <strong>Unweighted</strong> on the Tables screen.
    </p>
    <div class="stat-row" style="margin:14px 0">
      ${stats.map(([l, v]) =>
        `<div class="stat"><div class="label">${l}</div><div class="value">${esc(v)}</div></div>`
      ).join('')}
    </div>
    <p class="${bandClass}" style="font-weight:500">Weighting efficiency: ${esc(w.band)}</p>
    <p class="note">
      The effective base is what significance tests use, not the ${num(w.n_rows)} raw
      respondents &mdash; weighting costs precision, and treating the full base as
      independent would overstate significance.
    </p>
    ${spread(d)}
    ${warnings(w)}`;
}

function spread(d) {
  if (!d.min_weight) return '';
  const rows = [
    ['Smallest weight', num(d.min_weight, 3)],
    ['1st percentile', num(d.p1, 3)],
    ['Mean', num(d.mean_weight, 3)],
    ['99th percentile', num(d.p99, 3)],
    ['Largest weight', num(d.max_weight, 3)],
    ['Coefficient of variation', `${num(d.cv_percent, 1)}%`],
  ];
  return `<h2 style="font-size:0.9375rem;font-weight:500;margin:18px 0 8px">Weight spread</h2>
    <table class="xtab"><tbody>
      ${rows.map(([l, v]) =>
        `<tr><td class="row-label">${l}</td><td>${v}</td></tr>`).join('')}
    </tbody></table>`;
}

function warnings(w) {
  if (!w.warnings.length) return '';
  return `<div style="margin-top:16px">` +
    w.warnings.map((m) => `<p class="warn note">· ${esc(m)}</p>`).join('') + `</div>`;
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
}

datasetSelect.addEventListener('change', () => load(Number(datasetSelect.value)));
loadDatasets().catch((err) => {
  body.innerHTML = `<div class="empty"><strong>Couldn't load</strong>${err.message}</div>`;
});
