// Collapse is personal presentation state, never a project/workspace write.
// Native details controls remain usable if browser storage is unavailable.
const projectList = document.getElementById('projects');
if (projectList) {
  const reportPreferenceError = (message) => {
    const notice = document.getElementById('pj-preference-error');
    notice.textContent = message;
    notice.hidden = false;
  };
  for (const group of projectList.querySelectorAll('.pj-group')) {
    const key = projectList.dataset.projectGroupsKey + '.' + group.dataset.projectStatus;
    try {
      const saved = localStorage.getItem(key);
      if (saved === 'closed') group.open = false;
      else if (saved !== null) throw new Error('Invalid saved project group preference');
    } catch {
      reportPreferenceError('Could not restore saved collapse preferences. Groups still work for this visit.');
    }
    // Commit the next choice during native summary activation, before its
    // default action toggles .open. The later queued toggle event can lose a
    // race with navigation or overwrite a subsequent storage change.
    // Restoring .open is not a user activation and must never write a choice.
    group.querySelector('summary').addEventListener('click', (event) => {
      if (event.defaultPrevented) return;
      const opening = !group.open;
      try {
        if (opening) localStorage.removeItem(key);
        else localStorage.setItem(key, 'closed');
      } catch {
        reportPreferenceError('Could not save collapse preferences. Your changes will last for this visit.');
      }
    });
  }
}
