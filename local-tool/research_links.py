"""Paste public work links into the existing collection/research workflow."""
import json
import re
import time
import uuid
from urllib.parse import urlsplit,urlunsplit,parse_qs,urlencode,urljoin
import urllib.error
import urllib.request

HOSTS={
    'www.douyin.com':'douyin','douyin.com':'douyin','v.douyin.com':'douyin','www.iesdouyin.com':'douyin','iesdouyin.com':'douyin',
    'www.xiaohongshu.com':'xiaohongshu','xiaohongshu.com':'xiaohongshu','xhslink.com':'xiaohongshu','www.xhslink.com':'xiaohongshu',
    'www.bilibili.com':'bilibili','bilibili.com':'bilibili','m.bilibili.com':'bilibili','b23.tv':'bilibili',
    'www.youtube.com':'youtube','youtube.com':'youtube','m.youtube.com':'youtube','youtu.be':'youtube',
}
SHORT={'v.douyin.com','xhslink.com','www.xhslink.com','b23.tv'}
NAMES={'douyin':'抖音','xiaohongshu':'小红书','bilibili':'哔哩哔哩','youtube':'YouTube'}
LIMIT=12


def canonical(url):
    from research import public_url
    p=urlsplit(url)
    if p.scheme=='http':url='https://'+url[len('http://'):]
    url=public_url(url);p=urlsplit(url);host=(p.hostname or '').lower()
    platform=HOSTS.get(host)
    if not platform:raise ValueError('仅支持抖音、小红书、哔哩哔哩和 YouTube 的作品链接')
    if host in SHORT:return {'url':url,'platform':platform,'short':True}
    query=parse_qs(p.query)
    if platform=='youtube':
        ident=p.path.strip('/') if host=='youtu.be' else query.get('v',[''])[0] if p.path=='/watch' else p.path.strip('/').split('/')[-1] if re.fullmatch(r'/(shorts|live)/[A-Za-z0-9_-]{11}/?',p.path) else ''
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ident):raise ValueError('请粘贴单条 YouTube 视频链接，不是频道或播放列表')
        url='https://www.youtube.com/watch?v='+ident
    elif platform=='bilibili':
        match=re.fullmatch(r'/video/(BV[0-9A-Za-z]{10})/?',p.path)
        if not match:raise ValueError('请粘贴哔哩哔哩视频链接或 b23.tv 分享链接')
        url='https://www.bilibili.com/video/'+match[1]
    elif platform=='douyin':
        match=re.fullmatch(r'/(?:share/)?video/(\d{10,24})/?',p.path)
        if not match:raise ValueError('请粘贴单条抖音视频链接或 v.douyin.com 分享链接')
        url='https://www.douyin.com/video/'+match[1]
    else:
        match=re.fullmatch(r'/(?:explore|discovery/item)/([0-9a-fA-F]{24})/?',p.path)
        if not match:raise ValueError('请粘贴小红书单条笔记链接或完整分享文案')
        token=query.get('xsec_token',[''])[0]
        url='https://www.xiaohongshu.com/explore/'+match[1].lower()
        if token:url+='?'+urlencode({'xsec_token':token,'xsec_source':'pc_search'})
    return {'url':url,'platform':platform,'short':False}


