(() => {
  function markDashboard() {
    const page = document.getElementById('page');
    if (!page) return;

    const dashboardTitle = [...page.querySelectorAll('h1')]
      .find(el => el.textContent.trim() === 'Dashboard');

    if (!dashboardTitle) {
      page.classList.remove('dashboard-centered');
      return;
    }

    page.classList.add('dashboard-centered');

    const statGrids = [...page.querySelectorAll('.grid.stats')];
    if (statGrids[0]) statGrids[0].classList.add('dashboard-primary-stats');

    const pendingTitle = [...page.querySelectorAll('h2')]
      .find(el => el.textContent.trim() === 'Central de pendências');
    if (pendingTitle) {
      const card = pendingTitle.closest('.card');
      if (card) card.classList.add('dashboard-pending-card');
    }
  }

  const observer = new MutationObserver(markDashboard);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  markDashboard();
})();
