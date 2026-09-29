/* BTED additions for the pinned JBrowse 4.3.0 web application. */
const PLUS = '#0f766e';
const MINUS = '#be123c';
const UNKNOWN = '#64748b';
const MIRROR_HEIGHT = 180;
const MIRROR_RENDERER = 'BTEDMirroredSignalRenderer';
const BRIDGE_CHANNEL = 'bted-browser-v1';

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

export function visibleGff3(text, region) {
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line || line.startsWith('#')) continue;
    const fields = line.split('\t');
    if (fields.length !== 9) throw new Error('The source GFF3 has a malformed feature row.');
    const start = Number(fields[3]);
    const end = Number(fields[4]);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end)) throw new Error('The source GFF3 has an invalid coordinate.');
    if (fields[0] === region.ref && start <= region.end && end >= region.start) rows.push(line);
  }
  return `##gff-version 3\n##sequence-region ${region.ref} ${region.start} ${region.end}\n${rows.join('\n')}${rows.length ? '\n' : ''}`;
}

function configId(track) {
  return typeof track?.configuration === 'string'
    ? track.configuration : track?.configuration?.trackId || track?.trackId || '';
}

export function sharedView(view, allowed) {
  if (!view || !Number.isFinite(view.width) || view.width <= 0 ||
      !Number.isFinite(view.bpPerPx) || view.bpPerPx <= 0 || view.displayedRegions?.length !== 1) {
    throw new Error('Open one reference sequence before sharing this view.');
  }
  const left = view.pxToBp(0);
  const center = view.pxToBp(view.width / 2);
  const right = view.pxToBp(view.width);
  if (center.oob || !Number.isSafeInteger(center.coord) || center.coord < 1 ||
      left.refName !== center.refName || right.refName !== center.refName) {
    throw new Error('The current view crosses reference sequences and cannot be shared.');
  }
  const tracks = view.tracks.map((track) => ({
    id: configId(track), height: track.displays?.[0]?.height ?? track.displays?.[0]?.heightPreConfig,
  })).filter((track) => allowed.has(track.id));
  if (tracks.some((track) => !Number.isFinite(track.height) || track.height < 20 || track.height > 1000)) {
    throw new Error('A visible track has an invalid height.');
  }
  return {
    version: 1, ref: center.refName, center: center.coord,
    zoom: view.bpPerPx, reversed: center.reversed === true, tracks,
  };
}

export function validateSharedState(state, allowed) {
  if (!state || state.version !== 1 || typeof state.ref !== 'string' || !state.ref || state.ref.length > 255 ||
      !Number.isSafeInteger(state.center) || state.center < 1 ||
      !Number.isFinite(state.zoom) || state.zoom <= 0 || typeof state.reversed !== 'boolean' ||
      !Array.isArray(state.tracks) || state.tracks.length > allowed.size) {
    throw new Error('The shared browser link is invalid.');
  }
  const seen = new Set();
  for (const track of state.tracks) {
    if (!track || !allowed.has(track.id) || seen.has(track.id) ||
        !Number.isFinite(track.height) || track.height < 20 || track.height > 1000) {
      throw new Error('The shared browser link contains an unavailable track.');
    }
    seen.add(track.id);
  }
  return state;
}

