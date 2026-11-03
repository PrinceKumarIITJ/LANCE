"""Gmail desktop OAuth with PKCE. Credentials never leave the local data store."""
import base64
import hashlib
import os
import secrets
import threading
import time
from urllib.parse import urlencode
import httpx
import vault

SCOPES = 'https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly'
REDIRECT = 'http://127.0.0.1:8765/oauth/google/callback'
pending = {}
refresh_lock = threading.Lock()


def configure(data):
    client = data.get('installed')
    if not isinstance(client, dict) or not str(client.get('client_id', '')).endswith('.apps.googleusercontent.com') or not client.get('client_secret'):
        raise ValueError('Upload a Google OAuth Desktop app client JSON (installed client), not a service account key')
    # Never accept caller-controlled token/auth endpoints.
    vault.save('google-client', {'client_id': client['client_id'], 'client_secret': client['client_secret']})
    return {'configured': True}


def status():
    try:
        client, token = vault.load('google-client'), vault.load('google-token')
        return {'client_configured': bool(client), 'connected': bool(token),
                'email': token.get('email') if token else None,
                'smtp_configured': bool(os.environ.get('SMTP_USER') and os.environ.get('SMTP_PASSWORD'))}
    except (ValueError, OSError):
        return {'client_configured': False, 'connected': False, 'email': None, 'error': 'Reconnect local credentials'}


def begin():
    client = vault.load('google-client')
    if not client:
        raise ValueError('Configure a Google Desktop OAuth client first; see Settings and docs/SETUP.md')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    pending.clear()
    pending[state] = {'verifier': verifier, 'expires': time.time() + 600}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return {'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': client['client_id'], 'redirect_uri': REDIRECT, 'response_type': 'code',
        'scope': SCOPES, 'access_type': 'offline', 'prompt': 'consent', 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})}


def complete(code, state):
    record = pending.pop(state, None)
    if not record or record['expires'] < time.time():
        raise ValueError('Invalid/expired sign-in session. Start Connect Gmail again.')
    client = vault.load('google-client')
    with httpx.Client(timeout=30, trust_env=False) as session:
        response = session.post('https://oauth2.googleapis.com/token', data={
            **client, 'code': code, 'code_verifier': record['verifier'],
            'redirect_uri': REDIRECT, 'grant_type': 'authorization_code'})
        if not response.is_success:
            raise ValueError('Google sign-in exchange failed. Check your OAuth client and test-user configuration.')
        token = response.json()
        granted = set(token.get('scope', '').split())
        if not set(SCOPES.split()).issubset(granted):
            raise ValueError('Sending and read-only mailbox scopes are both required; reconnect and grant the requested permissions')
        identity = session.get('https://gmail.googleapis.com/gmail/v1/users/me/profile',
            headers={'Authorization': 'Bearer ' + token['access_token']})
        if not identity.is_success:
            raise ValueError('Could not verify Gmail identity')
    token['email'] = identity.json()['emailAddress']
    token['expires_at'] = time.time() + token.get('expires_in', 3600)
    vault.save('google-token', token)
    return {'connected': True, 'email': token['email']}


def access_token():
    with refresh_lock:
        token = vault.load('google-token')
        if not token:
            raise ValueError('Gmail is not connected')
        if token.get('expires_at', 0) <= time.time() + 60:
            if not token.get('refresh_token'):
                raise ValueError('Gmail sign-in expired; reconnect the account')
            client = vault.load('google-client')
            with httpx.Client(timeout=30, trust_env=False) as session:
                response = session.post('https://oauth2.googleapis.com/token', data={
                    **client, 'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'})
            if not response.is_success:
                raise ValueError('Gmail access expired/revoked; reconnect the account')
            updated = response.json()
            token.update(updated)
            token['expires_at'] = time.time() + updated.get('expires_in', 3600)
            vault.save('google-token', token)
        return token['access_token']


def send_mime(message):
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    with httpx.Client(timeout=40, trust_env=False) as client:
        response = client.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
            headers={'Authorization': 'Bearer ' + access_token()}, json={'raw': raw})
    if not response.is_success:
        raise ValueError('Gmail did not confirm acceptance; check Sent before retrying')
    return response.json()['id']


def inbox_messages():
    headers = {'Authorization': 'Bearer ' + access_token()}
    with httpx.Client(timeout=35, trust_env=False) as client:
        response = client.get('https://gmail.googleapis.com/gmail/v1/users/me/messages', headers=headers,
            params={'maxResults': 100, 'q': 'in:inbox newer_than:60d'})
        response.raise_for_status()
        for item in response.json().get('messages', []):
            detail = client.get('https://gmail.googleapis.com/gmail/v1/users/me/messages/' + item['id'],
                                headers=headers, params={'format': 'raw'})
            detail.raise_for_status()
            encoded = detail.json()['raw']
            yield base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
