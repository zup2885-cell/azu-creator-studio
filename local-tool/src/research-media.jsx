import React,{useEffect,useRef,useState} from 'react';
import {Check,FileText,Film,LoaderCircle,Upload} from 'lucide-react';
import './research-media.css';

// taste-skill-ignore: Zero-padding is required for real mm:ss video timestamps.
export const mediaTime=value=>{const s=Math.max(0,Math.floor(value||0));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`};

export function ResearchMedia({data,selected,mutate,load,notify,busy,onPick}){
  const [id,setId]=useState(''),[uploading,setUploading]=useState(false),[download,setDownload]=useState(false),[draft,setDraft]=useState('');
  const file=useRef();
  const choices=[...(data?.items||[])].sort((a,b)=>Number(selected.includes(b.id))-Number(selected.includes(a.id))||Number(b.saved)-Number(a.saved));
  const item=choices.find(i=>i.id===id)||choices[0];
  const ev=item?.media_evidence,mediaTask=data?.tasks.find(t=>t.kind==='media'&&t.item_ids?.includes(item?.id));
  const working=uploading||data?.tasks.some(t=>t.kind==='media'&&t.status==='running');
  useEffect(()=>{if(selected.length===1)setId(selected[0])},[selected.join(',')]);
  useEffect(()=>setDraft(item?.transcript||''),[item?.id,item?.media_checked_at,item?.transcript]);
  const upload=async chosen=>{
    if(!chosen||!item)return;
    if(!chosen.size||chosen.size>500*1024*1024){notify('请选择非空、500 MB以内的文件。');return}
    setUploading(true);
    try{
      const response=await fetch('/api/research/media-upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(chosen.name),'X-Item-ID':item.id},body:chosen});
      const result=await response.json();if(!response.ok)throw Error(result.error||'文件导入未完成');
      await load();notify(result.message);
    }catch(e){notify(e.message)}finally{setUploading(false);if(file.current)file.current.value=''}
  };
  const frameId=ev?.video_evidence||ev?.media_id;
  return <section className="research-media-panel" aria-label="视频内容读取">
    <div className="media-panel-heading"><div><h2>读懂参考视频</h2><p>先取字幕，再看结构。原片和字幕都保存在本机。</p></div><span>{data?.video_tools?.ready?'视频组件已就绪':'视频组件待就绪'}</span></div>
    <div className="media-input-row"><label className="research-field">补充哪条素材<select aria-label="选择要读取视频内容的素材" value={item?.id||''} onChange={e=>setId(e.target.value)} disabled={working||!choices.length}>{!choices.length&&<option value="">先粘贴链接收藏一条作品</option>}{choices.map(i=><option value={i.id} key={i.id}>{i.title}</option>)}</select></label><button className="text-button" disabled={!item} onClick={()=>onPick(item.id)}>选为分析样本</button></div>
    <div className="media-input-actions"><button className="button secondary" disabled={busy||working||!item||!['youtube','bilibili'].includes(item.platform)} onClick={()=>mutate('media-read',{id:item.id,download_video:download},r=>r.message)}><FileText size={16}/>读取平台字幕</button><button className="button secondary" disabled={busy||working||!item||!data?.video_tools?.ready} onClick={()=>file.current?.click()}>{uploading?<LoaderCircle size={16} className="spin"/>:<Upload size={16}/>}导入原片 / 字幕</button><input ref={file} className="sr-only" type="file" aria-label="导入视频音频或字幕" accept=".mp4,.mov,.mkv,.webm,.mp3,.wav,.m4a,.aac,.srt,.vtt,.txt" onChange={e=>upload(e.target.files[0])}/></div>
    <label className="media-download-option"><input type="checkbox" checked={download} onChange={e=>setDownload(e.target.checked)} disabled={working}/>平台无字幕时，尝试读取原片并转写</label>
    <p className="media-input-limit">平台字幕支持 YouTube、哔哩哔哩；抖音、小红书可导入本地文件。原片最多20分钟、500 MB；SRT / VTT / TXT 最多1 MB。遇到登录或验证限制会停止。</p>
    {mediaTask&&<p className={'media-task '+(mediaTask.status==='failed'?'failed':'')} role="status">{mediaTask.status==='running'?<LoaderCircle size={15} className="spin"/>:mediaTask.status==='complete'?<Check size={15}/>:<FileText size={15}/>}<span>{mediaTask.message}</span></p>}
    {(ev||item?.transcript)&&<div className="media-evidence"><div className="media-evidence-summary"><h3>已取得的内容</h3><span>{item?.transcript_verified?'字幕已核对':'字幕待核对'}{ev?.duration?` · ${mediaTime(ev.duration)}`:''}{ev?.scenes?.length?` · ${ev.scenes.length}个镜头`:''}</span></div>
      {ev?.frames?.length>0&&<><div className="media-frames">{ev.frames.map(frame=><a href={`/api/research/media/${frameId}/${frame.file}`} target="_blank" rel="noreferrer" key={frame.file}><img src={`/api/research/media/${frameId}/${frame.file}`} alt={`${mediaTime(frame.at)}的抽样关键帧`} loading="lazy"/><span>{mediaTime(frame.at)}</span></a>)}</div><p className="media-note">关键帧为抽样；AI最多读取8张，不能代替完整观看，也不能据此判断配乐或音效。</p></>}
      {ev?.scenes?.length>0&&<details className="media-disclosure"><summary><Film size={15}/>镜头时间表 · {ev.scenes.length}段</summary><ol className="media-scene-list">{ev.scenes.map((scene,i)=><li key={i}><span>{mediaTime(scene.start)}—{mediaTime(scene.end)}</span><span>{(scene.end-scene.start).toFixed(1)}秒</span></li>)}</ol></details>}
      <details className="media-disclosure"><summary><FileText size={15}/>查看与核对字幕{ev?.segments?.length?` · ${ev.segments.length}段`:''}</summary>{ev?.segments?.length>0&&<div className="media-segments">{ev.segments.map((s,i)=><p key={i}><time>{mediaTime(s.start)}</time><span>{s.text}</span></p>)}</div>}<label className="research-field">核对后的完整字幕<textarea aria-label="核对完整字幕" rows={6} maxLength={50000} value={draft} onChange={e=>setDraft(e.target.value)}/></label><button className="button secondary" disabled={busy||working||!draft.trim()} onClick={()=>mutate('save',{id:item.id,transcript:draft},'字幕已保存并标为人工核对。')}><Check size={15}/>保存并标为已核对</button><p className="media-note">语音转写可能识别人名有误；核对前，AI会将它作为待核实文本。</p></details>
    </div>}
  </section>
}
