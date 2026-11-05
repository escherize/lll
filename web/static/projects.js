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
    // Restoring .open queues a toggle too; it is not a new user preference.
    let previousOpen = group.open;
    group.addEventListener('toggle', () => {
      if (group.open === previousOpen) return;
      previousOpen = group.open;
      try {
        if (group.open) localStorage.removeItem(key);
        else localStorage.setItem(key, 'closed');
      } catch {
        reportPreferenceError('Could not save collapse preferences. Your changes will last for this visit.');
      }
    });
  }
}
