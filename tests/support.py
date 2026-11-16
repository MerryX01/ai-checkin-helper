"""测试辅助：可编排的假 HTTP transport。"""
from signin.core import http


def fake_transport(script):
    """script: list of ('ok', status, body) / ('raise', Exception)。"""
    calls = []

    def transport(method, url, headers, data, timeout):
        calls.append((method, url, headers, data))
        step = script.pop(0)
        if step[0] == 'raise':
            raise step[1]
        return http.RawResponse(step[1], step[2])

    return transport, calls


def make_client(script, **kw):
    transport, calls = fake_transport(script)
    kw.setdefault('sleep', lambda s: None)
    return http.Client(transport=transport, **kw), calls