def parse_links(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=20000:raise ValueError('请粘贴链接或分享文案，最多 2 万字')
    urls=[re.split(r'[，。；、！？）】》]',u,1)[0].rstrip('.,;:!?)]}') for u in re.findall(r'https?://[^\s<>"“”‘’]+',value)]
    if not urls:raise ValueError('没有找到链接，请粘贴视频网址或完整分享文案')
    if len(urls)>LIMIT:raise ValueError('每次最多放入 12 个链接，请分批添加')
    rows=[];seen=set()
    for url in urls:
        try:row=canonical(url)
        except ValueError as e:
            # Invalid URLs must not persist pasted passwords or private query
            # strings in the task log. They are never opened.
            try:
                p=urlsplit(url);display=urlunsplit((p.scheme,p.hostname or '',p.path,'',''))
            except ValueError:display='无效网址'
            row={'url':display[:3000],'platform':'','error':str(e)}
        if row['url'] in seen:continue
        seen.add(row['url']);rows.append(row)
    if not any(not r.get('error') for r in rows):raise ValueError(rows[0]['error'])
    return rows


def resolve_short(row):
    if not row['short']:return row
    from research_preview import checked_url
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    opener=urllib.request.build_opener(NoRedirect())
    url=row['url']
    for _ in range(4):
        current=canonical(url)
        if current['platform']!=row['platform']:raise ValueError('分享链接跳转到其他平台，已停止')
        if not current['short']:return current
        url=checked_url(url)
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept-Encoding':'identity'})
        try:
            with opener.open(request,timeout=8) as response:
                target=response.headers.get('Location')
        except urllib.error.HTTPError as e:
            if e.code not in (301,302,303,307,308):raise ValueError('分享链接暂时无法打开，请从浏览器复制完整作品链接') from None
            target=e.headers.get('Location')
        if not target:raise ValueError('分享链接未返回作品地址，请复制完整作品链接')
        url=urljoin(url,target)
        # Validate the next host BEFORE any next network request.
        next_row=canonical(url)
        if next_row['platform']!=row['platform']:raise ValueError('分享链接跳转到其他平台，已停止')
        if not next_row['short']:return next_row
    raise ValueError('分享链接跳转次数过多，已停止')


def start_links(research,body,background=True):
    from research import POOL,stamp
    intent=body.get('intent','library')
    if intent not in ('library','creative','strategy'):raise ValueError('请选择收藏、对标研究或选题研究')
    rows=parse_links(body.get('text'))
    ident=uuid.uuid4().hex[:24]
    doc={'channel':'links','action':'links','intent':intent,'query':'链接读取 · '+{'library':'素材收藏','creative':'对标研究','strategy':'选题研究'}[intent],
         'created_at':stamp(),'count':0,'processed':0,'total_links':len(rows),'rows':[],
         'message':'正在识别链接并读取公开资料，未取得的数据保留为空。'}
    with research.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM tasks WHERE status='running' AND kind IN ('links','discovery')").fetchone():
            raise ValueError('已有链接或赛道收集任务，请等当前任务完成后再添加')
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(ident,'links','running',json.dumps(doc,ensure_ascii=False),stamp()))
    if background:POOL.submit(run_links,research,ident,doc,rows)
    else:run_links(research,ident,doc,rows)
    return {'ok':True,'task_id':ident,'message':'已开始读取，结果会显示在链接输入框下方。'}


def link_only(research,row,message):
    from research import normalize_item
    label=NAMES[row['platform']]+'链接 · 资料未取得'
    item=normalize_item({'url':row['url'],'title':label},row['platform'],'link-only')
    with research.db() as db:old=db.execute("SELECT document FROM items WHERE id=? OR (json_extract(document,'$.platform')=? AND json_extract(document,'$.canonical_url')=?) ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END LIMIT 1",(item['id'],row['platform'],row['url'],item['id'])).fetchone()
    if old:
        previous=json.loads(old[0])
        useful=previous.get('source')!='link-only'
        if not useful:previous['collection_message']=message
        research.put(previous,True)
        return previous['id'],'kept' if useful else 'link_only',useful
    item.update(collection_status='link_only',collection_message=message)
    research.put(item,True)
    return item['id'],'link_only',False


