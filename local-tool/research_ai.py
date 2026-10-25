"""Run the approved official Codex CLI against frozen research inputs.

Authentication stays in Codex. No API keys, web automation, social writes or
model-generated commands are used by this adapter.
"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import tomllib

GUARD=threading.Lock()
SCHEMA=Path(__file__).with_name('research_report_schema.json')
APP_CLI=Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')
TIMEOUT=300
_status_cache={}


def binary():
    path=shutil.which('codex')
    return path or (str(APP_CLI) if APP_CLI.is_file() else None)


def enabled(state):
    try:return json.loads((Path(state)/'ai-analysis.json').read_text()).get('enabled') is True
    except (OSError,ValueError,AttributeError):return False


def status(state):
    exe=binary();active=enabled(state)
    if not exe:return {'installed':False,'enabled':active,'authenticated':False,'ready':False,'provider':'codex-cli','message':'本机 Codex CLI 未找到。'}
    cached=_status_cache.get(exe)
    if not cached or time.monotonic()-cached[0]>60:
        try:
            result=subprocess.run([exe,'login','status'],capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=8)
            # Check only the authentication mode; never read or return credentials.
            authenticated=result.returncode==0 and 'using ChatGPT' in result.stdout+result.stderr
        except (OSError,subprocess.TimeoutExpired):authenticated=False
        cached=(time.monotonic(),authenticated);_status_cache[exe]=cached
    authenticated=cached[1]
    return {'installed':True,'enabled':active,'authenticated':authenticated,'ready':active and authenticated,
            'provider':'codex-cli','message':'使用本机已登录的 Codex，结果自动返回本页；消耗 Codex 额度。' if active and authenticated else '请先在本机 Codex 登录 ChatGPT。' if active else '本机 Codex 已安装，自动分析尚未启用。'}


def model_options():
    # Reuse only the user's model preference; no hooks, providers, MCP servers,
    # secrets or arbitrary command configuration are copied into the worker.
    try:cfg=tomllib.loads((Path.home()/'.codex/config.toml').read_text())
    except (OSError,ValueError):return []
    result=[]
    if isinstance(cfg.get('model'),str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',cfg['model']):result+=['--model',cfg['model']]
    if cfg.get('model_reasoning_effort') in ('low','medium','high','xhigh','max','ultra'):
        result+=['-c','model_reasoning_effort='+json.dumps(cfg['model_reasoning_effort'])]
    return result


def command(exe,folder):
    output_schema=folder/'schema.json'
    if not output_schema.is_file():output_schema=SCHEMA
    args=[exe,'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','read-only',
          '--color','never','--cd',str(folder),'--output-schema',str(output_schema),'--output-last-message',str(folder/'report.json'),
          '-c','web_search="disabled"']
    for feature in ('shell_tool','multi_agent','apps','plugins','hooks','browser_use','browser_use_external','computer_use','in_app_browser','image_generation','view_image','sleep_tool'):
        args+=['--disable',feature]
    return args+model_options()+['-']


def start(research,request,background=True):
    from research import POOL
    if not status(research.root.parent)['ready']:raise ValueError('本机 Codex 尚未就绪，请检查登录状态；不会创建或索要 API 密钥。')
    with GUARD:
        with research.db() as db:
            if db.execute("SELECT 1 FROM tasks WHERE kind='analysis' AND status='running'").fetchone():
                raise ValueError('已有 AI 分析进行中，请等当前报告完成。')
        ids=request.get('ids')
        if isinstance(ids,list):
            rows={i['id']:i for i in research.items()}
            if any(rows.get(i,{}).get('source')=='link-only' for i in ids):
                raise ValueError('所选素材仍只有链接，尚无作品资料。请先补齐资料，再开始 AI 分析。')
        result=research.prepare_analysis(request);ident=result['task_id'];doc=research.task(ident)
        doc.update(provider='codex-cli',output_style='concise-v1',study_format='video-v1',phase='queued',message='AI 分析已开始，正在交给本机 Codex。报告会自动返回本页。')
        research.set_task(ident,'analysis','running',doc)
        if background:POOL.submit(run,research,ident)
    if not background:run(research,ident)
    return {'ok':True,'task_id':ident,'message':'AI 分析已开始，结果会自动返回网页。'}


def failure_message(log):
    value=log.lower()
    if any(s in value for s in ('usage limit','quota exceeded','rate limit','rate_limit')):return 'Codex 额度或速率受限，本次已停止，没有自动重试。'
    if any(s in value for s in ('unauthorized','not logged in','authentication','token expired')):return 'Codex 登录需要检查，本次未完成；请在 Codex 中重新登录。'
    return 'Codex 本次未返回有效报告，已停止；素材保留，可稍后手动重新分析。'


def run(research,ident):
    from research import stamp
    doc=research.task(ident)
    folder=research.root/'analysis-runs'/ident;folder.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(folder,0o700)
    process=None
    try:
        if not status(research.root.parent)['ready']:raise ValueError('Codex 当前未登录，分析已停止。')
        bundle=(research.root/'analysis-inputs'/f'{ident}.md').read_text()
        prompt='只输出符合 JSON Schema 的中文研究报告。不要调用工具、读取其他文件、启动其他 Agent、执行命令或访问链接。所有资料已经放在下方。\n'
        prompt+='只分析已提供的标题、简介、互动数据、字幕及附图。自动转写需保留误识别边界；没有音频输入，不能描述音效。附图为抽样，不能声称看完原片。\n'
        from research_study import instructions,schema
        research.atomic(folder/'schema.json',schema(doc['mode']))
        prompt+=instructions(doc['mode'])+'\n'
        prompt+=bundle.replace('分析完成后，由当前 Codex 用 research_cli.py finish 导入这份结果，不启动其他 Agent，不发送或发布任何内容。','仅返回 JSON，由网页后端校验并保存；不要执行导入命令。')
        prompt+='''\n\n## 本次报告的阅读要求（以此及最新 JSON Schema 为准）
读者是做抖音的创作者。用短句和自然中文，把“学什么、为什么、接着做什么”说清楚。不要写论文，不重复提醒同一个限制，不堆“维度、编码、观察性、身份表述”等术语。
必须额外输出 brief 简读对象，默认阅读量约220–320字，合计绝不超过420字：
- conclusion：一句直接建议，60字以内。指出研究哪个具体角度，需要补证时保留条件。
- points：1–3条真正重要的发现，每条 title 14字以内，detail 54字以内，并列出原素材 item_ids。说明具体看点或可参考做法，不重复结论。
- actions：1–3条现在能执行的动作，每条48字以内。给具体资料、步骤或比较对象，不写空泛方法论。
- caveat：70字以内，只合并说明本次最关键的信息缺口；不要把不确定的标题主张写成已确认事实。
完整分析也收敛：summary最多160字，findings最多3条，experiments最多3条，limitations最多3条。保持数字、近似标记、素材引用和事实边界；不能为了简短删掉“约、尚未确认”等必要限定词。不要编造已看过画面或已取得字幕。仅返回 JSON。
'''
        if len(prompt.encode())>500000:raise ValueError('分析输入过大，请减少素材或字幕。')
        doc.update(phase='analyzing',started_at=stamp(),message='本机 Codex 正在分析素材。报告经引用与格式校验后自动显示。')
        research.set_task(ident,'analysis','running',doc)
        log_path=folder/'runtime.log'
        env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','CODEX_API_KEY','ANTHROPIC_API_KEY')}
        with log_path.open('wb') as log:
            os.chmod(log_path,0o600)
            import hashlib
            context=json.loads((research.root/'analysis-inputs'/f'{ident}.json').read_text())
            frames=context['observations'].get('frame_attachments',[])
            args=command(binary(),folder)
            if frames:
                for frame in frames:
                    path=Path(frame['path'])
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=frame['sha256']:raise ValueError('关键帧已变化，请重新开始分析。')
                    args[-1:-1]=['--image',str(path)]
                prompt+='\n附件顺序：'+json.dumps([{'item_id':f['item_id'],'at':f['at']} for f in frames],ensure_ascii=False)+'。只能描述各时刻静态帧。'
            process=subprocess.Popen(args,cwd=folder,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log,env=env,start_new_session=True)
            try:process.communicate(prompt.encode(),timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                raise ValueError('AI 分析超过 5 分钟，已停止；没有自动重试，可稍后手动重新分析。') from None
        if process.returncode!=0:
            raise ValueError(failure_message(log_path.read_bytes()[-16000:].decode(errors='replace')))
        output=folder/'report.json'
        if not output.is_file() or not 1<=output.stat().st_size<=131072:raise ValueError('Codex 返回报告为空或超出大小限制，未保存为成功。')
        os.chmod(output,0o600)
        report=json.loads(output.read_text())
        research.finish(ident,report)
    except Exception as error:
        doc=research.task(ident)
        if doc['status']=='complete':return
        message=str(error) if isinstance(error,ValueError) and not isinstance(error,json.JSONDecodeError) else 'AI 分析未完成，未写入无效报告；素材仍保留。'
        doc.update(phase='failed',finished_at=stamp(),message=message,error_code='AI_ANALYSIS_FAILED')
        research.set_task(ident,'analysis','failed',doc)
    finally:
        if process and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
