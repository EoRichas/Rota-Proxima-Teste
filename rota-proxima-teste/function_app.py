import azure.functions as func
from azure.identity import ManagedIdentityCredential
import os, json, base64, re, unicodedata
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote
from datetime import datetime

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

GRAPH = "https://graph.microsoft.com/v1.0"

def _safe_name(value: str, fallback="Sem nome"):
    value = (value or fallback).strip()
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120] or fallback

def _token():
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if not client_id:
        raise RuntimeError("AZURE_CLIENT_ID não configurado.")
    cred = ManagedIdentityCredential(client_id=client_id)
    return cred.get_token("https://graph.microsoft.com/.default").token

def _graph(method, path, token, body=None, content_type="application/json"):
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
        else:
            data = body
        headers["Content-Type"] = content_type
    req = Request(GRAPH + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=45) as r:
            raw = r.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph HTTP {e.code}: {raw}") from e

def _find_child(drive_id, parent_id, name, token):
    path = f"/drives/{quote(drive_id, safe='')}/items/{quote(parent_id, safe='')}/children?$select=id,name,folder"
    data = _graph("GET", path, token)
    for item in data.get("value", []):
        if item.get("name", "").casefold() == name.casefold() and "folder" in item:
            return item["id"]
    return None

def _ensure_folder(drive_id, parent_id, name, token):
    existing = _find_child(drive_id, parent_id, name, token)
    if existing:
        return existing
    path = f"/drives/{quote(drive_id, safe='')}/items/{quote(parent_id, safe='')}/children"
    try:
        item = _graph("POST", path, token, {
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail"
        })
        return item["id"]
    except RuntimeError as exc:
        # Se outra chamada criou a pasta ao mesmo tempo, procura novamente.
        existing = _find_child(drive_id, parent_id, name, token)
        if existing:
            return existing
        raise exc

def _category(evidence_type):
    return {
        "collection_material": "Coleta",
        "delivery_drum_location": "Entrega",
        "weighing_scale": "Pesagem",
    }.get(evidence_type, "Outros")

@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"ok": True, "service": "func-rota-proxima", "storage": "sharepoint"}),
        mimetype="application/json",
        status_code=200,
    )

@app.route(route="upload-rota-pev", methods=["POST"])
def upload_rota_pev(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = req.get_json()

        required = ["route_id", "pev_name", "evidence_type", "filename", "content_base64"]
        missing = [k for k in required if not payload.get(k)]
        if missing:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "Campos obrigatórios ausentes", "missing": missing}),
                mimetype="application/json",
                status_code=400,
            )

        drive_id = os.environ.get("SHAREPOINT_DRIVE_ID")
        root_folder_id = os.environ.get("SHAREPOINT_ROOT_FOLDER_ID")
        if not drive_id or not root_folder_id:
            raise RuntimeError("SHAREPOINT_DRIVE_ID/SHAREPOINT_ROOT_FOLDER_ID não configurados.")

        token = _token()

        now = datetime.now()
        year = str(payload.get("year") or now.year)
        month_num = int(payload.get("month") or now.month)
        month_names = [
            "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
        ]
        month = f"{month_num:02d} - {month_names[month_num-1]}"

        route_id = str(payload["route_id"])
        route_name = _safe_name(payload.get("route_name") or f"Rota {route_id}")
        route_folder = _safe_name(f"Rota {int(route_id):05d} - {route_name}" if route_id.isdigit() else route_name)
        pev_folder = _safe_name(payload["pev_name"])
        category = _category(payload["evidence_type"])
        filename = _safe_name(payload["filename"], "foto.jpg")

        parent = root_folder_id
        for segment in [year, month, route_folder, pev_folder, category]:
            parent = _ensure_folder(drive_id, parent, segment, token)

        try:
            content = base64.b64decode(payload["content_base64"], validate=True)
        except Exception:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "content_base64 inválido"}),
                mimetype="application/json",
                status_code=400,
            )

        if len(content) > 20 * 1024 * 1024:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "Arquivo acima do limite de 20 MB desta função."}),
                mimetype="application/json",
                status_code=413,
            )

        upload_path = (
            f"/drives/{quote(drive_id, safe='')}/items/{quote(parent, safe='')}:"
            f"/{quote(filename, safe='')}:/content"
        )
        item = _graph("PUT", upload_path, token, content, "application/octet-stream")

        return func.HttpResponse(
            json.dumps({
                "ok": True,
                "id": item.get("id"),
                "name": item.get("name"),
                "webUrl": item.get("webUrl"),
                "size": item.get("size"),
                "folder": f"{year}/{month}/{route_folder}/{pev_folder}/{category}",
            }, ensure_ascii=False),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as exc:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            mimetype="application/json",
            status_code=500,
        )
