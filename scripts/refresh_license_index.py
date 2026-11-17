"""Collect installed distribution notices without importing runtime packages.

Call refresh(release) with the build environment's Python after copying original
licenses. This does not download licenses or claim a precise executable SBOM.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil


def _name(value):
    return re.sub(r'[-_.]+', '-', str(value)).lower()


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _notice(entry):
    return any(part.lower() == 'licenses' or
               any(word in part.lower() for word in ('license', 'copying', 'notice', 'copyright'))
               for part in entry.parts)


def refresh(release):
    """Refresh release/licenses indexes; preserve every existing notice body.

    Names present in this interpreter replace stale installed-component versions;
    prior components absent from this environment remain recorded. No package code
    executes. Missing installed license texts are explicitly reported, including
    pointers to separately supplied ASR texts when present.
    """
    release = Path(release).resolve()
    if not release.is_dir():
        raise ValueError('Release directory must already exist')
    licenses = release / 'licenses'
    licenses.mkdir(exist_ok=True)
    if licenses.resolve().parent != release:
        raise ValueError('licenses directory must remain inside release')
    destination = licenses / 'python-packages-r03'
    destination.mkdir(exist_ok=True)
    if not destination.resolve().is_relative_to(licenses):
        raise ValueError('Package notice destination escapes licenses')
    installed_path = licenses / 'INSTALLED-COMPONENTS.json'
    previous = json.loads(installed_path.read_text(encoding='utf-8-sig')) if installed_path.exists() else []
    if not isinstance(previous, list):
        raise ValueError('INSTALLED-COMPONENTS.json must be an array')
    merged = {_name(item['name']): item for item in previous if isinstance(item, dict) and item.get('name')}
    records = []
    distributions = sorted(metadata.distributions(), key=lambda d: (_name(d.metadata.get('Name', '')), d.version))
    seen = set()
    for dist in distributions:
        name, version = dist.metadata.get('Name'), dist.version
        if not name:
            continue
        normalized = _name(name)
        if normalized in seen:
            raise ValueError('Duplicate installed distribution: ' + normalized)
        seen.add(normalized)
        folder = destination / (normalized + '-' + re.sub(r'[^A-Za-z0-9._+-]', '_', version))
        copied, missing = [], []
        for entry in dist.files or []:
            relative = PurePosixPath(str(entry).replace('\\', '/'))
            if not (_notice(relative) or relative.name in ('METADATA', 'PKG-INFO', 'RECORD')):
                continue
            if relative.is_absolute() or '..' in relative.parts or any(':' in p for p in relative.parts):
                missing.append({'record': str(entry), 'reason': 'unsafe_record_path'})
                continue
            origin = Path(dist.locate_file(entry))
            target = folder.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Destination escapes notice directory')
            if not origin.is_file():
                missing.append({'record': str(entry), 'reason': 'record_file_missing'})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
            if _notice(relative):
                copied.append(target.relative_to(licenses).as_posix())
        manual = licenses / 'ASR' / normalized
        manual_texts = [p.relative_to(licenses).as_posix() for p in sorted(manual.rglob('*'))
                        if p.is_file() and _notice(PurePosixPath(p.name))] if manual.is_dir() else []
        record = {'name': name, 'version': version,
                  'license_metadata': dist.metadata.get('License-Expression') or dist.metadata.get('License') or '',
                  'source_urls': ['Project-URL: ' + value for value in dist.metadata.get_all('Project-URL', [])],
                  'license_files': copied, 'supplemental_license_files': manual_texts,
                  'license_status': 'collected_from_installed_record' if copied else
                      ('supplemental_text_only' if manual_texts else 'missing'),
                  'missing_record_files': missing,
                  'scope': 'current Python environment; not exact packaged executable SBOM'}
        home = dist.metadata.get('Home-page')
        if home:
            record['source_urls'].append('Home-page: ' + home)
        records.append(record)
        merged[normalized] = record
    inventory = {'scope': 'Entire current Python environment, including transitive dependencies and build tools; not an exact executable SBOM',
                 'collection': 'Installed distribution RECORD paths; no downloads; original texts copied unchanged',
                 'packages': records, 'missing_license_text': [r['name'] for r in records if r['license_status'] == 'missing']}
    _write(destination / 'ENVIRONMENT-INVENTORY.json', inventory)
    _write(installed_path, [merged[key] for key in sorted(merged)])
    index = []
    index_path = licenses / 'LICENSE-FILE-HASHES.json'
    for file in sorted(licenses.rglob('*')):
        if file.is_file() and file != index_path:
            if not file.resolve().is_relative_to(licenses):
                raise ValueError('License file resolves outside release')
            index.append({'file': file.relative_to(licenses).as_posix(), 'sha256': _digest(file),
                          'origin': 'Bundled original notice or collection metadata; see notices and source manifests'})
    _write(index_path, index)
    return {'packages': len(records), 'missing_license_text': inventory['missing_license_text'], 'license_files_hashed': len(index)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('release', type=Path)
    print(json.dumps(refresh(parser.parse_args().release), ensure_ascii=False))
