"""Opt-in live evaluation; shares the persistent application budget. No raw chats logged."""
import argparse
import asyncio
import json
import time
from pathlib import Path

from app.ai import SYSTEM, TOOL, completion
from app.config import settings


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-paid',action='store_true')
    parser.add_argument('--all-candidates',action='store_true')
    parser.add_argument('--resume')
    args=parser.parse_args()
    if not args.run_paid:
        raise SystemExit('Pass --run-paid to run bounded paid evaluation')
    questions=json.loads(Path('tests/evals/golden.json').read_text())
    models=['deepseek/deepseek-v3.2']
    if args.all_candidates:
        models+=['google/gemini-2.5-flash','google/gemini-2.5-pro','anthropic/claude-sonnet-4.5']
        questions=questions[:3]
    report=[r for r in json.loads(Path(args.resume).read_text())["results"] if "error_type" not in r] if args.resume else []
    for model in models:
        settings().openrouter_model=model
        for case in questions:
            if any(r["model"]==model and r["case_id"]==case["id"] for r in report):
                continue
            start=time.monotonic()
            try:
                result=await completion([{'role':'system','content':SYSTEM},{'role':'user','content':case['prompt']}],True)
                calls=result.get('tool_calls') or []
                operations=[json.loads(c['function']['arguments'])['operation'] for c in calls if c['function']['name']=='analytics']
                expected=case['expected_operation']
                passed=expected in operations if expected not in ('refuse','clarify') else not calls
                record={'case_id':case['id'],'model':model,'operations':operations,'expected':expected,'tool_selection_pass':passed,'latency_seconds':time.monotonic()-start}
            except Exception as exc:
                record={'case_id':case['id'],'model':model,'error_type':type(exc).__name__,'tool_selection_pass':False,'latency_seconds':time.monotonic()-start}
                if 'budget' in str(exc).lower():
                    report.append(record)
                    break
            report.append(record)
            print(json.dumps(record),flush=True)
    target=Path('/tmp/model-evaluation.json')
    target.write_text(json.dumps({'scope':'Tool-selection-only; not end-to-end answer quality','results':report},indent=2))


if __name__=='__main__':
    asyncio.run(main())
