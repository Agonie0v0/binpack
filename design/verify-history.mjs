// Run: node design/verify-history.mjs. No creation-page DOM is available here.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const ids=['announcement','refresh-history','history-detail','history-count','history-empty','history-list','clean-uploads'];
function element() {
  return {hidden:false,disabled:false,textContent:'',children:[],handlers:{},
    append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];},
    addEventListener(type,callback){this.handlers[type]=callback;}};
}
const elements=new Map(ids.map(id=>[id,element()]));
const job={id:'a'.repeat(32),reference:'my-app:latest',arch:'amd64',created:1,status:'complete',archive_ready:true};
let jobs=[job], connected=true, fail=false, confirmed=true, timer, requests=[];
const sandbox=vm.createContext({console,Date,
  setTimeout(callback){timer=callback;return 1;},clearTimeout(){timer=null;},confirm:()=>confirmed,
  window:{sessionReady:Promise.resolve({user:'tester'}),addEventListener(){},
    authFetch:async path=>{
      if(path==='/api/system') {if(!connected) throw Error('Docker unavailable');return {connected:true};}
      if(fail) throw Error('网络连接失败');
      return {jobs};
    },
    accountRequest:async path=>{requests.push(path);if(path.endsWith('/import')) jobs=[{...job,status:'importing',message:'正在导入'}];return {removed:2};},
  },document:{getElementById(id){assert.ok(elements.has(id),`Unexpected creation-page dependency: ${id}`);return elements.get(id);},createElement:element},
});
vm.runInContext(await readFile(new URL('./history.js',import.meta.url),'utf8'),sandbox);
await sandbox.refreshHistory();
const list=elements.get('history-list');
assert.equal(list.children.length,1);
const actions=()=>list.children[0].children[2].children;
assert.deepEqual(actions().map(node=>node.textContent),['镜像包','Compose','校验','导入飞牛','清理']);
assert.equal(actions()[0].href,`/downloads/${job.id}/image`);
confirmed=false;
await actions()[3].handlers.click();
assert.equal(actions()[3].disabled,false);
assert.equal(requests.length,0);
confirmed=true;
await actions()[3].handlers.click();
assert.equal(requests[0],`/api/jobs/${job.id}/import`);
assert.equal(typeof timer,'function');
assert.deepEqual(actions().map(node=>node.textContent),['镜像包','Compose','校验']);
jobs=[{...job,imported:true}];
await timer();
assert.equal(timer,null);
connected=false;
await sandbox.refreshHistory();
assert.equal(actions()[0].textContent,'镜像包');
fail=true;
await sandbox.refreshHistory();
assert.equal(list.children.length,1); // Keep existing results when refresh fails.
assert.equal(elements.get('history-detail').hidden,false);
assert.equal(elements.get('refresh-history').disabled,false);
fail=false; jobs=[];
await sandbox.refreshHistory();
assert.equal(list.children.length,0);
assert.equal(elements.get('history-empty').hidden,false);
await elements.get('clean-uploads').handlers.click({currentTarget:elements.get('clean-uploads')});
assert.equal(requests.at(-1),'/api/uploads/clean');
assert.match(elements.get('announcement').textContent,/已清理 2/);
console.log('PASS: standalone history, downloads without Docker, import/polling, cancellation, refresh recovery and cleanup.');
