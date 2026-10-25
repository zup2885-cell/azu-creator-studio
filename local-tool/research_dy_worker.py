"""Isolated dy-cli bridge. No browser-cookie extraction or social write commands.

Only imported API/search and QR authentication modules are used. This process
has its own config directory; the user's ~/.dy and browser profiles are unused.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


class ReadFailure(Exception):
    def __init__(self, code):self.code=code


def http_error_code(status,detail=False):
    if status==429:return 'RATE_LIMITED'
    if status==401:return 'NEED_LOGIN'
    if status in (403,412):return 'DETAIL_BLOCKED' if detail else 'PLATFORM_BLOCKED'
    if 300<=status<400:return 'NEED_LOGIN'
    return None


def isolate(root):
    from dy_cli.utils import config
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(root,0o700)
    config.CONFIG_DIR=str(root)
    config.CONFIG_FILE=str(root/'config.json')
    config.COOKIES_DIR=str(root/'cookies')
    config.DEFAULT_CONFIG['api']['cookie_file']=str(root/'cookies/default.json')
    return root/'cookies/default.json'


def public_item(row):
    if not isinstance(row,dict):return None
    ident=str(row.get('aweme_id') or '')
    if not re.fullmatch(r'\d{10,24}',ident):return None
    stat=row.get('statistics') or {}
    if not isinstance(stat,dict):stat={}
    def counter(key):
        v=stat.get(key)
        if isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=9007199254740991:return None
        return v
    # Public Douyin pages do not provide a reliable play counter: never treat
    # missing/placeholder play_count=0 as the video's actual number of views.
    author=row.get('author') or {};video=row.get('video') or {}
    if not isinstance(video,dict):video={}
    cover=video.get('cover') or video.get('origin_cover') or {}
    urls=cover.get('url_list') or [] if isinstance(cover,dict) else []
    published=row.get('create_time')
    try:published=datetime.fromtimestamp(published,timezone.utc).isoformat() if isinstance(published,int) else ''
    except (ValueError,OverflowError,OSError):published=''
    return {'aweme_id':ident,'title':str(row.get('desc') or '')[:1000],
            'text':str(row.get('desc') or '')[:50000],
            'author':str(author.get('nickname') or '')[:150] if isinstance(author,dict) else '',
            'cover':next((u for u in urls if isinstance(u,str) and u.startswith('https://')),''),
            'published_at':published,'metrics':{'plays':None,'likes':counter('digg_count'),
            'comments':counter('comment_count'),'favorites':counter('collect_count'),'shares':counter('share_count')}}


def client_for(cookie_file):
    import httpx
    from dy_cli.engines.api_client import DouyinAPIClient,SEARCH_URL,VIDEO_SEARCH_URL,VIDEO_DETAIL_URL
    allowed={SEARCH_URL,VIDEO_SEARCH_URL,VIDEO_DETAIL_URL}
    class ReadOnlyClient(DouyinAPIClient):
        @property
        def client(self):
            if self._client is None:
                # No ttwid POST, proxy changes, browser Cookie extraction, or
                # redirects carrying a Cookie to another host.
                self._client=httpx.Client(timeout=15,follow_redirects=False)
            return self._client

        def _request_with_retry(self,method,url,**kwargs):
            target=urlsplit(url)
            if method!='GET' or target.scheme!='https' or target.hostname!='www.douyin.com' or target.fragment:
                raise ReadFailure('READ_ONLY')
            if url.split('?',1)[0] not in allowed:raise ReadFailure('READ_ONLY')
            response=self.client.request(method,url,**kwargs)  # exactly one attempt
            code=http_error_code(response.status_code,url.split('?',1)[0]==VIDEO_DETAIL_URL)
            if code:raise ReadFailure(code)
            return response

        def _post(self,*args,**kwargs):raise ReadFailure('READ_ONLY')

        def _get(self,*args,**kwargs):
            data=super()._get(*args,**kwargs)
            nil=data.get('search_nil_info') or {}
            if isinstance(nil,dict) and nil.get('search_nil_type')=='verify_check':raise ReadFailure('PLATFORM_BLOCKED')
            if data.get('verify_check') or data.get('verify_info'):raise ReadFailure('PLATFORM_BLOCKED')
            if data.get('status_code') in (8,1105,1109):raise ReadFailure('NEED_LOGIN')
            if data.get('status_code') not in (None,0):raise ReadFailure('UPSTREAM_BROKEN')
            return data
    cookie=''
    if cookie_file.is_file():
        state=json.loads(cookie_file.read_text())
        cookie='; '.join(c['name']+'='+c['value'] for c in state.get('cookies',[])
                         if c.get('domain','').lstrip('.') in ('douyin.com','www.douyin.com')
                         and isinstance(c.get('name'),str) and isinstance(c.get('value'),str))
    return ReadOnlyClient(cookie=cookie,timeout=15)


def run(action,query,limit,root):
    cookie_file=isolate(root)
    if action=='login':
        from dy_cli.engines.playwright_client import PlaywrightClient
        # Upstream's explicit QR path creates an independent, visible browser.
        # Never call auth.login(--browser) or _extract_browser_cookies.
        os.umask(0o077)
        client=PlaywrightClient(account='default',headless=False)
        ok=client.login()
        if ok and cookie_file.is_file():
            state=json.loads(cookie_file.read_text())
            # Keep only this new login session's Douyin cookies. No localStorage,
            # unrelated sites, raw response bodies or user profile in the app DB.
            state={'cookies':[c for c in state.get('cookies',[]) if c.get('domain','').lstrip('.') in ('douyin.com','www.douyin.com','creator.douyin.com')],'origins':[]}
            cookie_file.write_text(json.dumps(state));os.chmod(cookie_file,0o600)
        return {'ok':bool(ok),'authenticated':bool(ok),'error':None if ok else {'code':'LOGIN_TIMEOUT'}}
    if action not in ('search','detail','probe'):raise ReadFailure('READ_ONLY')
    if not 1<=limit<=20 or not query or len(query)>300:raise ReadFailure('BAD_INPUT')
    client=client_for(cookie_file)
    try:
        if action=='detail':
            from dy_cli.engines.api_client import VIDEO_DETAIL_URL
            from dy_cli.utils.signature import get_base_params
            if not re.fullmatch(r'\d{10,24}',query):raise ReadFailure('BAD_INPUT')
            body=client._get(VIDEO_DETAIL_URL,params={**get_base_params(),'aweme_id':query})
            rows=[body.get('aweme_detail')]
        else:
            body=client.search(query,sort_type=1,search_type='video',count=limit)
            rows=[r.get('aweme_info') or r for r in (body.get('data') or []) if isinstance(r,dict)]
        items=[v for r in rows if (v:=public_item(r))]
        if not items:raise ReadFailure('NO_PUBLIC_DATA')
        return {'ok':True,'backend':'dy-cli-readonly','items':items[:limit]}
    finally:
        client.close()
        # The upstream signer owns a browser. Process exit is also a cleanup
        # boundary; close it on the same event loop when still available.
        from dy_cli.utils.signature import close_sign_page
        import asyncio
        try:
            loop=asyncio.get_event_loop()
            if not loop.is_closed():loop.run_until_complete(close_sign_page())
        except Exception:pass


if __name__=='__main__':
    try:
        result=run(sys.argv[1],sys.argv[2],int(sys.argv[3]),Path(sys.argv[4]))
    except ReadFailure as error:result={'ok':False,'error':{'code':error.code}}
    except Exception as error:
        # Do not serialize upstream exceptions: URLs/headers can contain secrets.
        name=type(error).__name__
        result={'ok':False,'error':{'code':'TIMEOUT' if 'Timeout' in name else 'UPSTREAM_BROKEN'}}
    print(json.dumps(result,ensure_ascii=False))
