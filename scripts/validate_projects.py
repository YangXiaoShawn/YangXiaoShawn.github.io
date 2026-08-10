#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANDATORY = [
    ROOT / 'manifests' / 'project_inventory.json',
    ROOT / 'manifests' / 'asset_inventory.csv',
    ROOT / 'manifests' / 'publication_rights.csv',
]
BANNED_DIRS = {'raw', 'artifacts', 'generated', 'tmp'}


def _has_banned_under(path: Path) -> list:
    bad = []
    if not path.exists():
        return bad
    for p in path.rglob('*'):
        if p.is_dir() and p.name in BANNED_DIRS:
            bad.append(str(p))
    return bad


def main():
    mandatory_missing = [str(p) for p in MANDATORY if not p.exists()]
    for rel in ['upload_ready/casuallab', 'upload_ready/macroeconomics', 'casuallab', 'macroeconomics']:
        p = ROOT / rel
        if not p.exists():
            mandatory_missing.append(f'{rel} (upload-ready project copy)')
    bad_dirs = []
    for rel in ['upload_ready/casuallab', 'upload_ready/macroeconomics', 'casuallab', 'macroeconomics']:
        bad_dirs.extend(_has_banned_under(ROOT / rel))
    if bad_dirs:
        bad_dirs = [f'BANNED_DIR:{p}' for p in bad_dirs]
    missing = mandatory_missing + bad_dirs
    if missing:
        raise SystemExit(f'Missing files: {missing}')
    print('validation-ok')

if __name__ == '__main__':
    main()
