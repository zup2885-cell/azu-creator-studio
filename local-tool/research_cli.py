#!/usr/bin/env python3
"""Bridge the current Codex conversation to frozen research tasks. No model API."""
import argparse
import json
import os
from pathlib import Path
from research import Research

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='阿祖研究工作台 · Codex 分析桥接')
    parser.add_argument('action', choices=['pending', 'context', 'finish','discover'])
    parser.add_argument('--scheduled',action='store_true')
    parser.add_argument('task_id', nargs='?')
    parser.add_argument('report', nargs='?')
    args = parser.parse_args()
    state = Path(os.environ.get('DOUYIN_STATE_DIR', str(Path.home() / 'Library/Application Support/TzFilmDouyin')))
    research = Research(state)
    if args.action=='discover':
        from research_discovery import start_discovery
        result=start_discovery(research,{'scheduled':args.scheduled},background=False)
        print(json.dumps(research.task(result['task_id']) if result.get('task_id') else result,ensure_ascii=False))
    elif args.action == 'pending':
        print(json.dumps([t for t in research.view()['tasks'] if t['status'] == 'awaiting_codex'], ensure_ascii=False, indent=2))
    elif args.action == 'context':
        task = research.task(args.task_id)
        if task['kind'] != 'analysis':
            parser.error('此任务不是分析任务')
        print((research.root / 'analysis-inputs' / f'{args.task_id}.md').read_text())
    else:
        if not args.report:
            parser.error('需要提供报告 JSON 的本地路径')
        print(json.dumps(research.finish(args.task_id, json.loads(Path(args.report).read_text())), ensure_ascii=False))
