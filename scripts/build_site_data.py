#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'manifests' / 'project_inventory.json'
OUT = ROOT / 'manifests' / 'deployment_map.yaml'

def main():
    projects = json.loads((SRC).read_text(encoding='utf-8')).get('projects', [])
    print('projects=', len(projects))
    for p in projects:
        print('-', p['project_slug'], p['project_title'])

if __name__ == '__main__':
    main()
