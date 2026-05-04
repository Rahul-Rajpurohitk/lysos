import json, re, sys
sys.path.insert(0, '/Users/rahulrajpurohit/IdeaProjects/lysos')
from datasets import load_from_disk
from collections import Counter

ds = load_from_disk('/Users/rahulrajpurohit/IdeaProjects/lysos/data/processed/amr-stage2-pro-v3')
PATTERNS = {
    'designer_proposal':     re.compile(r'\bPROPOSAL:\s*\S', re.IGNORECASE),
    'designer_rationale':    re.compile(r'\bRATIONALE:', re.IGNORECASE),
    'critic_weakness':       re.compile(r'\bWEAKNESS:', re.IGNORECASE),
    'critic_transform':      re.compile(r'\bTRANSFORMATION:', re.IGNORECASE),
    'critic_delta':          re.compile(r'\bEXPECTED_DELTA:', re.IGNORECASE),
    'critic_verdict':        re.compile(r'\bVERDICT:\s*ACCEPT', re.IGNORECASE),
    'strategist_decision':   re.compile(r'\bDECISION:\s*(TERMINATE|CONTINUE|BRANCH)', re.IGNORECASE),
    'resistome_briefing':    re.compile(r'resistome|resistance gene|Pathogen briefing', re.IGNORECASE),
    'tool_use_block':        re.compile(r'tool_use'),
}
counts = Counter()
n = 0
for split in ['train','valid']:
    for row in ds[split]:
        n += 1
        msgs = row['messages']
        if isinstance(msgs, str):
            try: msgs = json.loads(msgs)
            except: continue
        text = ''
        for m in msgs:
            c = m.get('content')
            if isinstance(c, str): text += c + '\n'
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict):
                        text += json.dumps(b)[:1500] + '\n'
        for name, pat in PATTERNS.items():
            if pat.search(text): counts[name] += 1
print(f'Scanned {n:,} rows.')
print(f'{"Pattern":<26} {"Count":>10} {"%":>7}')
print('-'*46)
for name in PATTERNS:
    c = counts[name]
    pct = 100.0 * c / max(1,n)
    print(f'{name:<26} {c:>10,} {pct:>6.2f}%')
