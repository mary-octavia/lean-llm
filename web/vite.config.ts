import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import {existsSync} from 'node:fs';
import {resolve} from 'node:path';
export default defineConfig({plugins:[react(),{name:'lean-assets-no-html-fallback',configureServer(server){server.middlewares.use((req,res,next)=>{const path=(req.url||'').split('?')[0];if(path.startsWith('/lean/')&&!existsSync(resolve('public',`.${path}`))){res.statusCode=404;res.end('Lean asset not found');return;}next();});}}],server:{headers:{'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'}},preview:{headers:{'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'}},build:{rollupOptions:{output:{manualChunks:{editor:['@uiw/react-codemirror','@codemirror/language'],cloud:['@supabase/supabase-js']}}}}});
