// Which project and dataset the user is working on. Kept in localStorage so
// moving between screens doesn't lose the context, and so a reload resumes
// where you were.
const KEY = 'spssq.context';

function load() {
  try { return JSON.parse(localStorage.getItem(KEY)) ?? {}; } catch { return {}; }
}

let context = load();
const listeners = new Set();

export function getContext() {
  return { ...context };
}

export function setContext(patch) {
  context = { ...context, ...patch };
  localStorage.setItem(KEY, JSON.stringify(context));
  listeners.forEach((fn) => fn(getContext()));
}

export function onContextChange(fn) {
  listeners.add(fn);
  fn(getContext());
  return () => listeners.delete(fn);
}
