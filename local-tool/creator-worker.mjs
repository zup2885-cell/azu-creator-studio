// Use this application's own existing creator login; never copy browser credentials.
import {chromium} from '/Users/m3air/GitHub/skills/tzfilm-douyin-tool/auto-reply/node_modules/playwright/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
const args=Object.fromEntries(process.argv.slice(2).reduce((out,value,index,all)=>{if(index%2===0)out.push([value.replace(/^--/,''),all[index+1]]);return out},[]));
const mode=args.mode||'sync';
if(!['sync','auth','covers'].includes(mode)||!args.state)throw new Error('Invalid collection arguments');
const state=path.resolve(args.state);
const emit=value=>console.log(JSON.stringify(value));
let context;
try {
  context=await chromium.launchPersistentContext(path.join(state,'browser/comment-profile'),{headless:mode!=='auth',viewport:{width:1440,height:900},acceptDownloads:true});
  const page=context.pages()[0]||await context.newPage();
  const metadata=[],pending=[];
  const visit=(value,depth=0)=>{
    if(!value||typeof value!=='object'||depth>9)return;
    if(Array.isArray(value)){value.slice(0,200).forEach(v=>visit(v,depth+1));return}
    const video=value.video||{},cover=video.cover?.url_list?.[0]||video.origin_cover?.url_list?.[0]||value.cover?.url_list?.[0];
    if(typeof value.desc==='string'&&cover&&value.create_time){metadata.push({title:value.desc,pub_date:new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Number(value.create_time)*1000)),cover,video_id:String(value.aweme_id||'')});return}
    Object.values(value).slice(0,100).forEach(v=>visit(v,depth+1));
  };
  page.on('response',r=>{if(!r.url().startsWith('https://creator.douyin.com/')||!r.headers()['content-type']?.includes('json'))return;pending.push((async()=>{try{const body=await r.body();if(body.length<3*1024*1024)visit(JSON.parse(body.toString()))}catch{}})())});
  await page.goto('https://creator.douyin.com/creator-micro/content/manage',{waitUntil:'domcontentloaded',timeout:45000});
  emit({phase:'checking',message:mode==='auth'?'请在专用浏览器中完成本人登录，登录成功后将自动保存。':'正在核实创作者中心登录与作品列表。'});
  const button=page.getByRole('button',{name:'导出数据',exact:true});
  try {await button.waitFor({state:'visible',timeout:mode==='auth'?180000:45000})}
  catch {
    const text=await page.locator('body').innerText().catch(()=>'');
    const diagnostics=path.join(state,'creator-sync/diagnostics');await fs.mkdir(diagnostics,{recursive:true,mode:0o700});
    await fs.writeFile(path.join(diagnostics,'last-page.json'),JSON.stringify({url:page.url(),text:text.slice(0,2500)},null,2),{mode:0o600});
    await page.screenshot({path:path.join(diagnostics,'last-page.png')}).catch(()=>{});
    if(/扫码登录|验证码登录|登录抖音创作者中心/.test(text)||/\/login(?:\?|$)/.test(page.url()))throw new Error('LOGIN_REQUIRED:抖音创作者登录需要本人确认，请点击“连接抖音账号”后扫码。');
    throw new Error('EXPORT_NOT_READY:作品列表未能加载完成，可能是网络、平台验证或登录状态待确认；旧数据已保留。');
  }
  if(mode==='auth'){
    emit({phase:'complete',authenticated:true,message:'本人创作者登录已保存，可采集作品数据。'});
  }else{
    // The export control can appear before the data rows. Wait for real rows.
    await page.waitForFunction(()=>/20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}/.test(document.body.innerText),{},{timeout:30000});
    await button.waitFor({state:'visible',timeout:5000});
    await Promise.allSettled(pending);
    const metadataFile=path.join(state,'creator-sync/work-metadata.json');
    await fs.writeFile(metadataFile,JSON.stringify(metadata),{mode:0o600});
    if(mode==='covers'){emit({phase:'complete',metadata_file:metadataFile,count:metadata.length,message:'已读取本人作品封面资料。'});}
    else{
    emit({phase:'downloading',message:'正在导出本人作品数据。'});
    const downloadPromise=page.waitForEvent('download',{timeout:45000});
    await button.click({timeout:10000});
    const download=await downloadPromise;
    if(await download.failure())throw new Error('作品文件下载失败，旧数据已保留。');
    const folder=path.join(state,'creator-sync/downloads');await fs.mkdir(folder,{recursive:true,mode:0o700});
    const target=path.join(folder,`作品列表-${Date.now()}.xlsx`);
    await download.saveAs(target);await fs.chmod(target,0o600);
    emit({phase:'complete',file:target,metadata_file:metadataFile,message:'作品列表已下载，正在校验并入库。'});
    }
  }
} catch(error){
  const value=String(error?.message||error);
  emit({phase:'failed',code:value.startsWith('LOGIN_REQUIRED:')?'LOGIN_REQUIRED':'COLLECTION_FAILED',message:value.startsWith('LOGIN_REQUIRED:')?value.slice(15):value.startsWith('EXPORT_NOT_READY:')?value.slice(17):'作品数据采集未完成。请检查登录、网络或平台验证；旧数据已保留。'});
  process.exitCode=1;
} finally {if(context)await context.close()}
