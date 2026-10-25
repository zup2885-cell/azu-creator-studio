"""User-managed tracks, evidence-based like thresholds, and bounded daily discovery."""
from copy import deepcopy
from datetime import datetime
import json
import re
import time
import uuid

PLATFORMS=('douyin','xiaohongshu','bilibili','youtube')
DEFAULT={'revision':0,'tracks':[],'thresholds':{p:50000 for p in PLATFORMS},'auto_update':True}


def clean_name(value):
    if not isinstance(value,str):raise ValueError('赛道名称需要是文字')
    name=value.strip()
    if name=='全部' or not 1<=len(name)<=30 or name.startswith('-') or re.search(r'[\x00-\x1f\x7f]',name):
        raise ValueError('赛道名称需要 1–30 个字，不能包含控制字符')
    return name


def preferences(research):
    with research.db() as db:
        row=db.execute("SELECT document FROM settings WHERE id='discovery'").fetchone()
    return json.loads(row[0]) if row else deepcopy(DEFAULT)


def save_preferences(research,body):
    tracks=body.get('tracks');thresholds=body.get('thresholds');auto=body.get('auto_update')
    if not isinstance(tracks,list) or len(tracks)>20:raise ValueError('最多添加 20 个赛道')
    if not isinstance(thresholds,dict) or set(thresholds)!=set(PLATFORMS):raise ValueError('请设置四个平台的最低点赞量')
    if any(isinstance(v,bool) or not isinstance(v,int) or not 100<=v<=1000000000 for v in thresholds.values()):
        raise ValueError('最低点赞量需要是 100–10亿之间的整数')
    if not isinstance(auto,bool):raise ValueError('自动更新状态需要是开关值')
    normalized=[];names=set();ids=set()
    for row in tracks:
        if not isinstance(row,dict):raise ValueError('赛道格式无效')
        name=clean_name(row.get('name'))
        if name.casefold() in names:raise ValueError('这个赛道已经添加过了')
        names.add(name.casefold())
        ident=row.get('id') or uuid.uuid4().hex[:16]
        if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{16}',ident) or ident in ids:raise ValueError('赛道标识无效')
        enabled=row.get('enabled',True)
        if not isinstance(enabled,bool):raise ValueError('赛道启用状态需要是开关值')
        ids.add(ident);normalized.append({'id':ident,'name':name,'enabled':enabled})
    with research.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT document FROM settings WHERE id='discovery'").fetchone()
        old=json.loads(row[0]) if row else deepcopy(DEFAULT)
        revision=body.get('revision')
        if isinstance(revision,bool) or not isinstance(revision,int) or revision!=old['revision']:raise ValueError('设置已在其他页面更改，请刷新后再保存')
        doc={'revision':old['revision']+1,'tracks':normalized,'thresholds':thresholds,'auto_update':auto}
        db.execute("INSERT INTO settings VALUES('discovery',?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",(json.dumps(doc,ensure_ascii=False),))
    return {'ok':True,'preferences':doc}


def qualifies(item,prefs):
    likes=item.get('metrics',{}).get('likes')
    return likes is not None and likes>=prefs['thresholds'].get(item.get('platform'),50000)


def choose_tracks(research,body):
    """Save checked options and start collection; no typed search term is needed."""
    from research import CATEGORIES
    prefs=preferences(research)
    names=body.get('names')
    existing={t['name']:t for t in prefs['tracks']}
    allowed=set(CATEGORIES)-{'全部'} | set(existing)
    if not isinstance(names,list) or len(names)>20 or any(not isinstance(n,str) or n not in allowed for n in names) or len(set(names))!=len(names):
        raise ValueError('请从内容赛道选项中勾选，不能重复选择')
    tracks=[dict(existing[n],enabled=True) if n in existing else {'name':n,'enabled':True} for n in names]
    saved=save_preferences(research,dict(prefs,revision=body.get('revision'),tracks=tracks))
    if not names:
        return dict(saved,message='已清空赛道选择，后续不会自动抓取。')
    try:
        discovery=start_discovery(research,{})
    except ValueError:
        return dict(saved,message='赛道已保存；当前已有更新任务，所选赛道会在后续每日更新时自动抓取。')
    return dict(saved,discovery=discovery,message='赛道已保存，正在自动查找达到点赞门槛的作品。')


