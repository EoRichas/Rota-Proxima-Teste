#!/usr/bin/env python3
import base64
import hashlib
import os
import re
import threading
import time

import server as rota

AZURE_FUNCTION_UPLOAD_URL = os.environ.get('AZURE_FUNCTION_UPLOAD_URL', '').strip()
_ORIGINAL_UPLOAD = rota.upload_test_evidence
BUCKET = 'rota-evidencias-teste'


def _decode_image_data(data_url):
    value = str(data_url or '').strip()
    match = re.fullmatch(r'data:(image/(?:jpeg|png|webp));base64,(.+)', value, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError('Envie uma foto válida nos formatos JPG, PNG ou WEBP')
    mime = match.group(1).lower()
    payload = match.group(2)
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError('Conteúdo da foto inválido') from exc
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError('A foto deve ter no máximo 8 MB')

    detected = None
    if len(raw) >= 3 and raw[:3] == b'\xff\xd8\xff':
        detected = 'image/jpeg'
    elif len(raw) >= 8 and raw[:8] == b'\x89PNG\r\n\x1a\n':
        detected = 'image/png'
    elif len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        detected = 'image/webp'
    if not detected or detected != mime:
        raise ValueError('O arquivo enviado não é uma imagem real ou o formato não corresponde ao conteúdo')

    ext = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}[mime]
    return payload, raw, ext


def _evidence_context(token, path_prefix):
    match = re.fullmatch(r'rota-(\d+)/pev-(\d+)/([^/]+)', str(path_prefix or '').strip())
    if not match:
        raise ValueError('Destino da evidência inválido')
    route_id = int(match.group(1))
    pev_id = int(match.group(2))
    evidence_type = match.group(3)
    route = rota.first(rota.Supa.get('routes', token, {
        'id': f'eq.{route_id}',
        'select': 'id,name,route_date',
        'limit': '1',
    })) or {}
    pev = rota.first(rota.Supa.get('pevs', token, {
        'id': f'eq.{pev_id}',
        'select': 'id,name',
        'limit': '1',
    })) or {}
    route_date = str(route.get('route_date') or '')
    year = None
    month = None
    parts = route_date.split('-')
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        year = parts[0]
        month = int(parts[1])
    return {
        'route_id': route_id,
        'route_name': route.get('name') or f'Rota {route_id}',
        'pev_id': pev_id,
        'pev_name': pev.get('name') or f'PEV {pev_id}',
        'evidence_type': evidence_type,
        'year': year,
        'month': month,
    }


def _sharepoint_filename(evidence_type, raw, ext):
    prefix = {
        'collection_material': 'LOCAL',
        'delivery_drum_location': 'TAMBOR',
        'stop_location': 'LOCAL',
        'drum': 'TAMBOR',
        'weighing_scale': 'PESAGEM',
    }.get(evidence_type, 'FOTO')
    digest = hashlib.sha256(raw).hexdigest()
    return f'{prefix}_{digest[:20]}.{ext}', digest


def _upload_to_sharepoint(token, data_url, path_prefix):
    if not AZURE_FUNCTION_UPLOAD_URL:
        raise RuntimeError('AZURE_FUNCTION_UPLOAD_URL não configurada no Render.')
    content_base64, raw, ext = _decode_image_data(data_url)
    ctx = _evidence_context(token, path_prefix)
    filename, digest = _sharepoint_filename(ctx['evidence_type'], raw, ext)
    body = {
        'route_id': ctx['route_id'],
        'route_name': ctx['route_name'],
        'pev_id': ctx['pev_id'],
        'pev_name': ctx['pev_name'],
        'evidence_type': ctx['evidence_type'],
        'filename': filename,
        'content_base64': content_base64,
    }
    if ctx['year']:
        body['year'] = ctx['year']
    if ctx['month']:
        body['month'] = ctx['month']
    response = rota.HTTP.post(AZURE_FUNCTION_UPLOAD_URL, json=body, timeout=70)
    try:
        data = response.json()
    except Exception:
        data = {}
    if not response.ok or not data.get('ok'):
        detail = str(data.get('error') or response.text or f'HTTP {response.status_code}').strip()
        raise RuntimeError(f'Falha ao salvar foto no SharePoint: {detail[:700]}')
    return ctx, digest, data


