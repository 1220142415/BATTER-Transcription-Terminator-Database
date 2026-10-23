/* BTED additions for the pinned JBrowse 4.3.0 web application. */
const PLUS = '#0f766e';
const MINUS = '#be123c';
const UNKNOWN = '#64748b';
const MIRROR_HEIGHT = 180;
const MIRROR_RENDERER = 'BTEDMirroredSignalRenderer';
const BRIDGE_CHANNEL = 'bted-browser-v1';

function isBtedEmbed() {
  return typeof window !== 'undefined' && window.parent && window.parent !== window &&
    new URLSearchParams(window.location.search).has('bted_bridge');
}

// Most tracks are self-contained. Indexed formats can be selected together with
// their existing index in one picker; do not guess or mix unrelated files.
export function selectLocalTrackFiles(files) {
  const indexes = files.filter(file => /\.(bai|crai|tbi|csi)$/i.test(file.name));
  const tracks = files.filter(file => !indexes.includes(file));
  if (tracks.length !== 1) throw new Error('Select one track file. Include its matching index only if required.');
  const track = tracks[0];
  const name = track.name.toLowerCase();
  const suffixes = /\.bam$/.test(name) ? ['bai', 'csi'] : /\.cram$/.test(name) ? ['crai'] :
    /\.(bed|gff3?|gtf|bedgraph|vcf)\.(gz|bgz)$/.test(name) ? ['tbi', 'csi'] : /\.bcf$/.test(name) ? ['csi'] : [];
  const matches = suffixes.flatMap(suffix => [name + '.' + suffix,
    ...(/\.(bam|cram)$/.test(name) ? [name.replace(/\.(bam|cram)$/, '') + '.' + suffix] : [])]);
  if (indexes.length > 1 || indexes.some(file => !matches.includes(file.name.toLowerCase()))) {
    throw new Error('The index does not match this track. Select the track and one matching index together.');
  }
  if (suffixes.length && !indexes.length) {
    throw new Error(`This format requires a ${suffixes.map(suffix => '.' + suffix).join(' or ')} index. Select the track and its index together; no index is needed for plain BED/GFF3 or BigWig.`);
  }
  return { track, index: indexes[0] };
}

// Preserve the native callbacks; only offer controls that match the data.
export function compactFeatureMenu(items, display, kind) {
  const strandFilters = ["jexl:get(feature,'strand')==1 || get(feature,'strand')=='+'",
    "jexl:get(feature,'strand')==-1 || get(feature,'strand')=='-'"];
  const filters = display.activeFilters();
  return items.map(item => {
    if (item.label === 'Show...') return { ...item, label: 'Labels and tooltips',
      subMenu: item.subMenu.filter(child => kind === 'reference' ||
        !['Show chevrons', 'Subfeature labels', 'Gene glyph'].includes(child.label)) };
    if (item.label === 'Display mode') return { ...item, label: 'Feature layout',
      subMenu: item.subMenu.filter(child => ['normal', 'compact'].includes(child.label))
        .map(child => ({ ...child, label: child.label === 'normal' ? 'Expanded' : 'Compact' })) };
    if (item.label === 'Filter by...') return { ...item, label: 'Feature filters', subMenu: [
      ...item.subMenu.filter(child => child.label !== 'Edit filters...' &&
        (kind === 'reference' || child.label !== 'Show only genes')),
      ...[['augmentation', 'Show sequence context windows', "jexl:get(feature,'type')!='training_sequence_window' && get(feature,'type')!='rfam_training_window'"],
        ['reference', 'Show reference-region annotations', "jexl:get(feature,'type')!='region'"]]
        .filter(([trackKind]) => trackKind === kind).map(([, label, exclude]) => ({
          label, type: 'checkbox', checked: !filters.includes(exclude),
          onClick: () => display.setJexlFilters(filters.includes(exclude)
            ? display.activeFilters().filter(filter => filter !== exclude)
            : [...display.activeFilters(), exclude]),
        })),
      { label: 'Strand', subMenu: ['All strands', '+ strand', '− strand'].map((label, index) => ({
        label, type: 'radio', checked: index ? filters.includes(strandFilters[index - 1]) :
          !strandFilters.some(filter => filters.includes(filter)),
        onClick: () => display.setJexlFilters([
          ...display.activeFilters().filter(filter => !strandFilters.includes(filter)),
          ...(index ? [strandFilters[index - 1]] : []),
        ]),
      })) },
    ] };
    return item;
  });
}

export function compactTrackActions(items, hasDownload) {
  return items.flatMap(item => item.label !== 'Track actions' ? [item] :
    hasDownload ? [] : (item.subMenu || []).filter(child => child.label === 'Save track data')
      .map(child => ({ ...child, label: 'Export visible track data' })));
}

