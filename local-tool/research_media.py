"""Bounded local media ingestion, transcript provenance and scene evidence."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
from urllib.parse import urlsplit,parse_qs
import uuid

POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='video-evidence')
GUARD=threading.Lock()
MAX_UPLOAD=500*1024*1024
SUFFIXES={'.mp4','.mov','.mkv','.webm','.mp3','.wav','.m4a','.aac','.srt','.vtt','.txt'}
WORKER=Path(__file__).with_name('research_media_worker.py')


def runtime(state):return Path(state)/'video-tools'/'venv'/'bin'/'python'
def scene_runtime(state):return Path(state)/'video-tools'/'scene-venv'/'bin'/'python'
def model_path(state):return Path(state)/'video-tools'/'models'/'small'


def status(state):
    base=Path(state)/'video-tools';manifest=base/'installed.json'
    try:versions=json.loads(manifest.read_text())
    except (OSError,ValueError):versions={}
    return {'installed':runtime(state).is_file() and bool(versions),
        'ready':runtime(state).is_file() and scene_runtime(state).is_file() and (model_path(state)/'model.bin').is_file(),
        'versions':versions,'max_mb':500,'max_minutes':20}


def folder_for(research,ident):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{24}',ident):raise ValueError('媒体编号无效')
    root=research.root/'media';root.mkdir(exist_ok=True,mode=0o700)
    return root/ident


def parse_subtitles(content,suffix):
    try:value=content.decode('utf-8-sig')
    except UnicodeError:raise ValueError('字幕需要 UTF-8 编码。') from None
    if len(value)>50000:raise ValueError('字幕超过 5 万字，请分段导入。')
    if suffix=='.txt':
        value=value.strip()
        if not value:raise ValueError('字幕内容为空。')
        return [],value
    def seconds(s):
        parts=s.replace(',','.').split(':');parts=[float(p) for p in parts]
        return sum(v*60**i for i,v in enumerate(reversed(parts)))
    segments=[]
    pattern=r'(?m)^((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)'
    for row in re.finditer(pattern,value,re.S):
        start,end=seconds(row[1]),seconds(row[2]);body=html.unescape(re.sub(r'<[^>]*>','',row[3])).strip()
        if not math.isfinite(start+end) or not 0<=start<end<=1200:raise ValueError('字幕时间需在 0–20 分钟内，结束时间大于开始时间。')
        if body and not (segments and segments[-1]['text']==body):segments.append({'start':start,'end':end,'text':body})
    if not segments:raise ValueError('未识别到有效的 SRT/VTT 时间轴。')
    return segments,'\n'.join(s['text'] for s in segments)


def invoke(state,doc,timeout=900):
    exe=scene_runtime(state) if doc['action']=='inspect' else runtime(state)
    if not exe.is_file():raise ValueError('视频研究组件尚未安装。')
    env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','CODEX_API_KEY','HF_TOKEN','HUGGING_FACE_HUB_TOKEN')}
    env.update(HF_HUB_DISABLE_TELEMETRY='1',OMP_NUM_THREADS='4',TOKENIZERS_PARALLELISM='false')
    proc=subprocess.Popen([str(exe),str(WORKER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,start_new_session=True)
    try:out,err=proc.communicate(json.dumps(doc).encode(),timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.communicate()
        raise ValueError('本次媒体处理超时，已停止；请改用更短的原片。') from None
    if proc.returncode:
        # Never reflect extractor logs (URLs/tokens) into the UI.
        if doc['action']=='platform':
            message=err[-12000:].decode(errors='replace').lower()
            if '429' in message:raise ValueError('平台返回429限流，本次已停止且不会自动重试。请稍后再试，或导入本地原片/字幕。')
            if any(s in message for s in ('sign in','login','captcha','403','412')):raise ValueError('平台要求登录、验证或拒绝读取。本次已停止；可导入本地原片或字幕。')
            raise ValueError('平台本次未返回可用内容，没有自动重试；可导入本地原片或字幕。')
        raise ValueError('本地文件读取未完成，原有资料已保留。请确认文件完整、20分钟以内，并检查视频组件。')
    if len(out)>4*1024*1024:raise ValueError('媒体分析结果过大。')
    return json.loads(out)


def media_item(research,item_id):
    item=next((i for i in research.items() if i['id']==item_id),None)
    if not item:raise ValueError('请先选择一条已收集的参考素材。')
    return item


def queue_task(research,item_id,folder,extra):
    from research import stamp
    with research.db() as db:
        if db.execute("SELECT 1 FROM tasks WHERE kind='media' AND status='running'").fetchone():raise ValueError('已有视频内容读取任务，请等它完成。')
    doc=dict(kind='media',channel='media',action='media',query='视频内容读取',item_ids=[item_id],media_id=folder.name,
        created_at=stamp(),phase='queued',message='正在读取字幕与镜头。一次处理一个视频。',**extra)
    research.set_task(folder.name,'media','running',doc)
    return doc


def receive_upload(research,stream,length,filename,item_id):
    if not isinstance(length,int) or not 0<length<=MAX_UPLOAD:raise ValueError('文件需非空且不超过 500 MB。')
    suffix=Path(filename).suffix.lower()
    if suffix not in SUFFIXES:raise ValueError('支持 MP4、MOV、MKV、WebM、常用音频及 SRT/VTT/TXT 字幕。')
    if suffix in ('.srt','.vtt','.txt') and length>1024*1024:raise ValueError('字幕文件不能超过 1 MB。')
    media_item(research,item_id)
    with GUARD:
        ident=uuid.uuid4().hex[:24];folder=folder_for(research,ident);folder.mkdir(mode=0o700)
        path=folder/('source'+suffix);digest=hashlib.sha256()
        try:
            with path.open('wb') as dest:
                os.chmod(path,0o600);remaining=length
                while remaining:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk:raise ValueError('文件未传完整，请重新选择。')
                    dest.write(chunk);digest.update(chunk);remaining-=len(chunk)
            if suffix in ('.srt','.vtt','.txt'):parse_subtitles(path.read_bytes(),suffix)
            doc=queue_task(research,item_id,folder,{'filename':Path(filename).name[:180],'source_file':path.name,'sha256':digest.hexdigest(),'origin':'local-upload'})
        except Exception:
            path.unlink(missing_ok=True);folder.rmdir();raise
        POOL.submit(run,research,ident,doc)
    return {'ok':True,'task_id':ident,'message':'文件已接收，完成后会自动显示字幕和镜头时间。'}


def platform_url(item):
    url=item['url'];parts=urlsplit(url)
    if item['platform']=='youtube':
        ident=parts.path[1:] if parts.hostname=='youtu.be' else parse_qs(parts.query).get('v',[''])[0]
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ident):raise ValueError('需要标准 YouTube 单条视频链接。')
        return 'https://www.youtube.com/watch?v='+ident
    if item['platform']=='bilibili':
        match=re.search(r'/video/(BV[A-Za-z0-9]{10})',parts.path)
        if not match:raise ValueError('请先展开为哔哩哔哩 BV 视频链接。')
        return 'https://www.bilibili.com/video/'+match[1]
    raise ValueError('这个平台暂不自动读取字幕；请在下方导入本地原片或字幕，已有数据会保留。')


def start_platform(research,request):
    from research import stamp
    item=media_item(research,request.get('id'));url=platform_url(item)
    download=request.get('download_video',False)
    if not isinstance(download,bool):raise ValueError('原片读取选项无效。')
    with GUARD:
        ident=uuid.uuid4().hex[:24];folder=folder_for(research,ident);folder.mkdir(mode=0o700)
        try:doc=queue_task(research,item['id'],folder,{'origin':'platform','url':url,'download_video':download})
        except Exception:folder.rmdir();raise
        POOL.submit(run,research,ident,doc)
    return {'ok':True,'task_id':ident,'message':'正在读取平台字幕；未取得时会说明原因。'}


def run(research,ident,doc):
    from research import stamp
    folder=folder_for(research,ident)
    try:
        item=media_item(research,doc['item_ids'][0]);state=research.root.parent
        source_file=doc.get('source_file');subtitle_source='uploaded';result={}
        if doc['origin']=='platform':
            result=invoke(state,{'action':'platform','url':doc['url'],'folder':str(folder),'download_video':doc['download_video']},timeout=180)
            if result.get('unavailable'):raise ValueError(result['message'])
            source_file=result.get('source') or result['subtitle'];subtitle_source='platform-automatic' if result.get('automatic') else 'platform'
        source=folder/source_file
        if source.suffix in ('.srt','.vtt','.txt'):
            segments,transcript=parse_subtitles(source.read_bytes(),source.suffix)
            result={'segments':segments,'transcript':transcript,'scenes':[],'frames':[],'has_video':False,'has_audio':False,'subtitle_only':True}
        else:
            doc.update(phase='transcribing',message='正在提取镜头并转写语音；本地处理可能需要几分钟。')
            research.set_task(ident,'media','running',doc)
            result=invoke(state,{'action':'inspect','source':str(source),'folder':str(folder)})
            if result['has_audio'] and not item.get('transcript'):
                result.update(invoke(state,{'action':'transcribe','source':str(source),'model':str(model_path(state))}))
            result['transcript']='\n'.join(s['text'] for s in result['segments'])
            subtitle_source='asr'
        evidence={k:result[k] for k in ('duration','has_video','has_audio','segments','scenes','frames','language','subtitle_only') if k in result}
        evidence.update(media_id=ident,source_file=source_file,origin=doc['origin'],subtitle_source=subtitle_source,created_at=stamp(),sha256=doc.get('sha256'),
            visual_verified=False,transcript_verified=False)
        research.atomic(folder/'evidence.json',evidence)
        # Re-read before applying, preserve human edits and existing verified transcripts.
        with research.db() as db:
            row=db.execute('SELECT document FROM items WHERE id=?',(item['id'],)).fetchone()
            if not row:raise ValueError('原素材已不存在，本次文件仍保留。')
            latest=json.loads(row['document']);old=latest.get('media_evidence',{})
            if not result.get('frames') and old.get('frames'):
                evidence['video_evidence']=old.get('video_evidence') or old['media_id']
                evidence['scenes']=old.get('scenes',[]);evidence['frames']=old['frames'];evidence['duration']=old.get('duration')
            latest['media_evidence']=evidence
            if result['transcript'] and not latest.get('transcript'):
                latest['transcript']=result['transcript'];latest['transcript_source']=subtitle_source;latest['transcript_verified']=False
            latest['media_checked_at']=stamp()
            db.execute('UPDATE items SET document=?,updated_at=? WHERE id=?',(json.dumps(latest,ensure_ascii=False,allow_nan=False),stamp(),item['id']))
        research.atomic(folder/'evidence.json',evidence)
        count=len(evidence.get('segments',[]));shots=len(evidence.get('scenes',[]))
        doc.update(phase='complete',count=count,finished_at=stamp(),message=f'读取完成：{count} 段字幕，{shots} 个镜头。自动转写待核对，关键帧是抽样，不代表完整观看。')
        research.set_task(ident,'media','complete',doc)
    except Exception as error:
        doc.update(phase='failed',finished_at=stamp(),message=str(error) if isinstance(error,ValueError) else '本次内容读取未完成，原有素材与字幕已保留。')
        research.set_task(ident,'media','failed',doc)


def asset(research,ident,name):
    folder=folder_for(research,ident)
    if name=='evidence.json':return folder/name,'application/json'
    if re.fullmatch(r'frame-\d{2}\.jpg',name):return folder/name,'image/jpeg'
    raise ValueError('媒体资源不存在。')


def analysis_images(research,items):
    result=[]
    for item in items:
        evidence=item.get('media_evidence',{});ident=evidence.get('video_evidence') or evidence.get('media_id')
        if not ident:continue
        frames=evidence.get('frames',[])
        sampled=[frames[i] for i in sorted(set(round(n*(len(frames)-1)/3) for n in range(4)))] if frames else []
        for frame in sampled:
            path,mime=asset(research,ident,frame.get('file',''))
            if path.is_file():result.append({'path':str(path),'item_id':item['id'],'at':frame['at']})
            if len(result)>=8:return result
    return result
