export const SCHEMA = 'lean2llm.proof/v1' as const;
export const BROWSER_PIN = 'lean-wasm:62b6a2291302d4bbeace37642a066b7510d0145c';
export const CHECKER_FINGERPRINT = 'browser-lean:a8aed095534e67061e2626b94e8e69193099091d:lean2llm-audit-v1';
export type ProofRequest = {name:string;context:string;statement:string};
export type ProofContent = {title:string;tags:string[];request:ProofRequest;proof:string;source:string;backend:'lean-tactic';toolchain:{pin:string;fingerprint:string};metadata:Record<string,unknown>};
export type Verification = {status:'unverified'|'verified';scope:string;checked_at:string|null;diagnostics:string;checker_fingerprint:string};
export type ProofRecord = {schema:typeof SCHEMA;id:string;content:ProofContent;verification:Verification};
export type Draft = {title:string;tags:string;name:string;context:string;statement:string;proof:string};
export const unverified = (diagnostics='Awaiting a fresh Lean check.'):Verification => ({status:'unverified',scope:'browser-local',checked_at:null,diagnostics,checker_fingerprint:''});
export function stableJson(value:unknown):string {
  if(typeof value==='string'&&/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value))throw new Error('Proof records require valid Unicode strings.');
  if(value===undefined||typeof value==='bigint'||typeof value==='function'||typeof value==='symbol')throw new Error('Proof records require JSON values.');
  if(typeof value==='number'&&!Number.isSafeInteger(value))throw new Error('Proof record numbers must be safe integers. Store fractional or larger numeric metadata as strings.');
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  const object = value as Record<string,unknown>;
  return `{${Object.keys(object).sort((a,b)=>{const aa=Array.from(a),bb=Array.from(b);for(let i=0;i<Math.min(aa.length,bb.length);i++){const delta=aa[i].codePointAt(0)!-bb[i].codePointAt(0)!;if(delta)return delta;}return aa.length-bb.length;}).map(key=>`${stableJson(key)}:${stableJson(object[key])}`).join(',')}}`;
}
export async function contentId(content:ProofContent):Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stableJson(content)));
  return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
}
export function makeSource(request:ProofRequest,proof:string):string {
  return `${request.context.trim()}\n\nset_option autoImplicit false\nset_option maxHeartbeats 400000\n\ntheorem ${request.name} : ${request.statement.trim()} := by\n${proof.trim().split('\n').map(line=>`  ${line}`).join('\n')}\n\n#print axioms ${request.name}\n#check ${request.name}\n`;
}
export function submissionIssue(draft:Draft):string|null {
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(draft.name)) return 'Use a simple theorem name containing letters, digits and underscores.';
  if (!draft.statement.trim() || !draft.proof.trim()) return 'A statement and a tactic proof are required.';
  const text = `${draft.context}\n${draft.statement}\n${draft.proof}`;
  if (new TextEncoder().encode(draft.name+draft.context+draft.statement).length>64000 || new TextEncoder().encode(draft.proof).length>32000) return 'Portable records accept up to 64 KB of request text and 32 KB of tactic proof.';
  const denied = /\b(sorry|sorryAx|admit|axiom|unsafe|native_decide|run_tac|run_elab|run_meta|elab|macro|syntax|initialize|builtin_initialize|import|set_option|attribute|local|scoped|open|namespace|end|export|audit_llm|llm|llm_theorem|implemented_by|extern|compiler|IO|Lean)\b|#|\b(open\s+Lean|evalTerm|ofReduceBool)\b/;
  const violation = text.match(denied);
  if (violation) return `The audited workbench cannot accept “${violation[0]}”. Use the local library for a custom environment.`;
  if (/:=|\b(by|where|theorem|def|example|namespace|end|section)\b/.test(draft.statement)) return 'Enter a proposition only in the statement field; declarations belong in context.';
  if (/[\r\n]\s*(theorem|def|example|namespace|section|end|inductive|structure|instance)\b/.test(`\n${draft.proof}`)) return 'The proof field accepts tactics only. Put supporting declarations in context.';
  return null;
}
export function auditOutput(name:string,output:string,errors:string[],exitCode:number):{verified:boolean;diagnostics:string} {
  if (exitCode!==0 || errors.length) return {verified:false,diagnostics:errors.join('\n')||output||'Lean reported an error.'};
  if (/\bsorryAx\b/.test(output)) return {verified:false,diagnostics:'The axiom audit found an unfinished proof (sorryAx).'};
  const escaped=name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  // This WASM fork prefixes declarations with a generated private module name.
  // Accept that exact qualification, while excluding arbitrary prefixes/suffixes.
  const qualified=`(?:_private\\.(?:[A-Za-z_][A-Za-z0-9_]*\\.)*[0-9]+\\.)?${escaped}`;
  const report=new RegExp(`^(?:'${qualified}'|${qualified}) (does not depend on any axioms|depends on axioms:[ \t]*\\[([^\\]]*)\\])[ \t]*$`,'gm');
  const matches=[...output.matchAll(report)];
  const allReports=output.match(/^.* (?:does not depend on any axioms|depends on axioms:).*$/gm)||[];
  if(matches.length!==1 || allReports.length!==1) return {verified:false,diagnostics:`Expected exactly one axiom report for ${name}; found ${matches.length} matching reports and ${allReports.length} total reports.\n${output}`};
  const match=matches[0];
  if(match[1]==='does not depend on any axioms')return {verified:true,diagnostics:output.trim()};
  const axioms=match[2].split(',').map(item=>item.trim()).filter(Boolean);
  const forbidden=axioms.filter(item=>!['propext','Classical.choice','Quot.sound'].includes(item));
  if(forbidden.length)return {verified:false,diagnostics:`Additional axioms detected: ${forbidden.join(', ')}.\n${output}`};
  return {verified:true,diagnostics:output.trim()};
}
export function portableSource(request:ProofRequest,proof:string):string {
  return `import Llm\n\nnamespace LlmGenerated\n\n${request.context}\n\ntheorem target :\n  ${request.statement} := by\n${proof.split('\n').map(line=>`  ${line}`).join('\n')}\n\naudit_llm target\n\nend LlmGenerated\n`;
}
export async function makeRecord(draft:Draft,verification:Verification=unverified()):Promise<ProofRecord> {
  const request={name:draft.name,context:draft.context,statement:draft.statement};
  const content:ProofContent={title:draft.title.trim()||draft.name,tags:draft.tags.split(',').map(tag=>tag.trim()).filter(Boolean),request,proof:draft.proof,source:portableSource(request,draft.proof),backend:'lean-tactic',toolchain:{pin:BROWSER_PIN,fingerprint:CHECKER_FINGERPRINT},metadata:{}};
  return {schema:SCHEMA,id:await contentId(content),content,verification};
}
export async function importRecords(input:unknown):Promise<ProofRecord[]> {
  const records=Array.isArray(input)?input:[input];
  if (records.length>1000) throw new Error('Import up to 1,000 proofs at a time.');
  return Promise.all(records.map(async item=>{
    if (!item || typeof item!=='object') throw new Error('The file contains an invalid proof record.');
    const record=item as ProofRecord;
    const content=record.content;
    if (record.schema!==SCHEMA || !content || content.backend!=='lean-tactic' || !content.request || typeof content.request.name!=='string' || typeof content.request.statement!=='string' || typeof content.request.context!=='string' || typeof content.proof!=='string' || typeof content.title!=='string' || typeof content.source!=='string' || !Array.isArray(content.tags) || content.tags.some(tag=>typeof tag!=='string') || !content.toolchain || typeof content.toolchain.pin!=='string' || typeof content.toolchain.fingerprint!=='string' || !content.toolchain.pin || !content.toolchain.fingerprint || content.toolchain.pin.length>256 || content.toolchain.fingerprint.length>256 || !content.metadata || typeof content.metadata!=='object' || Array.isArray(content.metadata)) throw new Error('Expected a lean2llm.proof/v1 tactic proof record.');
    const keys=(object:object)=>Object.keys(object).sort().join(',');
    if(keys(content)!=='backend,metadata,proof,request,source,tags,title,toolchain' || keys(content.request)!=='context,name,statement' || keys(content.toolchain)!=='fingerprint,pin')throw new Error('The proof record contains unsupported content fields.');
    if(!content.request.statement.trim()||!content.proof.trim()||new TextEncoder().encode(content.proof).length>32000||new TextEncoder().encode(content.request.name+content.request.context+content.request.statement).length>64000)throw new Error('The proof record exceeds the portable tactic size limits.');
    if(content.source!==portableSource(content.request,content.proof))throw new Error(`The source for “${content.title}” does not match its statement and proof.`);
    const id=await contentId(content);
    if (record.id!==id) throw new Error(`The content hash for “${content.title}” does not match. The import was stopped.`);
    return {schema:SCHEMA,id,content,verification:unverified('Imported proof. Recheck it in this browser before relying on its verification status.')};
  }));
}
const STORAGE_KEY='lean2llm.proofs.v1';
export function readLibrary():ProofRecord[] {
  try {const data=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');return Array.isArray(data)?data.filter(item=>item?.schema===SCHEMA&&item.content?.request&&item.verification).map(item=>({...item,verification:{...item.verification,status:'unverified',diagnostics:'Stored proof retrieved. Run Lean to establish a fresh check in this session.\n'+(item.verification.diagnostics||'')}})):[];} catch {return [];}
}
export function writeLibrary(records:ProofRecord[]) {localStorage.setItem(STORAGE_KEY,JSON.stringify(records));}
export function draftFrom(record:ProofRecord):Draft {return {title:record.content.title,tags:record.content.tags.join(', '),...record.content.request,proof:record.content.proof};}
export function download(name:string,body:string,type='application/json') {const url=URL.createObjectURL(new Blob([body],{type}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export const examples:Draft[]=[
  {title:'Identity, from first principles',tags:'logic, core',name:'identity',context:'',statement:'∀ (P : Prop), P → P',proof:'intro P h\nexact h'},
  {title:'Addition by induction',tags:'arithmetic, induction',name:'zero_add',context:'',statement:'∀ (n : Nat), 0 + n = n',proof:'intro n\ninduction n with\n| zero => rfl\n| succ n ih =>\n  exact congrArg Nat.succ ih'},
  {title:'Two steps, one identity',tags:'involution, induction, original-demo',name:'paired_steps_identity',context:'def pairedSteps {α : Type} (f : α → α) : Nat → α → α\n  | 0, x => x\n  | n + 1, x => pairedSteps f n (f (f x))',statement:'∀ (α : Type) (f : α → α), (∀ x, f (f x) = x) → ∀ n x, pairedSteps f n x = x',proof:'intro α f hf n\ninduction n with\n| zero => intro x; rfl\n| succ n ih =>\n  intro x\n  simp only [pairedSteps, hf]\n  exact ih x'},
];
