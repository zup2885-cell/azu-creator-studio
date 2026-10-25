"""Isolated video dependencies. Never imports account/browser sessions."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe',
        '-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)],
        stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=20)
    if result.returncode:raise ValueError('文件无法解码，请使用完整的 MP4、MOV、MKV、WebM 或音频文件。')
    doc=json.loads(result.stdout);duration=float(doc.get('format',{}).get('duration',0))
    if not 0<duration<=1200:raise ValueError('一次支持 20 分钟以内的非空视频或音频。')
    streams=doc.get('streams',[])
    return {'duration':round(duration,3),'has_video':any(s.get('codec_type')=='video' for s in streams),
        'has_audio':any(s.get('codec_type')=='audio' for s in streams)}


def inspect(doc):
    path=Path(doc['source']);folder=Path(doc['folder']);info=probe(path)
    scenes=[];frames=[]
    if info['has_video']:
        import cv2
        from scenedetect import open_video,SceneManager,ContentDetector
        cv2.setNumThreads(2)
        video=open_video(str(path));manager=SceneManager()
        manager.add_detector(ContentDetector(threshold=27,min_scene_len=10))
        manager.detect_scenes(video=video,show_progress=False)
        cuts=manager.get_scene_list(start_in_scene=True)
        for start,end in cuts:
            scenes.append({'start':round(start.seconds,3),'end':round(end.seconds,3)})
        if not scenes:scenes=[{'start':0,'end':info['duration']}]
        # At most 8 small frames per video. Cuts alone never imply narrative meaning.
        indices=sorted(set([0]+[round(i*(len(scenes)-1)/7) for i in range(8)]))
        for n,index in enumerate(indices):
            scene=scenes[index];at=min(scene['start']+0.25,(scene['start']+scene['end'])/2)
            name=f'frame-{n:02d}.jpg'
            result=subprocess.run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-ss',str(at),
                '-i',str(path),'-frames:v','1','-vf',"scale='min(640,iw)':-2",'-threads','2','-y',str(folder/name)],
                capture_output=True,timeout=25)
            if result.returncode==0:frames.append({'file':name,'at':round(at,3),'scene_index':index})
        video.close() if hasattr(video,'close') else None
    segments=[]
    return dict(info,scenes=scenes,frames=frames,segments=segments)


def transcribe(doc):
    from faster_whisper import WhisperModel
    model=WhisperModel(doc['model'],device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,local_files_only=True)
    stream,language=model.transcribe(doc['source'],beam_size=3,vad_filter=True,condition_on_previous_text=False)
    segments=[]
    for segment in stream:
        value=segment.text.strip()
        if value:segments.append({'start':round(segment.start,3),'end':round(segment.end,3),'text':value})
    return {'segments':segments,'language':language.language}


def fetch_platform(doc):
    import yt_dlp
    folder=Path(doc['folder'])
    opts={'quiet':True,'no_warnings':True,'noplaylist':True,'retries':0,'extractor_retries':0,
        'socket_timeout':15,'cachedir':False,'skip_download':True,'ignoreerrors':False,
        'remote_components':[], 'outtmpl':str(folder/'platform.%(ext)s')}
    # The caller accepts only canonical YouTube/Bilibili single-video URLs.
    with yt_dlp.YoutubeDL(opts) as ydl:info=ydl.extract_info(doc['url'],download=False)
    if not info or info.get('_type') in ('playlist','multi_video'):raise ValueError('请使用单条作品链接。')
    if info.get('duration') and info['duration']>1200:raise ValueError('一次支持 20 分钟以内的作品。')
    languages=list((info.get('subtitles') or {}))
    automatic=False
    if not languages:languages=list((info.get('automatic_captions') or {}));automatic=True
    lang=next((l for p in ('zh-Hans','zh-CN','zh','zh-Hant','en') for l in languages if l==p),None)
    if lang:
        opts.update(writesubtitles=not automatic,writeautomaticsub=automatic,subtitleslangs=[lang],subtitlesformat='vtt/best')
        with yt_dlp.YoutubeDL(opts) as ydl:ydl.download([doc['url']])
        files=[p for p in folder.glob('platform.*') if p.suffix in ('.vtt','.srt','.json3')]
        if files:return {'subtitle':files[0].name,'automatic':automatic,'language':lang}
    if not doc.get('download_video'):return {'unavailable':True,'message':'平台没有返回可用字幕，可导入本地原片转写。'}
    opts.update(skip_download=False,writesubtitles=False,writeautomaticsub=False,
        format='best[height<=480][ext=mp4]/best[height<=480]/worst',max_filesize=500*1024*1024)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info=ydl.extract_info(doc['url'],download=True);name=Path(ydl.prepare_filename(info))
    if not name.is_file() or name.stat().st_size>500*1024*1024:raise ValueError('未取得大小合适的原片，请改为本地导入。')
    return {'source':name.name}


if __name__=='__main__':
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    request=json.load(sys.stdin)
    # Dependencies occasionally log to stdout; the wire result is one JSON line.
    with contextlib.redirect_stdout(sys.stderr):
        result=inspect(request) if request['action']=='inspect' else transcribe(request) if request['action']=='transcribe' else fetch_platform(request)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