def run_links(research,ident,doc,rows):
    from research import stamp
    deadline=time.monotonic()+300;blocked={};saved=[];analysis=[];seen=set()
    try:
        for row in rows:
            result={'url':row['url'],'platform':row['platform'],'status':'invalid','message':row.get('error','')}
            if not row.get('error'):
                platform=row['platform'];problem=blocked.get(platform)
                if platform=='douyin':
                    from research_douyin import connection
                    state=connection(research.root.parent)
                    if state.get('detail_blocked'):problem='抖音已登录，但详情读取受限；只保存链接，没有重试接口。'
                    elif not state['ready']:problem='抖音连接尚未通过验证；只保存链接，没有打开登录窗口。'
                if time.monotonic()>=deadline:problem='本轮读取时间已到；已保存链接，可稍后继续。'
                if not problem:
                    try:row=resolve_short(row);result['url']=row['url']
                    except (ValueError,OSError) as e:problem=str(e) if isinstance(e,ValueError) else '分享链接本次未能打开，请使用完整作品网址。'
                if row['url'] in seen:
                    result.update(status='duplicate',message='同一作品已在本次读取，已合并。')
                else:
                    seen.add(row['url'])
                    child=None
                    if not problem:
                        child_id=uuid.uuid4().hex[:24]
                        child_doc={'channel':platform,'action':'read','query':row['url'],'limit':1,'category':'全部','save':True,
                                   'created_at':stamp(),'parent_id':ident}
                        research.set_task(child_id,'search','running',child_doc)
                        research.run_search(child_id,child_doc);child=research.task(child_id)
                        ids=child.get('item_ids') or []
                        if ids:
                            saved.extend(ids);analysis.extend(ids)
                            result.update(status='read',item_id=ids[0],message='已读取公开资料并收藏。字幕仅在实际取得时显示。')
                        else:
                            problem=child.get('message') or '未取得作品资料，已保留链接。'
                            if child.get('error_code') in ('NEED_LOGIN','PLATFORM_BLOCKED','RATE_LIMITED','NEED_SETUP'):blocked[platform]=problem
                    if problem:
                        item_id,status,useful=link_only(research,row,problem);saved.append(item_id)
                        if useful:analysis.append(item_id)
                        result.update(status=status,item_id=item_id,message=(problem.replace('只保存链接，没有重试接口。','未请求受限接口。')+' 已使用此前保存的资料，原采集时间保留。') if useful else problem)
            doc['rows'].append(result);doc['processed']+=1
            doc['count']=sum(r['status']=='read' for r in doc['rows'])
            doc['message']=f'已处理 {doc["processed"]}/{doc["total_links"]} 个链接，已读取 {doc["count"]} 条作品资料。'
            research.set_task(ident,'links','running',doc)
        doc.update(item_ids=list(dict.fromkeys(saved)),analysis_item_ids=list(dict.fromkeys(analysis)),finished_at=stamp())
        if analysis and doc['intent']!='library':
            try:
                from research_ai import enabled
                task=(research.start_analysis if enabled(research.root.parent) else research.prepare_analysis)({'ids':doc['analysis_item_ids'],'mode':doc['intent']})
                doc['analysis_task_id']=task['task_id']
            except ValueError as error:doc['analysis_error']=str(error)
        incomplete=any(r['status'] not in ('read','duplicate') for r in doc['rows']) or bool(doc.get('analysis_error'))
        doc['message']=f'已读取 {doc["count"]} 条作品资料，保存 {len(set(saved))} 条参考。'
        kept=sum(r['status']=='kept' for r in doc['rows'])
        if kept:doc['message']+=f' 其中 {kept} 条使用已保存资料，采集时间不变。'
        if incomplete:doc['message']+=' 部分链接未取得新资料，原因已逐条列出。'
        if doc.get('analysis_task_id'):doc['message']+=' AI 分析已开始，报告会自动返回网页。' if enabled(research.root.parent) else ' 分析任务已准备，交给当前 Codex 对话完成。'
        research.set_task(ident,'links','partial' if incomplete else 'complete',doc)
    except Exception:
        with research.db() as db:
            interrupted=db.execute("SELECT id,document FROM tasks WHERE status='running' AND json_extract(document,'$.parent_id')=?",(ident,)).fetchall()
        for child in interrupted:
            child_doc=json.loads(child['document']);child_doc.update(message='本次链接读取已中断，原有资料保留。',error_code='UPSTREAM_BROKEN')
            research.set_task(child['id'],'search','failed',child_doc)
        doc.update(message='本次链接读取未完成，已保存的资料仍保留。',item_ids=list(dict.fromkeys(saved)),finished_at=stamp())
        research.set_task(ident,'links','failed',doc)
