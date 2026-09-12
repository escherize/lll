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
