#!/usr/bin/env python3
"""Local dashboard and explicitly confirmed comment workflows, bound to loopback."""
import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, quote
from zoneinfo import ZoneInfo
import zipfile

ROOT = Path(__file__).resolve().parent
STATE = Path(os.environ.get('DOUYIN_STATE_DIR', str(Path.home() / 'Library/Application Support/TzFilmDouyin')))
IMPORTS = STATE / 'dashboard-imports'
TZ = ZoneInfo('Asia/Shanghai')
MAX_UPLOAD = 10 * 1024 * 1024
FIELDS = {'plays':'播放量','likes':'点赞量','comments':'评论量','shares':'分享量','favorites':'收藏量','profile_visits':'主页访问量','follower_gain':'粉丝增量','finish':'完播率','ctr5s':'5s完播率','ctrcov':'封面点击率','bounce':'2s跳出率','duration':'平均播放时长'}
RATES = {'finish','ctr5s','ctrcov','bounce'}
COUNTS = set(FIELDS) - RATES - {'duration'}

def now():
    return datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')

def number(value, field, raw=False):
    if value is None or str(value).strip() in ('', '-', '—', '--'):
        return None
    text = str(value).strip().replace(',', '')
    percent = text.endswith('%')
    n = float(text.removesuffix('%'))
    if not math.isfinite(n) or n < 0:
        raise ValueError(f'{FIELDS[field]}必须是非负有限数值')
    if field in RATES:
        n = n * 100 if raw and not percent else n
        if n > 100:
            raise ValueError(f'{FIELDS[field]}超出 0–100%')
    if field in COUNTS and (n != int(n) or n > 9007199254740991):
        raise ValueError(f'{FIELDS[field]}必须是有效整数')
    return int(n) if field in COUNTS else n

def normalize(document):
    raw = document.get('raw_rows')
    entries = raw if isinstance(raw, list) and raw else document.get('parsed_rows')
    if not isinstance(entries, list) or not entries or len(entries) > 20000:
        raise ValueError('文件需要包含 1–20000 条作品记录')
    rows, seen = [], set()
    is_raw = bool(raw)
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError(f'第 {index+1} 条记录格式错误')
        title = str(item.get('作品名称' if is_raw else 'title', '')).strip()
        date = item.get('发布时间' if is_raw else 'pub_date', '')
        if isinstance(date, datetime):
            date = date.strftime('%Y-%m-%d %H:%M:%S')
        date = str(date).strip()
        if not title or len(title) > 5000:
            raise ValueError(f'第 {index+1} 条作品名称为空或过长')
        try:
            datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise ValueError(f'第 {index+1} 条发布时间格式应为 YYYY-MM-DD HH:MM:SS')
        key = title + '\0' + date
        if key in seen:
            raise ValueError('文件含重复作品（名称与发布时间均相同），请先核对')
        seen.add(key)
        row = {'id':hashlib.sha256(key.encode()).hexdigest()[:20], 'title':title, 'pub_date':date,
               'status':str(item.get('审核状态' if is_raw else 'status', '未提供')).strip(),
               'format':str(item.get('体裁' if is_raw else 'format', '未提供'))}
        for field, label in FIELDS.items():
            row[field] = number(item.get(label if is_raw else field), field, is_raw)
        rows.append(row)
    rows.sort(key=lambda r:r['pub_date'], reverse=True)
    return rows

