(() => {
  // Compatibilidade entre o banco já atualizado e o frontend publicado anteriormente.
  roleLabel.production = 'Produção';

  const originalEnterApp = enterApp;
  const originalRenderNav = renderNav;
  const originalGo = go;

  enterApp = function(user) {
    if (user.role !== 'production') return originalEnterApp(user);
    state.user = user;
    $('#authScreen').classList.add('hidden');
    $('#appShell').classList.remove('hidden');
    $('#sidebarRole').textContent = roleLabel[user.role] || user.role;
    $('#currentUserCard').innerHTML = `<strong>${esc(user.name)}</strong><span>@${esc(user.username)}</span><button id="myPasswordBtn" class="btn ghost small" style="margin-top:8px">Minha senha</button>`;
    $('#myPasswordBtn').onclick = () => openPasswordModal(false);
    if (user.must_change_password) setTimeout(() => openPasswordModal(true), 80);
    $('#mobileUserInitial').textContent = user.name.slice(0,1).toUpperCase();
    renderNav();
    go('production');
  };

  renderNav = function() {
    if (state.user?.role !== 'production') return originalRenderNav();
    const items = [['production', 'Pesagens']];
    $('#nav').innerHTML = items.map(([id,label]) => `<button data-page="${id}">${label}</button>`).join('');
    $$('#nav button').forEach(b => b.onclick = () => {
      $('#sidebar').classList.remove('open');
      go(b.dataset.page);
    });
  };

  go = async function(page) {
    if (page !== 'production') return originalGo(page);
    if (state.routeListTimer) {
      clearInterval(state.routeListTimer);
      state.routeListTimer = null;
    }
    state.page = page;
    $$('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    $('#page').innerHTML = `<div class="empty">Carregando...</div>`;
    try {
      return await renderProduction();
    } catch (e) {
      $('#page').innerHTML = `<div class="warning">${esc(e.message)}</div>`;
    }
  };

  async function renderProduction() {
    const data = await api('/api/production');
    const items = data.items || [];
    $('#page').innerHTML = `
      <div class="page-head production-head">
        <div>
          <span class="eyebrow">Produção</span>
          <h1>Pesagens pendentes</h1>
          <p class="muted">Somente coletas concluídas pelo motorista e liberadas para pesagem aparecem aqui.</p>
        </div>
        <div class="page-head-actions">
          <button id="refreshProduction" class="btn secondary">Atualizar</button>
        </div>
      </div>
      ${items.length ? `
        <div class="production-grid">
          ${items.map(item => {
            const address = [
              `${item.street || ''}${item.number ? `, ${item.number}` : ''}`,
              item.district || '',
              item.city && item.state ? `${item.city}/${item.state}` : (item.city || item.state || ''),
            ].filter(Boolean).join(' • ');
            return `
              <form class="card production-card production-weighing-form"
                    data-route="${Number(item.route_id)}"
                    data-stop="${Number(item.id)}">
                <div class="production-card-head">
                  <div>
                    <span class="eyebrow">${esc(item.route_name || `Rota ${item.route_id}`)}</span>
                    <h2>${esc(item.pev_name || `PEV ${item.pev_id}`)}</h2>
                  </div>
                  <span class="badge normal">Coleta</span>
                </div>
                <p class="muted">${esc(fmtDate(item.route_date))}${address ? ` • ${esc(address)}` : ''}</p>
                <label class="field">
                  <span>Peso final (kg) *</span>
                  <input name="weight_kg" type="number" min="0.001" step="0.001"
                         inputmode="decimal" placeholder="0,000" required>
                </label>
                <div class="production-photo-box">
                  <strong>Foto da balança *</strong>
                  <p class="muted">A foto é obrigatória junto com o peso.</p>
                  <div class="evidence-actions">
                    <label class="btn secondary">📷 Tirar foto
                      <input class="hidden-file production-camera" type="file"
                             accept="image/jpeg,image/png,image/webp" capture="environment">
                    </label>
                    <label class="btn ghost">⬆ Fazer upload
                      <input class="hidden-file production-upload" type="file"
                             accept="image/jpeg,image/png,image/webp">
                    </label>
                  </div>
                  <div class="production-file-name muted">Nenhuma foto selecionada</div>
                </div>
                <button class="btn success wide" type="submit">Salvar peso e foto</button>
              </form>`;
          }).join('')}
        </div>` :
        `<div class="card production-empty">
           <h2>Nenhuma pesagem pendente</h2>
           <p class="muted">Quando o motorista encerrar todas as paradas de uma rota com coleta, as PEVs serão liberadas aqui automaticamente.</p>
         </div>`
      }`;

    if ($('#refreshProduction')) $('#refreshProduction').onclick = () => renderProduction();

    $$('.production-weighing-form').forEach(form => {
      let selected = null;
      const name = form.querySelector('.production-file-name');
      form.querySelectorAll('input[type=file]').forEach(input => {
        input.onchange = () => {
          selected = input.files?.[0] || null;
          if (name) name.textContent = selected ? selected.name : 'Nenhuma foto selecionada';
        };
      });
      form.onsubmit = async e => {
        e.preventDefault();
        const submit = form.querySelector('button[type=submit]');
        try {
          if (!selected) throw new Error('Tire uma foto da balança ou selecione uma imagem.');
          const rawWeight = String(new FormData(form).get('weight_kg') || '').replace(',', '.');
          const weight = Number(rawWeight);
          if (!Number.isFinite(weight) || weight <= 0) throw new Error('Informe um peso válido.');
          submit.disabled = true;
          submit.textContent = 'Salvando...';
          const image_data = await imageFileToDataUrl(selected);
          await api(`/api/routes/${Number(form.dataset.route)}/weighings`, {
            method: 'POST',
            body: {
              stop_id: Number(form.dataset.stop),
              weight_kg: weight,
              image_data,
            },
          });
          toast('Peso e foto da balança registrados.', 'success');
          await renderProduction();
        } catch (err) {
          toast(err.message, 'error');
          submit.disabled = false;
          submit.textContent = 'Salvar peso e foto';
        }
      };
    });
  }

  function stopPhotoState(route, stop) {
    const types = new Set(
      (route.evidences || [])
        .filter(e => Number(e.stop_id) === Number(stop.id))
        .map(e => e.evidence_type)
    );
    const location = types.has('stop_location');
    const drum = types.has('drum');
    return { location, drum, complete: location && drum };
  }

  hasStopEvidence = function(route, stop) {
    return stopPhotoState(route, stop).complete;
  };

  driverNextStopHtml = function(s, route) {
    const addr = `${esc(s.street)}, ${esc(s.number || 's/n')}${s.complement ? ` - ${esc(s.complement)}` : ''}<br>${s.district ? `${esc(s.district)} • ` : ''}${esc(s.city)}/${esc(s.state)}`;
    const photos = stopPhotoState(route, s);

    const evidenceBox = (type, title, done, cameraId, uploadId) => `
      <div class="evidence-box driver-photo-box ${done ? 'evidence-ok' : ''}">
        <strong>${title} *</strong>
        <p class="muted">Obrigatória para finalizar ou registrar a parada como não realizada.</p>
        ${done
          ? '<div class="success-note">✓ Foto registrada</div>'
          : `<div class="evidence-actions">
               <label class="btn secondary">📷 Tirar foto
                 <input id="${cameraId}" class="hidden-file" type="file"
                        accept="image/jpeg,image/png,image/webp" capture="environment"
                        data-evidence-type="${type}">
               </label>
               <label class="btn ghost">⬆ Fazer upload
                 <input id="${uploadId}" class="hidden-file" type="file"
                        accept="image/jpeg,image/png,image/webp"
                        data-evidence-type="${type}">
               </label>
             </div>
             <div id="upload-${type}" class="muted"></div>`}
      </div>`;

    return `<div class="card next-stop">
      <span class="eyebrow">Próxima parada • ${s.sequence}</span>
      <h2>${esc(s.pev_name)}</h2>
      <div class="next-stop-address">${addr}</div>
      <div class="info"><strong>Tipo de atendimento: ${esc(serviceTypeLabel[s.service_type || 'collection'])}</strong></div>
      ${s.exact_time ? `<div class="warning"><strong>Horário específico: ${esc(s.exact_time)}</strong></div>` : ''}
      <div class="dual-photo-grid">
        ${evidenceBox('stop_location', 'Foto do local', photos.location, 'locationCamera', 'locationUpload')}
        ${evidenceBox('drum', 'Foto do tambor', photos.drum, 'drumCamera', 'drumUpload')}
      </div>
      ${photos.complete
        ? '<div class="success-note driver-photos-ready">✓ Fotos obrigatórias concluídas</div>'
        : '<div class="warning driver-photos-warning">As fotos do local e do tambor são obrigatórias antes de encerrar a parada.</div>'}
      <div class="driver-actions">
        <button id="googleNav" class="btn blue">Google Maps</button>
        <button id="wazeNav" class="btn secondary">Waze</button>
        ${s.status === 'pending' ? '<button id="arriveStop" class="btn secondary full">Cheguei ao local</button>' : ''}
        <button id="completeStop" class="btn success full" ${photos.complete ? '' : 'disabled'}>✓ Finalizar parada</button>
        <button id="failStop" class="btn danger" ${photos.complete ? '' : 'disabled'}>Não realizada</button>
        <button id="recalcRoute" class="btn ghost">Recalcular restante</button>
      </div>
    </div>`;
  };

  bindDriverStopActions = function(route, next) {
    if (!next) return;
    const fullAddress = [
      `${next.street}${next.number ? `, ${next.number}` : ''}`,
      next.district || '',
      `${next.city} - ${next.state}`,
      next.cep || '',
      'Brasil',
    ].filter(Boolean).join(', ');
    const address = encodeURIComponent(fullAddress);

    if ($('#googleNav')) $('#googleNav').onclick = () =>
      window.open(`https://www.google.com/maps/dir/?api=1&destination=${address}&travelmode=driving&dir_action=navigate`, '_blank');
    if ($('#wazeNav')) $('#wazeNav').onclick = () =>
      window.open(`https://waze.com/ul?q=${address}&navigate=yes`, '_blank');

    if ($('#arriveStop')) $('#arriveStop').onclick = async () => {
      try {
        const pos = await getPosition();
        drawDriverRoute(await api(`/api/stops/${next.id}/arrive`, {
          method: 'POST',
          body: pos,
        }));
        toast('Chegada registrada.', 'success');
      } catch (e) {
        toast(e.message, 'error');
      }
    };

    const sendEvidence = async (file, evidence_type) => {
      try {
        const status = $(`#upload-${evidence_type}`);
        if (status) status.textContent = 'Enviando foto...';
        const image_data = await imageFileToDataUrl(file);
        await api(`/api/stops/${next.id}/evidence`, {
          method: 'POST',
          body: { image_data, evidence_type },
        });
        toast(
          evidence_type === 'stop_location'
            ? 'Foto do local registrada.'
            : 'Foto do tambor registrada.',
          'success'
        );
        drawDriverRoute(await api(`/api/routes/${route.id}`));
      } catch (e) {
        toast(e.message, 'error');
        const status = $(`#upload-${evidence_type}`);
        if (status) status.textContent = '';
      }
    };

    ['locationCamera', 'locationUpload', 'drumCamera', 'drumUpload'].forEach(id => {
      const input = $(`#${id}`);
      if (!input) return;
      input.onchange = () => {
        const file = input.files?.[0];
        const evidence_type = input.dataset.evidenceType;
        if (file && evidence_type) sendEvidence(file, evidence_type);
      };
    });

    if ($('#completeStop')) $('#completeStop').onclick = async () => {
      try {
        const photos = stopPhotoState(route, next);
        if (!photos.complete) throw new Error('Registre a foto do local e a foto do tambor antes de finalizar.');
        const pos = await getPosition();
        const updated = await api(`/api/stops/${next.id}/complete`, {
          method: 'POST',
          body: { ...pos, note: '' },
        });
        toast(
          updated.status === 'finished'
            ? 'Parada concluída. Rota finalizada automaticamente.'
            : 'Parada concluída.',
          'success'
        );
        drawDriverRoute(updated);
      } catch (e) {
        toast(e.message, 'error');
      }
    };

    if ($('#failStop')) $('#failStop').onclick = () => {
      const photos = stopPhotoState(route, next);
      if (!photos.complete) return toast(
        'Registre a foto do local e a foto do tambor antes de marcar como não realizada.',
        'error'
      );
      openFailModal(next, route);
    };

    if ($('#recalcRoute')) $('#recalcRoute').onclick = async () => {
      try {
        const pos = await getPosition(true);
        drawDriverRoute(await api(`/api/routes/${route.id}/recalculate`, {
          method: 'POST',
          body: { ...pos, local_time: localHHMM() },
        }));
        toast('Restante recalculado.', 'success');
      } catch (e) {
        toast(e.message, 'error');
      }
    };
  };

  const originalOpenFailModal = openFailModal;
  openFailModal = function(stop, route) {
    const photos = stopPhotoState(route, stop);
    if (!photos.complete) {
      toast('As fotos do local e do tambor são obrigatórias antes de registrar “Não realizada”.', 'error');
      return;
    }
    return originalOpenFailModal(stop, route);
  };

  // A pesagem não pertence mais ao motorista. Quando ele terminar as paradas,
  // a rota permanece aguardando o perfil Produção.
  weighingPanelHtml = function() {
    return `<div class="card driver-production-handoff">
      <h2>Etapa do motorista concluída</h2>
      <p class="muted">Todas as paradas foram encerradas. As coletas realizadas foram liberadas para a Produção registrar peso e foto da balança.</p>
      <div class="info">Você não precisa realizar pesagens nesta tela.</div>
    </div>`;
  };
  bindWeighingForms = function() {};

  function ensureOption(select, value, label) {
    if (!select || [...select.options].some(o => o.value === value)) return;
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  function removeFieldByName(form, name) {
    const input = form?.querySelector(`[name="${name}"]`);
    if (!input) return;
    const field = input.closest('label.field') || input.parentElement;
    if (field) field.remove();
  }

  function applyDomPatches() {
    ensureOption($('#userRoleFilter'), 'production', 'Produção');
    ensureOption($('#userForm select[name="role"]'), 'production', 'Produção');

    const pevForm = $('#pevForm');
    if (pevForm) {
      ['service_start', 'service_end', 'notes', 'internal_notes'].forEach(name =>
        removeFieldByName(pevForm, name)
      );
    }

    const requestForm = $('#requestForm');
    if (requestForm && !requestForm.dataset.workflowRequestReset) {
      requestForm.dataset.workflowRequestReset = '1';
      const start = requestForm.querySelector('[name="window_start"]');
      const end = requestForm.querySelector('[name="window_end"]');
      if (start) start.value = '';
      if (end) end.value = '';
    }
  }

  new MutationObserver(applyDomPatches).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  applyDomPatches();

  // Protege contra a continuação assíncrona de um boot que tenha começado antes
  // deste patch ser carregado.
  setTimeout(() => {
    if (state.user?.role === 'production' && state.page !== 'production') {
      renderNav();
      go('production');
    }
  }, 0);
})();
