/* BTED additions for the pinned JBrowse 4.3.0 web application. */
const PLUS = '#0f766e';
const MINUS = '#be123c';
const UNKNOWN = '#64748b';

export function strandColor(feature) {
  const value = feature?.get?.('strand');
  if (value === '+' || value === 1 || value === '1') return PLUS;
  if (value === '-' || value === -1 || value === '-1') return MINUS;
  return UNKNOWN;
}

function value(input) {
  if (input === undefined || input === null) return '';
  return String(input).trim();
}

function safeLink(input) {
  const text = value(input);
  if (!text) return '';
  try {
    const url = new URL(text, window.location.href);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

function metadataFor(config, readConfObject, getConf) {
  try {
    const plain = readConfObject(config);
    if (plain?.metadata?.btedAbout) return plain.metadata.btedAbout;
  } catch { /* Configuration models and plain objects use different readers. */ }
  try {
    const metadata = getConf(config, 'metadata');
    if (metadata?.btedAbout) return metadata.btedAbout;
  } catch { /* Keep the original About for unrelated tracks. */ }
  return null;
}

export default class BTEDTrackPlugin {
  name = 'BTEDTrackPlugin';
  version = '1.0.0';

  // JBrowse 4.3.0 calls configure() on every installed plugin.
  configure() {}

  install(pluginManager) {
    pluginManager.jexl.addFunction('btedStrandColor', strandColor);
    const React = pluginManager.jbrequire('react');
    const { readConfObject, getConf } = pluginManager.jbrequire('@jbrowse/core/configuration');
    const h = React.createElement;

    function facts(items) {
      const entries = items.filter(([, item]) => value(item));
      if (!entries.length) return null;
      return h('dl', { className: 'bted-about-facts' }, entries.map(([label, item]) =>
        h('div', { key: label }, h('dt', null, label), h('dd', null, value(item)))));
    }

    function links(items) {
      const entries = items.map(([label, href]) => [label, safeLink(href)]).filter(([, href]) => href);
      if (!entries.length) return null;
      return h('div', { className: 'bted-about-links' }, entries.map(([label, href]) =>
        h('a', { key: label, href, target: '_blank', rel: 'noopener noreferrer' }, label)));
    }

    function section(title, content) {
      const children = content.filter(Boolean);
      return children.length ? h('section', { key: title, className: 'bted-about-section' },
        h('h3', null, title), ...children) : null;
    }

    function BTEDAbout({ config }) {
      const about = metadataFor(config, readConfObject, getConf);
      if (!about) return null;
      const kind = value(about.kind);
      const study = kind === 'reference' ? null : section('Study', [
        facts([
          ['Title', about.title], ['Authors', about.authors], ['Journal', about.journal],
          ['Year', about.year], ['PMID', about.pmid],
        ]),
        links([['PubMed', about.pubmed_url], ['DOI', about.doi_url]]),
      ]);
      const evidence = kind === 'reference' ? null : section(kind === 'signal' ? 'Experimental signal' : 'Endpoint evidence', [
        facts([
          ['Source', about.source_id], ['Method', about.assay], ['Strand', about.strand],
          ['Endpoints', kind === 'endpoint' ? about.record_count : ''],
          ['Evidence', kind === 'signal' ? 'Measured experimental signal' : about.evidence],
          ['Reference assembly', about.assembly], ['Reference sequence', about.reference_name],
        ]),
        value(about.explanation) ? h('p', null, value(about.explanation)) : null,
      ]);
      const provenance = section(kind === 'reference' ? 'Reference and annotation' : 'Source and use', [
        facts([
          ['Reference', about.reference],
          [value(about.annotation_version).startsWith('GFF3 SHA-256') ? 'Annotation file fingerprint' : 'Annotation version', about.annotation_version],
          ['License', about.license], ['Limitations', about.limitations],
          ['Raw data accession', about.raw_data_accessions],
        ]),
        links([
          ['Download study GFF3', about.gff3_url],
          ['Open raw data', about.raw_data_url],
          ['Open NCBI assembly', about.reference_url],
        ]),
      ]);
      return h('div', { className: 'bted-about' },
        h('style', null, '.bted-about{min-width:min(680px,80vw);font:14px/1.55 Arial,sans-serif;color:#233044}.bted-about-section{padding:12px 0;border-bottom:1px solid #d9e1e8}.bted-about-section h3{margin:0 0 8px;font-size:16px}.bted-about-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 18px;margin:0}.bted-about-facts dt{color:#607080;font-size:12px}.bted-about-facts dd{margin:1px 0 0;overflow-wrap:anywhere}.bted-about-links{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}.bted-about-links a{color:#236aa2}@media(max-width:600px){.bted-about-facts{grid-template-columns:1fr}}'),
        study, evidence, provenance);
    }

    pluginManager.addToExtensionPoint('Core-replaceAbout', (Original, props) =>
      metadataFor(props?.config, readConfObject, getConf) ? BTEDAbout : Original);
  }
}
