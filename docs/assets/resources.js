'use strict';
// Deep links must open their containing report before scrolling into view.
function revealReportAnchor() {
  let id;
  try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
  const target = id && document.getElementById(id);
  if (!target) return;
  for (let parent = target.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === 'DETAILS') parent.open = true;
  }
  requestAnimationFrame(() => target.scrollIntoView());
}
window.addEventListener('hashchange', revealReportAnchor);
window.addEventListener('load', revealReportAnchor);
for (const table of document.querySelectorAll('.resource-content table')) {
  if (table.parentElement.matches('.report-table-scroll,.table-wrap,.table-container,.table-scroll')) continue;
  const wrapper = document.createElement('div');
  wrapper.className = 'report-table-scroll';
  wrapper.tabIndex = 0;
  wrapper.setAttribute('role', 'region');
  wrapper.setAttribute('aria-label', 'Scrollable results table');
  table.before(wrapper);
  wrapper.append(table);
}
