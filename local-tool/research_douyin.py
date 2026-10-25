"""Narrow, bounded adapter for the approved, isolated dy-cli installation."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit

PYTHON=Path.home()/'Library/Application Support/TzFilmDouyin/tools/dy-cli-venv/bin/python'
COMMIT='5267065ed29f3959d4011d32293d8e520f7d6388'
WORKER=Path(__file__).with_name('research_dy_worker.py')
LOCK=threading.Lock()
JOBS={}


def state_root(state):return Path(state)/'dy-readonly'


def read_state(root):
    try:return json.loads((root/'connection.json').read_text())
    except (OSError,ValueError):return {}


def save_state(root,**values):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(root,0o700)
    doc=dict(read_state(root),**values,updated_at=datetime.now(timezone.utc).isoformat())
    target=root/'connection.json';temp=root/'connection.tmp'
    temp.write_text(json.dumps(doc,ensure_ascii=False));os.chmod(temp,0o600);temp.replace(target)
    return doc


def connection(state):
    root=state_root(state);doc=read_state(root)
    waiting=bool(doc.get('status') in ('waiting_scan','validating') and time.time()-doc.get('started_at',0)<240)
    ready=bool(PYTHON.is_file() and doc.get('verified') and doc.get('commit')==COMMIT)
    return {'installed':PYTHON.is_file(),'ready':ready,'status':doc.get('status','not_connected'),
            'waiting':waiting,'authenticated':bool((root/'cookies/default.json').is_file()),
            'last_verified_at':doc.get('last_verified_at'),'verified_count':doc.get('verified_count',0),
            'qualified_count':doc.get('qualified_count',0),'error_code':doc.get('error_code'),
            'search_verified':bool(doc.get('last_verified_at')),'detail_blocked':bool(doc.get('detail_blocked')),
            'message':doc.get('message','尚未验证抖音搜索；请先扫码连接。')}


def run_worker(action,query,limit,state):
    if action not in ('login','probe','search','detail'):raise ValueError('不支持的抖音操作')
    if not PYTHON.is_file():return {'ok':False,'error':{'code':'NEED_SETUP'}}
    try:
        result=subprocess.run([str(PYTHON),str(WORKER),action,query,str(limit),str(state_root(state))],
                              stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=180 if action=='login' else 75)
        if len(result.stdout)>3*1024*1024:raise ValueError('元数据超过上限')
        response=json.loads(result.stdout)
        if not isinstance(response,dict):raise ValueError('无效来源结果')
        return response
    except subprocess.TimeoutExpired:return {'ok':False,'error':{'code':'TIMEOUT'}}
    except (ValueError,OSError):return {'ok':False,'error':{'code':'UPSTREAM_BROKEN'}}


def verify(state,query='汽车'):
    response=run_worker('probe',query,8,state)
    rows=response.get('items') or []
    known=[r for r in rows if isinstance(r,dict) and type((r.get('metrics') or {}).get('likes')) is int
           and 0<=r['metrics']['likes']<=9007199254740991]
    code=(response.get('error') or {}).get('code')
    ok=bool(response.get('ok') and known)
    save_state(state_root(state),verified=ok,status='ready' if ok else 'verification_failed',commit=COMMIT,
               verified_count=len(known),qualified_count=sum(r['metrics']['likes']>=50000 for r in known),
               last_verified_at=datetime.now(timezone.utc).isoformat() if ok else read_state(state_root(state)).get('last_verified_at'),error_code=code,
               message='抖音公开搜索与点赞读取已实测通过。' if ok else '抖音搜索尚未验证通过，本次没有启用自动抓取。')
    return response


def collect(action,query,limit,state):
    status=connection(state)
    if action=='read' and status['detail_blocked']:return {'ok':False,'error':{'code':'DETAIL_BLOCKED'}}
    if not status['ready']:
        return {'ok':False,'error':{'code':status['error_code'] if status['error_code'] in ('PLATFORM_BLOCKED','RATE_LIMITED') else 'NEED_LOGIN'}}
    if action=='read':
        parsed=urlsplit(query)
        match=re.fullmatch(r'/video/(\d{10,24})/?',parsed.path)
        if parsed.hostname not in ('www.douyin.com','douyin.com') or not match:raise ValueError('请使用完整的抖音视频作品链接')
        action='detail';query=match[1]
    elif action!='search':raise ValueError('不支持的抖音操作')
    response=run_worker(action,query,limit,state)
    if not response.get('ok'):
        code=(response.get('error') or {}).get('code')
        if action=='detail' and code=='DETAIL_BLOCKED':
            # An access denial on the detail endpoint does not invalidate an
            # independently verified search endpoint. Never retry that detail.
            save_state(state_root(state),detail_blocked=True,detail_error_code=code,
                       message='公开搜索可用；单条详情接口受限，详情读取已停止。')
        elif code in ('NEED_LOGIN','PLATFORM_BLOCKED','RATE_LIMITED'):
            save_state(state_root(state),verified=False,status='needs_attention',error_code=code,detail_blocked=status['detail_blocked'] or action=='detail',
                       message='单条详情接口返回访问限制，已暂停抖音采集。此前搜索已通过；请本人检查平台后重新验证搜索。' if action=='detail' else '抖音要求登录、验证或暂时限流，已停止自动采集；请本人检查后重新验证。')
    return response


def login(research,request,verify_only=False):
    state=research.root.parent;root=state_root(state)
    if request.get('check'):return dict(ok=True,**connection(state))
    if not PYTHON.is_file():raise ValueError('抖音独立采集环境尚未安装')
    if verify_only and not (root/'cookies/default.json').is_file():raise ValueError('请先本人扫码登录抖音')
    key=str(root)
    with LOCK:
        job=JOBS.get(key)
        if job and job.is_alive():return dict(ok=True,**connection(state))
        save_state(root,status='validating' if verify_only else 'waiting_scan',started_at=time.time(),verified=False,
                   error_code=None,message='正在验证现有登录的公开搜索。' if verify_only else '已打开独立抖音扫码窗口，请使用本人抖音 App 扫码并确认。')
        def work():
            try:
                if not verify_only:
                    response=run_worker('login','',1,state)
                    if not response.get('ok'):
                        save_state(root,status='login_failed',verified=False,error_code=(response.get('error') or {}).get('code'),
                                   message='本次登录未完成。可重新打开扫码窗口，原有浏览器不受影响。')
                        return
                save_state(root,status='validating',message='登录已完成，正在验证公开搜索和点赞读取。')
                tracks=[t for t in research.preferences()['tracks'] if t['enabled']]
                response=verify(state,tracks[0]['name'] if tracks else '汽车')
                if response.get('ok') and connection(state)['ready'] and tracks:
                    try:research.start_discovery({})
                    except ValueError:pass
            except Exception:
                save_state(root,status='login_failed',verified=False,error_code='UPSTREAM_BROKEN',message='抖音连接本次未完成，请稍后再试。')
        job=threading.Thread(target=work,daemon=True,name='douyin-qr-login');JOBS[key]=job;job.start()
    return dict(ok=True,**connection(state))
