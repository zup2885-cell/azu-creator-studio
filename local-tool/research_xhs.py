"""Read-only adapter for the user's existing local Xiaohongshu MCP service."""
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit,parse_qs,urlencode
import urllib.request
import urllib.error

BASE='http://127.0.0.1:18060'
READ_PATHS={'/api/v1/feeds/search','/api/v1/feeds/detail','/api/v1/login/status','/api/v1/login/qrcode'}


def request(path,body=None):
    if path not in READ_PATHS:raise ValueError('此连接仅允许读取作品和登录状态')
    cfg=tomllib.loads((Path.home()/'.codex/config.toml').read_text())
    server=cfg.get('mcp_servers',{}).get('xiaohongshu',{})
    if server.get('url','').rstrip('/')!=BASE+'/mcp':raise ValueError('小红书本地连接尚未配置')
    headers={k:v for k,v in server.get('http_headers',{}).items() if k.lower()=='authorization'}
    headers['Content-Type']='application/json'
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with opener.open(req,timeout=85) as response:
        data=response.read(3*1024*1024+1)
        if len(data)>3*1024*1024:raise ValueError('小红书返回过大')
        doc=json.loads(data)
    if not doc.get('success',True):
        msg=str(doc.get('message') or doc.get('error') or '')
        if '登录' in msg or 'login' in msg.lower():raise PermissionError('NEED_LOGIN')
        raise ValueError('小红书本次没有返回可用数据')
    return doc.get('data',doc)


def metric(value):
    if value is None or value=='':return None,False
    s=str(value).strip().replace(',','')
    if re.fullmatch(r'\d+',s):return int(s),False
    match=re.fullmatch(r'(\d+(?:\.\d+)?)(万|亿|[kKmMwW])\+?',s)
    if match:
        factor={'万':10000,'亿':100000000,'k':1000,'m':1000000,'w':10000}[match[2].lower()]
        return int(float(match[1])*factor),True
    return None,False


def to_item(row,original_url=''):
    card=row.get('noteCard') or row.get('note') or row
    ident=row.get('id') or card.get('noteId') or card.get('note_id')
    if not re.fullmatch(r'[0-9a-fA-F]{24}',str(ident or '')):raise ValueError('笔记标识无效')
    token=row.get('xsecToken') or card.get('xsecToken') or ''
    url=original_url or 'https://www.xiaohongshu.com/explore/'+ident+('?' + urlencode({'xsec_token':token,'xsec_source':'pc_search'}) if token else '')
    info=card.get('interactInfo') or {};metrics={};approx=[]
    for key,field in [('likes','likedCount'),('comments','commentCount'),('favorites','collectedCount'),('shares','shareCount')]:
        metrics[key],rounded=metric(info.get(field) if key!='shares' else info.get('sharedCount',info.get('shareCount')))
        if rounded:approx.append(key)
    user=card.get('user') or {};cover=card.get('cover') or {}
    image=cover.get('urlDefault') or cover.get('url') or next((v.get('url') for v in cover.get('infoList',[]) if v.get('url')),'')
    if not image:image=next((v.get('urlDefault') or v.get('url') for v in card.get('imageList',[]) if v.get('urlDefault') or v.get('url')),'')
    return {'url':url,'title':card.get('displayTitle') or card.get('title') or card.get('desc') or '小红书笔记','text':card.get('desc') or '',
            'author':user.get('nickname') or user.get('nickName') or '', 'cover':image,
            'metrics':metrics,'metric_approximate':approx,'published_at':card.get('time') or ''}


def collect(action,query,limit,popular=False):
    try:
        status=request('/api/v1/login/status')
        if not status.get('is_logged_in'):return {'ok':False,'error':{'code':'NEED_LOGIN'}}
        if action=='search':
            data=request('/api/v1/feeds/search',{'keyword':query,'filters':{'note_type':'不限','sort_by':'最多点赞' if popular else '综合'}})
            rows=data.get('feeds',[]) if isinstance(data,dict) else data
            items=[]
            for row in rows[:limit]:
                try:items.append(to_item(row))
                except (ValueError,TypeError,KeyError):continue
        else:
            parsed=urlsplit(query)
            ident=parsed.path.rstrip('/').split('/')[-1]
            if not re.fullmatch(r'[0-9a-fA-F]{24}',ident):raise ValueError('请使用完整的小红书笔记链接')
            token=parse_qs(parsed.query).get('xsec_token',[''])[0]
            if not token:raise ValueError('链接缺少作品访问参数，请从小红书分享中复制完整链接，或先按关键词搜索')
            data=request('/api/v1/feeds/detail',{'feed_id':ident,'xsec_token':token,'load_all_comments':False})
            detail=data.get('data',data)
            note=detail.get('note') or detail.get('noteCard') or detail
            items=[to_item({'id':ident,'note':note},query)]
        return {'ok':True,'backend':'existing-xiaohongshu-mcp','items':items}
    except PermissionError:
        return {'ok':False,'error':{'code':'NEED_LOGIN'}}
    except urllib.error.HTTPError as e:
        return {'ok':False,'error':{'code':'NEED_SETUP' if e.code==401 else 'RATE_LIMITED' if e.code==429 else 'UPSTREAM_BROKEN'}}
