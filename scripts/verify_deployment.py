#!/usr/bin/env python3
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

def main():
    # Minimal presence checks for deliverable completeness
    required = [
        ROOT / 'index.html',
        ROOT / 'projects' / 'casuallab' / 'index.html',
        ROOT / 'projects' / 'macroeconomics' / 'index.html',
        ROOT / 'casuallab' / 'project.yaml',
        ROOT / 'macroeconomics' / 'project.yaml',
        ROOT / 'casuallab' / 'README.md',
        ROOT / 'macroeconomics' / 'README.md',
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f'Verification failed, missing {missing}')
    print('verify-ok')

if __name__ == '__main__':
    main()
