import React,{useEffect,useRef,useState} from 'react';
import {RefreshCw,LogIn} from 'lucide-react';

export function CreatorSync({data,snap,reload,notify,page}) {
  const [job,setJob]=useState(data?.studio_job||{status:'idle'});
  const [submitting,setSubmitting]=useState(false);
  const latest=useRef({reload,notify});latest.current={reload,notify};
  const finished=useRef(null);
  useEffect(()=>{if(data?.studio_job)setJob(data.studio_job)},[data?.studio_job]);
  useEffect(()=>{
    if(job.status!=='running')return;
    let stopped=false;
    const poll=async()=>{try{
      const response=await fetch('/api/studio/status');if(!response.ok)return;
      const next=await response.json();if(stopped)return;setJob(next);
      if(next.status!=='running'&&next.id!==finished.current){finished.current=next.id;latest.current.notify(next.message);latest.current.reload(null,true)}
    }catch{}};
    const timer=setInterval(poll,2000);return()=>{stopped=true;clearInterval(timer)};
  },[job.status]);
  const start=async kind=>{
    setSubmitting(true);
    try{
      const response=await fetch('/api/studio/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      const result=await response.json();if(!response.ok)throw Error(result.error||'任务未能启动');
      setJob(result);latest.current.notify(result.message);
    }catch(error){latest.current.notify(error.message)}finally{setSubmitting(false)}
  };
  const busy=submitting||job.status==='running';
  const historical=snap&&snap.id!==data?.snapshots?.[0]?.id;
  const stale=data?.freshness?.is_stale;
  const unverified=data?.freshness?.time_verified===false;
  return <section className={'creator-sync '+(stale?'creator-sync-stale':'')} aria-label="抖音数据更新">
    <div className="creator-sync-copy"><strong>{busy?'任务进行中':historical?'正在查看历史记录':stale?'作品数据需要更新':unverified?'当前数据的采集时间未确认':'本人作品数据已载入'}</strong>
      <p role="status">{job.status==='running'||job.status==='failed'||job.status==='cancelled'?job.message:historical?`历史采集时间：${snap.capture_time}`:data?.snapshots?.[0]?`最近记录：${data.snapshots[0].capture_time}${stale?' · 已超过一天未更新':''}`:'连接本人抖音账号后，即可读取作品数据。'}</p>
    </div>
    <div className="creator-sync-actions"><button className="button primary" disabled={busy} onClick={()=>start('sync')}><RefreshCw size={14}/>{busy&&job.kind==='sync'?'正在更新…':'更新抖音数据'}</button>{page==='data'&&<button className="button secondary" disabled={busy} onClick={()=>start('auth')}><LogIn size={14}/>连接抖音账号</button>}<small>更新作品指标；复盘请到「AI 复盘」选择视频。</small></div>
  </section>;
}
