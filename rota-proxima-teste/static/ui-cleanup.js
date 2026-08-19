(() => {
  const reverseCache = new Map();

  function removeFieldByName(form, name) {
    const input = form?.querySelector(`[name="${name}"]`);
    if (!input) return;
    const field = input.closest('label.field') || input.parentElement;
    if (field) field.remove();
  }

  function setupRequestScheduleToggle(form) {
    if (!form || form.dataset.scheduleToggleReady === '1') return;
    const exactInput = form.querySelector('[name="exact_time"]');
    const priorityInput = form.querySelector('[name="priority"]');
    if (!exactInput || !priorityInput) return;

    const exactField = exactInput.closest('label.field');
    const priorityField = priorityInput.closest('label.field');
    if (!exactField || !priorityField) return;

    form.dataset.scheduleToggleReady = '1';

    const toggle = document.createElement('label');
    toggle.className = 'request-schedule-toggle';
    toggle.innerHTML = `
      <input type="checkbox" id="requestNeedsTime">
      <span>
        <strong>Necessário horário</strong>
        <small>Marque somente quando esta solicitação tiver horário combinado.</small>
      </span>`;

    const fields = document.createElement('div');
    fields.className = 'request-schedule-fields span-2';

    priorityField.before(toggle);
    toggle.after(fields);

    exactField.classList.remove('span-2');
    const exactLabel = exactField.querySelector(':scope > span');
    if (exactLabel) exactLabel.textContent = 'Horário *';
    const exactHelp = exactField.querySelector('small');
    if (exactHelp) exactHelp.remove();

    const priorityLabel = priorityField.querySelector(':scope > span');
    if (priorityLabel) priorityLabel.textContent = 'Prioridade';

    fields.append(exactField, priorityField);

    const checkbox = toggle.querySelector('input[type="checkbox"]');
    const sync = () => {
      const enabled = checkbox.checked;
      fields.hidden = !enabled;
      exactInput.required = enabled;
      if (!enabled) {
        exactInput.value = '';
        priorityInput.value = 'normal';
      }
    };

    checkbox.addEventListener('change', sync);
    sync();
  }

  function cleanRequestForm() {
    const form = document.getElementById('requestForm');
    if (!form) return;

    // Janela inicial/final deixa de existir na solicitação.
    ['window_start', 'window_end'].forEach(name => removeFieldByName(form, name));

    [...form.querySelectorAll('.info')].forEach(el => {
      const text = (el.textContent || '').toLowerCase();
      if (text.includes('janela normal') || text.includes('janela inicial') || text.includes('janela final')) {
        el.remove();
      }
    });

    setupRequestScheduleToggle(form);
  }

  function cleanPevOperation() {
    const form = document.getElementById('pevForm');
    if (!form) return;

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

  function enforceRequestOnlyPlannerRules() {
    const selector = document.getElementById('pevSelector');
    if (!selector || typeof state === 'undefined') return;

    const selectedRequests = state.requestSelection || [];
    const requestByPev = new Map(selectedRequests.map(r => [Number(r.pev_id), r]));

    selector.querySelectorAll('.pev-check').forEach(row => {
      const service = row.querySelector('.pev-service-type');
      const priority = row.querySelector('.pev-priority');
      const exact = row.querySelector('.pev-exact-time');
      const id = Number(service?.dataset.id || priority?.dataset.id || exact?.dataset.id || 0);
      if (!id) return;

      const request = requestByPev.get(id);
      const priorityValue = request?.priority || 'normal';
      const exactValue = request?.exact_time || '';

      state.plannerPriorities[id] = priorityValue;
      state.plannerExactTimes[id] = exactValue;

      if (priority) {
        priority.value = priorityValue;
        const control = priority.closest('.planner-control');
        if (control) control.style.display = 'none';
      }
      if (exact) {
        exact.value = exactValue;
        const control = exact.closest('.planner-control');
        if (control) control.style.display = 'none';
      }
      if (service) {
        const control = service.closest('.planner-control');
        if (control) control.classList.add('planner-service-only');
      }
    });
  }

  function formatAddress(data) {
    const a = data?.address || {};
    const street = a.road || a.pedestrian || a.residential || a.footway || a.path || '';
    const number = a.house_number || '';
    const district = a.suburb || a.neighbourhood || a.quarter || a.city_district || '';
    const city = a.city || a.town || a.village || a.municipality || '';
    const stateName = a.state || '';
    const postcode = a.postcode || '';

    const parts = [];
    if (street) parts.push(`${street}${number ? `, ${number}` : ''}`);
    if (district) parts.push(district);
    if (city || stateName) parts.push([city, stateName].filter(Boolean).join(' - '));
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
    enforceRequestOnlyPlannerRules();
    patchLastDriverPosition();
  }

  const observer = new MutationObserver(applyUiCleanup);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  applyUiCleanup();
})();
