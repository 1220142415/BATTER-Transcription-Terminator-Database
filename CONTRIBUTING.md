# Contributing to BTED

Report software issues or data corrections through [GitHub Issues](https://github.com/1220142415/BATTER-Transcription-Terminator-Database/issues). Include the page URL, genome accession, source or publication, and the observed problem.

## Code changes

Use the entry points in [Architecture](docs/ARCHITECTURE.md). Edit generators, `site/`, the Worker or the JBrowse plugin rather than generated HTML in `dist/`. Keep documentation, comments and diagnostics in English.

Run the relevant regression tests and these repository checks:

```sh
python scripts/validate_repo_layout.py
python scripts/check_markdown_links.py
python -m unittest discover -s tests -p 'test*.py' -q
node --test tests/*.mjs
```

For interface changes, exercise the affected filters, sorting, downloads or tracks in a browser. For track changes, check rendered features and sequence coordinates, not only track titles.

## Data corrections

- Identify the PMID/DOI, source file, worksheet or record, sample accessions and conditions.
- Keep the exact assembly version, sequence identifier, coordinate convention and strand. Sequence identity is required before reusing coordinates under a different reference name.
- Separate author-reported endpoints, signal-derived candidates and model predictions. Preserve distinct study records at overlapping positions.
- Record classification system, version or retrieval date, matching status and evidence separately from study organism names. See [collection rules](docs/COLLECTIONS.md).
- Check redistribution terms for each source file. Do not commit raw sequencing files, publisher workbooks, credentials or production exports.
- Prepare reviewed D1 changes with source evidence and rollback SQL before applying them. Scientific-file changes require a new fixed release; see the [database guide](database/README.md).

## Releases

Follow the fixed-input build and acceptance steps in [Deployment](docs/deployment.md). Report changed data counts and evidence with each data correction. GitHub CI validates the repository; it does not automatically deploy Cloudflare.
