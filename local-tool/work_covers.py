"""Verified owner-work covers kept outside statistical snapshots."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit

from operations import atomic_json,timestamp

HOSTS=('.douyinpic.com','.byteimg.com','.ibytedtos.com','.pstatp.com','.douyincdn.com')
def key(title):return ''.join(str(title).split())
def read(state):
    try:
        doc=json.loads((Path(state)/'work-covers/index.json').read_text())
        return {k:v for k,v in doc.items() if re.fullmatch('[a-f0-9]{20}',k) and isinstance(v,dict)} if isinstance(doc,dict) else {}
    except (OSError,ValueError):return {}
def allowed(url):
    try:
        p=urlsplit(url);return p.scheme=='https' and not p.username and not p.password and p.port in (None,443) and any((p.hostname or '').endswith(h) for h in HOSTS)
    except (ValueError,TypeError):return False
def image_bytes(data,mime):
    signatures={'image/jpeg':data.startswith(b'\xff\xd8\xff'),'image/png':data.startswith(b'\x89PNG\r\n\x1a\n'),'image/webp':data[:4]==b'RIFF' and data[8:12]==b'WEBP','image/avif':data[4:8]==b'ftyp' and b'avif' in data[8:32]}
    return bool(data) and len(data)<=5*1024*1024 and signatures.get(mime,False)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
def download(url):
    if not allowed(url):raise ValueError('封面地址不属于已支持的抖音图片源')
    opener=urllib.request.build_opener(NoRedirect)
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://creator.douyin.com/'}),timeout=15) as response:
        mime=response.headers.get_content_type();data=response.read(5*1024*1024+1)
    if not image_bytes(data,mime):raise ValueError('封面文件格式或大小无效')
    return data,mime
def ingest(state,rows,items,fetch=download):
    folder=Path(state)/'work-covers';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    index=read(state);matched=0;failures=0
    for row in rows:
        candidates=[i for i in items if key(i.get('title'))==key(row['title']) and str(i.get('pub_date',''))[:10]==row['pub_date'][:10] and i.get('cover')]
        if not candidates:continue
        if len({str(i.get('video_id','')) for i in candidates})>1:
            failures+=1;continue
        item=candidates[-1]
        try:
            if not allowed(item['cover']):raise ValueError('封面来源无效')
            data,mime=fetch(item['cover'])
            if not image_bytes(data,mime):raise ValueError('封面文件格式或大小无效')
            target=folder/(row['id']+'.img');temporary=target.with_suffix('.tmp');temporary.write_bytes(data);temporary.chmod(0o600);temporary.replace(target)
            video_id=str(item.get('video_id',''));index[row['id']]={'title':row['title'],'pub_date':row['pub_date'],'mime':mime,'source':'本人创作者中心','captured_at':timestamp(),'sha256':hashlib.sha256(data).hexdigest(),'url':f'https://www.douyin.com/video/{video_id}' if re.fullmatch(r'\d{10,25}',video_id) else ''}
            matched+=1
        except Exception:failures+=1
    atomic_json(folder/'index.json',index)
    return {'covers':matched,'failed':failures,'available':sum((folder/(i+'.img')).is_file() for i in index)}
def asset(state,ident):
    if not re.fullmatch('[a-f0-9]{20}',ident):raise ValueError('封面不存在')
    item=read(state).get(ident)
    path=Path(state)/'work-covers'/(ident+'.img')
    if not item or not path.is_file():raise ValueError('封面尚未取得')
    return path,item['mime']
def enrich(state,snapshots):
    index=read(state)
    for snap in snapshots:
        for row in snap['rows']:
            item=index.get(row['id'])
            if item and item.get('title')==row['title'] and item.get('pub_date')==row['pub_date'] and (Path(state)/'work-covers'/(row['id']+'.img')).is_file():
                row['cover']='/api/work-covers/'+row['id'];row['url']=item.get('url','')
    return snapshots
