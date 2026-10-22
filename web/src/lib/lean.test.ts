import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
const factory=vi.hoisted(()=>vi.fn());
vi.mock('@live-codes/lean-wasm',()=>({createCompiler:factory}));
import {cancelCheck,checkProof} from './lean';
const accepted={output:"'identity' does not depend on any axioms",errors:[],exitCode:0,compileMs:1};
const rejected={output:'',errors:['Type mismatch: True.intro has type True but was expected to have type False'],exitCode:1,compileMs:1};
const fault={output:'',errors:['memory access out of bounds'],exitCode:1,runtimeError:'memory access out of bounds',compileMs:1};
beforeEach(()=>{cancelCheck();factory.mockReset();vi.stubGlobal('location',{origin:'http://localhost'});});
afterEach(()=>{cancelCheck();vi.unstubAllGlobals();});
describe('browser Lean worker recovery',()=>{
 it('isolates successful checks in separate workers',async()=>{const run=vi.fn().mockResolvedValue(accepted);const dispose=vi.fn();factory.mockResolvedValue({run,dispose});expect((await checkProof('identity','valid',()=>{})).verified).toBe(true);expect((await checkProof('identity','valid again',()=>{})).verified).toBe(true);expect(factory).toHaveBeenCalledTimes(2);expect(run).toHaveBeenCalledTimes(2);expect(dispose).toHaveBeenCalledTimes(2);});
 it('recovers valid → runtime fault → real rejection → valid using fresh workers',async()=>{const first={run:vi.fn().mockResolvedValue(accepted),dispose:vi.fn()};const failedWorker={run:vi.fn().mockResolvedValue(fault),dispose:vi.fn()};const second={run:vi.fn().mockResolvedValue(rejected),dispose:vi.fn()};const third={run:vi.fn().mockResolvedValue(accepted),dispose:vi.fn()};factory.mockResolvedValueOnce(first).mockResolvedValueOnce(failedWorker).mockResolvedValueOnce(second).mockResolvedValueOnce(third);expect((await checkProof('identity','valid',()=>{})).verified).toBe(true);const bad=await checkProof('identity','invalid',()=>{});expect(bad.verified).toBe(false);expect(bad.diagnostics).toContain('Type mismatch');expect((await checkProof('identity','valid again',()=>{})).verified).toBe(true);expect(factory).toHaveBeenCalledTimes(4);expect(first.dispose).toHaveBeenCalled();expect(second.dispose).toHaveBeenCalled();});
 it('bounds runtime fault recovery to one retry and keeps its diagnostics',async()=>{factory.mockImplementation(()=>Promise.resolve({run:vi.fn().mockResolvedValue(fault),dispose:vi.fn()}));const result=await checkProof('identity','runtime failure',()=>{});expect(result.verified).toBe(false);expect(result.diagnostics).toContain('memory access');expect(factory).toHaveBeenCalledTimes(2);});
});
