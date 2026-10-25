"""Reproduce the local video adapters without changing the dashboard venv."""
import json
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parent


def install(state):
    target=Path(state)/'video-tools';target.mkdir(parents=True,exist_ok=True)
    for name,requirements in [('venv','video-requirements.txt'),('scene-venv','scene-requirements.txt')]:
        folder=target/name
        if not (folder/'bin/python').is_file():venv.EnvBuilder(with_pip=True).create(folder)
        subprocess.run([str(folder/'bin/python'),'-m','pip','install','-r',str(ROOT/requirements)],check=True)
        lock=subprocess.check_output([str(folder/'bin/python'),'-m','pip','freeze'],text=True)
        (target/(name+'-lock.txt')).write_text(lock)
    script="""import json,importlib.metadata as m,os
from pathlib import Path
from huggingface_hub import snapshot_download
root=Path(__import__('sys').argv[1])
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_XET']='1'
snapshot_download('Systran/faster-whisper-small',local_dir=root/'models/small',allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*','preprocessor_config.json'],max_workers=2)
print(json.dumps({k:m.version(k) for k in ['faster-whisper','yt-dlp','av']}))
"""
    output=subprocess.check_output([str(target/'venv/bin/python'),'-c',script,str(target)],text=True)
    versions=json.loads(output.strip().splitlines()[-1]);versions['scenedetect']='0.7.2'
    (target/'installed.json').write_text(json.dumps(versions,indent=2))
    print('视频组件与本地 small 模型已准备。')


if __name__=='__main__':
    install(sys.argv[1] if len(sys.argv)>1 else Path.home()/'Library/Application Support/TzFilmDouyin')
