"""Build a guarded private runtime; leave the installed upstream source unchanged."""
from pathlib import Path
import shutil


def replace_once(source,old,new):
    if source.count(old)!=1:
        raise ValueError('评论模块版本已变化，安全适配未通过；已停止发送。')
    return source.replace(old,new)


def prepare(module,root):
    runtime=Path(root)/'runtime'
    if runtime.exists(): shutil.rmtree(runtime)
    runtime.mkdir(mode=0o700)
    shutil.copytree(Path(module)/'src',runtime/'src')
    (runtime/'node_modules').symlink_to(Path(module)/'node_modules',target_is_directory=True)
    (runtime/'package.json').write_text('{"type":"module","private":true}')
    license=Path(module).parent/'LICENSE'
    if license.is_file(): shutil.copy2(license,runtime/'LICENSE')
    workflow=runtime/'src/comment-workflow.mjs'
    text=workflow.read_text()
    anchor='    console.log(`已选中作品：${getSelectedWorkOutput(targetWork).title}`);\n    const replySummary = await replyToComments(page, {'
    guard='''    const actualTitle = String(getSelectedWorkOutput(targetWork).title).replace(/\\s+/g, "");
    const expectedTitle = String(selectedWorkHint.title).replace(/\\s+/g, "");
    if (actualTitle !== expectedTitle) throw new Error("作品完整标题不一致，拒绝发送。");
    const actualPublish = String(getSelectedWorkOutput(targetWork).publishText || "").replace(/\\s+/g, "");
    const expectedPublish = String(selectedWorkHint.publishText || "").replace(/\\s+/g, "");
    if (!expectedPublish || actualPublish !== expectedPublish) throw new Error("作品发布时间不一致，拒绝发送。");
'''
    text=replace_once(text,anchor,guard+anchor)
    workflow.write_text(text)
    flow=runtime/'src/lib/reply-flow.mjs';text=flow.read_text()
    text=replace_once(text,'const requireCommentMatch = remainingPlanCount > 1 || visibleCommentCount > 1;','const requireCommentMatch = true; // Require full comment as well as username.')
    text=replace_once(text,'normalizedLeft === normalizedRight ||\n    normalizedLeft.includes(normalizedRight) ||\n    normalizedRight.includes(normalizedLeft)','normalizedLeft === normalizedRight')
    text=replace_once(text,'if (isResolvedReplyStatus(replyResult.status)) {','if (true) { // Never retry a possibly submitted comment inside the same job.')
    flow.write_text(text)
    return runtime
