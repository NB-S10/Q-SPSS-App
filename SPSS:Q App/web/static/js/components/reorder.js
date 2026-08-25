// Drag-to-reorder a list of rows.
//
// Pointer events rather than the HTML5 drag-and-drop API. Native DnD depends on
// the browser deciding a drag has begun, competes with text selection inside the
// row, and does nothing at all on touch. Pointer events behave the same
// everywhere, work with a trackpad and a finger, and can be driven in a test.
//
// Every row also takes Alt+Up / Alt+Down, which beats dragging on a long scale.
//
// `itemSelector` is what MOVES; `handleSelector` is what you grab. They differ in
// a table, where the drag affordance is the label cell but the element that has
// to be reordered is its <tr> -- moving the cell itself would drop it into
// another row.

const DRAG_THRESHOLD = 3; // px before a press counts as a drag rather than a click

export function makeReorderable(
  container,
  {
    onReorder,
    itemSelector = '[data-reorder-item]',
    handleSelector = null,
    // Optional (dragged, target) predicate. Return false to refuse a drop
    // position -- used to stop a banner column being dragged out of its own
    // group, where it would mean nothing.
    canDrop = null,
  } = {},
) {
  let dragged = null;
  let startY = 0;
  let startX = 0;
  let moved = false;

  const items = () => [...container.querySelectorAll(itemSelector)];

  function onPointerDown(event) {
    if (event.button !== 0) return;
    if (handleSelector && !event.target.closest(handleSelector)) return;
    const item = event.target.closest(itemSelector);
    if (!item || !container.contains(item)) return;

    dragged = item;
    startY = event.clientY;
    startX = event.clientX;
    moved = false;
    // No setPointerCapture: moves are tracked on document, so capture buys
    // nothing and throws if the pointer id isn't currently active.
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp, { once: true });
    document.addEventListener('pointercancel', onPointerUp, { once: true });
  }

  function onPointerMove(event) {
    if (!dragged) return;
    const travelled = container.dataset.reorderAxis === 'x'
      ? Math.abs(event.clientX - startX)
      : Math.abs(event.clientY - startY);
    if (!moved && travelled < DRAG_THRESHOLD) return;
    if (!moved) {
      moved = true;
      dragged.classList.add('dragging');
      container.classList.add('reordering');
    }
    event.preventDefault();

    // Insert before or after whichever row the pointer is currently over,
    // depending on which half of it we are in.
    for (const other of items()) {
      if (other === dragged) continue;
      if (canDrop && !canDrop(dragged, other)) continue;
      const box = other.getBoundingClientRect();
      // Horizontal lists (a table's column headings) are compared on x, since
      // every heading shares the same vertical band.
      const horizontal = container.dataset.reorderAxis === 'x';
      const position = horizontal ? event.clientX : event.clientY;
      const start = horizontal ? box.left : box.top;
      const size = horizontal ? box.width : box.height;
      if (position < start || position > start + size) continue;
      const after = position > start + size / 2;
      other.parentNode.insertBefore(dragged, after ? other.nextSibling : other);
      break;
    }
  }

  function onPointerUp() {
    document.removeEventListener('pointermove', onPointerMove);
    if (!dragged) return;
    const wasDrag = moved;
    dragged.classList.remove('dragging');
    container.classList.remove('reordering');
    dragged = null;
    moved = false;
    if (wasDrag) onReorder(currentOrder(container, itemSelector));
  }

  function onKeyDown(event) {
    const horizontal = container.dataset.reorderAxis === 'x';
    const back = horizontal ? 'ArrowLeft' : 'ArrowUp';
    const forward = horizontal ? 'ArrowRight' : 'ArrowDown';
    if (!event.altKey || (event.key !== back && event.key !== forward)) return;
    if (handleSelector && !event.target.closest(handleSelector)) return;
    const item = event.target.closest(itemSelector);
    if (!item) return;
    event.preventDefault();
    const sibling = event.key === back
      ? item.previousElementSibling
      : item.nextElementSibling;
    if (!sibling || !sibling.matches(itemSelector)) return;
    if (canDrop && !canDrop(item, sibling)) return;
    if (event.key === back) item.parentNode.insertBefore(item, sibling);
    else item.parentNode.insertBefore(sibling, item);
    item.focus();
    onReorder(currentOrder(container, itemSelector));
  }

  container.addEventListener('pointerdown', onPointerDown);
  container.addEventListener('keydown', onKeyDown);

  return () => {
    container.removeEventListener('pointerdown', onPointerDown);
    container.removeEventListener('keydown', onKeyDown);
  };
}

export function currentOrder(container, itemSelector = '[data-reorder-item]') {
  return [...container.querySelectorAll(itemSelector)].map((n) => n.dataset.value);
}