def _delete_supabase_object(token, path):
    r = rota.HTTP.delete(
        f'{rota.SUPABASE_URL}/storage/v1/object/{BUCKET}',
        headers={
            'apikey': rota.SUPABASE_KEY,
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        json={'prefixes': [path]},
        timeout=30,
    )
    if not r.ok:
        try:
            msg = r.json().get('message') or r.json().get('error') or r.text
        except Exception:
            msg = r.text
        raise RuntimeError(msg or f'Falha ao limpar Storage: HTTP {r.status_code}')


def _finish_sync_after_insert(token, storage_path, ctx, digest, sp_data):
    evidence = None
    for _ in range(20):
        rows = rota.Supa.get('route_evidences', token, {
            'storage_path': f'eq.{storage_path}',
            'select': 'id,storage_path,sharepoint_status',
            'limit': '1',
        }) or []
        if rows:
            evidence = rows[0]
            break
        time.sleep(.25)
    if not evidence:
        print(f'[SHAREPOINT] evidência não localizada para finalizar limpeza: {storage_path}')
        return
    eid = int(evidence['id'])
    sp_path = str(sp_data.get('folder') or '')
    try:
        rota.Supa.update('route_evidences', token, {'id': f'eq.{eid}'}, {
            'sharepoint_status': 'synced',
            'sharepoint_item_id': sp_data.get('id'),
            'sharepoint_url': sp_data.get('webUrl'),
            'sharepoint_path': sp_path,
            'sharepoint_sha256': digest,
            'sharepoint_synced_at': rota.now_iso(),
            'sharepoint_last_error': None,
        })
        _delete_supabase_object(token, storage_path)
        rota.Supa.update('route_evidences', token, {'id': f'eq.{eid}'}, {
            'storage_deleted_at': rota.now_iso(),
        })
        print(f"[SHAREPOINT] sincronizada e removida do Supabase: evidencia={eid} rota={ctx['route_id']} pev={ctx['pev_id']}")
    except Exception as exc:
        try:
            rota.Supa.update('route_evidences', token, {'id': f'eq.{eid}'}, {
                'sharepoint_status': 'error',
                'sharepoint_last_error': str(exc)[:1000],
            })
        except Exception:
            pass
        print(f'[SHAREPOINT] limpeza pendente evidencia={eid}: {exc}')


def upload_test_evidence(token, data_url, path_prefix):
    # Rejeita conteúdo que não seja uma imagem real antes de gravar a fila temporária.
    _decode_image_data(data_url)
    # Mantém o Supabase apenas como fila temporária/contingência.
    storage_path = _ORIGINAL_UPLOAD(token, data_url, path_prefix)
    try:
        ctx, digest, sp_data = _upload_to_sharepoint(token, data_url, path_prefix)
    except Exception:
        raise
    threading.Thread(
        target=_finish_sync_after_insert,
        args=(token, storage_path, ctx, digest, sp_data),
        daemon=True,
    ).start()
    return storage_path


def _stop_photo_types(token, stop_id):
    rows = rota.Supa.get('route_evidences', token, {
        'stop_id': f'eq.{stop_id}',
        'evidence_type': 'in.(stop_location,drum)',
        'select': 'evidence_type',
    }) or []
    return {str(row.get('evidence_type')) for row in rows}


def _production_pending(token):
    routes = rota.Supa.get('routes', token, {
        'status': 'eq.in_progress',
        'select': 'id,name,route_date,status,driver_id',
        'order': 'route_date.asc,id.asc',
    }) or []
    if not routes:
        return []
    route_map = {int(r['id']): r for r in routes}
    route_ids = ','.join(str(x) for x in route_map)
    stops = rota.Supa.get('route_stops', token, {
        'route_id': f'in.({route_ids})',
        'status': 'eq.completed',
        'service_type': 'eq.collection',
        'select': 'id,route_id,pev_id,sequence,status,service_type,collected_weight_kg',
        'order': 'route_id.asc,sequence.asc',
    }) or []
    if not stops:
        return []
    stop_ids = ','.join(str(int(x['id'])) for x in stops)
    weighings = rota.Supa.get('route_weighings', token, {
        'stop_id': f'in.({stop_ids})',
        'select': 'stop_id',
    }) or []
    weighed = {int(w['stop_id']) for w in weighings if w.get('stop_id') is not None}
    pending = [s for s in stops if int(s['id']) not in weighed]
    if not pending:
        return []
    pev_ids = ','.join(str(x) for x in sorted({int(s['pev_id']) for s in pending}))
    pevs = rota.Supa.get('pevs', token, {
        'id': f'in.({pev_ids})',
        'select': 'id,name,street,number,district,city,state,cep',
    }) or []
    pev_map = {int(p['id']): p for p in pevs}
    items = []
    for stop in pending:
        route = route_map.get(int(stop['route_id']), {})
        pev = pev_map.get(int(stop['pev_id']), {})
        items.append({
            **stop,
            'route_name': route.get('name') or f'Rota {stop["route_id"]}',
            'route_date': route.get('route_date'),
            'pev_name': pev.get('name') or f'PEV {stop["pev_id"]}',
            'street': pev.get('street', ''),
            'number': pev.get('number', ''),
            'district': pev.get('district', ''),
            'city': pev.get('city', ''),
            'state': pev.get('state', ''),
            'cep': pev.get('cep', ''),
        })
    return items


class SharePointHandler(rota.AppHandler):
    def api_get(self, path):
        if path in ('/api/evidence-sync', '/api/evidence-sync/file'):
            user = self.require_user()
            if not user:
                return
            if user.get('role') != 'admin':
                return self.send_json({'error': 'Sem permissão'}, 403)
            return self.send_json({
                'error': 'Sincronização local desativada neste ambiente. As fotos são enviadas automaticamente ao SharePoint.'
            }, 410)
        if path == '/api/production':
            user = self.require_user()
            if not user:
                return
            if user.get('role') != 'production':
                return self.send_json({'error': 'Sem permissão'}, 403)
            try:
                return self.send_json({'items': _production_pending(self.token())})
            except Exception as exc:
                return self.send_json({'error': str(exc)}, 400)
        if path == '/api/health':
            return self.send_json({
                'ok': True,
                'build': 'SHAREPOINT-DUAL-PHOTO-PRODUCTION-2026-08-19',
                'listen': f'{rota.HOST}:{rota.PORT}',
                'render': rota.IS_RENDER,
                'external_url': os.environ.get('RENDER_EXTERNAL_URL', ''),
                'sharepoint_upload_configured': bool(AZURE_FUNCTION_UPLOAD_URL),
                'evidence_storage': 'sharepoint',
                'supabase_role': 'temporary-queue',
                'cleanup_after_sharepoint_confirmation': True,
                'driver_required_evidences': ['stop_location', 'drum'],
                'production_weighing': True,
            })
        return super().api_get(path)

    def api_write(self, method, path):
        evidence_match = re.fullmatch(r'/api/stops/(\d+)/evidence', path)
        action_match = re.fullmatch(r'/api/stops/(\d+)/(complete|fail)', path)
        weighing_match = re.fullmatch(r'/api/routes/(\d+)/weighings', path)

        if method == 'POST' and evidence_match:
            try:
                data = self.read_json()
            except Exception as exc:
                return self.send_json({'error': f'JSON inválido: {exc}'}, 400)
            user = self.require_user()
            if not user:
                return
            if user.get('role') != 'driver':
                return self.send_json({'error': 'Sem permissão'}, 403)
            token = self.token()
            sid = int(evidence_match.group(1))
            evtype = str(data.get('evidence_type') or '').strip()
            if evtype not in ('stop_location', 'drum'):
                return self.send_json({'error': 'Tipo de evidência inválido. Envie foto do local ou do tambor.'}, 400)
            try:
                _decode_image_data(data.get('image_data'))
                stop = rota.first(rota.Supa.get('route_stops', token, {
                    'id': f'eq.{sid}',
                    'select': 'id,route_id,pev_id,status,service_type,routes!route_stops_route_id_fkey(driver_id,status)',
                    'limit': '1',
                }))
                if not stop:
                    return self.send_json({'error': 'Parada não encontrada'}, 404)
                route = stop.get('routes') or {}
                if str(route.get('driver_id') or '') != str(user.get('id') or '') or route.get('status') != 'in_progress':
                    return self.send_json({'error': 'Parada indisponível'}, 403)
                if stop.get('status') not in ('pending', 'arrived'):
                    return self.send_json({'error': 'Esta parada já foi encerrada'}, 409)
                existing = rota.Supa.get('route_evidences', token, {
                    'stop_id': f'eq.{sid}',
                    'evidence_type': f'eq.{evtype}',
                    'select': 'id',
                    'limit': '1',
                }) or []
                if existing:
                    return self.send_json({'ok': True, 'already_registered': True})
                route_id = int(stop['route_id'])
                storage_path = upload_test_evidence(
                    token,
                    data.get('image_data'),
                    f'rota-{route_id}/pev-{stop["pev_id"]}/{evtype}',
                )
                evidence = rota.first(rota.Supa.insert('route_evidences', token, {
                    'route_id': route_id,
                    'stop_id': sid,
                    'pev_id': stop['pev_id'],
                    'evidence_type': evtype,
                    'storage_path': storage_path,
                    'created_by': user['id'],
                }))
                rota.audit(
                    token, user, 'evidence', 'stop', sid,
                    'Evidência fotográfica registrada',
                    None, None,
                    {'evidence_type': evtype, 'storage_path': storage_path},
                )
                return self.send_json({'ok': True, 'evidence': evidence}, 201)
            except ValueError as exc:
                return self.send_json({'error': str(exc)}, 400)
            except Exception as exc:
                return self.send_json({'error': str(exc)}, 400)

        if method == 'POST' and action_match:
            try:
                data = self.read_json()
            except Exception as exc:
                return self.send_json({'error': f'JSON inválido: {exc}'}, 400)
            user = self.require_user()
            if not user:
                return
            if user.get('role') != 'driver':
                return self.send_json({'error': 'Sem permissão'}, 403)
            token = self.token()
            sid = int(action_match.group(1))
            action = action_match.group(2)
            try:
                stop = rota.first(rota.Supa.get('route_stops', token, {
                    'id': f'eq.{sid}',
                    'select': 'id,route_id,pev_id,status,service_type',
                    'limit': '1',
                }))
                if not stop:
                    return self.send_json({'error': 'Parada não encontrada'}, 404)
                photos = _stop_photo_types(token, sid)
                missing = []
                if 'stop_location' not in photos:
                    missing.append('foto do local')
                if 'drum' not in photos:
                    missing.append('foto do tambor')
                if missing:
                    return self.send_json({
                        'error': 'Adicione ' + ' e '.join(missing) + ' antes de encerrar a parada.'
                    }, 409)
                result = rota.Supa.rpc('update_stop_atomic', token, {
                    'p_stop_id': sid,
                    'p_action': action,
                    'p_data': data,
                })
                return self.send_json(
                    rota.try_auto_finish_route(
                        token, user, int(result['route_id']),
                        data.get('lat'), data.get('lng'),
                    )
                )
            except Exception as exc:
                return self.send_json({'error': str(exc)}, 400)

        if method == 'POST' and weighing_match:
            try:
                data = self.read_json()
            except Exception as exc:
                return self.send_json({'error': f'JSON inválido: {exc}'}, 400)
            user = self.require_user()
            if not user:
                return
            if user.get('role') != 'production':
                return self.send_json({'error': 'Pesagem disponível somente para o perfil Produção'}, 403)
            token = self.token()
            rid = int(weighing_match.group(1))
            sid = int(data.get('stop_id') or 0)
            weight = rota.num(data.get('weight_kg'))
            if not sid:
                return self.send_json({'error': 'Informe a coleta'}, 400)
            if not weight or weight <= 0:
                return self.send_json({'error': 'Informe um peso válido'}, 400)
            try:
                _decode_image_data(data.get('image_data'))
                stop = rota.first(rota.Supa.get('route_stops', token, {
                    'id': f'eq.{sid}',
                    'route_id': f'eq.{rid}',
                    'status': 'eq.completed',
                    'service_type': 'eq.collection',
                    'select': 'id,route_id,pev_id,status,service_type',
                    'limit': '1',
                }))
                if not stop:
                    return self.send_json({
                        'error': 'Esta coleta não está liberada para pesagem ou já foi pesada.'
                    }, 409)
                storage_path = upload_test_evidence(
                    token,
                    data.get('image_data'),
                    f'rota-{rid}/pev-{stop["pev_id"]}/weighing_scale',
                )
                evidence = rota.first(rota.Supa.insert('route_evidences', token, {
                    'route_id': rid,
                    'stop_id': sid,
                    'pev_id': stop['pev_id'],
                    'evidence_type': 'weighing_scale',
                    'storage_path': storage_path,
                    'created_by': user['id'],
                }))
                weighing = rota.first(rota.Supa.insert('route_weighings', token, {
                    'route_id': rid,
                    'stop_id': sid,
                    'pev_id': stop['pev_id'],
                    'weight_kg': weight,
                    'evidence_id': evidence['id'],
                    'created_by': user['id'],
                }))
                return self.send_json({
                    'ok': True,
                    'weighing': weighing,
                    'message': 'Peso e foto da balança registrados.',
                }, 201)
            except ValueError as exc:
                return self.send_json({'error': str(exc)}, 400)
            except Exception as exc:
                return self.send_json({'error': str(exc)}, 400)

        return super().api_write(method, path)


rota.upload_test_evidence = upload_test_evidence
rota.AppHandler = SharePointHandler
rota.BUILD_ID = 'SHAREPOINT-DUAL-PHOTO-PRODUCTION-2026-08-19'


if __name__ == '__main__':
    print('[SHAREPOINT] Destino definitivo das fotos: SharePoint')
    print('[SUPABASE] Storage usado apenas como fila temporária e contingência')
    print('[MOTORISTA] Fotos obrigatórias: local + tambor')
    print('[PRODUCAO] Peso + foto da balança obrigatórios')
    rota.main()
