#!/usr/bin/env python3
import base64
import hashlib
import os
import re

import server as rota

AZURE_FUNCTION_UPLOAD_URL = os.environ.get('AZURE_FUNCTION_UPLOAD_URL', '').strip()
_ORIGINAL_UPLOAD = rota.upload_test_evidence


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
        'collection_material': 'material',
        'delivery_drum_location': 'tambor-local',
        'weighing_scale': 'balanca',
    }.get(evidence_type, 'foto')
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f'{prefix}_{digest}.{ext}'


def _upload_to_sharepoint(token, data_url, path_prefix):
    if not AZURE_FUNCTION_UPLOAD_URL:
        return None

    content_base64, raw, ext = _decode_image_data(data_url)
    ctx = _evidence_context(token, path_prefix)
    body = {
        'route_id': ctx['route_id'],
        'route_name': ctx['route_name'],
        'pev_name': ctx['pev_name'],
        'evidence_type': ctx['evidence_type'],
        'filename': _sharepoint_filename(ctx['evidence_type'], raw, ext),
        'content_base64': content_base64,
    }
    if ctx['year']:
        body['year'] = ctx['year']
    if ctx['month']:
        body['month'] = ctx['month']

    try:
        response = rota.HTTP.post(AZURE_FUNCTION_UPLOAD_URL, json=body, timeout=70)
    except Exception as exc:
        raise RuntimeError(f'Falha de comunicação com o SharePoint: {exc}') from exc

    try:
        data = response.json()
    except Exception:
        data = {}

    if not response.ok or not data.get('ok'):
        detail = str(data.get('error') or response.text or f'HTTP {response.status_code}').strip()
        if len(detail) > 700:
            detail = detail[:700] + '...'
        raise RuntimeError(f'Falha ao salvar foto no SharePoint: {detail}')

    print(
        f"[SHAREPOINT] foto salva: rota={ctx['route_id']} pev={ctx['pev_id']} "
        f"tipo={ctx['evidence_type']} arquivo={data.get('name') or body['filename']}"
    )
    return data


def upload_test_evidence(token, data_url, path_prefix):
    # SharePoint é o destino automático adicional. O bucket privado do Supabase
    # continua sendo mantido como cópia operacional/compatibilidade com a tela
    # de sincronização local já existente.
    #
    # A chamada ao SharePoint ocorre primeiro. O nome do arquivo é derivado do
    # hash do conteúdo, então uma tentativa repetida usa o mesmo caminho e não
    # cria cópias diferentes no SharePoint.
    _upload_to_sharepoint(token, data_url, path_prefix)
    return _ORIGINAL_UPLOAD(token, data_url, path_prefix)


class SharePointHandler(rota.AppHandler):
    def api_get(self, path):
        if path == '/api/health':
            return self.send_json({
                'ok': True,
                'build': 'SHAREPOINT-AZURE-2026-08-14',
                'listen': f'{rota.HOST}:{rota.PORT}',
                'render': rota.IS_RENDER,
                'external_url': os.environ.get('RENDER_EXTERNAL_URL', ''),
                'sharepoint_upload_configured': bool(AZURE_FUNCTION_UPLOAD_URL),
                'evidence_storage': 'sharepoint+supabase' if AZURE_FUNCTION_UPLOAD_URL else 'supabase',
            })
        return super().api_get(path)


rota.upload_test_evidence = upload_test_evidence
rota.AppHandler = SharePointHandler
rota.BUILD_ID = 'SHAREPOINT-AZURE-2026-08-14'


if __name__ == '__main__':
    if AZURE_FUNCTION_UPLOAD_URL:
        print('[SHAREPOINT] Integração automática via Azure Function: ATIVA')
    else:
        print('[SHAREPOINT] AZURE_FUNCTION_UPLOAD_URL não configurada; usando somente Supabase por enquanto.')
    rota.main()
