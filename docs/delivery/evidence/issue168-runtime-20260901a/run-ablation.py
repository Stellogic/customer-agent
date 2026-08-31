import json
import os
import platform
from pathlib import Path
from baseline_agent.knowledge_ablation import run_layered_ablation

out = Path(os.environ['ISSUE168_OUTPUT'])
for repeat in range(3):
    report = run_layered_ablation(
        os.environ['ISSUE168_BASE_URL'],
        environment={'python': platform.python_version(), 'platform': platform.platform(),
                     'head_sha': os.environ['ISSUE168_HEAD'], 'base_sha': os.environ['ISSUE168_BASE'],
                     'repeat': repeat, 'source': 'live Spring/PostgreSQL/BGE'},
        parameters={'candidate_limit': 20, 'rrf_k': 60, 'top_k': 5, 'repeat': repeat},
        output=out / f'ablation-{repeat}.json',
    )
    print(json.dumps({'repeat': repeat, 'status': report['status'],
          'modes': {name: {'status': mode['status'], 'metrics': mode['metrics'],
                           'count': len(mode['rows'])} for name, mode in report['modes'].items()}},
          ensure_ascii=False), flush=True)
