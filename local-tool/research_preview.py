"""Read public HTML head metadata only. No browser, login, cookies or script execution."""
from html.parser import HTMLParser
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit
import urllib.request


def uses_local_https_proxy():
    """Recognize an already configured local proxy; never change network settings."""
    proxy = urllib.request.getproxies().get('https', '')
    parsed = urlsplit(proxy)
    try:
        return parsed.scheme in ('http', 'https') and ipaddress.ip_address(parsed.hostname or '').is_loopback and bool(parsed.port)
    except ValueError:
        return False


def checked_url(url):
    from research import public_url
    url = public_url(url)
    host = urlsplit(url).hostname
    addresses = socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    ips = [ipaddress.ip_address(a[4][0]) for a in addresses]
    # A local proxy may map public DNS names to its reserved benchmark range.
    # urllib sends HTTPS through that existing proxy, not directly to these IPs.
    fake_dns = ipaddress.ip_network('198.18.0.0/15')
    proxy_dns = bool(ips) and all(ip.version == 4 and ip in fake_dns for ip in ips) and uses_local_https_proxy()
    if not ips or (any(not ip.is_global for ip in ips) and not proxy_dns):
        raise ValueError('预览只允许公开网站，不能读取本机或内网')
    return url


class PreviewHead(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = {}; self.icons = []; self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:return
        a=dict(attrs)
        if tag=='meta':
            name=(a.get('property') or a.get('name') or '').lower()
            if name in ('og:image','twitter:image','twitter:image:src') and a.get('content'):
                self.images.setdefault(name,a['content'])
        if tag=='link' and a.get('href'):
            rel=(a.get('rel') or '').lower().split()
            if 'icon' in rel or 'apple-touch-icon' in rel:
                self.icons.append((0 if 'icon' in rel else 1,a['href']))

    def handle_endtag(self, tag):
        if tag=='head':self.done=True

    def result(self, url):
        from research import public_url
        def resolve(value):
            if not value:return ''
            try:return public_url(urljoin(url,value))
            except ValueError:return ''
        image=next((resolve(self.images.get(k)) for k in ('og:image','twitter:image','twitter:image:src') if resolve(self.images.get(k))), '')
        icons=[resolve(v) for _,v in sorted(self.icons,key=lambda r:r[0])]
        favicon=next((v for v in icons if v),resolve('/favicon.ico'))
        return {'cover':image,'favicon':favicon}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections=3
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req,fp,code,msg,headers,checked_url(newurl))


def fetch_preview(url):
    url=checked_url(url)
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; AzuPublicPreview/1.0)','Accept':'text/html,application/xhtml+xml','Accept-Encoding':'identity'})
    opener=urllib.request.build_opener(SafeRedirect())
    with opener.open(request,timeout=8) as response:
        if response.headers.get_content_type() not in ('text/html','application/xhtml+xml'):
            return {'cover':'','favicon':'','status':'not_html'}
        parser=PreviewHead(); total=0; deadline=time.monotonic()+20
        encoding=response.headers.get_content_charset() or 'utf-8'
        try:''.encode(encoding)
        except LookupError:encoding='utf-8'
        while total<196608 and not parser.done:
            if time.monotonic()>=deadline:raise TimeoutError('预览读取超时')
            body=response.read(min(8192,196608-total))
            if not body:break
            total+=len(body)
            parser.feed(body.decode(encoding,errors='replace'))
        return dict(parser.result(response.geturl()),status='complete')
