import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp,readFile,readdir,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {prepareMirrorAssets} from './prepare-lean-assets.mjs';
const body=Buffer.from('pinned Lean asset bytes');
const hash=createHash('sha256').update(body).digest('hex');
async function fixture(run){const destination=await mkdtemp(join(tmpdir(),'lean2llm-asset-test-'));try{await run(destination);}finally{await rm(destination,{recursive:true,force:true});}}
test('installs only hash-verified downloads atomically',()=>fixture(async destination=>{await prepareMirrorAssets({manifest:{'core.bin':hash},destination,fetcher:async()=>new Response(body),log:()=>{}});assert.deepEqual(await readFile(join(destination,'core.bin')),body);assert.deepEqual(await readdir(destination),['core.bin']);}));
test('reuses a valid cache without a network request',()=>fixture(async destination=>{await writeFile(join(destination,'core.bin'),body);await prepareMirrorAssets({manifest:{'core.bin':hash},destination,fetcher:async()=>{throw new Error('must not fetch');},log:()=>{}});}));
test('rejects corrupt downloads before creating an accepted file',()=>fixture(async destination=>{await assert.rejects(prepareMirrorAssets({manifest:{'core.bin':hash},destination,fetcher:async()=>new Response('corrupted bytes'),log:()=>{}}),/hash mismatch/);assert.deepEqual(await readdir(destination),[]);}));
test('rejects a corrupt cache instead of skipping validation',()=>fixture(async destination=>{await writeFile(join(destination,'core.bin'),'corrupted cache');await assert.rejects(prepareMirrorAssets({manifest:{'core.bin':hash},destination,fetcher:async()=>new Response(body),log:()=>{}}),/corrupted cache file/);}));
test('fails on HTTP errors and prevents path traversal',()=>fixture(async destination=>{await assert.rejects(prepareMirrorAssets({manifest:{'core.bin':hash},destination,fetcher:async()=>new Response('denied',{status:403}),log:()=>{}}),/HTTP 403/);await assert.rejects(prepareMirrorAssets({manifest:{'../escape':hash},destination,fetcher:async()=>new Response(body),log:()=>{}}),/Unsafe Lean asset path/);}));
