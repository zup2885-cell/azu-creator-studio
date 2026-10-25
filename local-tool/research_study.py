"""Different contracts for reference breakdown and next-topic decisions."""
import copy
import json
import math
from pathlib import Path

BASE=Path(__file__).with_name('research_report_schema.json')


def schema(mode):
    doc=json.loads(BASE.read_text())
    string=lambda n:{'type':'string','minLength':1,'maxLength':n}
    if mode=='creative':
        section={'type':'object','additionalProperties':False,'required':['opening','beats','pacing','borrow','avoid'],'properties':{
            'opening':string(140),'pacing':string(140),'borrow':string(120),'avoid':string(120),
            'beats':{'type':'array','maxItems':6,'items':{'type':'object','additionalProperties':False,
                'required':['item_id','start','end','detail'], 'properties':{'item_id':string(24),
                'start':{'type':'number','minimum':0,'maximum':1200},'end':{'type':'number','minimum':0,'maximum':1200},'detail':string(100)}}}}}
        key='breakdown'
    else:
        section={'type':'object','additionalProperties':False,'required':['topic','angle','audience','reason','sources'],
            'properties':{k:string(n) for k,n in [('topic',50),('angle',100),('audience',80),('reason',140)]}}
        section['properties']['sources']={'type':'array','minItems':1,'maxItems':3,'items':string(80)}
        key='decision'
    doc['required'].append(key);doc['properties'][key]=section
    return doc


def instructions(mode):
    if mode=='creative':return '''这是对标拆解，不是选题推荐。核心问题：这条/这些作品怎样表达，我能借鉴什么？
breakdown.opening：有字幕就分析开头原句与信息顺序；只有标题就明确写“仅标题线索，开场待补原片”。
breakdown.beats：最多6个带时间的结构节点，每个含item_id/start/end/detail。只有提供了带时间字幕、镜头数据或实际附图，才填写对应有证据的节点；没有时间证据必须给空数组，禁止推算时间。区分字幕内容与静态画面。
breakdown.pacing：基于真实镜头时长/字幕段落解释节奏；没有就直说缺少节奏证据，不靠点赞补写。
borrow/avoid：各一项可借鉴的表达办法和不可直接照搬之处。单样本称“单片拆解”，多个样本才比较，不虚构其他作者。
brief的结论先回答具体借鉴什么；findings聚焦开头、结构和表达差异。不要输出下一条选题决策。
'''
    return '''这是选题决策，不重复逐段拆解别人。核心问题：我下一条做谁、讲什么角度、为什么值得继续准备？
优先使用observations.benchmark_context里已完成的对标结论，结合本次素材，选一个方向。没有对标报告也可决策，但如实说明依据范围。
decision.topic：一个具体人物/事件/主题；angle：一个明确切口；audience：解决谁的哪个问题；reason：依据信息与推测分开，公开点赞不是需求验证；sources：1–3项下一步必须补的具体资料。
不输出成片标题、口播和完整稿件；不重复镜头节奏拆解。brief先给唯一优先方向。若资料不足，给有条件的研究候选，不伪装已确认的创作事实。
'''


def validate_study(report,task):
    if task.get('study_format')!='video-v1':return {}
    key='breakdown' if task['mode']=='creative' else 'decision'
    value=report.get(key);spec=schema(task['mode'])['properties'][key]
    if not isinstance(value,dict) or set(value)!=set(spec['required']):raise ValueError('报告缺少本步骤的专属结果：'+key)
    for k,rule in spec['properties'].items():
        if rule['type']=='string' and (not isinstance(value[k],str) or not 1<=len(value[k].strip())<=rule['maxLength']):raise ValueError('专属研究结果文字格式无效。')
    if key=='decision':
        rows=value['sources']
        if not isinstance(rows,list) or not 1<=len(rows)<=3 or any(not isinstance(s,str) or not 1<=len(s.strip())<=80 for s in rows):raise ValueError('选题需提供1–3项具体补证资料。')
    else:
        rows=value['beats']
        if not isinstance(rows,list) or len(rows)>6:raise ValueError('结构节点最多6项。')
        context=json.loads((Path(task['bundle_path']).with_suffix('.json')).read_text())
        items={i['id']:i for i in context['items']}
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'item_id','start','end','detail'}:raise ValueError('结构节点格式无效。')
            item=items.get(row['item_id'])
            start,end=row['start'],row['end']
            if not item or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in (start,end)) or not 0<=start<end<=1200:raise ValueError('节点引用或时间无效。')
            evidence=item.get('media_evidence',{})
            if not evidence.get('segments') and not evidence.get('scenes'):raise ValueError('未取得时间证据，不能生成带时间节点。')
            bound=evidence.get('duration') or max((s['end'] for s in evidence.get('segments',[])),default=0)
            if end>bound+0.5:raise ValueError('结构节点超出原始证据时长。')
            if not isinstance(row['detail'],str) or not 1<=len(row['detail'].strip())<=100:raise ValueError('节点说明无效。')
    return {key:copy.deepcopy(value)}
