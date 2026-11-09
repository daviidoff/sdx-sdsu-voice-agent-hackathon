"""Snapshot evaluation/application source without credentials or live data.

Build frontend inside this snapshot to avoid mixing concurrently edited sources.
Use EVAL_CREDENTIALS_FILE to read the original .env without copying it.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from evaluation.backend import ROOT


def freeze(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Use a new destination; never overwrite an existing baseline')
    files = []
    for folder in ('app','evaluation','protocols','frontend','web/src'):
        for path in (ROOT/folder).rglob('*'):
            relative = path.relative_to(ROOT)
            if path.is_file() and not path.is_symlink() and not any(p in {'node_modules','dist','__pycache__','.git','.runtime'} for p in relative.parts) and path.suffix in {'.py','.ts','.tsx','.mjs','.js','.json','.css','.html','.svg','.png','.woff2','.md'}:
                files.append(path)
    files += [ROOT/'scripts/configure_elevenlabs.py',ROOT/'test cases.md']
    digests = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        destination.mkdir(parents=True)
        for path in files:
            target = destination/path.relative_to(ROOT)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target)
        for name, digest in digests.items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest or hashlib.sha256((destination/name).read_bytes()).hexdigest()!=digest:
                raise RuntimeError('Source changed while copying; retry with a new snapshot')
        # Dependencies are reused only for building; actual compiled assets are local.
        (destination/'frontend/node_modules').symlink_to(ROOT/'frontend/node_modules',target_is_directory=True)
        manifest = {'created_at':datetime.now(timezone.utc).isoformat(),'source_root':str(ROOT),
                    'source_sha256':digests,'notice':'Source copied consistently; frontend must be built here. Credentials and live data excluded.'}
        (destination/'evaluation-source-manifest.json').write_text(json.dumps(manifest,indent=2))
    except Exception:
        shutil.rmtree(destination,ignore_errors=True)
        raise
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    print(freeze(args.output))
