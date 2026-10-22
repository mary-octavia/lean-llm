import {createHash,randomUUID} from 'node:crypto';
import {existsSync,readFileSync} from 'node:fs';
import {mkdir,readFile,rename,unlink,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {gzipSync} from 'node:zlib';

export const DEFAULT_MIRROR='https://lean2llm.com/lean/';
const MAX_ASSET_BYTES=64*1024*1024;
const sha256=bytes=>createHash('sha256').update(bytes).digest('hex');
function assetPath(name){
 if(!/^[A-Za-z0-9._/-]+$/.test(name)||name.startsWith('/')||name.split('/').some(part=>part==='..'||part==='.'))throw new Error(`Unsafe Lean asset path: ${name}`);
 return name;
}
function mirrorBase(value){
 const url=new URL(value.endsWith('/')?value:`${value}/`);
 if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash)throw new Error('Lean asset mirrors must be an HTTPS base URL without credentials, query, or fragment.');
 return url;
}
async function checkedDownload(url,expected,fetcher){
 const response=await fetcher(url,{headers:{'accept-encoding':'identity'},signal:AbortSignal.timeout(60000)});
 if(!response.ok)throw new Error(`Lean asset HTTP ${response.status}: ${url.pathname}`);
 if(Number(response.headers.get('content-length'))>MAX_ASSET_BYTES)throw new Error(`Lean asset exceeds size limit: ${url.pathname}`);
 const chunks=[];let length=0;
 if(!response.body)throw new Error(`Empty Lean asset response: ${url.pathname}`);
 for await(const chunk of response.body){length+=chunk.byteLength;if(length>MAX_ASSET_BYTES)throw new Error(`Lean asset exceeds size limit: ${url.pathname}`);chunks.push(chunk);}
 const bytes=Buffer.concat(chunks);
 const actual=sha256(bytes);
 if(actual!==expected)throw new Error(`Pinned Lean asset hash mismatch: ${url.pathname}. Expected ${expected}, got ${actual}.`);
 return bytes;
}
export async function prepareMirrorAssets({manifest,destination,mirror=DEFAULT_MIRROR,fetcher=fetch,log=console.log}){
 const origin=mirrorBase(mirror);
 for(const [name,expected]of Object.entries(manifest)){
  if(!/^[a-f0-9]{64}$/.test(expected))throw new Error(`Invalid pinned SHA256 for ${name}`);
  const file=resolve(destination,assetPath(name));
  if(existsSync(file)){
   const actual=sha256(await readFile(file));
   if(actual!==expected)throw new Error(`Pinned Lean asset hash mismatch: ${name}. Expected ${expected}, got ${actual}. Remove the corrupted cache file before retrying.`);
   continue;
  }
  log(`Fetching pinned Lean asset: ${name}`);
  const bytes=await checkedDownload(new URL(name,origin),expected,fetcher);
  await mkdir(dirname(file),{recursive:true});
  const temporary=`${file}.partial-${randomUUID()}`;
  try{await writeFile(temporary,bytes,{flag:'wx'});await rename(temporary,file);}
  finally{await unlink(temporary).catch(error=>{if(error.code!=='ENOENT')throw error;});}
 }
 log(`Verified SHA-256 hashes for ${Object.keys(manifest).length} pinned Lean runtime assets.`);
}

async function main(){
 const web=resolve(fileURLToPath(new URL('..',import.meta.url)));
 const manifest=JSON.parse(readFileSync(resolve(web,'runtime-assets.sha256.json'),'utf8'));
 const destination=resolve(web,'public/lean');
 const mirror=process.env.LEAN2LLM_ASSET_MIRROR;
 const missing=Object.keys(manifest).some(name=>!existsSync(resolve(destination,name)));
 // Keep the pinned upstream fetcher as a bootstrap path. CI can select the
 // first-party mirror directly, avoiding upstream IP/geography rate limits.
 if(missing&&!mirror){
  try{
   execFileSync(process.execPath,[resolve(web,'vendor/lean-wasm/bin/fetch-assets.mjs'),destination,'--only','wasm'],{stdio:'inherit',cwd:web});
   const script=resolve(destination,'lean-wasm/lean.js');
   const gzip=resolve(destination,'lean-wasm/lean.js.gz');
   if(existsSync(script)&&!existsSync(gzip))await writeFile(gzip,gzipSync(readFileSync(script)));
  }catch(error){
   console.warn(`Upstream Lean asset bootstrap unavailable (exit ${error.status??'unknown'}). Falling back to the pinned first-party mirror.`);
  }
 }
 await prepareMirrorAssets({manifest,destination,mirror:mirror||DEFAULT_MIRROR});
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))await main();