def start_discovery(research,body,background=True):
    from research import POOL,stamp
    prefs=preferences(research);scheduled=body.get('scheduled',False)
    if not isinstance(scheduled,bool):raise ValueError('自动更新标识需要是开关值')
    tracks=[t for t in prefs['tracks'] if t['enabled']]
    if not tracks:return {'ok':True,'skipped':True,'message':'尚未添加启用的内容赛道，本次不抓取任何内容。'}
    if scheduled and not prefs['auto_update']:return {'ok':True,'skipped':True,'message':'每日自动更新已关闭。'}
    task_id=uuid.uuid4().hex[:24]
    doc={'channel':'discovery','action':'discovery','query':'按已添加赛道更新爆款','created_at':stamp(),
         'track_ids':[t['id'] for t in tracks],'scheduled':scheduled,'count':0,'processed':0,'planned':len(tracks)*4,
         'message':'正在按当前启用赛道更新，未达到点赞门槛的作品不进入爆款列表。'}
    today=datetime.now().astimezone().date().isoformat()
    with research.db() as db:
        db.execute('BEGIN IMMEDIATE')
        active=db.execute("SELECT 1 FROM tasks WHERE kind='discovery' AND status='running'").fetchone()
        if active and scheduled:return {'ok':True,'skipped':True,'message':'已有赛道更新进行中，本次自动任务不重复启动。'}
        if active:raise ValueError('赛道更新已经在进行中，完成后会自动显示结果')
        if scheduled:
            previous=db.execute("SELECT document FROM settings WHERE id='discovery-day'").fetchone()
            if previous and json.loads(previous[0])==today:return {'ok':True,'skipped':True,'message':'今日已执行过自动赛道更新，不重复抓取。'}
            db.execute("INSERT INTO settings VALUES('discovery-day',?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",(json.dumps(today),))
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(task_id,'discovery','running',json.dumps(doc,ensure_ascii=False),stamp()))
    # Rotate oldest checked tracks first so bounded runs do not starve later tracks.
    with research.db() as db:
        checked={r[0]:r[1] for r in db.execute('SELECT id,document FROM settings WHERE id LIKE \'track-check:%\'')}
    tracks.sort(key=lambda t:checked.get('track-check:'+t['id'],''))
    doc['track_ids']=[t['id'] for t in tracks]
    research.set_task(task_id,'discovery','running',doc)
    if background:POOL.submit(run_discovery,research,task_id,doc)
    else:run_discovery(research,task_id,doc)
    return {'ok':True,'task_id':task_id}


def run_discovery(research,task_id,doc):
    from research import stamp,SCHEMA
    deadline=time.monotonic()+600;blocked=set();errors=[];found=set();query_count=0
    try:
        for track_id in doc['track_ids']:
            for platform in ('douyin','bilibili','youtube','xiaohongshu'):
                current=preferences(research)
                track=next((t for t in current['tracks'] if t['id']==track_id and t['enabled']),None)
                if not track or (doc['scheduled'] and not current['auto_update']):break
                if platform in blocked:continue
                if time.monotonic()>=deadline or query_count>=20:break
                child_id=uuid.uuid4().hex[:24]
                query=SCHEMA.get('youtube_queries',{}).get(track['name'],track['name']) if platform=='youtube' else track['name']
                child={'channel':platform,'action':'search','query':query,'category':track['name'],'track_id':track_id,
                       'popular':True,'limit':8,'created_at':stamp(),'count':0,'parent_id':task_id}
                research.set_task(child_id,'search','running',child)
                research.run_search(child_id,child)
                result=research.task(child_id)
                query_count+=1;doc['processed']+=1
                found.update(result.get('item_ids',[]))
                if result['status']=='failed':
                    errors.append({'platform':platform,'message':result.get('message','本次未取得数据')})
                    blocked.add(platform)
                if result.get('enrichment_error') in ('PLATFORM_BLOCKED','RATE_LIMITED','NEED_LOGIN','NEED_SETUP'):
                    blocked.add(platform)
                    errors.append({'platform':platform,'message':'平台未返回完整互动数据，已停止本次该平台的后续采集。'})
                elif result.get('enrichment_error'):
                    errors.append({'platform':platform,'message':'部分作品的互动数据未取得，其余已取得数据保留。'})
                doc['message']=f'已处理 {doc["processed"]} 个平台赛道；正在按当前点赞门槛核对结果。'
                research.set_task(task_id,'discovery','running',doc)
            with research.db() as db:
                db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',('track-check:'+track_id,stamp()))
            if time.monotonic()>=deadline or query_count>=20:break
        prefs=preferences(research)
        active={t['name'] for t in prefs['tracks'] if t['enabled']}
        hits=[i for i in research.items() if i['id'] in found and i.get('research_category') in active and qualifies(i,prefs)]
        doc.update(count=len(hits),candidate_count=len(found),errors=errors,finished_at=stamp(),
                   message=f'本次取得 {len(found)} 条候选，{len(hits)} 条达到当前点赞门槛。',
                   pending=max(0,doc['planned']-doc['processed']))
        if errors:
            names={'douyin':'抖音','bilibili':'哔哩哔哩','youtube':'YouTube','xiaohongshu':'小红书'}
            doc['message']+=' '+ '；'.join(names[e['platform']]+'：'+e['message'] for e in errors)
        status='partial' if errors or doc['pending'] else 'complete'
        if errors and not found:status='failed'
        research.set_task(task_id,'discovery',status,doc)
    except Exception:
        doc.update(message='本次赛道更新未完成，已取得的数据仍保留。',finished_at=stamp())
        research.set_task(task_id,'discovery','failed',doc)
