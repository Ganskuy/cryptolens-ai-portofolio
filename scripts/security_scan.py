"""Scan the exact tracked/staged manifest without printing suspected secret values."""
import re
import subprocess
from pathlib import Path

files=subprocess.check_output(['git','ls-files','--cached','-z']).decode().split('\0')
patterns=[re.compile(rb'sk-or-v1-[A-Za-z0-9]{20,}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{20,}'),re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
errors=[]
for filename in filter(None,files):
    path=Path(filename)
    if not path.is_file():continue
    if path.name=='.env' or filename.startswith(('.venv/','node_modules/')):errors.append((filename,'excluded file'))
    if path.stat().st_size>50*1024*1024:errors.append((filename,'oversized artifact'))
    data=path.read_bytes()
    if any(p.search(data) for p in patterns):errors.append((filename,'credential pattern'))
for name,reason in errors:print(name+': '+reason)
print(f'Scanned {sum(bool(x) for x in files)} manifest entries; violations: {len(errors)}')
raise SystemExit(bool(errors))
