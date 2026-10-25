"""Reject dependency conflicts introduced beyond those in the pinned serving base."""
import json,subprocess
from pathlib import Path
root=Path('/opt/tokenlabs')
before={s.strip() for s in (root/'base-pip-check.txt').read_text().splitlines() if s.strip() and s.strip()!='No broken requirements found.'}
r=subprocess.run(['python3','-m','pip','check'],capture_output=True,text=True)
after={s.strip() for s in r.stdout.splitlines() if s.strip() and s.strip()!='No broken requirements found.'}
report={'passed':not(after-before),'existing_conflicts':sorted(before),'introduced_conflicts':sorted(after-before)}
(root/'dependency-check.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
if not report['passed']:raise SystemExit('New dependency conflicts in Flint runtime')
