// Shared shell behavior also runs on pages without Datastar or an SSE stream.
const navigationToggle = document.getElementById('nav-toggle');
const navigationRail = document.getElementById('rail');
if (navigationToggle && navigationRail) {
  const setOpen = (open) => {
    navigationToggle.setAttribute('aria-expanded', String(open));
    navigationRail.classList.toggle('mobile-open', open);
  };
  navigationToggle.addEventListener('click', () => {
    setOpen(navigationToggle.getAttribute('aria-expanded') !== 'true');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && navigationToggle.getAttribute('aria-expanded') === 'true') {
      setOpen(false);
      navigationToggle.focus();
    }
  });
}

// LLL-447: the ⌘K palette's keyboard half. The markup is rendered with every
// rail (shell.html) and the search half arrives from the server; what is left
// is opening, filtering the static Go-to rows, and moving a selection. Plain
// JS on purpose: this is the one shell behaviour that has to work on a page
// whose Datastar has not booted yet.
const palette = document.getElementById('cmdk');
if (palette && typeof palette.showModal === 'function') {
  const field = document.getElementById('cmdk-q');
  const goTo = document.getElementById('cmdk-goto');
  const none = document.getElementById('cmdk-none');
  const results = document.getElementById('cmdk-results');
  // The server's answer says its own empty case ("no issue matches x"), so
  // this line is only for the case it cannot cover: nothing typed matches a
  // destination and no answer has arrived, including when the fetch never
  // happens at all.
  const sayNone = () => {
    if (none) none.hidden = shown().length > 0 || results.childElementCount > 0;
  };
  const shown = () => [...palette.querySelectorAll('[data-cmdk-item]')]
    .filter((el) => el.offsetParent !== null);
  const select = (el) => {
    for (const other of palette.querySelectorAll('[data-cmdk-item]')) {
      other.classList.toggle('cmdk-sel', other === el);
      other.setAttribute('aria-selected', String(other === el));
    }
    if (el) el.scrollIntoView({block: 'nearest'});
  };
  const move = (step) => {
    const items = shown();
    if (!items.length) return;
    const at = items.indexOf(palette.querySelector('.cmdk-sel'));
    if (at < 0) return select(items[step > 0 ? 0 : items.length - 1]);
    select(items[(at + step + items.length) % items.length]);
  };
  // The Go-to rows are this page's own destinations, so filtering them needs
  // no server. The issue rows are the server's answer and are left alone.
  const filter = () => {
    const q = field.value.trim().toLowerCase();
    for (const row of goTo.querySelectorAll('[data-cmdk-item]')) {
      row.hidden = q !== '' && !row.textContent.toLowerCase().includes(q);
    }
    goTo.hidden = !goTo.querySelector('[data-cmdk-item]:not([hidden])');
    sayNone();
    select(shown()[0]);
  };
  const open = () => {
    if (palette.open) return;
    palette.showModal();
    field.select();
    filter();
  };
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      open();
    }
  });
  // The search half: one GET for the team's issues and docs, debounced, with
  // the previous one aborted so a slow answer cannot overwrite a newer query.
  // The response is plain HTML for #cmdk-results, because /issues loads no
  // Datastar and the palette must not work on five pages out of six.
  const endpoint = field.dataset.cmdkSearch;
  let pending;
  let timer;
  const ask = () => {
    const q = field.value.trim();
    if (pending) pending.abort();
    if (!q) {
      results.innerHTML = '';
      sayNone();
      return;
    }
    pending = new AbortController();
    fetch(endpoint + '&q=' + encodeURIComponent(q), {signal: pending.signal})
      .then((res) => (res.ok ? res.text() : ''))
      .then((html) => {
        // The server answers with the whole #cmdk-results element; keep this
        // page's node and take its children, so the id survives.
        const parsed = new DOMParser().parseFromString(html, 'text/html');
        results.innerHTML = parsed.getElementById('cmdk-results')?.innerHTML ?? '';
        // The list changed, so where the old selection sat means nothing:
        // take the top of the new one. Enter has to follow the best match,
        // not whichever destination happened to be selected while the
        // answer was still in flight.
        select(shown()[0]);
        sayNone();
      })
      .catch(() => {});
  };
  field.addEventListener('input', () => {
    filter();
    clearTimeout(timer);
    timer = setTimeout(ask, 200);
  });
  palette.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || (event.key === 'Tab' && !event.shiftKey)) {
      event.preventDefault();
      move(1);
    } else if (event.key === 'ArrowUp' || (event.key === 'Tab' && event.shiftKey)) {
      event.preventDefault();
      move(-1);
    } else if (event.key === 'Enter') {
      const target = palette.querySelector('.cmdk-sel') || shown()[0];
      if (target) {
        event.preventDefault();
        target.click();
      }
    }
  });
  // A click on the backdrop is outside the dialog's own box.
  palette.addEventListener('click', (event) => {
    if (event.target === palette) palette.close();
  });
}

// LLL-531/532: single-key shortcuts. They never fire while typing, with a
// modifier held (⌘K and browser keys keep theirs), or over an open dialog,
// so a letter meant for a field is never eaten. 'g' starts a chord whose
// second key picks a rail row by its data-g, so the destination is always
// the href the rail itself rendered.
const shortcutSheet = document.getElementById('kbd-help');
let chordAt = 0;
document.addEventListener('keydown', (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.target.closest?.('input, textarea, select, [contenteditable]')) return;
  if (document.querySelector('dialog[open]')) return;
  if (Date.now() - chordAt < 1000) {
    chordAt = 0;
    const row = document.querySelector(`#rail [data-g="${CSS.escape(event.key)}"]`);
    if (row) {
      event.preventDefault();
      row.click();
    }
    return;
  }
  chordAt = 0;
  if (event.key === 'g') {
    chordAt = Date.now();
  } else if (event.key === '?' && shortcutSheet) {
    event.preventDefault();
    shortcutSheet.showModal();
  } else if (event.key === '/') {
    const search = document.getElementById('board-search-input');
    if (search) {
      event.preventDefault();
      search.focus();
    }
  }
});
if (shortcutSheet) {
  shortcutSheet.addEventListener('click', (event) => {
    if (event.target === shortcutSheet) shortcutSheet.close();
  });
}
