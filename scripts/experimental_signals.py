"""Pinned, sample-specific experimental signals shared by site builders."""
import copy
import json
import re
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / 'data/registry/experimental-signals.json'
HF_PREFIX = 'https://huggingface.co/datasets/liurulong/terminator/resolve'


def load_signals(path=REGISTRY):
    data = json.loads(path.read_text(encoding='utf-8'))
    revision = data['revision']
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Experimental signals require a fixed revision')
    seen = set()
    for sample in data['samples']:
        key = (sample['genome_id'], sample['source_id'], sample['sample_id'])
        if key in seen or {s['strand'] for s in sample['signals']} != {'plus', 'minus'} or len(sample['signals']) != 2:
            raise ValueError('Duplicate sample or incomplete strand pair')
        seen.add(key)
        root = f"v0.5.0/genomes/experimental-only/{sample['genome_id']}/studies/PMID_{sample['pmid']}/sources/{sample['source_id']}/samples/{sample['sample_id']}"
        for signal in sample['signals']:
            if signal['path'] != f"{root}/signal.{signal['strand']}.bw" or signal['byte_size'] <= 0 or not re.fullmatch(r'[0-9a-f]{64}', signal['sha256']):
                raise ValueError('Invalid signal registration')
            signal['url'] = f"{HF_PREFIX}/{revision}/{signal['path']}"
    return data['samples'], revision


def signal_assets(assets):
    samples, revision = load_signals()
    for sample in samples:
        for signal in sample['signals']:
            assets[signal['path'].split('/', 1)[1]] = {
                'url': signal['url'], 'byte_size': signal['byte_size'], 'sha256': signal['sha256'],
                'revision': revision, 'asset_kind': 'bigwig', 'version': 'v0.5.0', 'local_path': None,
            }
    return assets


def apply_signal_tracks(config, sources):
    samples, _revision = load_signals()
    tracks = config.setdefault('tracks', [])
    for sample in samples:
        source = sources.get(sample['source_id'])
        if not source or source.get('assembly') != sample['genome_id']:
            continue
        if source['pmid'] != sample['pmid']:
            raise ValueError('Signal publication differs from endpoint publication')
        endpoint = next((t for t in tracks if t.get('metadata', {}).get('btedAbout', {}).get('kind') == 'endpoint'
                         and sample['source_id'] in [t.get('metadata', {}).get('source_id'), *t.get('metadata', {}).get('source_ids', [])]), None)
        if not endpoint:
            raise ValueError('Signal sample has no matching endpoint track')
        old = [t for t in tracks if t.get('metadata', {}).get('btedAbout', {}).get('kind') == 'signal'
               and t['metadata']['btedAbout'].get('source_id') == sample['source_id']]
        track_id = f"bted_{sample['sample_id'].lower()}_mirrored_signal"
        about = copy.deepcopy(endpoint['metadata']['btedAbout'])
        for key in ('record_count', 'evidence', 'gff3_url', 'limitations', 'reference_name'):
            about.pop(key, None)
        about.update(kind='signal', sample_id=sample['sample_id'], assay=sample['assay'],
                     conditions=sample['conditions'], strand='+ / −', coverage=sample['coverage'],
                     reference_name=', '.join(sample['reference_contigs']),
                     raw_data_accessions=sample['sample_id'],
                     raw_data_url=f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={sample['sample_id']}")
        merged = {
            'type': 'MultiQuantitativeTrack', 'trackId': track_id,
            'name': f"PMID {sample['pmid']} · {sample['assay']} · {sample['sample_id']}",
            'category': ['Experimental signal', f"PMID {sample['pmid']}"],
            'assemblyNames': endpoint['assemblyNames'],
            'adapter': {'type': 'MultiWiggleAdapter', 'subadapters': [
                {'type': 'BigWigAdapter', 'source': s['strand'], 'name': '+ strand' if s['strand'] == 'plus' else '− strand',
                 'color': '#0f766e' if s['strand'] == 'plus' else '#be123c',
                 'bigWigLocation': {'uri': s['url'], 'locationType': 'UriLocation'}} for s in sample['signals']]},
            'metadata': {'btedMirroredSignal': True, 'btedAbout': about, 'btedDownloads': [
                {'kind': 'bigwig', 'label': '+ strand BigWig' if s['strand'] == 'plus' else '− strand BigWig',
                 'url': s['url'], 'filename': f"{sample['sample_id']}.signal.{s['strand']}.bw"} for s in sample['signals']]},
            'displays': [{'type': 'MultiLinearWiggleDisplay', 'displayId': f'{track_id}-MultiLinearWiggleDisplay', 'defaultRendering': 'xyplot', 'autoscale': 'global', 'scaleType': 'log', 'height': 180}],
        }
        old_ids = {t['trackId'] for t in old}
        tracks[:] = [t for t in tracks if t['trackId'] != track_id]
        tracks.insert(tracks.index(endpoint) + 1, merged)
        for view in config.get('defaultSession', {}).get('views', []):
            visible = view.get('tracks', [])
            visible[:] = [t for t in visible if t['configuration'] not in old_ids]
            index = next((i for i, t in enumerate(visible) if t['configuration'] == endpoint['trackId']), None)
            if index is not None:
                visible.insert(index + 1, {'id': f'{track_id}-v04-view', 'type': 'MultiQuantitativeTrack', 'configuration': track_id,
                    'displays': [{'id': f'{track_id}-v04-display', 'type': 'MultiLinearWiggleDisplay', 'configuration': merged['displays'][0]['displayId'], 'showSidebar': False}]})
