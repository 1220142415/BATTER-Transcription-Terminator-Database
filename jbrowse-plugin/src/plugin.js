/* BTED additions for the pinned JBrowse 4.3.0 web application. */
const PLUS = '#0f766e';
const MINUS = '#be123c';
const UNKNOWN = '#64748b';
const MIRROR_HEIGHT = 180;
const MIRROR_RENDERER = 'BTEDMirroredSignalRenderer';

function signalValue(feature) {
  const raw = feature.get('summary') ? feature.get('maxScore') : feature.get('score');
  const number = Number(raw);
  return Number.isFinite(number) ? Math.max(0, number) : 0;
}

export function paintMirroredSignal(ctx, features, region, bpPerPx, width, height = MIRROR_HEIGHT, scaleMax) {
  const baseline = height / 2;
  const observed = [...features].filter((feature) => ['plus', 'minus'].includes(feature.get('source')));
  const maximum = Number.isFinite(scaleMax) && scaleMax > 0 ? scaleMax : Math.max(1, ...observed.map(signalValue));
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#f8fbfa';
  ctx.fillRect(0, 0, width, baseline);
  ctx.fillStyle = '#fff8fa';
  ctx.fillRect(0, baseline, width, baseline);
  ctx.strokeStyle = '#82919b';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, baseline + 0.5);
  ctx.lineTo(width, baseline + 0.5);
  ctx.stroke();
  for (const feature of observed) {
    const source = feature.get('source');
    const start = Number(feature.get('start'));
    const end = Number(feature.get('end'));
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    const left = region.reversed ? (region.end - end) / bpPerPx : (start - region.start) / bpPerPx;
    const span = Math.max(1, (end - start) / bpPerPx);
    if (left + span < 0 || left > width) continue;
    const magnitude = Math.max(1, signalValue(feature) / maximum * (baseline - 14));
    ctx.fillStyle = source === 'plus' ? PLUS : MINUS;
    ctx.fillRect(left, source === 'plus' ? baseline - magnitude : baseline + 1, span, magnitude);
  }
  return maximum;
}

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
    const { readConfObject, getConf, ConfigurationSchema } = pluginManager.jbrequire('@jbrowse/core/configuration');
    const { getContainingTrack } = pluginManager.jbrequire('@jbrowse/core/util');
    const FeatureRendererType = pluginManager.jbrequire('@jbrowse/core/pluggableElementTypes/renderers/FeatureRendererType').default;
    const h = React.createElement;

    function isMirrored(display) {
      try {
        return getConf(getContainingTrack(display), 'metadata')?.btedMirroredSignal === true;
      } catch {
        return false;
      }
    }

    function MirroredRendering({ pixelData, width, height, features, regions, bpPerPx, displayModel }) {
      const canvasRef = React.useRef(null);
      React.useEffect(() => {
        const ctx = canvasRef.current?.getContext('2d');
        if (!ctx || !pixelData) return;
        const image = ctx.createImageData(width, height);
        image.data.set(pixelData);
        ctx.putImageData(image, 0, 0);
      }, [pixelData, width, height]);
      function hit(event) {
        const rect = canvasRef.current?.getBoundingClientRect();
        const region = regions?.[0];
        if (!rect || !region || !features?.values) return undefined;
        const source = event.clientY - rect.top < height / 2 ? 'plus' : 'minus';
        const offset = event.clientX - rect.left;
        const position = region.reversed ? region.end - offset * bpPerPx : region.start + offset * bpPerPx;
        const tolerance = Math.max(1, bpPerPx * 3);
        for (const feature of features.values()) {
          if (feature.get('source') !== source) continue;
          if (position >= Number(feature.get('start')) - tolerance && position <= Number(feature.get('end')) + tolerance) return feature;
        }
        return undefined;
      }
      return h('canvas', {
        ref: canvasRef, width, height, 'aria-label': 'Experimental signal: plus strand above, minus strand below',
        style: { display: 'block', width: '100%', height },
        onMouseMove: (event) => displayModel?.setFeatureUnderMouse?.(hit(event)),
        onMouseLeave: () => displayModel?.setFeatureUnderMouse?.(undefined),
        onClick: (event) => { const feature = hit(event); if (feature) displayModel?.selectFeature?.(feature); },
      });
    }

    class MirroredSignalRenderer extends FeatureRendererType {
      supportsSVG = false;

      async render(args) {
        const features = await this.getFeatures(args);
        const region = args.regions[0];
        const width = Math.max(1, Math.ceil((region.end - region.start) / args.bpPerPx));
        const height = args.height || MIRROR_HEIGHT;
        const canvas = typeof OffscreenCanvas === 'function' ? new OffscreenCanvas(width, height) : document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('BTED mirrored signal needs a 2D canvas');
        const sharedMax = args.scaleOpts?.domain?.[1];
        const visibleMax = paintMirroredSignal(ctx, features.values(), region, args.bpPerPx, width, height, sharedMax);
        return { features, width, height, visibleMax, pixelData: ctx.getImageData(0, 0, width, height).data };
      }
    }

    pluginManager.addRendererType((pm) => new MirroredSignalRenderer({
      name: MIRROR_RENDERER,
      ReactComponent: MirroredRendering,
      configSchema: ConfigurationSchema(MIRROR_RENDERER, {}, { explicitlyTyped: true }),
      pluginManager: pm,
    }));
    pluginManager.addToExtensionPoint('Core-extendPluggableElement', (element) => {
      if (element.name !== 'MultiLinearWiggleDisplay') return element;
      const native = { xyplot: 'MultiXYPlotRenderer', multirowxy: 'MultiRowXYPlotRenderer',
        multirowdensity: 'MultiDensityRenderer', multiline: 'MultiLineRenderer', multirowline: 'MultiRowLineRenderer' };
      element.stateModel = element.stateModel.extend((self) => {
        const originalMenu = self.trackMenuItems;
        return { views: {
          get rendererTypeName() {
            return isMirrored(self) ? MIRROR_RENDERER : native[self.rendererTypeNameSimple] || 'MultiXYPlotRenderer';
          },
          trackMenuItems() {
            const items = originalMenu();
            if (!isMirrored(self)) return items;
            const hidden = new Set(['Score', 'Renderer type', 'Edit colors/arrangement...', 'Fill mode', 'Show sidebar']);
            return items.filter((item) => !hidden.has(item.label));
          },
        } };
      });
      return element;
    });

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
        h('a', { key: label, href, className: 'bted-about-action', target: '_blank', rel: 'noopener noreferrer' }, label)));
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
        h('style', null, '.MuiDialog-paper:has(.bted-about){width:min(820px,calc(100vw - 28px));max-width:820px}.bted-about{box-sizing:border-box;padding:14px 24px 24px;color:#20342f;font:13px/1.5 Arial,sans-serif}.bted-about-lead{margin:0 0 6px;padding:11px 14px;border-left:3px solid #0f766e;background:#eff7f4;color:#344c45}.bted-about-section{margin-top:18px;padding-top:14px;border-top:1px solid #dce7e2}.bted-about-section h3{margin:0 0 8px;color:#35554c;font:750 11px/1.3 Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase}.bted-about-facts{margin:0}.bted-about-facts>div{display:grid;grid-template-columns:minmax(120px,27%) minmax(0,1fr);gap:14px;border-bottom:1px solid #edf1ef;padding:8px 0}.bted-about-facts>div:last-child{border-bottom:0}.bted-about-facts dt{color:#60766e;font-size:11px;font-weight:750;letter-spacing:.035em;text-transform:uppercase}.bted-about-facts dd{min-width:0;margin:0;overflow-wrap:anywhere;font-size:13px}.bted-about-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:13px}.bted-about-action{display:inline-flex;align-items:center;min-height:34px;padding:6px 11px;border:1px solid #0f766e;border-radius:4px;background:#0f766e;color:white!important;font-weight:700;text-decoration:none}.bted-about-action:hover{background:#115e55}.bted-about-action:focus-visible{outline:3px solid #8acabd;outline-offset:2px}@media(max-width:600px){.bted-about{padding:12px 14px 18px}.bted-about-facts>div{grid-template-columns:1fr;gap:2px}.bted-about-links{display:grid}.bted-about-action{justify-content:center}}'),
        value(about.explanation) ? h('p', { className: 'bted-about-lead' }, value(about.explanation)) : null,
        study, evidence, provenance);
    }

    pluginManager.addToExtensionPoint('Core-replaceAbout', (Original, props) =>
      metadataFor(props?.config, readConfObject, getConf) ? BTEDAbout : Original);
  }
}
