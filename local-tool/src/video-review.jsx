import React,{useEffect,useState} from 'react';
import {CalendarClock,Info,NotebookPen,RefreshCw,ChevronRight} from 'lucide-react';
import {Card,CardHeader} from './ui';
import {WorkCover} from './work-cover';
const nf=new Intl.NumberFormat('zh-CN');
const fmt=v=>v==null?'—':nf.format(v);
const value=(v,unit)=>v==null?'—':unit==='%'?`${v.toFixed(2)}%`:`${fmt(v)}${unit==='人'?' 人':''}`;
const clean=t=>t.split('#')[0].trim().split(/\r?\n/)[0];
export function AutomationPanel({state,compact=false}){
  if(compact)return <div className="automation-strip"><CalendarClock size={16}/><strong>数据定时更新</strong><span>{state?.schedule_label||'每天 21:00（北京时间）'}</span><span>{state?.last_success_at?`最近成功 ${state.last_success_at}`:'等待首次采集'}</span></div>;
  return <details className="review-automation"><summary>数据更新状态 <ChevronRight size={14}/></summary><p>最近成功采集：{state?.last_success_at||'尚未采集'}；{state?.schedule_label||'每天 21:00（北京时间）'}。</p>{state?.last_error&&<p>{state.last_error}</p>}<a href="#data">前往数据中心</a></details>
}
export function AnalysisPage({data,snap,initialWorkId}){
  const works=snap?.rows.filter(r=>r.status==='公开')||[];
  const running=data?.studio_job?.kind==='review'&&data.studio_job.status==='running'&&data.studio_job.review_input?.snapshot_id===snap?.id?data.studio_job:null;
  const [workId,setWorkId]=useState(()=>{let remembered;try{remembered=sessionStorage.getItem('azu-review-work')}catch{}return running?.review_input?.work_id||initialWorkId||(works.some(w=>w.id===remembered)?remembered:works[0]?.id)||''}),[notes,setNotes]=useState(running?.review_input?.notes||''),[reports,setReports]=useState([]),[job,setJob]=useState(running),[submitting,setSubmitting]=useState(false),[error,setError]=useState('');
  useEffect(()=>{try{if(workId)sessionStorage.setItem('azu-review-work',workId)}catch{}},[workId]);
  const loadReports=async()=>{try{const response=await fetch('/api/work-reviews');if(response.ok)setReports((await response.json()).reports)}catch{}};
  useEffect(()=>{loadReports()},[snap?.id]);
  useEffect(()=>{if(running)return;if(initialWorkId&&works.some(w=>w.id===initialWorkId))setWorkId(initialWorkId);else if(!works.some(w=>w.id===workId))setWorkId(works[0]?.id||'')},[initialWorkId,snap?.id]);
  useEffect(()=>{
    if(job?.status!=='running')return;
    let stopped=false;const timer=setInterval(async()=>{try{const r=await fetch('/api/studio/status');const next=await r.json();if(stopped)return;setJob(next);if(next.status!=='running')loadReports()}catch{}},2000);
    return()=>{stopped=true;clearInterval(timer)};
  },[job?.status]);
  const work=works.find(w=>w.id===workId),busy=submitting||job?.status==='running';
  const report=reports.find(r=>r.work_id===workId&&r.snapshot_id===snap?.id&&r.source_sha256===snap?.sha256);
  const start=async()=>{setSubmitting(true);setError('');try{const response=await fetch('/api/studio/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot_id:snap.id,work_id:workId,notes})});const result=await response.json();if(!response.ok)throw Error(result.error||'复盘未能开始');setJob(result)}catch(e){setError(e.message)}finally{setSubmitting(false)}};
  const overall=data?.analyses?.find(r=>r.snapshot_id===snap?.id&&r.source_sha256===snap?.sha256);
  return <section className="video-review-page">
    <Card className="review-picker"><CardHeader><div><h2>先选一条，认真复盘</h2><p>围绕涨粉，逐项看留人、完播、互动和关注转化。</p></div><span className="review-scope">单条视频</span></CardHeader>
      <div className="review-picker-controls"><label>选择要复盘的视频<select aria-label="选择复盘视频" value={workId} disabled={busy} onChange={e=>{setWorkId(e.target.value);setNotes('');setError('');setJob(null)}}>{works.map(w=><option value={w.id} key={w.id}>{clean(w.title)} · {w.pub_date.slice(0,10)}</option>)}</select></label><button className="button primary" disabled={busy||!work} onClick={start}><NotebookPen size={16}/>{busy?'正在复盘…':report?'重新复盘这条视频':'复盘这条视频'}</button></div>
      <details className="review-notes"><summary>补充原稿或你的观察，让复盘更具体（可选）</summary><textarea aria-label="补充原稿或观察" maxLength={6000} disabled={busy} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="可以粘贴这条视频的口播稿，或写下你想排查的问题。"/><small>{notes.length}/6000 · 消耗当前 Codex 额度，生成后保存在本机。</small></details>
    </Card>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {job&&<div className={'review-job '+(job.status==='failed'?'review-job-error':'')} role="status"><RefreshCw size={15}/>{job.message}</div>}
    {work&&<><Card className="review-video"><WorkCover key={work.id} row={work}/><div><span className="review-eyebrow">正在查看的作品</span><h2>{clean(work.title)}</h2><p>{work.pub_date.slice(0,16)} 发布 · 数据采集于 {snap.capture_time}</p>{work.url&&<a href={work.url} target="_blank" rel="noreferrer">打开原视频 ↗</a>}</div></Card>
    <div className="review-key-metrics">{[['累计播放',fmt(work.plays),'次'],['作品归因涨粉',fmt(work.follower_gain),'人'],['5 秒留存',value(work.ctr5s,'%'),''],['完播率',value(work.finish,'%'),'']].map(([label,v,unit])=><Card key={label}><span>{label}</span><strong>{v}<small>{unit}</small></strong></Card>)}</div></>}
    {report?<><Card className="review-verdict"><span className="review-eyebrow">这条最值得先改什么</span><h2>{report.summary}</h2><p>生成于 {report.generated_at} · {report.notes_provided?'已结合你提供的原稿或观察':'当前依据作品数据，尚未观看原片'}</p></Card>
    <div className="review-section-title"><h2>逐项诊断</h2><span>每项都有数据、判断、改法和验证方式</span></div>
    <div className="review-diagnostics">{report.diagnostics.map((item,index)=>{const e=report.evidence[item.metric];return <details key={item.metric} open={index<2} className="review-diagnostic"><summary><span className="review-diagnostic-title"><b>{index+1}</b>{e.label}</span><strong>{value(e.value,e.unit)}</strong><ChevronRight size={16}/></summary><div className="review-diagnostic-body"><div className="review-evidence">本条 {value(e.value,e.unit)}<span>同账号参考中位数 {value(e.median,e.unit)} · {e.sample_count} 条样本</span></div><p className="review-observation">{item.observation}</p><dl><div><dt>可能原因</dt><dd>{item.hypothesis}</dd></div><div><dt>具体怎么改</dt><dd>{item.action}</dd></div><div><dt>如何验证</dt><dd>{item.check}</dd></div></dl></div></details>})}</div>
    <Card className="review-experiment"><CardHeader><h2>下一条，只验证一个主要改动</h2></CardHeader><dl><div><dt>这次改什么</dt><dd>{report.experiment.change}</dd></div><div><dt>哪些尽量不变</dt><dd>{report.experiment.keep}</dd></div><div><dt>怎么判定有效</dt><dd>{report.experiment.judge}</dd></div></dl></Card>
    <details className="review-boundaries"><summary><Info size={15}/>这份复盘的依据与限制</summary><p>{report.comparison_limit}</p><ul>{report.limitations.map((s,i)=><li key={i}>{s}</li>)}</ul></details>
    </>:<Card className="review-empty"><NotebookPen size={27}/><h2>这条视频还没有当前数据的复盘</h2><p>选好视频，点击上方“复盘这条视频”。报告只针对这一条，后续可以切换作品查看。</p></Card>}
    {overall&&<details className="legacy-review"><summary>查看以前保存的账号整体报告</summary><p>{overall.summary}</p>{overall.findings.map((f,i)=><article key={i}><h3>{f.title}</h3><p>{f.evidence}</p><p>{f.interpretation}</p></article>)}</details>}
    <AutomationPanel state={data?.automation}/>
  </section>
}
