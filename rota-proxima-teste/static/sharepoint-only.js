// Ambiente de teste: o destino definitivo das evidências é o SharePoint.
// Remove a antiga sincronização manual para pasta local sem alterar o restante da UI.
(function () {
  const originalRenderNav = window.renderNav;
  if (typeof originalRenderNav === 'function') {
    window.renderNav = function () {
      originalRenderNav();
      document.querySelectorAll('#nav button[data-page="photo-sync"]').forEach(el => el.remove());
    };
  }

  const originalGo = window.go;
  if (typeof originalGo === 'function') {
    window.go = async function (page) {
      if (page === 'photo-sync') page = 'dashboard';
      return originalGo(page);
    };
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('#nav button[data-page="photo-sync"]').forEach(el => el.remove());
  });
})();