def capture(path):
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document,dict):
        raise ValueError('JSON 顶层必须是对象')
    rows = normalize(document)
    time = str(document.get('capture_time',''))
    try:
        datetime.strptime(time, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        raise ValueError(f'{path.name} 缺少有效记录时间')
    public = [r for r in rows if r['status']=='公开']
    totals = {k:(None if any(r[k] is None for r in public) else sum(r[k] for r in public)) for k in COUNTS}
    return {'id':path.stem,'capture_time':time,'time_kind':document.get('time_kind','capture'),
            'source_name':document.get('source_name',path.name),'source_kind':document.get('source_kind','tzfilm'),
            'rows':rows,'total_rows':len(rows),'public_count':len(public),'private_count':sum(r['status']=='自见' for r in rows),
            'totals':totals,'missing_counts':{k:sum(r[k] is None for r in rows) for k in FIELDS},
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'account':'当前导出账号'}

def snapshots():
    candidates = list((STATE/'exports').glob('抖音数据_*.json')) + list(IMPORTS.glob('*.json'))
    valid, errors = [], []
    for path in candidates:
        try:
            valid.append(capture(path))
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            errors.append({'file':path.name,'error':str(exc)})
    valid.sort(key=lambda s:(s['capture_time'],s['id']), reverse=True)
    return valid, errors

def payload():
    valid, errors = snapshots()
    from work_covers import enrich
    enrich(STATE,valid)
    from operations import read_state,read_analyses
    from studio_jobs import view
    latest=valid[0] if valid else None
    age=(datetime.now(TZ)-datetime.strptime(latest['capture_time'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)).total_seconds()/3600 if latest else None
    return {'snapshots':valid,'errors':errors,'loaded_at':now(),'local_only':True,'automation':read_state(STATE),'analyses':read_analyses(STATE,valid),'studio_job':view(STATE),'freshness':{'age_hours':round(max(0,age),1) if age is not None else None,'is_stale':age is None or age>24,'time_verified':bool(latest and latest['time_kind']=='capture')}}

def export_csv(snapshot_id, status='公开', query='', sort='pub_date'):
    valid,_ = snapshots()
    selected=next((s for s in valid if s['id']==snapshot_id),None)
    if selected is None:
        raise ValueError('找不到所选快照，请重新读取数据')
    rows=[r for r in selected['rows'] if (status=='全部' or r['status']==status) and query.lower() in r['title'].lower()]
    if sort=='pub_date':
        rows.sort(key=lambda r:r['pub_date'],reverse=True)
    elif sort in ('plays','finish','likes'):
        rows.sort(key=lambda r:r[sort] if r[sort] is not None else -1,reverse=True)
    else:
        raise ValueError('排序方式无效')
    columns=[('title','作品名称'),('pub_date','发布时间'),('status','状态'),('plays','播放量'),('finish','完播率(%)'),('ctr5s','5秒完播率(%)'),('ctrcov','封面点击率(%)'),('bounce','2秒跳出率(%)'),('duration','平均播放时长(秒)'),('likes','点赞量'),('comments','评论量'),('favorites','收藏量'),('shares','分享量'),('profile_visits','主页访问量'),('follower_gain','作品归因涨粉')]
    def safe(value):
        if value is None:return ''
        text=str(value)
        return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text
    buf=io.StringIO(newline='');writer=csv.writer(buf)
    writer.writerow([name for _,name in columns])
    for row in rows:writer.writerow([safe(row[key]) for key,_ in columns])
    return ('\ufeff'+buf.getvalue()).encode('utf-8'),f'作品数据_{selected["capture_time"][:10]}.csv'

def import_file(content, name):
    if not content or len(content)>MAX_UPLOAD:
        raise ValueError('文件为空或超过 10 MB')
    suffix = Path(name).suffix.lower()
    if suffix == '.json':
        document = json.loads(content.decode('utf-8-sig'))
        if not isinstance(document,dict):
            raise ValueError('JSON 顶层必须是对象')
        rows = normalize(document)
        timestamp = str(document.get('capture_time') or now())
        datetime.strptime(timestamp,'%Y-%m-%d %H:%M:%S')
        kind = document.get('time_kind','capture' if document.get('capture_time') else 'import')
        if kind not in ('capture','import'):
            raise ValueError('时间类型无效')
    elif suffix == '.xlsx':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if sum(e.file_size for e in z.infolist())>80*1024*1024:
                raise ValueError('Excel 解压体积过大')
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(content),read_only=True,data_only=True)
        sheet = book.active
        if sheet.max_row>20001 or sheet.max_column>100:
            raise ValueError('Excel 超过 20000 行或 100 列')
        cells = sheet.iter_rows(values_only=True)
        headers = [str(c).strip() if c is not None else '' for c in next(cells)]
        required = {'作品名称','发布时间','审核状态','播放量'}
        if not required.issubset(headers):
            raise ValueError('请选择抖音「作品列表」导出的 Excel，缺少必要表头')
        raw = [dict(zip(headers,r)) for r in cells if any(c is not None for c in r)]
        book.close()
        rows = normalize({'raw_rows':raw})
        timestamp, kind = now(), 'import'
    else:
        raise ValueError('仅支持 .xlsx 和 TzFilm .json 文件')
    # Preserve semantic deduplication across original captures and repeated imports.
    existing, _ = snapshots()
    fingerprint = json.dumps(rows,ensure_ascii=False,sort_keys=True)
    for snap in existing:
        if json.dumps(snap['rows'],ensure_ascii=False,sort_keys=True)==fingerprint:
            return {'duplicate':True,'snapshot_id':snap['id'],'message':'这些作品数据已经在看板中，无需重复导入。'}
    normalized = {'capture_time':timestamp,'time_kind':kind,'source_kind':'import',
                  'source_name':Path(name).name,'parsed_rows':rows}
    IMPORTS.mkdir(mode=0o700,parents=True,exist_ok=True)
    key = hashlib.sha256(content).hexdigest()[:16]
    target = IMPORTS/f'import-{timestamp.replace(":", "").replace(" ", "-")}-{key}.json'
    temp = target.with_suffix('.tmp')
    with open(temp,'w',encoding='utf-8') as stream:
        os.chmod(temp,0o600)
        json.dump(normalized,stream,ensure_ascii=False,indent=2,allow_nan=False)
    temp.replace(target)
    return {'duplicate':False,'snapshot_id':target.stem,'message':f'已导入 {len(rows)} 条作品。','time_kind':kind}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)

    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        super().end_headers()

    def allowed(self):
        host = self.headers.get('Host','').split(':')[0]
        origin = self.headers.get('Origin')
        if host not in ('127.0.0.1','localhost'):
            return False
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.port not in (8766,4186):
                return False
        return True

    def respond(self,document,status=200):
        content = json.dumps(document,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if not self.allowed():
            return self.respond({'error':'仅允许本机访问'},403)
        path = urlsplit(self.path).path
        if path == '/api/comments':
            from comments import Console
            return self.respond(Console(STATE).view())
        if path == '/api/data':
            return self.respond(payload())
        if path == '/api/health':
            return self.respond({'ok':True,'service':'azu-douyin-studio','version':'1.4.0','research':True,'creator_sync':True,'manual_review':True})
        if path.startswith('/api/work-covers/'):
            from work_covers import asset
            try:
                file,mime=asset(STATE,path.rsplit('/',1)[-1]);content=file.read_bytes()
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','private, max-age=3600');self.end_headers();self.wfile.write(content)
            except (ValueError,OSError):self.respond({'error':'封面尚未取得'},404)
            return
        if path == '/api/work-reviews':
            from work_review import reports
            valid,_=snapshots()
            return self.respond({'reports':reports(STATE,valid)})
        if path == '/api/studio/status':
            from studio_jobs import view
            return self.respond(view(STATE))
        if path == '/api/research':
            from research import Research
            return self.respond(Research(STATE).view())
        if path.startswith('/api/research/media/'):
            from research import Research
            from research_media import asset
            try:
                parts=path.split('/')
                if len(parts)!=6:raise ValueError('媒体资源不存在')
                file,mime=asset(Research(STATE),parts[4],parts[5])
                content=file.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type',mime)
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Cache-Control','private, max-age=3600')
                self.send_header('Content-Length',str(len(content)))
                self.end_headers();self.wfile.write(content)
            except (ValueError,OSError):self.respond({'error':'媒体资源不存在'},404)
            return
        if path == '/api/research/export':
            from research import Research
            params=parse_qs(urlsplit(self.path).query)
            try:
                content,mime,name=Research(STATE).export(params.get('format',['json'])[0],params.get('task_id',[None])[0])
                self.send_response(200)
                self.send_header('Content-Type',mime)
                self.send_header('Content-Disposition','attachment; filename="'+name+'"')
                self.send_header('Content-Length',str(len(content)))
                self.end_headers();self.wfile.write(content)
            except (ValueError,OSError) as exc:
                self.respond({'error':str(exc)},400)
            return
        if path == '/api/export':
            params=parse_qs(urlsplit(self.path).query)
            try:
                content,name=export_csv(params.get('snapshot',[''])[0],params.get('status',['公开'])[0],params.get('query',[''])[0],params.get('sort',['pub_date'])[0])
                self.send_response(200)
                self.send_header('Content-Type','text/csv; charset=utf-8')
                self.send_header('Content-Disposition',"attachment; filename=works.csv; filename*=UTF-8''"+quote(name))
                self.send_header('Content-Length',str(len(content)))
                self.end_headers();self.wfile.write(content)
            except ValueError as exc:
                self.respond({'error':str(exc)},400)
            return
        if path.startswith('/api/'):
            return self.respond({'error':'接口不存在'},404)
        return super().do_GET()

    def do_POST(self):
        if not self.allowed():
            return self.respond({'error':'仅允许本机访问'},403)
        path = urlsplit(self.path).path
        if path.startswith('/api/studio/'):
            if self.headers.get('Origin') not in ('http://127.0.0.1:8766','http://localhost:8766','http://127.0.0.1:4186','http://localhost:4186') or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.respond({'error':'请从本人本地创作台操作'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=65536:return self.respond({'error':'请求大小无效'},413)
                document=json.loads(self.rfile.read(length))
                if not isinstance(document,dict):raise ValueError('请求格式无效')
                from studio_jobs import start
                return self.respond(start(STATE,path.rsplit('/',1)[-1],request=document))
            except (ValueError,TypeError) as exc:return self.respond({'error':str(exc)},400)
            except Exception:return self.respond({'error':'任务启动失败，原数据已保留。'},500)
        if path=='/api/research/media-upload':
            if self.headers.get('Origin') not in ('http://127.0.0.1:8766','http://localhost:8766','http://127.0.0.1:4186','http://localhost:4186') or self.headers.get('Content-Type','').split(';')[0]!='application/octet-stream':
                return self.respond({'error':'请通过本地研究页面导入文件'},403)
            try:
                from research import Research
                from research_media import receive_upload,MAX_UPLOAD as MEDIA_UPLOAD_LIMIT
                from urllib.parse import unquote
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=MEDIA_UPLOAD_LIMIT:return self.respond({'error':'文件需非空且不超过500 MB'},413)
                self.connection.settimeout(120)
                return self.respond(receive_upload(Research(STATE),self.rfile,length,unquote(self.headers.get('X-Filename','')),self.headers.get('X-Item-ID','')))
            except (ValueError,TypeError) as exc:return self.respond({'error':str(exc)},400)
            except Exception:return self.respond({'error':'文件未完整导入，原有资料已保留。'},400)
        if path.startswith('/api/research/'):
            if self.headers.get('Origin') not in ('http://127.0.0.1:8766','http://localhost:8766','http://127.0.0.1:4186','http://localhost:4186') or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.respond({'error':'请通过本地研究页面操作'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=6*1024*1024:
                    return self.respond({'error':'请求大小超限'},413)
                request=json.loads(self.rfile.read(length))
                if not isinstance(request,dict):raise ValueError('请求需要是对象')
                from research import Research
                return self.respond(Research(STATE).dispatch(path.rsplit('/',1)[-1],request))
            except (ValueError,TypeError,KeyError) as exc:
                return self.respond({'error':str(exc)},400)
            except Exception:
                return self.respond({'error':'研究操作未完成，原有数据已保留。'},500)
        if path.startswith('/api/comments/'):
            # Mutation requests must originate in our UI, not cross-site forms.
            if self.headers.get('Origin') not in ('http://127.0.0.1:8766','http://localhost:8766','http://127.0.0.1:4186','http://localhost:4186') or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.respond({'error':'请通过本地评论页面操作'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=100000: raise ValueError('请求大小无效')
                request=json.loads(self.rfile.read(length))
                if not isinstance(request,dict): raise ValueError('请求格式无效')
                valid,_=snapshots()
                works=valid[0]['rows'] if valid else []
                from comments import dispatch
                result=dispatch(STATE,path.rsplit('/',1)[-1],request,works)
                return self.respond(result)
            except (ValueError,TypeError,KeyError) as exc:
                return self.respond({'error':str(exc)},400)
            except Exception:
                return self.respond({'error':'评论操作未完成，请查看本地日志。'},500)
        if path != '/api/import':
            return self.respond({'error':'接口不存在'},404)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length<=0 or length>MAX_UPLOAD:
                return self.respond({'error':'请选择 10 MB 以内的非空文件'},413)
            from urllib.parse import unquote
            name = unquote(self.headers.get('X-Filename',''))
            result = import_file(self.rfile.read(length),name)
            self.respond(result)
        except (ValueError,UnicodeError,zipfile.BadZipFile,StopIteration,KeyError,TypeError) as exc:
            self.respond({'error':str(exc) or '文件格式无法识别'},400)
        except Exception:
            self.respond({'error':'导入失败，请检查文件是否为完整的抖音作品导出文件。'},400)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8766)
    args = parser.parse_args()
    from research import Research
    Research(STATE).recover()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'阿祖 · 抖音创作台 http://127.0.0.1:{args.port}',flush=True)
    server.serve_forever()
