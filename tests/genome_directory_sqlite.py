"""SQLite bridge for testing the exact directory SQL emitted by the Worker."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_genome_directory import compact, sort_key

path = Path(sys.argv[1])
database = sqlite3.connect(path)
database.row_factory = sqlite3.Row
if sys.argv[2] == 'init':
    database.executescript((Path(__file__).resolve().parents[1] / 'database/migrations/0005_genome_directory.sql').read_text())
    database.execute('CREATE TABLE hf_genome_metadata(revision TEXT, genome_id TEXT, catalogue_row_json TEXT, PRIMARY KEY(revision, genome_id)) WITHOUT ROWID')
    summary = dict(total=60, sources=['IMG'], phyla=['P1', 'P2'], available=31,
                   counts={'annotation': {'Available': 31, 'Missing': 29}, 'source': {'IMG': 60}, 'genome_type': {'MAG': 60},
                           'phylum': {'P1': 30, 'P2': 30}, 'dataset': {'experimental': 5, 'prediction': 30, 'augmentation': 20}})
    database.execute('INSERT INTO hf_directory_releases VALUES (?, ?, ?, ?, ?)', ('a'*24, 'a'*40, 'b'*40, compact(summary), 'ready'))
    for index in range(60):
        accession = f'GCF_{index}'
        endpoints = 100-index if index < 5 else 0
        record = [accession, '000', f'OTU-{index}', f'Species {index}', 'MAG', int(index % 3 == 0), 0, 0, 0, 'matched' if index % 2 == 0 else 'unavailable', index % 2, f'p__P{1+index%2};c__C{1+index%2}', 'IMG']
        ds = dict(taxonomyPhylum=f'P{1+index%2}', taxonomyGenus='', sortEndpoints=str(endpoints), sortPredictions=str(index%2), sortTraining=str(index%3 == 0 and 1 or 0))
        row = {'batter': record, 'dataset': ds}
        if index == 1:
            row['recoveredAnnotation'] = dict(coverage='partial', matched_reference_contigs=1, total_reference_contigs=3)
        search = f'{accession} OTU-{index} Species {index} {record[11]}'.lower()
        values = ['a'*24, accession, sort_key(accession), sort_key(record[3]), record[3], 'IMG', 'MAG', 'Available' if index % 2 == 0 or index == 1 else 'Missing',
                  endpoints, index % 2, int(index % 3 == 0), None, None, ds['taxonomyPhylum'], f'C{1+index%2}', '', '', '', '', search,
                  1 if index == 1 else None, 3 if index == 1 else None, 'partial' if index == 1 else None]
        database.execute('INSERT INTO hf_directory_genomes VALUES (NULL,' + ','.join('?' for _ in values) + ')', values)
        database.execute('INSERT INTO hf_genome_metadata VALUES(?,?,?)', ('a'*40, accession, compact(record)))
    database.execute("INSERT INTO hf_directory_search(hf_directory_search) VALUES('rebuild')")
    database.commit()
    print('{}')
else:
    query = json.load(sys.stdin)
    rows = database.execute(query['sql'], query['binds']).fetchall()
    print(json.dumps([dict(row) for row in rows]))
database.close()