// Keep direct HF reads first; use the registered same-origin copy only after a
// network/CORS failure. Runs in both JBrowse's page and adapter workers.
const nativeFetch = globalThis.fetch.bind(globalThis);
const backupAssets = new Set();
let releaseManifest;
const batterManifests = new Map();
const conditionManifests = new Map();
async function fetchRegisteredBtedAsset(input, init = {}) {
  const url = input instanceof Request ? input.url : String(input);
  const method = init.method || (input instanceof Request ? input.method : 'GET');
  const condition = /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.5\.0\/(genomes\/experimental-only\/(GCF_\d+\.\d+)\/studies\/PMID_\d+\/sources\/(BATTER_[A-Za-z0-9_]+)\/conditions\/[A-Za-z0-9_-]+\/mean3\/signal\.(?:plus|minus)\.bw)$/.exec(url);
  const match = condition || /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.[34]\.0\/(.+)$/.exec(url)
    || /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.5\.0\/(genomes\/experimental-only\/[A-Za-z0-9_.-]+\/studies\/PMID_\d+\/sources\/BATTER_[A-Za-z0-9_]+\/samples\/GSM\d+\/signal\.(?:plus|minus)\.bw)$/.exec(url)
    || /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.5\.0\/(genomes\/experimental-only\/GCF_\d+\.\d+\/predictions\/BATTER-TPE-\d{8}\/prediction\.(?:bed|gff3\.gz(?:\.tbi)?))$/.exec(url)
    || /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.5\.0\/(genomes\/experimental-only\/GCF_000005845\.2\/reference\/reference\.fna(?:\.fai)?)$/.exec(url);
  const batter = /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/([0-9a-f]{40})\/v0\.5\.0\/genomes\/batter-(\d{3})\/([A-Za-z0-9_.-]+)\/(?:reference|training|predictions|annotations\/batter)\/([^/]+)$/.exec(url)
    || /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/([0-9a-f]{40})\/v0\.5\.0\/batter\/batches\/(\d{3})\/genomes\/([A-Za-z0-9_.-]+)\/([^/]+)$/.exec(url);
  const recovered = /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/([0-9a-f]{40})\/v0\.5\.1\/annotation-recovery\/2026-10-14\/genomes\/([A-Za-z0-9_.-]+)\/(genes\.gff3)$/.exec(url);
  if ((!match && !batter && !recovered) || !['GET', 'HEAD'].includes(method)) return nativeFetch(input, init);
  const signal = init.signal || (input instanceof Request ? input.signal : undefined);
  let originalError;
  if (!backupAssets.has(url)) {
    try {
      const response = await nativeFetch(input, { ...init, cache: init.cache === 'no-store' || (input instanceof Request && input.cache === 'no-store') ? 'no-store' : 'force-cache', credentials: 'omit', referrerPolicy: 'no-referrer' });
      if (response.ok || !([403, 408, 429].includes(response.status) || response.status >= 500)) return response;
      originalError = new Error(`Data origin returned HTTP ${response.status}.`);
    } catch (error) {
      if (signal?.aborted || !(error instanceof TypeError)) throw error;
      originalError = error;
    }
  }
  try {
    if (batter || recovered) {
      const genome = batter ? batter[3] : recovered[2];
      const key = batter ? `${batter[1]}/${genome}` : `annotation/${recovered[1]}/${genome}`;
      if (!batterManifests.has(key)) {
        const query = batter ? `?revision=${batter[1]}` : '';
        const promise = nativeFetch(`${globalThis.location.origin}/api/batter/${encodeURIComponent(genome)}${query}`, { signal, cache: 'no-cache' }).then(response => {
          if (!response.ok) throw new Error('Augmentation metadata unavailable.');
          return response.json();
        });
        batterManifests.set(key, promise);
        promise.catch(() => batterManifests.delete(key));
      }
      const metadata = await batterManifests.get(key);
      const asset = metadata.browser_files?.[batter ? batter[4] : recovered[3]];
      const versionMatched = batter ? metadata.revision === batter[1] && metadata.batch === batter[2]
        : metadata.annotation?.annotation_revision === recovered[1];
      if (!versionMatched || asset?.url !== url ||
          !asset.fallback_url?.startsWith(`/api/batter/${encodeURIComponent(genome)}/files/`)) throw new Error('No matching augmentation backup.');
      const backupRequest = new Request(new URL(asset.fallback_url, `${globalThis.location.origin}/`), input instanceof Request ? input : init);
      const response = await nativeFetch(backupRequest, init);
      if (!response.ok || response.headers.get('x-bted-sha256') !== asset.sha256 || response.headers.get('x-bted-revision') !== metadata.revision) throw new Error('Augmentation backup mismatched.');
      backupAssets.add(url);
      return response;
    }
    let asset;
    if (condition) {
      const sourceId = condition[3];
      if (!conditionManifests.has(sourceId)) {
        const promise = nativeFetch(`${globalThis.location.origin}/api/sources/${sourceId}`, { signal, cache: 'no-cache' }).then(response => {
          if (!response.ok) throw new Error('Signal metadata unavailable.');
          return response.json();
        });
        conditionManifests.set(sourceId, promise);
        promise.catch(() => conditionManifests.delete(sourceId));
      }
      const payload = await conditionManifests.get(sourceId);
      const entry = payload.source?.assets?.find(a => a.logical_path === condition[1] && a.asset_kind === 'bigwig');
      if (payload.release?.release_version !== 'v0.4.0' || payload.source?.assembly_accession !== condition[2]
          || payload.source?.source_id !== sourceId || !/^[0-9a-f]{64}$/.test(entry?.sha256 || '')) throw new Error('Signal metadata mismatched.');
      asset = { url: entry.origin_url, sha256: entry.sha256, fallback_url: `/api/assets/${entry.asset_key}` };
    } else {
      releaseManifest ||= nativeFetch(`${globalThis.location.origin}/assets/data-release.json`, { cache: 'no-cache' }).then(response => {
        if (!response.ok) throw new Error('Data manifest unavailable.');
        return response.json();
      });
      const manifest = await releaseManifest;
      if (manifest.releaseVersion !== 'v0.4.0') throw new Error('Data manifest mismatched.');
      asset = manifest.assets?.[decodeURIComponent(match[1])];
    }
    if (asset?.url !== url ||
        !/^\/api\/assets\/v0\.4\.0--[0-9a-f]{64}$/.test(asset.fallback_url || '')) throw originalError || new Error('No matching backup asset.');
    const backupRequest = new Request(new URL(asset.fallback_url, `${globalThis.location.origin}/`), input instanceof Request ? input : init);
    const response = await nativeFetch(backupRequest, init);
    if (!response.ok || response.headers.get('x-bted-sha256') !== asset.sha256) throw new Error('Backup asset unavailable or mismatched.');
    backupAssets.add(url);
    return response;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw originalError || error;
  }
}
// Version-pinned data can be reused across iframe loads and adapter workers.
// Cache Storage cannot store 206 directly: the internal entry is 200, and the
// original status and Range headers are restored when that exact slice is read.
const ASSET_CACHE = 'bted-genome-slices-v1';
const MAX_CACHED_SLICE = 512 * 1024;
const MAX_CACHED_SLICES = 128;
function immutableGenomeUrl(value) {
  if (/^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.[345]\.0\//.test(value)) return true;
  if (/^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/v0\.5\.1\/annotation-recovery\/2026-10-14\/genomes\/[A-Za-z0-9_.-]+\/genes\.gff3$/.test(value)) return true;
  try {
    const url = new URL(value, globalThis.location.origin);
    return url.origin === globalThis.location.origin &&
      (/^\/api\/assets\/v0\.4\.0--[0-9a-f]{64}$/.test(url.pathname) ||
       /^\/api\/batter\/[A-Za-z0-9_.-]+\/files\/[^/]+$/.test(url.pathname) &&
       /^[0-9a-f]{40}$/.test(url.searchParams.get('revision') || ''));
  } catch { return false; }
}
export async function fetchBtedAsset(input, init = {}) {
  const url = input instanceof Request ? input.url : String(input);
  const method = init.method || (input instanceof Request ? input.method : 'GET');
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init.headers).forEach((value, name) => headers.set(name, value));
  const signal = init.signal || (input instanceof Request ? input.signal : undefined);
  const eligible = method === 'GET' && init.cache !== 'no-store' &&
    !(input instanceof Request && input.cache === 'no-store') &&
    immutableGenomeUrl(url) &&
    !['authorization', 'if-range', 'if-none-match', 'if-modified-since'].some(name => headers.has(name));
  let cache;
  let key;
  if (eligible && globalThis.caches) {
    signal?.throwIfAborted();
    try {
      cache = await globalThis.caches.open(ASSET_CACHE);
      key = new URL(globalThis.location.origin);
      key.pathname = '/__bted-genome-cache__';
      key.searchParams.set('asset', url);
      key.searchParams.set('range', headers.get('range') || '');
      const stored = await cache.match(key.href);
      signal?.throwIfAborted();
      if (stored) {
        const restoredHeaders = new Headers(stored.headers);
        const status = Number(restoredHeaders.get('x-bted-cached-status'));
        restoredHeaders.delete('x-bted-cached-status');
        return new Response(stored.body, { status, headers: restoredHeaders });
      }
    } catch (error) {
      if (signal?.aborted) throw error;
      cache = undefined; // Private mode/quota failures must not block browsing.
    }
  }
  const response = await fetchRegisteredBtedAsset(input, init);
  const size = Number(response.headers.get('content-length'));
  if (cache && [200, 206].includes(response.status) && size > 0 && size <= MAX_CACHED_SLICE) {
    try {
      const bytes = await response.clone().arrayBuffer();
      signal?.throwIfAborted();
      if (bytes.byteLength === size && bytes.byteLength <= MAX_CACHED_SLICE) {
        const storedHeaders = new Headers(response.headers);
        storedHeaders.set('x-bted-cached-status', String(response.status));
        storedHeaders.delete('vary'); // Exact URL and range are encoded in the key.
        await cache.put(key.href, new Response(bytes, { headers: storedHeaders }));
        const keys = await cache.keys();
        for (const old of keys.slice(0, Math.max(0, keys.length - MAX_CACHED_SLICES))) await cache.delete(old);
      }
    } catch (error) {
      if (signal?.aborted) throw error;
    }
  }
  return response;
}
if (/^https?:\/\//.test(globalThis.location?.origin || '')) globalThis.fetch = fetchBtedAsset;

function signalValue(feature) {
  const raw = feature.get('summary') ? feature.get('maxScore') : feature.get('score');
  const number = Number(raw);
  return Number.isFinite(number) ? Math.max(0, number) : 0;
}

export function paintMirroredSignal(ctx, features, region, bpPerPx, width, height = MIRROR_HEIGHT, scaleMax, scaleType = 'linear') {
  const baseline = height / 2;
  const observed = [...features].filter((feature) => ['plus', 'minus'].includes(feature.get('source')));
  if (!Number.isFinite(scaleMax) || scaleMax <= 0) throw new Error('Visible-window signal scale is unavailable');
  const maximum = scaleMax;
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
    const value = signalValue(feature);
    const fraction = scaleType === 'log' ? Math.log1p(value) / Math.log1p(maximum) : value / maximum;
    const magnitude = Math.min(1, fraction) * (baseline - 14);
    if (!magnitude) continue;
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

export function augmentationColor(feature) {
  const attributes = feature?.get?.('attributes') || {};
  const value = attributes.dataset_class;
  const dataset = Array.isArray(value) ? value[0] : value;
  if (['training_sequence_window', 'rfam_training_window'].includes(feature?.get?.('type'))) return dataset === 'rfam_training_window' ? '#ddd6fe' : '#bfdbfe';
  return strandColor(feature);
}

export function isBtedScientificFeature(feature) {
  return /^(?:BATTER|BTED)(?:[_-]|$)/.test(feature.get('source') || '') &&
    ['terminator_endpoint', 'augmented_terminator_span', 'rfam_training_span',
      'predicted_terminator_region', 'training_sequence_window', 'rfam_training_window'].includes(feature.get('type'));
}

// Predictions contain intervals, not independently resolved single-base 3′ end sites.
export function predictionTooltip(feature) {
  const strand = feature.get('strand');
  const plus = strand === 1 || strand === '+';
  const minus = strand === -1 || strand === '-';
  const start = feature.get('start') + 1, end = feature.get('end');
  const format = coordinate => Number(coordinate).toLocaleString('en-US');
  return `${feature.get('refName')}:${format(start)}–${format(end)} (${plus ? '+' : minus ? '−' : '?'}) · ${format(end - start + 1)} bp` +
    (plus || minus ? ` · 3′ boundary: ${format(plus ? end : start)}` : '') +
    ` · Score: ${feature.get('score') ?? 'Unavailable'}`;
}

// Native Box layout reserves space for a 7 px direction marker and provides hit detection.
export function drawBtedScientificFeature({ ctx, feature, featureLayout: box, reversed, canvasWidth }) {
  const type = feature.get('type');
  const directionalRegion = ['augmented_terminator_span', 'rfam_training_span', 'predicted_terminator_region'].includes(type);
  const color = type === 'terminator_endpoint' || directionalRegion ? strandColor(feature) : augmentationColor(feature);
  const strand = feature.get('strand');
  const direction = (strand === 1 || strand === '+' ? 1 : strand === -1 || strand === '-' ? -1 : 0) * (reversed ? -1 : 1);
  const left = box.x, right = left + box.width;
  if (right + 7 < 0 || left - 7 > canvasWidth) return;
  const height = box.height, top = box.y, mid = top + height / 2;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.25;
  if (type === 'training_sequence_window' || type === 'rfam_training_window') {
    ctx.fillRect(left, top + height * 0.2, box.width, height * 0.6);
    return;
  }
  const endpoint = type === 'terminator_endpoint';
  // Single-base endpoints anchor at the base center; region flags anchor at the original 3′ boundary.
  const anchor = endpoint ? left + box.width / 2 : direction > 0 ? right : left;
  if (direction) {
    // Like RAPPTOR, attach the flag at the pole top and extend the pole only downward.
    const poleHeight = Math.min(12, height - 2);
    const flagHeight = poleHeight / 2;
    const flagTop = mid - poleHeight / 2, flagBottom = flagTop + flagHeight;
    const flagMid = flagTop + flagHeight / 2;
    // The bar shows the original region span and meets the foot of the boundary flag.
    if (!endpoint) ctx.fillRect(left, flagTop + poleHeight - 3, box.width, 3);
    ctx.beginPath();
    ctx.moveTo(anchor, flagTop);
    ctx.lineTo(anchor + direction * 6, flagTop);
    ctx.lineTo(anchor + direction * 4, flagMid);
    ctx.lineTo(anchor + direction * 6, flagBottom);
    ctx.lineTo(anchor, flagBottom);
    ctx.closePath();
    if (endpoint) ctx.fill();
    else ctx.stroke();
    ctx.strokeStyle = '#1f2937';
    ctx.beginPath();
    ctx.moveTo(anchor, flagTop);
    ctx.lineTo(anchor, flagTop + poleHeight);
    ctx.stroke();
    // JBrowse builds hit bounds after draw(); include the full interval and the flag on either strand.
    const hitLeft = Math.min(endpoint ? anchor : left, anchor + direction * 6) - 1;
    const hitRight = Math.max(endpoint ? anchor : right, anchor + direction * 6) + 1;
    box.x = hitLeft;
    box.totalLayoutWidth = hitRight - hitLeft;
  } else if (endpoint) {
    ctx.beginPath();
    ctx.moveTo(anchor, top);
    ctx.lineTo(anchor, top + height);
    ctx.stroke();
  } else {
    // With no strand, no 3′ boundary can be chosen: preserve the interval as a neutral bar.
    const barHeight = Math.max(3, Math.min(6, height * 0.55));
    ctx.fillRect(left, mid - barHeight / 2, box.width, barHeight);
  }
}

// Counts describe published records across the entire contig, not the viewport or signal coverage.
export function experimentalContigCoverage(tracks, assemblyName, refName) {
  const endpoints = tracks.filter(track => track.assemblyNames?.includes(assemblyName) &&
    track.metadata?.btedAbout?.kind === 'endpoint');
  if (!endpoints.length) return { status: 'unavailable', count: null };
  let count = 0;
  for (const track of endpoints) {
    const counts = track.metadata.btedContigCounts;
    if (!counts || Object.values(counts).some(n => !Number.isSafeInteger(n) || n < 0)) {
      return { status: 'unknown', count: null };
    }
    count += counts[refName] || 0;
  }
  return { status: count ? 'covered' : 'empty', count };
}

export function endpointTrackCount(track, refName) {
  if (track?.metadata?.btedAbout?.kind !== 'endpoint') return null;
  const coverage = experimentalContigCoverage([track], track.assemblyNames?.[0], refName);
  return { status: coverage.status,
    text: coverage.count === null ? 'Count unavailable' : `${coverage.count.toLocaleString('en-US')} ${coverage.count === 1 ? 'record' : 'records'}`,
    title: coverage.count === null ? 'Count unavailable' :
      `${refName} · ${coverage.count.toLocaleString('en-US')} ${coverage.count === 1 ? 'record' : 'records'} · Whole contig, both strands` };
}

export function scientificTrackCount(track, refName) {
  const kind = track?.metadata?.btedAbout?.kind;
  if (kind === 'endpoint') return { ...endpointTrackCount(track, refName), kind };
  if (!['augmentation', 'prediction'].includes(kind)) return null;
  const counts = track.metadata.btedContigCounts;
  const count = counts && Object.values(counts).every(n => Number.isSafeInteger(n) && n >= 0)
    ? counts[refName] ?? null : null;
  const detail = track.metadata.btedContigBreakdown?.[refName];
  const breakdown = kind === 'augmentation' && detail
    ? ` · OTU: ${detail.otu.toLocaleString('en-US')}; Rfam: ${detail.rfam.toLocaleString('en-US')}` : '';
  return { kind, status: count === null ? 'unknown' : count ? 'covered' : 'empty',
    text: count === null ? 'Count unavailable' : `${count.toLocaleString('en-US')} ${count === 1 ? 'region' : 'regions'}`,
    title: count === null ? 'Count unavailable' :
      `${refName} · ${count.toLocaleString('en-US')} ${count === 1 ? 'region' : 'regions'} · Whole contig, both strands${breakdown}` };
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

export function downloadUrl(raw) {
  const url = safeLink(raw);
  if (!url) return '';
  const parsed = new URL(url);
  if (parsed.origin === window.location.origin) return url;
  if (parsed.hostname === 'huggingface.co' &&
      /^\/datasets\/liurulong\/terminator\/resolve\/[0-9a-f]{40}\/(?:v0\.[34]\.0\/|v0\.5\.0\/genomes\/batter-\d{3}\/[A-Za-z0-9_.-]+\/(?:reference|training|predictions|annotations\/batter)\/)/.test(parsed.pathname)) return url;
  return '';
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

export async function showDefaultLocalReference(view, assembly, assemblyName) {
  const refName = view?.displayedRegions?.[0]?.refName;
  const reference = assembly?.regions?.find((region) => region.refName === refName);
  const start = Number(reference?.start ?? 0);
  const end = Number(reference?.end);
  if (!reference || !Number.isFinite(start) || !Number.isFinite(end) || end <= start ||
      !Number.isFinite(view.width) || view.width <= 0 ||
      !Number.isFinite(view.bpPerPx) || view.bpPerPx <= 0 ||
      !Number.isFinite(view.offsetPx)) {
    throw new Error('The reference sequence is unavailable.');
  }
  const initialSpan = view.bpPerPx * 1000;
  const center = Math.min(end, Math.max(start + 1,
    Math.round(start + (view.offsetPx + 500) * view.bpPerPx)));
  await view.navToLocString(`${refName}:${center}`, assemblyName);
  view.zoomTo(Math.max(0.001, initialSpan / view.width), view.width / 2);
}

export default class BTEDTrackPlugin {
  name = 'BTEDTrackPlugin';
  version = '1.0.0';

  // JBrowse 4.3.0 calls configure() on every installed plugin.
  configure() {}

  install(pluginManager) {
    pluginManager.jexl.addFunction('btedStrandColor', strandColor);
    pluginManager.jexl.addFunction('btedAugmentationColor', augmentationColor);
    pluginManager.jexl.addFunction('btedPredictionTooltip', predictionTooltip);
    const React = pluginManager.jbrequire('react');
    const { readConfObject, getConf, ConfigurationSchema } = pluginManager.jbrequire('@jbrowse/core/configuration');
    const { getContainingTrack, getContainingView, getSession } = pluginManager.jbrequire('@jbrowse/core/util');
    const { Dialog } = pluginManager.jbrequire('@jbrowse/core/ui');
    const FeatureRendererType = pluginManager.jbrequire('@jbrowse/core/pluggableElementTypes/renderers/FeatureRendererType').default;
    const h = React.createElement;

    pluginManager.addGlyphType(() => {
      const { GlyphType } = pluginManager.jbrequire('@jbrowse/core/pluggableElementTypes');
      return new GlyphType({ name: 'BTEDScientificGlyph', priority: 100,
        match: isBtedScientificFeature, draw: drawBtedScientificFeature });
    });

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
        const scoreMax = args.scaleOpts?.stats?.scoreMax;
        const sharedMax = scoreMax === 0 ? 1 : scoreMax;
        const visibleMax = paintMirroredSignal(ctx, features.values(), region, args.bpPerPx, width, height, sharedMax, args.scaleOpts?.scaleType);
        return { features, width, height, visibleMax, signalScale: args.scaleOpts?.scaleType, pixelData: ctx.getImageData(0, 0, width, height).data };
      }
    }

    pluginManager.addRendererType((pm) => new MirroredSignalRenderer({
      name: MIRROR_RENDERER,
      ReactComponent: MirroredRendering,
      configSchema: ConfigurationSchema(MIRROR_RENDERER, {}, { explicitlyTyped: true }),
      pluginManager: pm,
    }));
    pluginManager.addToExtensionPoint('Core-extendSession', model => model.extend(self => {
      const originalMenu = self.getTrackActionMenuItems;
      return { views: { getTrackActionMenuItems(config, extra) {
        const items = originalMenu(config, extra);
        return isBtedEmbed() && metadataFor(config, readConfObject, getConf) ? compactTrackActions(items,
          Boolean(readConfObject(config)?.metadata?.btedDownloads?.length)) : items;
      } } };
    }));
    pluginManager.addToExtensionPoint('Core-extendPluggableElement', (element) => {
      if (element.name === 'LinearGenomeView') {
        element.stateModel = element.stateModel.extend(self => {
          const originalMenu = self.menuItems;
          return { views: { menuItems() {
            const items = originalMenu();
            if (!isBtedEmbed()) return items;
            const mirrored = self.tracks.some(track => getConf(track, 'metadata')?.btedMirroredSignal);
            return items.filter(item => item.label !== 'Return to import form' &&
              !(mirrored && item.label === 'Export SVG')).map(item => item.label === 'Show...' ? {
                ...item, subMenu: item.subMenu.filter(child => child.label !== 'Show header'),
              } : item);
          } } };
        });
        return element;
      }
      if (['FeatureTrack', 'MultiQuantitativeTrack', 'ReferenceSequenceTrack'].includes(element.name)) {
        element.stateModel = element.stateModel.extend(self => {
          const originalMenu = self.trackMenuItems;
          return { views: { trackMenuItems() {
            const items = originalMenu();
            if (!isBtedEmbed() || !metadataFor(self.configuration, readConfObject, getConf)) return items;
            return items.filter(item => item.label !== 'Display types' || element.name === 'ReferenceSequenceTrack')
              .map(item => item.label === 'Display types' ? { ...item, label: 'Sequence display' } : item);
          } } };
        });
        return element;
      }
      if (element.name === 'LinearBasicDisplay') {
        element.stateModel = element.stateModel.extend((self) => {
          const originalMenu = self.trackMenuItems;
          return { views: {
            get prefersOffset() {
              return ['endpoint', 'prediction', 'augmentation'].includes(metadataFor(getContainingTrack(self).configuration, readConfObject, getConf)?.kind);
            },
            trackMenuItems() {
            const items = originalMenu();
            const kind = metadataFor(getContainingTrack(self).configuration, readConfObject, getConf)?.kind;
            return withDownloadMenu(self, isBtedEmbed() && kind ? compactFeatureMenu(items, self, kind) : items);
          } } };
        });
        return element;
      }
      if (element.name !== 'MultiLinearWiggleDisplay') return element;
      const native = { xyplot: 'MultiXYPlotRenderer', multirowxy: 'MultiRowXYPlotRenderer',
        multirowdensity: 'MultiDensityRenderer', multiline: 'MultiLineRenderer', multirowline: 'MultiRowLineRenderer' };
      element.stateModel = element.stateModel.extend((self) => {
        const originalMenu = self.trackMenuItems;
        return { views: {
          get autoscaleType() {
            return isMirrored(self) ? 'local' : self.autoscale ?? getConf(self, 'autoscale');
          },
          get rendererTypeName() {
            return isMirrored(self) ? MIRROR_RENDERER : native[self.rendererTypeNameSimple] || 'MultiXYPlotRenderer';
          },
          trackMenuItems() {
            const items = originalMenu();
            if (!isMirrored(self)) return withDownloadMenu(self, items);
            const hidden = new Set(['Renderer type', 'Edit colors/arrangement...', 'Fill mode', 'Show sidebar']);
            return withDownloadMenu(self, items.filter(item => !hidden.has(item.label)).map(item =>
              item.label === 'Score' ? { ...item, label: 'Signal scale',
                subMenu: item.subMenu.filter(child => ['Autoscale type', 'Scale type'].includes(child.label)).map(child =>
                  child.label === 'Scale type' ? { ...child, subMenu: child.subMenu.map(option => ({
                    ...option, label: option.label === 'Log scale' ? 'Log (1 + value)' : 'Linear',
                  })) } : {
                    ...child, label: 'Scale to', subMenu: child.subMenu.filter(option => option.label === 'Local')
                      .map(option => ({ ...option, label: 'Visible window' })),
                  }) } : item));
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
      const evidence = kind === 'reference' ? null : section(kind === 'signal' ? 'Experimental signal' : kind === 'augmentation' ? 'Augmentation / Rfam regions' : kind === 'prediction' ? 'Model prediction' : 'Endpoint evidence', [
        facts([
          ['Method', about.assay], ['Strand', about.strand],
          ['Sample', kind === 'signal' ? about.sample_id : ''],
          ['Conditions', kind === 'signal' ? about.conditions : ''],
          ['Coverage', kind === 'signal' ? about.coverage : ''],
          ['Records (genome)', kind === 'endpoint' ? about.record_count : ''],
          ['Regions (genome)', ['augmentation', 'prediction'].includes(kind) ? about.record_count : ''],
          ['Evidence', kind === 'endpoint' ? about.evidence : ''],
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
          ['Raw data', about.raw_data_url],
          ['NCBI assembly', about.reference_url],
        ]),
      ]);
      return h('div', { className: 'bted-about', ref: node => {
        const title = node?.closest('[role="dialog"]')?.querySelector('.MuiDialogTitle-root > span');
        if (title) title.textContent = title.textContent.replace(/^(?:BATTER|BTED)_[A-Za-z0-9_]+\s*·\s*/, '');
      } },
        h('style', null, '.MuiDialog-paper:has(.bted-about){width:min(820px,calc(100vw - 28px));max-width:820px}.bted-about{box-sizing:border-box;padding:14px 24px 24px;color:#20342f;font:13px/1.5 Arial,sans-serif}.bted-about-lead{margin:0 0 6px;padding:11px 14px;border-left:3px solid #0f766e;background:#eff7f4;color:#344c45}.bted-about-section{margin-top:18px;padding-top:14px;border-top:1px solid #dce7e2}.bted-about-section h3{margin:0 0 8px;color:#35554c;font:750 11px/1.3 Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase}.bted-about-facts{margin:0}.bted-about-facts>div{display:grid;grid-template-columns:minmax(120px,27%) minmax(0,1fr);gap:14px;border-bottom:1px solid #edf1ef;padding:8px 0}.bted-about-facts>div:last-child{border-bottom:0}.bted-about-facts dt{color:#60766e;font-size:11px;font-weight:750;letter-spacing:.035em;text-transform:uppercase}.bted-about-facts dd{min-width:0;margin:0;overflow-wrap:anywhere;font-size:13px}.bted-about-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:13px}.bted-about-action{display:inline-flex;align-items:center;min-height:34px;padding:6px 11px;border:1px solid #0f766e;border-radius:4px;background:#0f766e;color:white!important;font-weight:700;text-decoration:none}.bted-about-action:hover{background:#115e55}.bted-about-action:focus-visible{outline:3px solid #8acabd;outline-offset:2px}@media(max-width:600px){.bted-about{padding:12px 14px 18px}.bted-about-facts>div{grid-template-columns:1fr;gap:2px}.bted-about-links{display:grid}.bted-about-action{justify-content:center}}'),
        kind === 'signal' ? h('p', { className: 'bted-about-lead' }, '+ strand above zero; − strand below.') : null,
        study, evidence, provenance);
    }

    // Keep native detail, track selection and import callbacks intact.
    // The portal only changes where the widget is rendered in the genome page.
    const widgetTitles = { BaseFeatureWidget: 'Feature details',
      HierarchicalTrackSelectorWidget: 'Tracks', AddTrackWidget: 'Import tracks' };
    const externalWidgets = new WeakMap();
    pluginManager.addToExtensionPoint('Core-replaceWidget', (Original, { model }) => {
      if (!isBtedEmbed() || !widgetTitles[model?.type]) return Original;
      let host;
      try {
        host = window.parent.document.querySelector('[data-browser-feature-details]');
      } catch { return Original; }
      const target = host?.querySelector('[data-feature-details-content]')?.shadowRoot
        ?.querySelector('[data-native-feature-details]');
      if (!target) return Original;
      // Set before the drawer commit, preventing even a transient layout shrink.
      document.documentElement.dataset.btedExternalDetails = '';
      if (!externalWidgets.has(Original)) {
        const { createPortal } = pluginManager.jbrequire('react-dom');
        const { ThemeProvider, useTheme } = pluginManager.jbrequire('@mui/material/styles');
        function ExternalFeatureDetails(props) {
          const theme = useTheme();
          const [importSource, setImportSource] = React.useState('local');
          const [importError, setImportError] = React.useState('');
          const portalTheme = React.useMemo(() => ({ ...theme, components: {
            ...theme.components,
            ...Object.fromEntries(['MuiPopover', 'MuiPopper', 'MuiModal'].map(name => [name, {
              ...theme.components?.[name],
              defaultProps: { ...theme.components?.[name]?.defaultProps, container: target },
            }])),
          } }), [theme]);
          React.useEffect(() => {
            const close = host.querySelector('[data-close-feature-details]');
            const title = widgetTitles[props.model.type];
            host.querySelector('h2').textContent = title;
            target.dataset.widgetType = props.model.type;
            close.setAttribute('aria-label', `Close ${title.toLowerCase()}`);
            const note = host.querySelector('[data-browser-widget-note]');
            note.hidden = props.model.type !== 'AddTrackWidget';
            note.textContent = props.model.type === 'AddTrackWidget'
              ? 'Use matching reference and contig names. Local files stay in your browser.' : '';
            const closeDetails = () => {
              props.session.hideWidget(props.model);
              window.frameElement?.focus({ preventScroll: true });
            };
            const escape = event => { if (event.key === 'Escape') closeDetails(); };
            const style = document.createElement('style');
            target.prepend(style);
            // Emotion inserts rules through CSSOM. Copy after native content
            // changes so newly expanded properties receive their original styles.
            let update;
            function syncStyles() {
              cancelAnimationFrame(update);
              update = requestAnimationFrame(() => {
                style.textContent = [...document.styleSheets].map(sheet => {
                  try { return [...sheet.cssRules].map(rule => rule.cssText).join('\n'); }
                  catch { return ''; }
                }).join('\n') + `
                  [data-native-feature-details]{color:#3b303b;font:14px/1.5 Arial,sans-serif}
                  .MuiAccordion-root{box-shadow:none!important;border:1px solid #e7dce4}
                  .MuiAccordionSummary-root{background:#faf7f9!important}
                  .MuiAccordionDetails-root{padding:12px 14px!important}
                  .MuiAccordionDetails-root > p{margin:10px 0 6px;font-weight:600;color:#4b2d47}
                  .css-2imjyh{display:grid;grid-template-columns:110px minmax(0,1fr);border-bottom:1px solid #eee8ed;font-size:13px}
                  .css-c392m0{width:auto!important;padding:5px 9px;background:#faf7f9;overflow-wrap:anywhere}
                  .css-1rdet1e{padding:5px 9px;overflow-wrap:anywhere}
                  [data-widget-type="HierarchicalTrackSelectorWidget"] .MuiFab-root{display:none}
                  [data-widget-type="AddTrackWidget"] [aria-label="local file"]{display:none}
                  .bted-local-track-files{display:grid;gap:12px;margin:8px 0 18px;padding:12px;border:1px solid #e7dce4;border-radius:6px;background:#faf7f9}
                  .bted-local-track-files label{display:grid;gap:5px;font-size:12px;font-weight:600}
                  .bted-local-track-files input{max-width:100%;font:12px Arial,sans-serif}
                  .bted-local-track-files p{margin:0;font-size:12px}
                  .bted-import-source{display:flex;gap:8px;margin:4px 0 12px}
                  .bted-import-source button{padding:7px 12px;border:1px solid #d8cbd5;border-radius:6px;background:#fff;color:#4b2d47;cursor:pointer;font:600 12px Arial,sans-serif}
                  .bted-import-source button[aria-pressed="true"]{background:#f0e7ef;border-color:#986389}
                  .bted-import-source button:focus-visible{outline:2px solid #986389;outline-offset:2px}
                  .bted-native-import > .MuiFormControl-root{display:none}
                  .bted-native-import--local .MuiPaper-root:has([aria-label="file, url, or account picker"]){display:none}
                  @media(max-width:600px){.css-2imjyh{grid-template-columns:110px minmax(0,1fr)}}
                `;
              });
            }
            const observer = new MutationObserver(records => {
              if (records.some(record => record.target !== style && !style.contains(record.target))) syncStyles();
            });
            observer.observe(target, { childList: true, subtree: true, attributes: true });
            observer.observe(document.head, { childList: true, subtree: true });
            syncStyles();
            host.hidden = false;
            document.documentElement.dataset.btedExternalDetails = '';
            close.addEventListener('click', closeDetails);
            host.addEventListener('keydown', escape);
            close.focus({ preventScroll: true });
            const onUnload = () => { host.hidden = true; };
            window.addEventListener('pagehide', onUnload);
            return () => {
              observer.disconnect();
              cancelAnimationFrame(update);
              style.remove();
              host.hidden = true;
              delete document.documentElement.dataset.btedExternalDetails;
              close.removeEventListener('click', closeDetails);
              host.removeEventListener('keydown', escape);
              window.removeEventListener('pagehide', onUnload);
            };
          }, [props.model, props.session]);
          // Native File System pickers run in the iframe's window, which lacks
          // activation after a click in the outer portal. HTML file inputs live
          // with the portal; use JBrowse's blob registry and native import form.
          const importing = props.model.type === 'AddTrackWidget';
          const localFiles = importing && importSource === 'local' ? h('div', { className: 'bted-local-track-files' },
            h('label', null, 'Track file', h('input', { type: 'file', multiple: true, onChange: event => {
              const files = [...(event.target.files || [])];
              if (!files.length) return;
              props.model.setTrackData(undefined);
              props.model.setIndexTrackData(undefined);
              try {
                const selected = selectLocalTrackFiles(files);
                const location = file => pluginManager.jbrequire('@jbrowse/core/util/tracks').storeBlobLocation({
                  // RPC serialization expects the iframe's File realm.
                  blob: new File([file], file.name, { type: file.type, lastModified: file.lastModified }),
                });
                props.model.setTrackData(location(selected.track));
                if (selected.index) props.model.setIndexTrackData(location(selected.index));
                setImportError('');
              } catch (error) { setImportError(error.message); }
            } })),
            h('p', null, 'BED, GFF3 and BigWig: select one file. BAM or indexed compressed tracks: select the track and its matching index together.'),
            importError ? h('p', { role: 'alert' }, importError) : null) : null;
          const nativeImport = h(Original, { ...props, toolbarHeight: 0, modal: true,
            ...(props.model.type === 'HierarchicalTrackSelectorWidget' ? {
              overrideDimensions: { height: 'min(480px, calc(100dvh - 240px))', position: 'relative' },
            } : {}),
          });
          return createPortal(h(ThemeProvider, { theme: portalTheme },
            ...(importing ? [h('div', { className: 'bted-import-source', role: 'group', 'aria-label': 'Track source' },
              ...[['local', 'Local file'], ['remote', 'Remote URL']].map(([source, label]) => h('button', {
                key: source, type: 'button', 'aria-pressed': importSource === source,
                onClick: () => {
                  if (source === importSource) return;
                  props.model.clearData();
                  setImportError('');
                  setImportSource(source);
                },
              }, label)))] : []),
            ...(localFiles ? [localFiles] : []),
            importing ? h('div', { key: importSource, className: `bted-native-import${importSource === 'local' ? ' bted-native-import--local' : ''}` }, nativeImport) : nativeImport), target);
        }
        externalWidgets.set(Original, ExternalFeatureDetails);
      }
      return externalWidgets.get(Original);
    });

    pluginManager.addToExtensionPoint('Core-replaceAbout', (Original, props) =>
      metadataFor(props?.config, readConfObject, getConf) ? BTEDAbout : Original);

    if (typeof document !== 'undefined' && document.head) {
      const navigationStyle = document.createElement('style');
      navigationStyle.textContent = `
        /* Native JBrowse overview-to-window geometry, in both browser modes. */
        .css-11ojfo7 > svg > polygon { fill: #805277; fill-opacity: .32; stroke: #603355; stroke-opacity: 1; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
      `;
      document.head.append(navigationStyle);
    }

    if (typeof window !== 'undefined' && window.parent && window.parent !== window &&
        typeof window.addEventListener === 'function') {
      const nonce = new URLSearchParams(window.location.search).get('bted_bridge');
      if (nonce) {
        // The genome page supplies the title and sharing controls. Advanced
        // session/view management belongs in the full browser; keep the
        // coordinate toolbar and track selector available in the embed.
        // Selectors below match the pinned JBrowse 4.3.0 header structure.
        const compactEmbed = document.createElement('style');
        compactEmbed.textContent = `
          html[data-bted-external-details] #root > [style*="grid-template-columns"] {
            grid-template-columns: [main] minmax(0, 1fr) !important;
          }
          html[data-bted-external-details] .MuiPaper-root:has([data-testid="widget-drawer-selects"]) {
            display: none !important;
          }
          header.MuiAppBar-root:has(> .MuiToolbar-root > [aria-label="Rename session"]),
          [data-testid^="view-container-"]:first-child:not(:has(~ [data-testid^="view-container-"])) > :first-child,
          [data-testid^="view-container-"] + .css-vycneo { display: none !important; }
          html, body, #root { background: #fff !important; }
          [data-testid^="view-container-"] {
            margin: 0 !important; padding: 0 !important; border-radius: 0 !important;
            background: #fff !important; box-shadow: none !important;
          }
          [data-testid^="view-container-"] > .MuiPaper-root { border-radius: 0 !important; }
          [data-testid^="view-container-"]:first-child:not(:has(~ [data-testid^="view-container-"])) .css-1dv8lbb {
            top: 0 !important;
          }
          [data-testid^="view-container-"]:first-child:not(:has(~ [data-testid^="view-container-"])) [data-testid="rubberband_controls"] {
            transform: translateY(-28px);
          }
          [data-testid^="view-container-"] + [data-testid^="view-container-"] { border-top: 1px solid #e4dce2; }
          .bted-track-count { flex-shrink: 0; margin: 0 7px; padding: 2px 7px; border: 1px solid #d8cbd5; border-radius: 4px; background: #fff; color: #5b3c53; font: 600 11px/1.4 Arial,sans-serif; white-space: nowrap; }
          .bted-track-count[data-state="empty"] { color: #68717b; background: #f4f5f6; border-color: #dce0e4; }
          .bted-track-count::before { content: ''; display: inline-block; width: 9px; height: 10px; margin-right: 5px; vertical-align: -1px; background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 9 10'%3E%3Cpath d='M1 1V9M1 1h7L6 3.5l2 2.5H1Z' fill='none' stroke='%23737780' stroke-width='1' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat center; }
          .bted-track-count[data-kind="endpoint"]::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 9 10'%3E%3Cpath d='M1 1V9M1 1h7L6 3.5l2 2.5H1Z' fill='%23737780' stroke='%23737780' stroke-width='1' stroke-linejoin='round'/%3E%3C/svg%3E"); }
          [data-testid^="trackRenderingContainer-"] { border-bottom: 1px solid #eee8ed; }
          /* Pinned JBrowse overview and coordinate toolbar; keep data colors unchanged. */
          .css-1dv8lbb { background: #f4eff4 !important; border-bottom: 1px solid #c7b7c4; color: #4b2d47; }
          .css-1y73v8g { background: #fcfafc !important; }
          .css-8i8koh .MuiTypography-root { color: #4b2d47 !important; }
          .css-8i8koh .css-pohvk8 { border-color: #b8a3b3 !important; background-color: #fcfafc; }
          .css-8i8koh .css-evrjnx { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 15 9'%3E%3Cpath d='M-.1 0L6 4.5L-.1 9' fill='none' stroke='%23c4b1bf'/%3E%3C/svg%3E"); }
          /* Native narrow windows can be one pixel wide: keep their location visible. */
          .css-8i8koh .css-1nyqiym { min-width: 3px; background: rgba(128,82,119,.28) !important; border: 1px solid #603355 !important; box-shadow: 0 0 0 1px rgba(255,255,255,.8); }
          .css-11ojfo7 { background: #fcfafc; }
          .css-1dv8lbb .MuiIconButton-root { color: #65425e; }
          .css-1dv8lbb .MuiButton-outlined { border-color: #a98aa2; color: #54334e; background: #fff; }
          .css-1dv8lbb .MuiSlider-root { color: #805277; }
          .css-1dv8lbb .MuiSlider-rail { background-color: #bdacb8; opacity: 1; }
          .css-1dv8lbb .MuiSlider-thumb { border: 2px solid #fff; box-shadow: 0 0 0 1px #805277; }
          [data-testid="autocomplete"] .MuiOutlinedInput-root { border-radius: 5px; background: #fff; }
          [data-testid="autocomplete"] .MuiOutlinedInput-notchedOutline { border-color: #b69aae; }
        `;
        document.head.append(compactEmbed);
      }
      const root = () => pluginManager.rootModel;
      const view = () => root()?.session?.views?.find((item) => item.type === 'LinearGenomeView');
      const viewReady = () => { try { return view()?.width > 0; } catch { return false; } };
      const allowed = () => new Set([
        ...(root()?.jbrowse?.tracks || []), ...(root()?.jbrowse?.assemblies || []).map(assembly => assembly.sequence),
      ].filter((track) => track && (track.type === 'ReferenceSequenceTrack' || metadataFor(track, readConfObject, getConf)))
        .map(configId).filter(Boolean));
      const trackCount = () => {
        const names = new Set(view().assemblyNames);
        const sequences = new Set((root().session.assemblies || []).filter(assembly =>
          names.has(readConfObject(assembly)?.name)).map(assembly => configId(assembly.sequence)));
        return Object.values(root().session.getTracksById()).filter(track =>
          sequences.has(configId(track)) || (readConfObject(track)?.assemblyNames || []).some(name => names.has(name))).length;
      };
      const reply = (type, id, details) => window.parent.postMessage(
        { channel: BRIDGE_CHANNEL, nonce, type, id, ...details }, window.location.origin);
      window.addEventListener('message', async (event) => {
        const message = event.data;
        if (event.origin !== window.location.origin || event.source !== window.parent ||
            message?.channel !== BRIDGE_CHANNEL || message.nonce !== nonce ||
            !['capture', 'restore', 'show-default', 'navigate', 'select-tracks', 'add-user-track'].includes(message.type)) return;
        try {
          const current = view();
          if (!current) throw new Error('The genome browser is still loading.');
          const available = allowed();
          if (message.type === 'select-tracks' || message.type === 'add-user-track') {
            if (message.type === 'select-tracks') current.activateTrackSelector();
            else {
              const session = root().session;
              const widget = session.addWidget('AddTrackWidget', 'addTrackWidget', { view: current.id });
              session.showWidget(widget);
            }
            reply('panel-opened', message.id, { trackCount: trackCount() });
          } else if (message.type === 'show-default') {
            const assemblyName = current.assemblyNames?.[0];
            const assembly = await root().session.assemblyManager.waitForAssembly(assemblyName);
            await showDefaultLocalReference(current, assembly, assemblyName);
            reply('default-shown', message.id, {});
          } else if (message.type === 'navigate') {
            if (typeof message.location !== 'string' || message.location.length > 255 ||
                /[\u0000-\u001f]/.test(message.location)) throw new Error('The reference location is invalid.');
            await current.navToLocString(message.location, current.assemblyNames?.[0]);
            reply('navigated', message.id, {});
          } else if (message.type === 'capture') {
            reply('captured', message.id, { state: sharedView(current, available),
              hasUserTracks: current.tracks.some(track => !available.has(configId(track))) });
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
          if (nonce) for (const current of root().session.views) {
            if (current.type === 'LinearGenomeView') current.setTrackLabels('overlapping');
          }
          reply('ready', '', { trackCount: trackCount(), frameHeight: Math.ceil(200 + view().tracks.reduce(
            (height, track) => height + (track.displays?.[0]?.height || 140) + 26, 0)) });
          // Keep the count with its own track; native coordinate/contig navigation remains available.
          const { reaction } = pluginManager.jbrequire('mobx');
          let labels = [];
          function updateCounts() {
            for (const { handle, summary } of labels) {
              const heading = [...document.querySelectorAll('[data-testid^="dragHandle-"]')]
                .find(element => element.dataset.testid === handle)?.parentElement;
              if (!heading) continue;
              let badge = heading.querySelector('.bted-track-count');
              if (!badge) {
                badge = document.createElement('span');
                badge.className = 'bted-track-count';
                badge.setAttribute('role', 'status');
                badge.setAttribute('aria-live', 'polite');
                heading.append(badge);
              }
              if (badge.textContent !== summary.text) badge.textContent = summary.text;
              badge.title = summary.title;
              badge.dataset.state = summary.status;
              badge.dataset.kind = summary.kind;
            }
          }
          if (reaction) {
            const dispose = reaction(() => JSON.stringify(root().session.views.flatMap(current => {
              if (current.type !== 'LinearGenomeView' || !current.width) return [];
              const left = current.pxToBp(0), right = current.pxToBp(current.width);
              const center = current.pxToBp(current.width / 2);
              const ref = center.refName && (!left.refName || left.refName === center.refName) &&
                (!right.refName || right.refName === center.refName) ? center.refName : null;
              return current.tracks.flatMap(track => {
                const config = readConfObject(track.configuration);
                const summary = scientificTrackCount(config, ref);
                if (!summary) return [];
                if (!ref) { summary.text = 'Multiple contigs'; summary.title = 'Navigate to one contig to see its track count.'; summary.status = 'unknown'; }
                return [{ handle: `dragHandle-${current.id}-${configId(track)}`, summary }];
              });
            })), state => { labels = JSON.parse(state); updateCounts(); }, { fireImmediately: true });
            // Headers mount after the view becomes ready and can remount after track actions.
            const observer = new MutationObserver(updateCounts);
            observer.observe(document.getElementById('root'), { childList: true, subtree: true });
            window.addEventListener('pagehide', () => { dispose(); observer.disconnect(); }, { once: true });
          }
        } else if (++attempts >= 80) {
          window.clearInterval(ready);
          reply('error', '', { message: 'The genome browser did not finish loading.' });
        }
      }, 250);
    }

    if (typeof window !== 'undefined' && window.parent === window &&
        new URLSearchParams(window.location.search).get('bted_default') === '1') {
      let attempts = 0;
      const ready = window.setInterval(async () => {
        const root = pluginManager.rootModel;
        const current = root?.session?.views?.find((item) => item.type === 'LinearGenomeView');
        if (current?.width > 0) {
          window.clearInterval(ready);
          try {
            const assemblyName = current.assemblyNames?.[0];
            const assembly = await root.session.assemblyManager.waitForAssembly(assemblyName);
            await showDefaultLocalReference(current, assembly, assemblyName);
            const url = new URL(window.location.href);
            url.searchParams.delete('bted_default');
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
