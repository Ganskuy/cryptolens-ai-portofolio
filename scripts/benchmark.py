"""Bounded local latency probe. Does not invoke AI or trading endpoints."""
import json
import statistics
import time
import urllib.request

results = {}
for path in ['/api/v1/market/overview', '/api/v1/analytics/risk?asset_id=bitcoin&days=90']:
    durations = []
    for _ in range(20):
        start = time.perf_counter()
        with urllib.request.urlopen('http://localhost:8100'+path, timeout=10) as response:
            response.read()
        durations.append((time.perf_counter()-start)*1000)
    results[path] = {'samples':len(durations),'p50_ms':statistics.median(durations),'p95_ms':sorted(durations)[18],'max_ms':max(durations)}
print(json.dumps(results,indent=2))
