// Tabs: <div data-tabs> with buttons[data-tab] and .panel[data-panel]
document.querySelectorAll('[data-tabs]').forEach(root => {
  const btns = root.querySelectorAll(':scope > .tabs button');
  const show = id => {
    btns.forEach(b => b.setAttribute('aria-selected', b.dataset.tab === id));
    root.querySelectorAll(':scope > .panel').forEach(p => p.hidden = p.dataset.panel !== id);
    root.querySelectorAll(`:scope > .panel[data-panel="${id}"] iframe[data-src]`).forEach(f => { if (!f.src) f.src = f.dataset.src; });
  };
  btns.forEach(b => b.addEventListener('click', () => show(b.dataset.tab)));
  if (btns.length) show(btns[0].dataset.tab);
});
