(() => {
  const CLOUD_URL = 'https://rota-proxima-teste.onrender.com';

  function qrUrl(value) {
    return `https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=8&data=${encodeURIComponent(value)}`;
  }

  function openCloudModal() {
    modal(`
      <div class="modal-box mobile-cloud-box">
        <div class="modal-head">
          <div>
            <span class="eyebrow">Celular</span>
            <h2>Abrir Rota Próxima</h2>
          </div>
          <button type="button" class="icon-btn modal-close">×</button>
        </div>
        <div class="mobile-qr-wrap">
          <img src="${qrUrl(CLOUD_URL)}" alt="QR Code para abrir o Rota Próxima no celular">
        </div>
        <p class="mobile-cloud-help muted">Escaneie com a câmera do celular para abrir o ambiente de teste no Render.</p>
        <div class="mobile-cloud-url">${esc(CLOUD_URL)}</div>
        <div class="form-actions">
          <button id="shareMobileCloud" type="button" class="btn secondary">Compartilhar link</button>
          <button id="copyMobileCloud" type="button" class="btn ghost">Copiar link</button>
          <button type="button" class="btn primary modal-close">Fechar</button>
        </div>
      </div>`);

    const shareBtn = document.getElementById('shareMobileCloud');
    if (shareBtn) shareBtn.onclick = async () => {
      try {
        if (navigator.share) {
          await navigator.share({ title: 'Rota Próxima', text: 'Acesse o Rota Próxima no celular', url: CLOUD_URL });
        } else {
          await navigator.clipboard.writeText(CLOUD_URL);
          toast('Link copiado.', 'success');
        }
      } catch (err) {
        if (err?.name !== 'AbortError') toast('Não foi possível compartilhar o link.', 'error');
      }
    };

    const copyBtn = document.getElementById('copyMobileCloud');
    if (copyBtn) copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(CLOUD_URL);
        toast('Link copiado.', 'success');
      } catch (_) {
        toast('Não foi possível copiar o link.', 'error');
      }
    };
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
    button.id = 'openMobileQr';
    button.className = 'mobile-qr-trigger';
    button.setAttribute('aria-label', 'Abrir QR Code para celular');
    button.title = 'Abrir no celular';
    button.textContent = '📱';
    button.onclick = openCloudModal;
    row.appendChild(button);
  }

  new MutationObserver(patchLoginAccess).observe(document.documentElement, { childList: true, subtree: true });
  patchLoginAccess();
})();
