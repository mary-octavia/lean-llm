import { createClient } from '@supabase/supabase-js';
import type { ProofRecord } from './proofs';
import { importRecords } from './proofs';
const url=import.meta.env.VITE_SUPABASE_URL;
const key=import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY;
export const cloud=url&&key?createClient(url,key,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}}):null;
export async function pushProofs(records:ProofRecord[]) {
  if(!cloud) throw new Error('Cloud sync is not configured for this deployment.');
  const {data:{user}}=await cloud.auth.getUser();
  if(!user) throw new Error('Sign in before syncing your private library.');
  if(!records.length)return;
  const {error}=await cloud.from('lean2llm_proofs').upsert(records.map(record=>({user_id:user.id,content_id:record.id,record,updated_at:new Date().toISOString()})),{onConflict:'user_id,content_id'});
  if(error)throw error;
}
export async function pullProofs():Promise<ProofRecord[]> {
  if(!cloud)throw new Error('Cloud sync is not configured for this deployment.');
  const {data:{user}}=await cloud.auth.getUser();if(!user)throw new Error('Sign in before retrieving your private proofs.');
  const {data,error}=await cloud.from('lean2llm_proofs').select('record').eq('user_id',user.id).order('updated_at',{ascending:false}).limit(1000);
  if(error)throw error;
  return importRecords((data||[]).map(row=>row.record));
}
