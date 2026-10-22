import CodeMirror from '@uiw/react-codemirror';
import { StreamLanguage } from '@codemirror/language';
const lean=StreamLanguage.define({startState:()=>({}),token(stream){if(stream.match(/--.*/))return 'comment';if(stream.match(/"(?:[^"\\]|\\.)*"/))return 'string';if(stream.match(/\b(theorem|def|by|intro|exact|induction|with|simp|only|rw|rfl|fun|forall|match|if|then|else|let|in|have|apply|cases|constructor|assumption)\b/))return 'keyword';if(stream.match(/\b(Nat|Prop|Type|Bool|List|True|False)\b/))return 'typeName';if(stream.match(/\b\d+\b/))return 'number';stream.next();return null;}});
export default function Editor({value,onChange,label,height='240px'}:{value:string;onChange?:(value:string)=>void;label:string;height?:string}) {
 return <div className="code-editor" aria-label={label}><CodeMirror value={value} onChange={onChange} height={height} extensions={[lean]} editable={!!onChange} basicSetup={{foldGutter:false,highlightActiveLine:true,autocompletion:false}} aria-label={label} theme="light"/></div>;
}
