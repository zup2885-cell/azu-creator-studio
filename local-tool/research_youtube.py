"""Read public metadata with the existing yt-dlp installation, without downloads."""
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlencode


def search_popular(query,limit,reach):
    interpreter=Path(reach).resolve().with_name('python')
    if not interpreter.is_file():return {'ok':False,'error':{'code':'NEED_SETUP'}}
    # Read from YouTube's own "热门程度" search link, verified in its filter UI.
    url='https://www.youtube.com/results?'+urlencode({'search_query':query,'sp':'CAM%3D'})
    args=[str(interpreter),'-m','yt_dlp','--ignore-config','--skip-download','--flat-playlist',
          '--dump-single-json','--playlist-end',str(limit),'--no-warnings','--retries','0',
          '--extractor-retries','0','--socket-timeout','15',url]
    run=subprocess.run(args,capture_output=True,text=True,timeout=75,stdin=subprocess.DEVNULL)
    if run.returncode:
        err=run.stderr.lower()
        return {'ok':False,'error':{'code':'PLATFORM_BLOCKED' if 'not a bot' in err or 'sign in to confirm' in err else 'RATE_LIMITED' if '429' in err else 'UPSTREAM_BROKEN'}}
    if len(run.stdout)>6*1024*1024:raise ValueError('搜索元数据过大')
    info=json.loads(run.stdout);items=[]
    import re
    for row in (info.get('entries') or [])[:limit]:
        ident=row.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ident):continue
        cover=row.get('thumbnail') or next((t.get('url') for t in reversed(row.get('thumbnails') or []) if t.get('url')),'')
        items.append({'url':'https://www.youtube.com/watch?v='+ident,'title':row.get('title'),
                      'author':row.get('channel') or row.get('uploader'),'cover':cover,
                      'raw':{k:row.get(k) for k in ('view_count','like_count','comment_count')}})
    return {'ok':True,'backend':'yt-dlp-public-popular','items':items}


def read_youtube(url, reach):
    interpreter=Path(reach).resolve().with_name('python')
    if not interpreter.is_file():
        return {'ok':False,'error':{'code':'NEED_SETUP'}}
    fields='%(.{id,title,webpage_url,uploader,channel,description,view_count,like_count,comment_count,thumbnail,upload_date,_type})j'
    args=[str(interpreter),'-m','yt_dlp','--ignore-config','--skip-download',
          '--no-playlist','--print',fields,'--no-warnings','--retries','0',
          '--extractor-retries','0','--socket-timeout','15']
    if shutil.which('node'):args+=['--js-runtimes','node']
    run=subprocess.run(args+[url],capture_output=True,text=True,timeout=100,stdin=subprocess.DEVNULL)
    if run.returncode:
        err=run.stderr.lower()
        code='PLATFORM_BLOCKED' if 'not a bot' in err or 'sign in to confirm' in err else 'RATE_LIMITED' if '429' in err else 'UPSTREAM_BROKEN'
        return {'ok':False,'error':{'code':code}}
    if len(run.stdout)>6*1024*1024:raise ValueError('视频元数据过大')
    info=json.loads(run.stdout)
    if info.get('_type') in ('playlist','multi_video'):raise ValueError('请粘贴单条作品链接')
    # Retain nulls. A missing or hidden counter must never become zero.
    raw={k:info.get(k) for k in ('view_count','like_count','comment_count','thumbnail')}
    return {'ok':True,'backend':'yt-dlp-public-metadata','items':[{
        'url':info.get('webpage_url') or url,'title':info.get('title'),
        'author':info.get('uploader') or info.get('channel'),
        'text':info.get('description'),'raw':raw,
        'published_at':info.get('upload_date') or ''}]}
