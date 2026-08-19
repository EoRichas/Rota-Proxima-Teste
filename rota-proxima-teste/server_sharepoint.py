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
    value = str(data_url or '')
    if ',' not in value:
        raise ValueError('Envie uma foto válida')
    header, payload = value.split(',', 1)
    if 'base64' not in header:
        raise ValueError('Formato de foto inválido')
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError('Conteúdo da foto inválido') from exc
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError('A foto deve ter no máximo 8 MB')
    mime = 'image/jpeg'
    if header.startswith('data:image/png'):
        mime = 'image/png'
    elif header.startswith('data:image/webp'):
        mime = 'image/webp'
    ext = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}.get(mime, 'jpg')
    return payload, raw, ext


def _evidence_context(token, path_prefix):
    match = re.fullmatch(r'rota-(\d+)/pev-(\d+)/([^/]+)', str(path_prefix or '').strip())
    if not match:
        raise ValueError('Destino da evidência inválido')
    route_id = int(match.group(1))
    pev_id = int(match.group(2))
    evidence_type = match.group(3)
    route = rota.first(rota.Supa.get('routes', token, {'id': f'eq.{route_id}', 'select': 'id,name,route_date', 'limit': '1'})) or {}
    pev = rota.first(rota.Supa.get('pevs', token, {'id': f'eq.{pev_id}', 'select': 'id,name', 'limit': '1'})) or {}
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
    # Exclusão exclusivamente pela Storage API, nunca por SQL.
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
    # A linha route_evidences é inserida logo depois que upload_test_evidence retorna.
    # Esperamos essa linha existir; só então registramos o comprovante do SharePoint
    # e removemos o arquivo temporário do Supabase.
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
        # Se a confirmação/limpeza falhar, NÃO apagamos metadados nem forçamos a exclusão.
        # O arquivo permanece disponível no Supabase para nova tentativa.
        try:
            rota.Supa.update('route_evidences', token, {'id': f'eq.{eid}'}, {
                'sharepoint_status': 'error',
                'sharepoint_last_error': str(exc)[:1000],
            })
        except Exception:
            pass
        print(f'[SHAREPOINT] limpeza pendente evidencia={eid}: {exc}')


def upload_test_evidence(token, data_url, path_prefix):
    # Fluxo de teste:
    # 1) guarda a foto no bucket privado do Supabase como fila/segurança temporária;
    # 2) envia a mesma foto para o SharePoint via Azure Function;
    # 3) confirma no banco os dados retornados pelo SharePoint;
    # 4) só depois remove o arquivo físico do Supabase.
    # Se o SharePoint falhar, a foto continua no Supabase e a operação informa erro.
    storage_path = _ORIGINAL_UPLOAD(token, data_url, path_prefix)
    try:
        ctx, digest, sp_data = _upload_to_sharepoint(token, data_url, path_prefix)
    except Exception:
        # Não removemos a cópia temporária em nenhuma falha.
        raise
    threading.Thread(
        target=_finish_sync_after_insert,
        args=(token, storage_path, ctx, digest, sp_data),
        daemon=True,
    ).start()
    return storage_path


class SharePointHandler(rota.AppHandler):
    def api_get(self, path):
        if path in ('/api/evidence-sync','/api/evidence-sync/file'):
            user=self.require_user()
            if not user:return
            if user.get('role')!='admin':return self.send_json({'error':'Sem permissão'},403)
            return self.send_json({'error':'Sincronização local desativada neste ambiente. As fotos são enviadas automaticamente ao SharePoint.'},410)
        if path == '/api/health':
            return self.send_json({
                'ok': True,
                'build': 'SHAREPOINT-ROTA-PEV-2026-08-19',
                'listen': f'{rota.HOST}:{rota.PORT}',
                'render': rota.IS_RENDER,
                'external_url': os.environ.get('RENDER_EXTERNAL_URL', ''),
                'sharepoint_upload_configured': bool(AZURE_FUNCTION_UPLOAD_URL),
                'evidence_storage': 'sharepoint',
                'supabase_role': 'temporary-queue',
                'cleanup_after_sharepoint_confirmation': True,
            })
        return super().api_get(path)


rota.upload_test_evidence = upload_test_evidence
rota.AppHandler = SharePointHandler
rota.BUILD_ID = 'SHAREPOINT-ROTA-PEV-2026-08-19'


if __name__ == '__main__':
    print('[SHAREPOINT] Destino definitivo das fotos: SharePoint')
    print('[SUPABASE] Storage usado apenas como fila temporária e contingência')
    rota.main()
