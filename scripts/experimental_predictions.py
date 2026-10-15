"""Verified predictions on the experimental reference assemblies."""
import json
import re
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / 'data/registry/experimental-predictions.json'
HF_PREFIX = 'https://huggingface.co/datasets/liurulong/terminator/resolve'


def load_predictions(path=REGISTRY):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not re.fullmatch(r'[0-9a-f]{40}', data['revision']) or not re.fullmatch(r'BATTER-TPE-\d{8}', data['run']):
        raise ValueError('Prediction files require a fixed revision and run')
    for genome, row in data['genomes'].items():
        if not re.fullmatch(r'GCF_\d+\.\d+', genome) or row['prediction_count'] != sum(row['contig_counts'].values()):
            raise ValueError('Invalid prediction assembly/count')
        if any(k not in row['reference']['contigs'] or v < 1 for k, v in row['contig_counts'].items()):
            raise ValueError('Prediction contig differs from reference')
        if set(row['files']) != {'prediction.bed', 'prediction.gff3.gz', 'prediction.gff3.gz.tbi'}:
            raise ValueError('Prediction file set incomplete')
        for item in [*row['files'].values(), *row.get('reference_files', {}).values()]:
            if item['byte_size'] <= 0 or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
                raise ValueError('Invalid prediction asset identity')
    return data


def prediction_assets(assets):
    data = load_predictions()
    for genome, row in data['genomes'].items():
        root = f"genomes/experimental-only/{genome}/predictions/{data['run']}"
        for name, item in row['files'].items():
            kind = 'bed' if name.endswith('.bed') else 'tbi' if name.endswith('.tbi') else 'gff3'
            path = f'{root}/{name}'
            assets[path] = {**item, 'url': f"{HF_PREFIX}/{data['revision']}/v0.5.0/{path}",
                            'revision': data['revision'], 'asset_kind': kind, 'version': 'v0.5.0', 'local_path': None}
        for name, item in row.get('reference_files', {}).items():
            path = f'genomes/experimental-only/{genome}/reference/{name}'
            assets[path] = {**item, 'url': f"{HF_PREFIX}/{item['revision']}/v0.5.0/{path}",
                           'asset_kind': 'fai' if name.endswith('.fai') else 'fasta', 'version': 'v0.5.0', 'local_path': None}
    return assets


def apply_prediction_track(config, genome):
    data = load_predictions()
    row = data['genomes'].get(genome)
    if not row:
        return config
    assembly = config['assemblies'][0]
    expected = row['reference']['source_url']
    if assembly['sequence']['adapter']['fastaLocation']['uri'] != expected:
        raise ValueError(f'Prediction reference differs from browser: {genome}')
    urls = {name: f"{HF_PREFIX}/{data['revision']}/v0.5.0/genomes/experimental-only/{genome}/predictions/{data['run']}/{name}" for name in row['files']}
    track_id = 'bted_experimental_prediction'
    track = {
        'type': 'FeatureTrack', 'trackId': track_id, 'name': 'Predicted regions', 'category': ['Model prediction'], 'assemblyNames': [assembly['name']],
        'adapter': {'type': 'Gff3TabixAdapter', 'gffGzLocation': {'uri': urls['prediction.gff3.gz'], 'locationType': 'UriLocation'},
                    'index': {'location': {'uri': urls['prediction.gff3.gz.tbi'], 'locationType': 'UriLocation'}, 'indexType': 'TBI'}},
        'displays': [{'type': 'LinearBasicDisplay', 'displayId': track_id + '_display', 'height': 160, 'showLabels': False,
                      'renderer': {'type': 'SvgFeatureRenderer', 'showLabels': False, 'height': 14, 'color1': 'jexl:btedStrandColor(feature)',
                                   'color2': 'jexl:btedStrandColor(feature)', 'mouseover': 'jexl:btedPredictionTooltip(feature)'}}],
        'metadata': {'evidence_class': 'model_prediction', 'btedContigCounts': row['contig_counts'],
                     'btedAbout': {'kind': 'prediction', 'assembly': genome, 'evidence': 'Model prediction', 'record_count': row['prediction_count'],
                                   'assay': 'BATTER-TPE', 'reference': row['reference']['organism_name'],
                                   'reference_url': f'https://www.ncbi.nlm.nih.gov/datasets/genome/{genome}/'},
                     'btedDownloads': [{'kind': 'prediction', 'label': 'Prediction BED' if name.endswith('.bed') else 'Prediction GFF3',
                                        'url': urls[name], 'filename': f'{genome}.{name}'} for name in ('prediction.bed', 'prediction.gff3.gz')]},
    }
    tracks = config.setdefault('tracks', [])
    tracks[:] = [t for t in tracks if t['trackId'] != track_id]
    tracks.append(track)
    for view in config.get('defaultSession', {}).get('views', []):
        visible = view.setdefault('tracks', [])
        visible[:] = [t for t in visible if t['configuration'] != track_id]
        visible.append({'id': track_id + '_view', 'type': 'FeatureTrack', 'configuration': track_id,
                        'displays': [{'id': track_id + '_view_display', 'type': 'LinearBasicDisplay', 'configuration': track_id + '_display'}]})
    return config


def prediction_only_config(genome):
    row = load_predictions()['genomes'][genome]
    assets = prediction_assets({})
    root = f'genomes/experimental-only/{genome}/reference/'
    ref = row['first_region']
    sequence_id = genome + '_refseq'
    config = {'assemblies': [{'name': genome, 'sequence': {'type': 'ReferenceSequenceTrack', 'trackId': sequence_id, 'name': 'Reference sequence',
                'adapter': {'type': 'IndexedFastaAdapter', 'fastaLocation': {'uri': assets[root+'reference.fna']['url'], 'locationType': 'UriLocation'},
                            'faiLocation': {'uri': assets[root+'reference.fna.fai']['url'], 'locationType': 'UriLocation'}}}}], 'tracks': [],
              'defaultSession': {'name': f'BTED · {genome}', 'views': [{'id': 'bted_linear_genome_view', 'type': 'LinearGenomeView',
                'bpPerPx': 1, 'offsetPx': max(0, ref['start']-200),
                'displayedRegions': [{'refName': ref['refName'], 'start': 0, 'end': row['reference']['contigs'][ref['refName']], 'reversed': False, 'assemblyName': genome}],
                'tracks': [{'id': sequence_id+'_view', 'type': 'ReferenceSequenceTrack', 'configuration': sequence_id,
                            'displays': [{'id': sequence_id+'_display', 'type': 'LinearReferenceSequenceDisplay', 'configuration': sequence_id+'-LinearReferenceSequenceDisplay', 'showTranslation': True, 'heightPreConfig': 120}]}]}]}}
    return apply_prediction_track(config, genome)
