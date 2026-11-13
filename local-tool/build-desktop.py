#!/usr/bin/env python3
"""Compile a native macOS app launcher; a shell script alone is not a valid app executable."""
from pathlib import Path
import json
import plistlib
import subprocess

ROOT=Path(__file__).resolve().parent
APP=Path.home()/'Desktop/阿祖抖音创作台.app'
MAC=APP/'Contents/MacOS'
RES=APP/'Contents/Resources'
MAC.mkdir(parents=True,exist_ok=True)
RES.mkdir(parents=True,exist_ok=True)
binary=MAC/'azu-studio'
temporary=MAC/'azu-studio.new'
subprocess.run(['xcrun','clang','-fobjc-arc','-framework','Cocoa','-mmacosx-version-min=13.0',str(ROOT/'desktop-main.m'),'-o',str(temporary)],check=True)
temporary.replace(binary)
binary.chmod(0o755)
python=Path.home()/'Library/Application Support/TzFilmDouyin/venv/bin/python'
(RES/'launcher-config.json').write_text(json.dumps({'python':str(python),'launcher':str(ROOT/'launcher.py')},ensure_ascii=False,indent=2))
info={'CFBundleName':'阿祖抖音创作台','CFBundleDisplayName':'阿祖抖音创作台','CFBundleIdentifier':'local.azu.douyin-studio','CFBundleExecutable':'azu-studio','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.4.0','CFBundleVersion':'7','CFBundleIconFile':'Studio.icns','LSMinimumSystemVersion':'13.0','LSUIElement':True,'NSHighResolutionCapable':True,'NSDesktopFolderUsageDescription':'读取桌面的抖音数据看板项目，以启动本地创作台。'}
with open(APP/'Contents/Info.plist','wb') as stream:plistlib.dump(info,stream)
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(APP)],check=True)
subprocess.run(['/usr/bin/codesign','--verify','--strict',str(APP)],check=True)
print(APP)
