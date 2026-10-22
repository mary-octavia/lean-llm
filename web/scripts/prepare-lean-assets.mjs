import {createHash} from 'node:crypto';
import {existsSync,readFileSync,writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {gzipSync} from 'node:zlib';
const manifest=JSON.parse(readFileSync(new URL('../runtime-assets.sha256.json',import.meta.url),'utf8'));
const base=new URL('../public/lean/',import.meta.url);
const missing=Object.keys(manifest).some(path=>path!=='lean-wasm/lean.js.gz'&&!existsSync(new URL(path,base)));
if(missing)execFileSync(process.execPath,['vendor/lean-wasm/bin/fetch-assets.mjs','public/lean','--only','wasm'],{stdio:'inherit'});
if(!existsSync(new URL('lean-wasm/lean.js.gz',base)))writeFileSync(new URL('lean-wasm/lean.js.gz',base),gzipSync(readFileSync(new URL('lean-wasm/lean.js',base))));
for(const [path,expected]of Object.entries(manifest)){
 const actual=createHash('sha256').update(readFileSync(new URL(path,base))).digest('hex');
 if(actual!==expected)throw new Error(`Pinned Lean asset hash mismatch: ${path}. Expected ${expected}, got ${actual}.`);
}
console.log(`Verified SHA-256 hashes for ${Object.keys(manifest).length} pinned Lean runtime assets.`);
