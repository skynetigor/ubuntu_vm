#!/usr/bin/env python3
# Upserts Kibana workflows from a directory of YAML files.
#
# Required env vars:
#   WORKFLOWS_DIR   — path to directory containing *.yml / *.yaml workflow files
#
# Optional env vars (read from kibana/.env if present):
#   KIBANA_URL      — default: http://localhost:5601
#   KIBANA_USERNAME — default: elastic
#   KIBANA_PASSWORD — default: changeme
import base64, json, os, sys, urllib.error, urllib.request
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

def load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip()

KIBANA_DIR = Path(__file__).resolve().parent.parent
load_dotenv(KIBANA_DIR / '.env')

WORKFLOWS_DIR = os.environ.get('WORKFLOWS_DIR', '')
if not WORKFLOWS_DIR:
    print("No WORKFLOWS_DIR set. Skipping.")
    sys.exit(0)

KIBANA_URL      = os.environ.get('KIBANA_URL',      'http://localhost:5601').rstrip('/')
KIBANA_USERNAME = os.environ.get('KIBANA_USERNAME', 'elastic')
KIBANA_PASSWORD = os.environ.get('KIBANA_PASSWORD', 'changeme')

_AUTH = base64.b64encode(f'{KIBANA_USERNAME}:{KIBANA_PASSWORD}'.encode()).decode()
_HEADERS = {
    'Authorization':            f'Basic {_AUTH}',
    'kbn-xsrf':                 'true',
    'x-elastic-internal-origin': 'Kibana',
    'Content-Type':             'application/json',
}

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(KIBANA_URL + path, data=data, headers=_HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{method} {path} → HTTP {e.code}: {e.read().decode()}')

# ── Fetch existing workflows (paginated) ──────────────────────────────────────

def fetch_all_workflows():
    by_name, page = {}, 1
    while True:
        resp    = api('POST', '/api/workflows/search', {'size': 100, 'page': page, 'query': ''})
        results = resp.get('results', [])
        for w in results:
            by_name[w['name']] = w['id']
        if page >= resp.get('total', 1) or not results:
            break
        page += 1
    return by_name

def delete_if_exists(workflow_id):
    try:
        api('DELETE', f'/api/workflows/{workflow_id}')
    except RuntimeError as e:
        if 'HTTP 404' not in str(e):
            raise

def extract_field(lines, field):
    prefix = f'{field}:'
    return next(
        (l[len(prefix):].strip().strip('"\'') for l in lines if l.startswith(prefix)),
        None,
    )

def strip_id(raw_yaml):
    return '\n'.join(l for l in raw_yaml.splitlines() if not l.startswith('id:'))

# ── Main ──────────────────────────────────────────────────────────────────────

workflow_files = sorted(
    p for p in Path(WORKFLOWS_DIR).iterdir()
    if p.suffix in ('.yml', '.yaml')
)
if not workflow_files:
    print(f"No YAML files found in {WORKFLOWS_DIR}. Skipping.")
    sys.exit(0)

print(f"=== Fetching existing workflows from {KIBANA_URL} ===")
existing_by_name = fetch_all_workflows()
print(f"    Found {len(existing_by_name)} existing workflow(s)")

errors = 0
for path in workflow_files:
    raw_yaml = path.read_text()
    lines    = raw_yaml.splitlines()

    wf_id = extract_field(lines, 'id')
    name  = extract_field(lines, 'name')

    if not name:
        print(f"ERROR [{path.name}]: no top-level 'name:' field found", file=sys.stderr)
        errors += 1
        continue

    try:
        if wf_id:
            print(f"=== Replacing by id ({wf_id}): {name} ===")
            delete_if_exists(wf_id)
        elif name in existing_by_name:
            print(f"=== Replacing by name: {name} ===")
            api('DELETE', f'/api/workflows/{existing_by_name[name]}')
        else:
            print(f"=== Creating: {name} ===")

        result = api('POST', '/api/workflows', {'yaml': strip_id(raw_yaml)})
        print(f"    id: {result.get('id')}")
    except Exception as e:
        print(f"ERROR [{name}]: {e}", file=sys.stderr)
        errors += 1

print("=== Done ===")
sys.exit(1 if errors else 0)