export async function fitFullReference(view, assembly, assemblyName) {
  const refName = view?.displayedRegions?.[0]?.refName;
  const reference = assembly?.regions?.find((region) => region.refName === refName);
  const start = Number(reference?.start ?? 0);
  const end = Number(reference?.end);
  if (!reference || !Number.isFinite(start) || !Number.isFinite(end) || end <= start ||
      !Number.isFinite(view.width) || view.width <= 0) {
    throw new Error('The reference sequence is unavailable.');
  }
  await view.navToLocString(`${refName}:${start + 1}..${end}`, assemblyName);
  view.zoomTo(Math.max(0.001, (end - start) * 1.02 / view.width), view.width / 2);
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
    const { getContainingTrack, getContainingView, getSession } = pluginManager.jbrequire('@jbrowse/core/util');
    const { Dialog } = pluginManager.jbrequire('@jbrowse/core/ui');
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
      if (element.name === 'LinearBasicDisplay') {
        element.stateModel = element.stateModel.extend((self) => {
          const originalMenu = self.trackMenuItems;
          return { views: { trackMenuItems() { return withDownloadMenu(self, originalMenu()); } } };
        });
        return element;
      }
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
            if (!isMirrored(self)) return withDownloadMenu(self, items);
            const hidden = new Set(['Score', 'Renderer type', 'Edit colors/arrangement...', 'Fill mode', 'Show sidebar']);
            return withDownloadMenu(self, items.filter((item) => !hidden.has(item.label)));
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
      const provenance = section(kind === 'reference' ? 'Reference and annotation' : 'Source data', [
        facts([
          ['Reference', about.reference],
          ['Reference sequence', kind === 'reference' ? about.reference_name : ''],
          ['Raw data accession', about.raw_data_accessions],
        ]),
        links([
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

    if (typeof window !== 'undefined' && window.parent && window.parent !== window &&
        typeof window.addEventListener === 'function') {
      const nonce = new URLSearchParams(window.location.search).get('bted_bridge');
      if (nonce) {
        // JBrowse 4.3.0 leaves a 300px empty drop area after the last view.
        // The genome page embeds one view and sizes its frame to the tracks.
        const compactEmbed = document.createElement('style');
        compactEmbed.textContent = '[data-testid^="view-container-"] + .css-vycneo{display:none!important}';
        document.head.append(compactEmbed);
      }
      const root = () => pluginManager.rootModel;
      const view = () => root()?.session?.views?.find((item) => item.type === 'LinearGenomeView');
      const viewReady = () => { try { return view()?.width > 0; } catch { return false; } };
      const allowed = () => new Set((root()?.jbrowse?.tracks || [])
        .filter((track) => metadataFor(track, readConfObject, getConf))
        .map(configId).filter(Boolean));
      const reply = (type, id, details) => window.parent.postMessage(
        { channel: BRIDGE_CHANNEL, nonce, type, id, ...details }, window.location.origin);
      window.addEventListener('message', async (event) => {
        const message = event.data;
        if (event.origin !== window.location.origin || event.source !== window.parent ||
            message?.channel !== BRIDGE_CHANNEL || message.nonce !== nonce ||
            !['capture', 'restore', 'fit-default', 'navigate'].includes(message.type)) return;
        try {
          const current = view();
          if (!current) throw new Error('The genome browser is still loading.');
          const available = allowed();
          if (message.type === 'fit-default') {
            const assemblyName = current.assemblyNames?.[0];
            const assembly = await root().session.assemblyManager.waitForAssembly(assemblyName);
            await fitFullReference(current, assembly, assemblyName);
            reply('fitted', message.id, {});
          } else if (message.type === 'navigate') {
            if (typeof message.location !== 'string' || message.location.length > 255 ||
                /[\u0000-\u001f]/.test(message.location)) throw new Error('The reference location is invalid.');
            await current.navToLocString(message.location, current.assemblyNames?.[0]);
            reply('navigated', message.id, {});
          } else if (message.type === 'capture') {
            reply('captured', message.id, { state: sharedView(current, available) });
          } else {
            const state = validateSharedState(message.state, available);
            const assemblyName = current.assemblyNames?.[0];
            const assembly = await root().session.assemblyManager.waitForAssembly(assemblyName);
            const reference = assembly?.regions?.find((item) => item.refName === state.ref);
            if (!reference || state.center > reference.end) throw new Error('The shared reference position is unavailable.');
            await current.navToLocString(`${state.ref}:${state.center}${state.reversed ? '[rev]' : ''}`, assemblyName);
            current.zoomTo(state.zoom, current.width / 2);
            const selected = new Set(state.tracks.map((track) => track.id));
            for (const track of [...current.tracks]) {
              const id = configId(track);
              if (available.has(id) && !selected.has(id)) current.hideTrack(id);
            }
            for (const track of state.tracks) {
              const opened = current.showTrack(track.id);
              opened.displays?.[0]?.setHeight?.(track.height);
            }
            for (const track of [...state.tracks].reverse()) {
              const opened = current.tracks.find((item) => configId(item) === track.id);
              if (opened) current.moveTrackToTop(opened.id);
            }
            reply('restored', message.id, {});
          }
        } catch (error) {
          reply('error', message.id, { message: error?.message || 'The browser view could not be shared.' });
        }
      });
      let attempts = 0;
      const ready = window.setInterval(() => {
        if (viewReady()) {
          window.clearInterval(ready);
          reply('ready', '', {});
        } else if (++attempts >= 80) {
          window.clearInterval(ready);
          reply('error', '', { message: 'The genome browser did not finish loading.' });
        }
      }, 250);
    }

    if (typeof window !== 'undefined' && window.parent === window &&
        new URLSearchParams(window.location.search).get('bted_fit') === '1') {
      let attempts = 0;
      const ready = window.setInterval(async () => {
        const root = pluginManager.rootModel;
        const current = root?.session?.views?.find((item) => item.type === 'LinearGenomeView');
        if (current?.width > 0) {
          window.clearInterval(ready);
          try {
            const assemblyName = current.assemblyNames?.[0];
            const assembly = await root.session.assemblyManager.waitForAssembly(assemblyName);
            await fitFullReference(current, assembly, assemblyName);
            const url = new URL(window.location.href);
            url.searchParams.delete('bted_fit');
            window.history.replaceState(window.history.state, '', url);
          } catch { /* The full-length default session remains available. */ }
        } else if (++attempts >= 80) {
          window.clearInterval(ready);
        }
      }, 250);
    }

    function currentRegion(display) {
      try {
        const view = getContainingView(display);
        if (view.displayedRegions?.length !== 1 || !view.width) return null;
        const left = view.pxToBp(0);
        const right = view.pxToBp(view.width);
        if (!left.refName || left.refName !== right.refName) return null;
        const start = Math.max(1, Math.floor(Math.min(left.coord, right.coord)));
        const end = Math.max(start, Math.ceil(Math.max(left.coord, right.coord)) - 1);
        return { ref: left.refName, start, end };
      } catch { return null; }
    }

    function downloadUrl(raw) {
      const url = safeLink(raw);
      if (!url) return '';
      const parsed = new URL(url);
      if (parsed.origin === window.location.origin) return url;
      if (parsed.hostname === 'huggingface.co' &&
          /^\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.[34]\.0\//.test(parsed.pathname)) return url;
      return '';
    }

    function DownloadDialog({ handleClose, downloads, region }) {
      const [status, setStatus] = React.useState('');
      const [busy, setBusy] = React.useState(false);
      async function download(item, scope) {
        const url = downloadUrl(item.url);
        if (!url) { setStatus('This track has no approved download address.'); return; }
        setBusy(true);
        setStatus('Preparing download…');
        let objectUrl;
        try {
          const response = await fetch(url, { credentials: 'omit' });
          if (!response.ok) throw new Error(`Download failed (${response.status}).`);
          const isRegion = scope === 'visible';
          const blob = isRegion
            ? new Blob([visibleGff3(await response.text(), region)], { type: 'text/plain;charset=utf-8' })
            : await response.blob();
          objectUrl = URL.createObjectURL(blob);
          const base = value(item.filename).replace(/[^A-Za-z0-9_.-]/g, '_') || 'BTED-track';
          const filename = isRegion
            ? `${base.replace(/\.gff3(?:\.gz)?$/i, '')}.${region.ref.replace(/[^A-Za-z0-9_.-]/g, '_')}.${region.start}-${region.end}.gff3`
            : base;
          const anchor = document.createElement('a');
          anchor.href = objectUrl;
          anchor.download = filename;
          anchor.style.display = 'none';
          document.body.append(anchor);
          anchor.click();
          anchor.remove();
          window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
          handleClose();
        } catch (error) {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          setStatus(error?.message || 'Track data could not be downloaded.');
          setBusy(false);
        }
      }
      return h(Dialog, { open: true, onClose: handleClose, title: 'Download track data', maxWidth: 'sm', fullWidth: true },
        h('div', { className: 'bted-download-dialog' },
          h('style', null, '.bted-download-dialog{padding:0 22px 20px;color:#20342f;font:13px/1.5 Arial,sans-serif}.bted-download-dialog p{margin:0 0 14px;color:#50665d}.bted-download-row{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;padding:12px 0;border-top:1px solid #e0e9e5}.bted-download-row strong{font-size:13px}.bted-download-actions{display:flex;flex-wrap:wrap;gap:7px}.bted-download-actions button{min-height:34px;padding:6px 10px;border:1px solid #0f766e;border-radius:4px;background:#0f766e;color:white;font:700 12px Arial,sans-serif;cursor:pointer}.bted-download-actions button:disabled{opacity:.45;cursor:not-allowed}.bted-download-status{min-height:18px;color:#9b273f!important}@media(max-width:600px){.bted-download-dialog{padding:0 14px 16px}}'),
          h('p', null, 'Download the published file for this track. A visible-region GFF3 keeps the original feature fields.'),
          downloads.map((item, index) => h('div', { className: 'bted-download-row', key: `${item.kind}-${index}` },
            h('strong', null, item.label),
            h('div', { className: 'bted-download-actions' },
              item.kind === 'endpoint' ? h('button', { type: 'button', disabled: busy || !region,
                title: region ? `${region.ref}:${region.start}-${region.end}` : 'Available only when one reference sequence is visible',
                onClick: () => download(item, 'visible') }, 'Visible region GFF3') : null,
              h('button', { type: 'button', disabled: busy, onClick: () => download(item, 'whole') }, 'Whole file')))),
          h('p', { className: 'bted-download-status', role: 'status' }, status)));
    }

    function withDownloadMenu(display, items) {
      let downloads;
      try {
        downloads = getConf(getContainingTrack(display), 'metadata')?.btedDownloads;
      } catch { return items; }
      if (!Array.isArray(downloads) || !downloads.length) return items;
      const approved = downloads.filter((item) => item && ['endpoint', 'bigwig', 'reference'].includes(item.kind) && value(item.label) && value(item.filename));
      if (!approved.length) return items;
      return [...items, { label: 'Download track data', priority: 50, onClick: () => {
        const session = getSession(display);
        const region = currentRegion(display);
        session.queueDialog((done) => [DownloadDialog, { handleClose: done, downloads: approved, region }]);
      } }];
    }
  }
}
