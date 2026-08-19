(() => {
  const reverseCache = new Map();

  function removeFieldByName(form, name) {
    const input = form?.querySelector(`[name="${name}"]`);
    if (!input) return;
    const field = input.closest('label.field') || input.parentElement;
    if (field) field.remove();
  }

  function cleanRequestForm() {
    const form = document.getElementById('requestForm');
    if (!form) return;

    // Remove completamente a janela visual da solicitação.
    ['window_start', 'window_end'].forEach(name => removeFieldByName(form, name));

    // Remove o aviso antigo que fazia referência à janela normal.
    [...form.querySelectorAll('.info')].forEach(el => {
      const text = (el.textContent || '').toLowerCase();
      if (text.includes('janela normal') || text.includes('janela inicial') || text.includes('janela final')) {
        el.remove();
      }
    });
  }

  function cleanPevOperation() {
    const form = document.getElementById('pevForm');
    if (!form) return;

    // Remove a seção visual Operação inteira do cadastro da PEV.
    const operationTitle = [...form.querySelectorAll('h3')]
      .find(el => (el.textContent || '').trim().toLowerCase() === 'operação');
    if (operationTitle) {
      const wrapper = operationTitle.closest('.span-2') || operationTitle.parentElement;
      if (wrapper) wrapper.remove();
    }

    [
      'service_start',
      'service_end',
      'default_priority',
      'favorite',
      'notes',
      'internal_notes',
    ].forEach(name => removeFieldByName(form, name));
  }

  function formatAddress(data) {
    const a = data?.address || {};
    const street = a.road || a.pedestrian || a.residential || a.footway || a.path || '';
    const number = a.house_number || '';
    const district = a.suburb || a.neighbourhood || a.quarter || a.city_district || '';
    const city = a.city || a.town || a.village || a.municipality || '';
    const state = a.state || '';
    const postcode = a.postcode || '';

    const parts = [];
    if (street) parts.push(`${street}${number ? `, ${number}` : ''}`);
    if (district) parts.push(district);
    if (city || state) parts.push([city, state].filter(Boolean).join(' - '));
    if (postcode) parts.push(`CEP ${postcode}`);

    return parts.join(' • ') || data?.display_name || 'Endereço não identificado';
  }

  async function reverseGeocode(lat, lng) {
    const key = `${Number(lat).toFixed(5)},${Number(lng).toFixed(5)}`;
    if (reverseCache.has(key)) return reverseCache.get(key);

    const task = (async () => {
      const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lng)}&zoom=18&addressdetails=1&accept-language=pt-BR`;
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`Geocodificação indisponível (${response.status})`);
      return formatAddress(await response.json());
    })().catch(() => 'Endereço não identificado');

    reverseCache.set(key, task);
    return task;
  }

  function patchLastDriverPosition() {
    [...document.querySelectorAll('.info')].forEach(box => {
      if (box.dataset.driverAddressState) return;
      const strong = box.querySelector('strong');
      if (!strong || (strong.textContent || '').trim() !== 'Última posição do motorista:') return;

      const text = box.textContent || '';
      const match = text.match(/(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)/);
      if (!match) return;

      const lat = match[1];
      const lng = match[2];
      const afterCoords = text.slice((match.index || 0) + match[0].length).trim();
      const meta = afterCoords.replace(/^•\s*/, '');

      box.dataset.driverAddressState = 'loading';
      box.innerHTML = `<strong>Última posição do motorista:</strong> <span class="driver-position-address">Localizando endereço...</span>${meta ? ` • ${esc(meta)}` : ''}`;

      reverseGeocode(lat, lng).then(address => {
        const target = box.querySelector('.driver-position-address');
        if (!target) return;
        target.textContent = address;
        box.dataset.driverAddressState = 'done';
      });
    });
  }

  function applyUiCleanup() {
    cleanRequestForm();
    cleanPevOperation();
    patchLastDriverPosition();
  }

  const observer = new MutationObserver(applyUiCleanup);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  applyUiCleanup();
})();
