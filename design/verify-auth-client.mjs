// Regression check: network/proxy failures must never become raw browser copy.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const sandbox = vm.createContext({window:{},fetch:null});
vm.runInContext(await readFile(new URL('./auth-client.js',import.meta.url),'utf8'),sandbox);
const request = sandbox.window.authFetch;
sandbox.fetch = async () => {throw new TypeError('Failed to fetch');};
await assert.rejects(request('/api/auth/login'),/无法连接账号服务，请检查网络后重试/);
sandbox.fetch = async () => ({status:502,ok:false,json:async()=>{throw new SyntaxError('Unexpected token <');}});
await assert.rejects(request('/api/auth/login'),/账号服务暂时不可用，请稍后重试/);
sandbox.fetch = async () => ({status:401,ok:false,json:async()=>({error:'账号或密码不正确。'})});
await assert.rejects(request('/api/auth/login'),error => error.status===401 && error.message==='账号或密码不正确。');
sandbox.fetch = async () => ({status:200,ok:true,json:async()=>({ok:true})});
assert.equal((await request('/api/auth/login')).ok,true);
console.log('PASS: localized network/JSON failures, preserved business errors, successful response.');
