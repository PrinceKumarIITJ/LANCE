"""Bounded HTTPS reading with public DNS validation and IP-pinned TLS connections."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin
from discovery import public_url


def public_addresses(host):
    answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(answer[4][0] for answer in answers))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('Destination resolves to a non-public address')
    return ips


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self,host,ip):
        super().__init__(host,443,timeout=20,context=ssl.create_default_context())
        self.pinned_ip=ip

    def connect(self):
        raw=socket.create_connection((self.pinned_ip,443),timeout=self.timeout)
        self.sock=self._context.wrap_socket(raw,server_hostname=self.host)


def fetch(url,max_bytes=1_500_000):
    for redirect in range(4):
        url=public_url(url)
        parts=urlsplit(url)
        ips=public_addresses(parts.hostname)
        connection=PinnedConnection(parts.hostname,ips[0])
        try:
            target=parts.path or '/'
            if parts.query:
                target+='?'+parts.query
            connection.request('GET',target,headers={'User-Agent':'LANCE/1.0 personal career research','Accept':'text/html,application/json,text/plain','Accept-Encoding':'identity'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location:
                    raise ValueError('Redirect has no destination')
                url=urljoin(url,location)
                continue
            if response.status!=200:
                raise ValueError(f'Public page returned HTTP {response.status}; import its text manually if login is required')
            kind=response.getheader('Content-Type','').lower()
            if not any(t in kind for t in ('html','json','text/plain')):
                raise ValueError('Only public HTML, JSON or text sources are supported')
            data=response.read(max_bytes+1)
            if len(data)>max_bytes:
                raise ValueError('Public page exceeds the research size limit')
            return {'url':url,'content':data.decode('utf-8',errors='replace'),'content_type':kind}
        finally:
            connection.close()
    raise ValueError('Too many redirects')
