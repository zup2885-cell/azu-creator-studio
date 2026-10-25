#!/usr/bin/env python3
"""Start only this dashboard; no login startup, capture scheduling or browser automation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
STATE = Path(os.environ.get('DOUYIN_STATE_DIR',str(Path.home()/'Library/Application Support/TzFilmDouyin')))
URL = 'http://127.0.0.1:8766'

def health():
    try:
        with urllib.request.urlopen(URL+'/api/health',timeout=1) as response:
            return json.load(response).get('service')=='azu-douyin-studio'
    except (OSError, ValueError):
        return False

def start():
    if health():
        return False
    if not (ROOT/'dist/index.html').is_file():
        raise RuntimeError('页面构建文件缺失，请先在 local-tool 中运行 npm run build。')
    STATE.mkdir(parents=True,exist_ok=True)
    log_dir=STATE/'logs'
    log_dir.mkdir(exist_ok=True)
    log_path=log_dir/'dashboard.log'
    if log_path.exists() and log_path.stat().st_size>2*1024*1024:
        log_path.replace(log_path.with_suffix('.previous.log'))
    with open(log_path,'ab') as log:
        os.chmod(log_path,0o600)
        process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    for attempt in range(35):
        if process.poll() is not None:
            raise RuntimeError('启动失败，可能有其他程序占用 8766 端口。请查看本地 dashboard.log。')
        if health():
            (STATE/'dashboard.pid').write_text(str(process.pid))
            return True
        time.sleep(.1)
    raise RuntimeError('服务启动超时，请查看本地 dashboard.log。')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    try:
        created=start()
        print(('创作台已启动：' if created else '创作台已在运行：')+URL)
        if args.open:
            subprocess.run(['/usr/bin/open',URL],check=True)
    except Exception as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
