"""Private credential files: Windows DPAPI; owner-only permissions on Unix."""
import base64
import ctypes
import json
import os
from ctypes import wintypes
from store import DATA


class Blob(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]


def _crypt(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError('Windows credential protection is unavailable in this session. Launch LANCE from your normal Windows account; no unencrypted fallback is used.')
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def path(name):
    if name not in ('google-client', 'google-token'):
        raise ValueError('Unknown credential type')
    return DATA / (name + '.sealed')


def save(name, value):
    data = json.dumps(value).encode()
    sealed = b'DPAPI:' + base64.b64encode(_crypt(data)) if os.name == 'nt' else b'PRIVATE:' + data
    target = path(name)
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(sealed)


def load(name):
    target = path(name)
    if not target.exists():
        return None
    data = target.read_bytes()
    if data.startswith(b'DPAPI:'):
        if os.name != 'nt':
            raise ValueError('Reconnect this account on the current OS')
        data = _crypt(base64.b64decode(data[6:]), decrypt=True)
    elif data.startswith(b'PRIVATE:'):
        data = data[8:]
    else:
        raise ValueError('Unrecognized credential file; reconnect your account')
    return json.loads(data)


def remove(name):
    path(name).unlink(missing_ok=True)
