(() => {
  let installPrompt = null;
  let installed = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
  });

  window.addEventListener('appinstalled', () => {
    installed = true;
    installPrompt = null;
    toast('Rota Próxima instalado no aparelho.', 'success');
  });

  function isIOS() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent);
  }

  function fallbackInstallInfo() {
    if (installed) {
      return toast('O Rota Próxima já está instalado neste aparelho.', 'success');
    }

    if (isIOS()) {
      modal(`
        <div class="modal-box mobile-install-box">
          <div class="modal-head">
            <div><span class="eyebrow">Instalação</span><h2>Instalar no iPhone</h2></div>
            <button type="button" class="icon-btn modal-close">×</button>
          </div>
          <div class="info mobile-install-help">
            Abra esta página no Safari, toque em <strong>Compartilhar</strong> e escolha <strong>Adicionar à Tela de Início</strong>.
          </div>
          <div class="form-actions"><button type="button" class="btn primary modal-close">Entendi</button></div>
        </div>`);
      return;
    }

    modal(`
      <div class="modal-box mobile-install-box">
        <div class="modal-head">
          <div><span class="eyebrow">Instalação</span><h2>Instalar Rota Próxima</h2></div>
          <button type="button" class="icon-btn modal-close">×</button>
        </div>
        <div class="info mobile-install-help">
          O navegador ainda não liberou a instalação automática. Abra o menu do navegador e escolha <strong>Instalar aplicativo</strong> ou <strong>Adicionar à tela inicial</strong>.
        </div>
        <div class="form-actions"><button type="button" class="btn primary modal-close">Fechar</button></div>
      </div>`);
  }

  async function requestInstall() {
    if (installed) return fallbackInstallInfo();
    if (!installPrompt) return fallbackInstallInfo();

    try {
      installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      if (choice.outcome === 'accepted') {
        installPrompt = null;
      }
    } catch (_) {
      fallbackInstallInfo();
    }
  }

  function patchLoginAccess() {
    const loginForm = document.getElementById('loginForm');
    if (!loginForm || loginForm.dataset.mobileAccessReady === '1') return;
    const eyebrow = [...loginForm.querySelectorAll('.eyebrow')]
      .find(el => (el.textContent || '').trim().toLowerCase() === 'acesso');
    if (!eyebrow) return;

    loginForm.dataset.mobileAccessReady = '1';
    const row = document.createElement('span');
    row.className = 'auth-access-row';
    eyebrow.replaceWith(row);
    row.appendChild(eyebrow);

    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'installMobileApp';
    button.className = 'mobile-qr-trigger';
    button.setAttribute('aria-label', 'Instalar Rota Próxima');
    button.title = 'Instalar aplicativo';
    button.textContent = '📱';
    button.onclick = requestInstall;
    row.appendChild(button);
  }

  new MutationObserver(patchLoginAccess).observe(document.documentElement, { childList: true, subtree: true });
  patchLoginAccess();
})();
