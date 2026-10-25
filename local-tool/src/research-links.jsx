import React,{useState} from 'react';
import {ArrowRight,Check,ExternalLink,Link2,LoaderCircle} from 'lucide-react';

const titles={library:'读取并收藏',creative:'读取并分析对标',strategy:'读取并分析选题'};
const names={douyin:'抖音',xiaohongshu:'小红书',bilibili:'哔哩哔哩',youtube:'YouTube'};
const statuses={read:'已读取',kept:'保留原资料',link_only:'仅保存链接',invalid:'不支持',duplicate:'已合并'};

export function ResearchLinks({intent,busy,running,task,onSubmit,onDetail,onAnalysis}){
  const [input,setInput]=useState('');
  const collecting=task?.status==='running';
  return <section className="research-link-entry" aria-label="粘贴链接读取作品">
    <div className="link-entry-heading"><Link2 size={20}/><div><h2>粘贴视频链接</h2><p>{intent==='library'?'把参考作品存下来，标题、封面和公开数据一起保存。':intent==='creative'?'放入想比较的作品，读取资料后自动进行 AI 对标分析。':'放入参考作品，读取资料后自动进行 AI 选题分析。'}</p></div></div>
    <form onSubmit={async e=>{e.preventDefault();const result=await onSubmit(input,intent);if(result)setInput('')}}>
      <label className="sr-only" htmlFor={'research-links-'+intent}>视频链接或完整分享文案</label>
      <textarea id={'research-links-'+intent} value={input} maxLength={20000} rows={3} onChange={e=>setInput(e.target.value)} placeholder="粘贴视频链接，或直接粘贴抖音、小红书的整段分享文案。多个链接可换行放入。" required/>
      <div className="link-entry-footer"><p>支持四个平台 · 每次最多 12 个链接{intent!=='library'&&' · 使用本机 Codex 自动分析'}</p><button className="button primary" disabled={busy||running||!input.trim()}>{collecting?<LoaderCircle size={15} className="spin"/>:<ArrowRight size={15}/>}{collecting?'读取中…':titles[intent]}</button></div>
    </form>
    {task&&<div className="link-read-results" aria-live="polite"><div className="link-read-summary">{collecting?<LoaderCircle className="spin" size={15}/>:task.status==='complete'?<Check size={15}/>:<Link2 size={15}/>}<p>{task.message}</p></div>
      {task.rows?.map((r,i)=><article className={'link-read-row '+r.status} key={r.url+i}><div><span>{names[r.platform]||'网址'}</span><strong>{statuses[r.status]||'待处理'}</strong>{r.item_id?<button className="text-button" onClick={()=>onDetail(r.item_id)}>查看资料 <ArrowRight size={12}/></button>:r.platform&&<a href={r.url} target="_blank" rel="noreferrer">打开原链接 <ExternalLink size={12}/></a>}</div><p>{r.message}</p><small title={r.url}>{r.url}</small></article>)}
      {task.analysis_task_id&&<button className="button secondary" onClick={()=>onAnalysis(task.analysis_task_id)}>查看分析状态 <ArrowRight size={14}/></button>}
      {task.analysis_error&&<p className="link-read-notice">{task.analysis_error}</p>}
    </div>}
  </section>
}
