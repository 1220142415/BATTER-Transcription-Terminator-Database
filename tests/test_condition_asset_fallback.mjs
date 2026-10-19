import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../jbrowse-plugin/src/plugin.js', import.meta.url), 'utf8');
const snippet = source.slice(source.indexOf('const nativeFetch ='), source.indexOf('// Version-pinned data'));
const registration = JSON.parse(readFileSync(new URL('../data/registry/s021-derived-signals.json', import.meta.url)));

test('condition HF network failure uses exact D1 registered same-origin file with Range preserved', async () => {
  const signal = registration.conditions[0].signals[0];
  const calls = [];
  const payload = { release:{release_version:'v0.4.0'}, source:{ source_id:registration.source_id,
    assembly_accession:registration.genome_id, assets:[{ ...signal, logical_path:signal.path.slice(7), asset_kind:'bigwig',origin_url:signal.url }] } };
  const native = async (input, init={}) => {
    const url = input instanceof Request ? input.url : String(input);
    calls.push(url);
    if (url.startsWith('https://huggingface.co/')) throw new TypeError('Network failed');
    if (url.endsWith('/api/sources/'+registration.source_id)) return Response.json(payload);
    assert.equal(url, 'https://bted.test/api/assets/'+signal.asset_key);
    assert.equal(input.headers.get('range'), 'bytes=0-63');
    return new Response(new Uint8Array(64),{status:206,headers:{'x-bted-sha256':signal.sha256}});
  };
  const fetchAsset = new Function('globalThis', 'Request', 'Response', snippet+'\nreturn fetchRegisteredBtedAsset;')(
    { fetch:native,location:{origin:'https://bted.test'} },Request,Response);
  const response = await fetchAsset(signal.url, {headers:{range:'bytes=0-63'}});
  assert.equal(response.status,206);
  assert.equal(calls.length,3);
  await fetchAsset(signal.url,{headers:{range:'bytes=0-63'}});
  assert.equal(calls.length,4); // Reuse registered metadata and known working backup.
  payload.source.assets[0].origin_url = signal.url.replace(registration.revision,'a'.repeat(40));
  const freshFetch = new Function('globalThis', 'Request', 'Response', snippet+'\nreturn fetchRegisteredBtedAsset;')(
    { fetch:native,location:{origin:'https://bted.test'} },Request,Response);
  await assert.rejects(freshFetch(signal.url,{headers:{range:'bytes=0-63'}}));
});
