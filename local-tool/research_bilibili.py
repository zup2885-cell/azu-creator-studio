"""Public video metadata API used by Agent-Reach, retaining its cover and counters."""
import json
import re
from pathlib import Path
import subprocess
from urllib.parse import urlsplit,urlencode
import urllib.request
import urllib.error


def search_popular(query,limit):
    # Reuse the existing SDK's current WBI search contract; the legacy unsigned
    # search endpoint returns HTTP 403 and cannot supply a real keyword feed.
    python=Path.home()/'.agent-reach/tools/bili-cli/venv/bin/python'
    if not python.is_file():return {'ok':False,'error':{'code':'NEED_SETUP'}}
    try:
        run=subprocess.run([str(python),str(Path(__file__).with_name('research_bili_search.py')),query,str(limit)],
                           capture_output=True,text=True,timeout=75,stdin=subprocess.DEVNULL)
        if len(run.stdout)>3*1024*1024:raise ValueError('B站元数据过大')
        return json.loads(run.stdout)
    except subprocess.TimeoutExpired:return {'ok':False,'error':{'code':'TIMEOUT'}}
    except (ValueError,OSError):return {'ok':False,'error':{'code':'UPSTREAM_BROKEN'}}


def read_video(url):
    host=urlsplit(url).hostname or ''
    if host not in ('www.bilibili.com','bilibili.com'):return None
    match=re.fullmatch(r'/video/(BV[0-9A-Za-z]{10})/?',urlsplit(url).path)
    if not match:return None
    req=urllib.request.Request('https://api.bilibili.com/x/web-interface/view?'+urlencode({'bvid':match[1]}),headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'})
    try:
        with urllib.request.urlopen(req,timeout=8) as response:
            body=response.read(1024*1024+1)
        if len(body)>1024*1024:return None
        data=json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code in (403,412,429):raise PermissionError('平台要求验证或限流，停止补全') from None
        return None
    if data.get('code') in (-352,-412,-509):raise PermissionError('平台要求验证或限流，停止补全')
    if data.get('code')!=0:return None
    video=data.get('data') or {}
    return {'url':'https://www.bilibili.com/video/'+match[1],'title':video.get('title'),'author':(video.get('owner') or {}).get('name'),
            'text':video.get('desc'),'cover':video.get('pic'),'raw':{'stat':video.get('stat') or {}},'published_at':video.get('pubdate') or ''}
