import React from 'react';
import {ChevronDown} from 'lucide-react';
import './research-report.css';
import {mediaTime} from './research-media';

export function ResearchReportBody({report,date}){
  const brief=report.brief;
  return <div className="research-report-body report-readable">
    <div className="report-byline"><span>{report.provider}</span><time>{date(report.created_at)}</time></div>
    <section className="report-recommendation" aria-label="一句话建议"><span>一句话建议</span><h3>{brief?.conclusion||report.summary}</h3></section>
    {brief&&<>
      <section className="report-key-points" aria-label="重点看什么"><h4>重点看什么</h4><ul>{brief.points.map((point,i)=><li key={i}><strong>{point.title}</strong><p>{point.detail}</p></li>)}</ul></section>
      <section className="report-next-steps" aria-label="下一步怎么做"><h4>下一步怎么做</h4><ol>{brief.actions.map((action,i)=><li key={i}>{action}</li>)}</ol></section>
      <p className="report-caveat"><strong>这次还缺什么</strong>{brief.caveat}</p>
    </>}
    {report.breakdown&&<details className="report-special"><summary>开头、结构与节奏</summary><dl><dt>开头怎么抓人</dt><dd>{report.breakdown.opening}</dd><dt>节奏依据</dt><dd>{report.breakdown.pacing}</dd><dt>可以借鉴</dt><dd>{report.breakdown.borrow}</dd><dt>不要照搬</dt><dd>{report.breakdown.avoid}</dd></dl>{report.breakdown.beats.length>0&&<><h4>结构节点</h4><ol>{report.breakdown.beats.map((b,i)=><li key={i}><time>{mediaTime(b.start)}—{mediaTime(b.end)}</time>{b.detail}</li>)}</ol></>}</details>}
    {report.decision&&<details className="report-special"><summary>优先选题与准备资料</summary><dl><dt>优先做什么</dt><dd>{report.decision.topic}</dd><dt>切入角度</dt><dd>{report.decision.angle}</dd><dt>给谁看</dt><dd>{report.decision.audience}</dd><dt>为什么考虑它</dt><dd>{report.decision.reason}</dd></dl><h4>需要补充的资料</h4><ul>{report.decision.sources.map((s,i)=><li key={i}>{s}</li>)}</ul></details>}
    <details className="report-full" key={report.id||report.task_id}>
      <summary><span>查看依据与完整分析 <small>{report.findings.length} 条</small></span><ChevronDown size={16} aria-hidden="true"/></summary>
      <div className="report-full-content"><h4>完整结论</h4><p>{report.summary}</p>
        {report.findings.map((finding,i)=><article key={i}><h4>{finding.title}</h4><label>依据</label><p>{finding.evidence}</p><label>分析</label><p>{finding.interpretation}</p></article>)}
        {report.experiments?.length>0&&<><h4>下一步验证</h4><ul>{report.experiments.map((text,i)=><li key={i}>{text}</li>)}</ul></>}
        <h4>结论边界</h4><ul>{report.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul>
      </div>
    </details>
  </div>
}
