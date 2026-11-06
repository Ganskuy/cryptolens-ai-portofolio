"""Explicit opt-in paid smoke check. App admission is the authoritative token gate."""
import argparse
import json
import time
import uuid

import httpx

parser=argparse.ArgumentParser()
parser.add_argument('--run-paid',action='store_true')
args=parser.parse_args()
if not args.run_paid:
    raise SystemExit('Use --run-paid to authorize a paid smoke request')
start=time.monotonic()
events=[]
with httpx.Client(timeout=120) as client:
    client.get('http://localhost:8100/api/v1/health/ready')
    with client.stream('POST','http://localhost:8100/api/v1/ai/chat/stream',json={'message':'Analyze Bitcoin historical risk over ninety days. Use risk metrics and cite the dataset.','request_id':str(uuid.uuid4())}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('data: '):
                event=json.loads(line[6:])
                events.append(event)
                print(event['stage'],flush=True)
report={'latency_seconds':time.monotonic()-start,'events':events}
with open('docs/live-ai-smoke.json','w') as f: json.dump(report,f,indent=2)
print('Outcome:',events[-1]['stage'])
