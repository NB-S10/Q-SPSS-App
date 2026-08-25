// Conditional formatting for a crosstab block.
//
// Four scopes, because "shade the big numbers" means different things depending
// on the question you are asking:
//
//   total   How far each cell sits from its row's Total. Diverging: blue above,
//           amber below. The analyst's default -- it answers "who is unusual".
//   row     Rank within each row. Answers "which subgroup is highest on this
//           answer", regardless of how common the answer is overall.
//   column  Rank within each column. Answers "what matters most to this
//           subgroup", i.e. reads a column top to bottom.
//   table   Rank across every cell. Answers "where are the big numbers".
//
// Which columns get shaded follows from the question. Under `total` and `row`
// the Total column is the baseline being compared against, so shading it would
// be circular; under `column` and `table` it is just another set of numbers and
// is shaded like the rest.
//
// Rows excluded from the base never take part: they sit outside the percentages
// the rest of the table adds up to, so ranking them alongside would mislead.

const DIVERGING = { above: 'hi', below: 'lo' };
const MAX_ALPHA = 0.52;
// Sequential scales give their lowest value a faint tint rather than none.
// Leaving it white reads as missing data, and contradicts the legend. Diverging
// scales keep a hard floor of nothing, because a cell level with the total
// genuinely has no difference to show.
const MIN_ALPHA = 0.05;

export const SCOPES = {
  off: 'Off',
  total: 'Compare with total',
  row: 'Within each row',
  column: 'Within each column',
  table: 'Across whole table',
};

export function includesTotalColumn(scope) {
  return scope === 'column' || scope === 'table';
}

/**
 * Build a shader for one block.
 * Returns null when nothing should be shaded, otherwise
 * (cell, rowIndex, colIndex) -> "" | 'class="hi" style="--heat:0.31"'
 */
export function buildShader(block, { stat, scope, hasTotal }) {
  if (scope === 'off') return null;
  if (scope === 'total' && !hasTotal) return null;

  const firstColumn = includesTotalColumn(scope) && hasTotal ? 0 : (hasTotal ? 1 : 0);
  const rows = block.rows.map((r, i) => ({ row: r, index: i }))
    .filter(({ row }) => !row.excluded);

  const valueAt = (row, colIndex) => {
    const v = row.cells[colIndex]?.[stat];
    return v === null || v === undefined ? null : v;
  };

  if (scope === 'total') {
    // Reference is the 90th percentile of gaps, not the largest, so one tiny
    // subgroup with a wild figure cannot flatten the rest of the table.
    const gaps = [];
    for (const { row } of rows) {
      const base = valueAt(row, 0);
      if (base === null) continue;
      for (let c = 1; c < row.cells.length; c++) {
        const v = valueAt(row, c);
        if (v !== null) gaps.push(Math.abs(v - base));
      }
    }
    const reference = percentile(gaps, 0.9) ?? null;
    if (!reference) return null;

    return (cell, rowIndex, colIndex) => {
      if (colIndex === 0 || block.rows[rowIndex].excluded) return '';
      const v = cell[stat];
      const base = block.rows[rowIndex].cells[0]?.[stat];
      if (v == null || base == null) return '';
      const gap = v - base;
      const strength = Math.min(Math.abs(gap) / reference, 1) * MAX_ALPHA;
      if (strength < 0.04) return '';
      return attr(gap >= 0 ? DIVERGING.above : DIVERGING.below, strength);
    };
  }

  // The remaining scopes are sequential: normalise against a min and max taken
  // over whichever cells the scope covers.
  const ranges = new Map();

  if (scope === 'row') {
    for (const { row, index } of rows) {
      const values = collect(row, firstColumn, valueAt);
      ranges.set(`r${index}`, extent(values));
    }
  } else if (scope === 'column') {
    const width = block.rows[0]?.cells.length ?? 0;
    for (let c = firstColumn; c < width; c++) {
      const values = rows.map(({ row }) => valueAt(row, c)).filter((v) => v !== null);
      ranges.set(`c${c}`, extent(values));
    }
  } else {
    const values = [];
    for (const { row } of rows) values.push(...collect(row, firstColumn, valueAt));
    ranges.set('all', extent(values));
  }

  return (cell, rowIndex, colIndex) => {
    if (colIndex < firstColumn || block.rows[rowIndex].excluded) return '';
    const v = cell[stat];
    if (v == null) return '';
    const key = scope === 'row' ? `r${rowIndex}` : scope === 'column' ? `c${colIndex}` : 'all';
    const range = ranges.get(key);
    if (!range || range.span === 0) return '';
    const normalised = (v - range.min) / range.span;
    return attr('seq', MIN_ALPHA + normalised * (MAX_ALPHA - MIN_ALPHA));
  };
}

function collect(row, firstColumn, valueAt) {
  const out = [];
  for (let c = firstColumn; c < row.cells.length; c++) {
    const v = valueAt(row, c);
    if (v !== null) out.push(v);
  }
  return out;
}

function extent(values) {
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return { min, max, span: max - min };
}

function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(Math.floor(sorted.length * p), sorted.length - 1)] || null;
}

function attr(className, strength) {
  return `class="${className}" style="--heat:${strength.toFixed(3)}"`;
}

export function legendFor(scope) {
  if (scope === 'off') return '';
  if (scope === 'total') {
    return swatch('rgba(23,92,165,0.45)', 'above total')
         + swatch('rgba(186,117,23,0.45)', 'below total');
  }
  const within = { row: 'in this row', column: 'in this column', table: 'in the table' }[scope];
  return swatch(`rgba(23,92,165,${MIN_ALPHA})`, `lowest ${within}`)
       + swatch(`rgba(23,92,165,${MAX_ALPHA})`, `highest ${within}`);
}

function swatch(colour, label) {
  return `<div class="heat-key"><i style="background:${colour}"></i> ${label}</div>`;
}
