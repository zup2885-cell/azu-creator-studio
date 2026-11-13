"""Read media comments without modifying upstream or the guarded send runtime."""
from pathlib import Path
import shutil

from comment_runtime import replace_once


def prepare(module,root):
    module=Path(module);runtime=Path(root)/'export-runtime'
    if runtime.exists():shutil.rmtree(runtime)
    runtime.mkdir(mode=0o700)
    shutil.copytree(module/'src',runtime/'src')
    (runtime/'node_modules').symlink_to(module/'node_modules',target_is_directory=True)
    (runtime/'package.json').write_text('{"type":"module","private":true}')
    if (module.parent/'LICENSE').is_file():shutil.copy2(module.parent/'LICENSE',runtime/'LICENSE')
    snapshot=runtime/'src/lib/comment-snapshot.mjs';text=snapshot.read_text()
    begin='    const collectViaContentSelectors = () => {'
    end='\n    const collectViaBlocks = () =>'
    if text.count(begin)!=1 or text.count(end)!=1:raise ValueError('评论读取模块已变化，图片适配未通过。')
    start=text.index(begin);finish=text.index(end,start)
    text=text[:start]+Path(__file__).with_name('comment_media_extractor.js').read_text().rstrip()+text[finish:]
    text=replace_once(text,'        signature: currentMainComment.signature,',
        '        mediaOnly: currentMainComment.mediaOnly,\n        mediaKeys: currentMainComment.mediaKeys,\n        signature: currentMainComment.signature,')
    text=replace_once(text,'          imageUrls: entry.imageUrls,',
        '          imageUrls: entry.imageUrls,\n          mediaOnly: entry.mediaOnly,\n          mediaKeys: entry.mediaKeys,')
    snapshot.write_text(text)
    workflow=runtime/'src/comment-workflow.mjs';text=workflow.read_text()
    # Keep this export read-only: record media identities, never download or send them.
    download='    await downloadCommentImages(exportComments, outputPath);'
    if text.count(download)!=2:raise ValueError('评论导出模块已变化，已停止读取。')
    text=text.replace(download,'    // Media identities are sufficient for a manual-review entry.')
    start=text.index('export async function exportUnrepliedComments(')
    finish=text.index('export async function exportAllComments(',start)
    section=text[start:finish]
    section=replace_once(section,'        count: exportComments.length,',
        '''        count: exportComments.length,
        fetchedAt: new Date().toISOString(),
        collection: {scope:"selected_work_unreplied", scanned:comments.length,
          exported:exportComments.length, filteredByHistory:skipped,
          mediaOnly:exportComments.filter(c => c.mediaOnly).length,
          replyThreadsExpanded:false},''')
    section=replace_once(section,'            username: comment.username,',
        '''            mediaOnly: comment.mediaOnly === true,
            mediaKeys: comment.mediaKeys || [],
            publishText: comment.publishText || "",
            username: comment.username,''')
    workflow.write_text(text[:start]+section+text[finish:])
    output=runtime/'src/lib/result-store.mjs';text=output.read_text()
    old=r'    const key = `${String(entry.username ?? "")}\u0000${String(entry.commentText ?? "")}`;'
    text=replace_once(text,old,old+'\n    const mediaKey = entry.mediaOnly ? "\\u0000" + JSON.stringify([...(entry.mediaKeys || [])].sort()) : "";')
    # The upstream final serializer otherwise merges distinct pictures by username.
    text=replace_once(text,'    if (seen.has(key)) {','    if (seen.has(key + mediaKey)) {')
    text=replace_once(text,'    seen.add(key);','    seen.add(key + mediaKey);')
    text=replace_once(text,'    nextResult.comments = dedupedComments.entries;',
        '''    nextResult.comments = dedupedComments.entries;
    if (nextResult.collection) nextResult.collection = {...nextResult.collection,
      exported:nextResult.comments.length, mediaOnly:nextResult.comments.filter(c => c.mediaOnly).length};''')
    output.write_text(text)
    return runtime
