"""Run in the already-installed bili-cli SDK environment; public read-only search."""
import asyncio
import html
import json
import re
import sys
import time

async def collect(keyword,limit):
    from bilibili_api import search,video,request_settings
    request_settings.set_wbi_retry_times(1)  # One attempt; no retry after a challenge.
    request_settings.set('timeout',10)
    data=await search.search_by_type(keyword=keyword,search_type=search.SearchObjectType.VIDEO,
                                    order_type=search.OrderVideo.CLICK,page=1,page_size=limit)
    items=[];deadline=time.monotonic()+45
    for row in data.get('result',[])[:limit]:
        ident=row.get('bvid','')
        if not re.fullmatch(r'BV[0-9A-Za-z]{10}',ident):continue
        item={'url':'https://www.bilibili.com/video/'+ident,'title':html.unescape(re.sub('<[^>]*>','',row.get('title',''))),
              'author':row.get('author'),'cover':row.get('pic'),'raw':{'play':row.get('play')}}
        if time.monotonic()<deadline:
            info=await video.Video(bvid=ident).get_info()
            item.update(title=info.get('title') or item['title'],author=(info.get('owner') or {}).get('name') or item['author'],
                        cover=info.get('pic') or item['cover'],text=info.get('desc'),published_at=info.get('pubdate'),raw={'stat':info.get('stat') or {}})
        items.append(item)
    return {'ok':True,'backend':'bilibili-installed-sdk-public','items':items}

if __name__=='__main__':
    try:
        result=asyncio.run(collect(sys.argv[1],int(sys.argv[2])))
    except Exception as exc:
        code=getattr(exc,'code',None)
        name=type(exc).__name__
        result={'ok':False,'error':{'code':'PLATFORM_BLOCKED' if code in (403,412,-403,-412,-352) or 'WbiRetry' in name else 'RATE_LIMITED' if code in (429,-509) else 'UPSTREAM_BROKEN'}}
    print(json.dumps(result,ensure_ascii=False))
