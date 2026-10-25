import React from 'react';
import {CalendarClock,CheckCircle2,Clock3,Info,ShieldCheck,Sparkles} from 'lucide-react';
import {Card,CardHeader} from './ui';

const phases={not_configured:'尚未设置',running:'采集中',analysis_pending:'等待分析',idle:'最近一次已完成',capture_pending:'等待首次自动采集',needs_attention:'本次采集需要处理'};
export function AutomationPanel({state,compact=false}) {
  const active=state?.enabled===true;
  const phase=state?.phase||'not_configured';
  if(compact)return <div className="automation-strip"><CalendarClock size={16}/><strong>{active?'每日自动更新':'自动更新待设置'}</strong><span>{state?.schedule_label||'每天 21:00（北京时间）'}</span><span className={`automation-state ${phase==='needs_attention'?'attention':''}`}>{phases[phase]||'状态待确认'}</span><small>页面每分钟读取本地结果</small></div>;
  return <Card className="automation-card"><CardHeader><div><h2><CalendarClock size={17}/> 每日更新与分析</h2><p>{active?'已设置每日任务':'任务尚未启用'} · {state?.schedule_label||'每天 21:00（北京时间）'}</p></div><span className={`status ${phase==='needs_attention'?'private':'public'}`}>{phases[phase]||'状态待确认'}</span></CardHeader><div className="automation-details"><div><span>运行方式</span><strong>Codex 自动化</strong></div><div><span>最近尝试</span><strong>{state?.last_attempt_at||'尚未执行'}</strong></div><div><span>最近成功采集</span><strong>{state?.last_success_at||'等待首次验证'}</strong></div><div><span>独立 OpenAI API</span><strong>{state?.api_connected?'已连接':'未连接'}</strong></div></div>{state?.last_error&&<p className="automation-error">{state.last_error}</p>}<p className="automation-explain"><Info size={14}/>电脑需联网，Codex 需运行，Chrome 需保持本人抖音登录。未成功采集时保留原数据并显示状态。</p></Card>
}

export function AnalysisPage({data,snap}) {
  const report=data?.analyses?.find(r=>r.snapshot_id===snap?.id&&r.source_sha256===snap?.sha256);
  return <><AutomationPanel state={data?.automation}/>{report?<><Card className="analysis-summary"><div className="analysis-kicker"><Sparkles size={17}/><span>AI 复盘</span><small>{report.provider}</small></div><h2>{report.summary}</h2><div className="analysis-meta"><span><Clock3 size={12}/>分析生成于 {report.generated_at}</span><span>对应数据 {report.capture_time}</span></div></Card><div className="findings-grid">{report.findings.map((item,index)=><Card className="finding" key={index}><span className="finding-index">{String(index+1).padStart(2,'0')}</span><h2>{item.title}</h2><label>数据证据</label><p>{item.evidence}</p><label>分析与解释</label><p>{item.interpretation}</p></Card>)}</div><div className="analysis-bottom"><Card className="analysis-actions"><CardHeader><h2>下一条怎么做</h2><CheckCircle2 size={17}/></CardHeader><ol>{report.actions.map((text,i)=><li key={i}>{text}</li>)}</ol></Card><Card className="analysis-limits"><CardHeader><h2>这份分析的边界</h2><ShieldCheck size={17}/></CardHeader><ul>{report.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></Card></div></>:<Card className="empty"><Sparkles size={28}/><h3>这份记录还没有 AI 分析</h3><p>每日任务成功采集后，Codex 会生成带数据依据的复盘。<br/>不会将其他时点的分析套到当前记录上。</p></Card>}<div className="data-footnote"><span><ShieldCheck size={14}/>分析来自已登录的 Codex 自动化；独立 API 密钥仍未接通。</span></div></>;
}
