import { createCompiler } from '@live-codes/lean-wasm';
import { auditOutput } from './proofs';
interface RunResult {output:string;errors:string[];exitCode:number;compileMs?:number;runtimeError?:string;}
interface Compiler {run:(source:string)=>Promise<RunResult>;dispose:()=>void;}
let compiler:Compiler|null=null;
let pending:Promise<Compiler>|null=null;
let generation=0;
let controller:AbortController|null=null;
function discardCompiler(){controller?.abort();controller=null;compiler?.dispose();compiler=null;pending=null;}
export function cancelCheck(){generation++;discardCompiler();}
async function getCompiler(current:number,onProgress:(message:string)=>void):Promise<Compiler>{
 if(current!==generation)throw new Error('Check cancelled.');
 if(!pending&&!compiler){
  onProgress('Preparing Lean · first use downloads approximately 47 MB');
  controller=new AbortController();
  const report=(value:string)=>{if(current===generation)onProgress(value);};
  pending=createCompiler({signal:controller.signal,baseUrl:import.meta.env.VITE_LEAN_ASSETS_URL||`${location.origin}/lean`,syntaxCheck:'auto',onProgress:report,onStatus:report}).then((created:Compiler)=>{
   if(current!==generation){created.dispose();throw new Error('Check cancelled.');}
   compiler=created;return created;
  }).catch((error:unknown)=>{if(current===generation)pending=null;throw error;});
 }
 return compiler||await pending!;
}
export async function checkProof(name:string,source:string,onProgress:(message:string)=>void){
 const current=generation;
 let timeoutId:ReturnType<typeof setTimeout>|undefined;
 const timeout=new Promise<never>((_,reject)=>{timeoutId=setTimeout(()=>{if(current===generation){cancelCheck();reject(new Error('The checker reached its 90-second limit. Your proof is still available to save and export.'));}},90000);});
 const perform=async()=>{
  let active=await getCompiler(current,onProgress);
  onProgress('Lean is elaborating the theorem and checking its axioms…');
  let result=await active.run(source);
  if(current!==generation)throw new Error('Check cancelled.');
  // Every top-level check receives an isolated worker; even a fresh worker can
  // fail at runtime, so preserve its diagnostic and allow one bounded restart.
  // Retry one time in an isolated fresh worker; every accepted result still needs
  // the exact theorem's successful kernel check and axiom report.
  if(result.runtimeError){
   discardCompiler();
   onProgress('Restarting the Lean worker after a runtime error…');
   active=await getCompiler(current,onProgress);
   result=await active.run(source);
  }
  if(current!==generation)throw new Error('Check cancelled.');
  if(result.exitCode!==0)discardCompiler();
  return {...auditOutput(name,result.output,result.errors,result.exitCode),elapsed:result.compileMs};
 };
 try{return await Promise.race([perform(),timeout]);}
 catch(error){if(current===generation)discardCompiler();throw error;}
 finally{if(timeoutId)clearTimeout(timeoutId);if(current===generation)discardCompiler();}
}
