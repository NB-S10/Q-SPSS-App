// Shared chrome: the context readout and the text-size control.
import { onContextChange } from './state.js';

/* Every font size in the stylesheet is a rem, so one root size scales the whole
   interface. Column widths and padding stay in px deliberately -- shrinking the
   text to fit more table on screen is the point, and scaling the gaps with it
   would just make small sizes cramped instead of denser.
   Browser zoom still works as usual and is independent of this. */
const SIZE_KEY = 'spssq.textSize';
const MIN_SIZE = 11;
const MAX_SIZE = 19;
const DEFAULT_SIZE = 15;

function readSize() {
  const stored = Number(localStorage.getItem(SIZE_KEY));
  return Number.isFinite(stored) && stored >= MIN_SIZE && stored <= MAX_SIZE
    ? stored : DEFAULT_SIZE;
}

function applySize(size) {
  const clamped = Math.min(Math.max(size, MIN_SIZE), MAX_SIZE);
  document.documentElement.style.setProperty('--ui-font-size', `${clamped}px`);
  localStorage.setItem(SIZE_KEY, String(clamped));
  const readout = document.getElementById('text-size-value');
  if (readout) readout.textContent = String(clamped);
  const smaller = document.getElementById('text-smaller');
  const bigger = document.getElementById('text-bigger');
  if (smaller) smaller.disabled = clamped <= MIN_SIZE;
  if (bigger) bigger.disabled = clamped >= MAX_SIZE;
  return clamped;
}

let textSize = applySize(readSize());

document.getElementById('text-smaller')?.addEventListener('click', () => {
  textSize = applySize(textSize - 1);
});
document.getElementById('text-bigger')?.addEventListener('click', () => {
  textSize = applySize(textSize + 1);
});

const bar = document.getElementById('context-bar');

onContextChange((ctx) => {
  if (!bar) return;
  if (!ctx.projectName) {
    bar.textContent = 'No project open';
    return;
  }
  const bits = [ctx.projectName];
  if (ctx.datasetName) bits.push(ctx.datasetName);
  if (ctx.nRows) bits.push(`n=${Number(ctx.nRows).toLocaleString('en-GB')}`);
  bar.textContent = bits.join('  ·  ');
});
