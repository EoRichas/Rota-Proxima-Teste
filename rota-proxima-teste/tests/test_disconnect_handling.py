import contextlib
import io
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def install_optional_dependency_stubs():
    try:
        import requests  # noqa: F401
        import reportlab  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    class DummySession:
        def mount(self, *_args, **_kwargs):
            return None

    class Dummy:
        def __init__(self, *_args, **_kwargs):
            pass

    requests = types.ModuleType('requests')
    requests.Session = DummySession
    adapters = types.ModuleType('requests.adapters')
    adapters.HTTPAdapter = Dummy
    sys.modules['requests'] = requests
    sys.modules['requests.adapters'] = adapters

    reportlab = types.ModuleType('reportlab')
    reportlab_lib = types.ModuleType('reportlab.lib')
    colors = types.ModuleType('reportlab.lib.colors')
    colors.HexColor = lambda value: value
    colors.white = 'white'
    pagesizes = types.ModuleType('reportlab.lib.pagesizes')
    pagesizes.A4 = (595, 842)
    styles = types.ModuleType('reportlab.lib.styles')
    styles.getSampleStyleSheet = lambda: {}
    styles.ParagraphStyle = Dummy
    enums = types.ModuleType('reportlab.lib.enums')
    enums.TA_CENTER = 'CENTER'
    platypus = types.ModuleType('reportlab.platypus')
    for name in ('SimpleDocTemplate', 'Paragraph', 'Spacer', 'LongTable', 'TableStyle', 'Table', 'Image'):
        setattr(platypus, name, Dummy)
    sys.modules.update({
        'reportlab': reportlab,
        'reportlab.lib': reportlab_lib,
        'reportlab.lib.colors': colors,
        'reportlab.lib.pagesizes': pagesizes,
        'reportlab.lib.styles': styles,
        'reportlab.lib.enums': enums,
        'reportlab.platypus': platypus,
    })


install_optional_dependency_stubs()

import server
import server_sharepoint


class BrokenWriter:
    def write(self, _raw):
        raise BrokenPipeError(32, 'Broken pipe')


def disconnected_handler():
    handler = server_sharepoint.SharePointHandler.__new__(server_sharepoint.SharePointHandler)
    handler.command = 'GET'
    handler.path = '/api/routes'
    handler.headers = {}
    handler.pending_headers = []
    handler.wfile = BrokenWriter()
    handler.close_connection = False
    handler.send_response = lambda _status: None
    handler.send_header = lambda _key, _value: None
    handler.end_headers = lambda: None
    handler.common_security_headers = lambda: None
    return handler


class ClientDisconnectTests(unittest.TestCase):
    def test_send_json_closes_connection_without_reraising(self):
        handler = disconnected_handler()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sent = handler.send_json({'ok': True})
        self.assertFalse(sent)
        self.assertTrue(handler.close_connection)
        self.assertIn('[CLIENT DISCONNECTED] GET /api/routes: BrokenPipeError', output.getvalue())


class SharePointOnlyTests(unittest.TestCase):
    def test_legacy_sync_endpoint_is_gone_for_admin(self):
        handler = server_sharepoint.SharePointHandler.__new__(server_sharepoint.SharePointHandler)
        handler.require_user = lambda: {'role': 'admin'}
        handler.send_json = lambda body, status=200, extra_headers=None: (status, body)
        status, body = handler.api_get('/api/evidence-sync')
        self.assertEqual(410, status)
        self.assertIn('desativada', body['error'])

    def test_frontend_does_not_restore_local_sync(self):
        source = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('const SHAREPOINT_ONLY = true;', source)
        self.assertIn("user.role === 'admin' && !SHAREPOINT_ONLY", source)
        self.assertNotIn("['photo-sync','Fotos no computador']", source)


if __name__ == '__main__':
    unittest.main()
