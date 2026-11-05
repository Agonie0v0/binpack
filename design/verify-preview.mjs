// Run: node verify-preview.mjs. Checks the local ELF selection boundary.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value:id === 'image-tag' ? 'latest' : id === 'runtime' ? 'auto' : '',
    hidden:false, disabled:false, textContent:'',
    classList:{add(){},remove(){}},addEventListener(){},
  });
  return elements.get(id);
}
const context = vm.createContext({DataView,Error,setTimeout,
  document:{getElementById:element,querySelector:element},
});
const script = await readFile(new URL('./studio.js',import.meta.url),'utf8');
vm.runInContext(script,context);
function elf(machine,name='my-app-linux-amd64') {
  const data = new Uint8Array(64);
  data.set([0x7f,0x45,0x4c,0x46,2,1]);
  new DataView(data.buffer).setUint16(18,machine,true);
  return {name,size:64,slice(){return {arrayBuffer:async()=>data.buffer}}};
}
await context.chooseFile(elf(62));
assert.equal(element('architecture').textContent,'linux/amd64');
assert.equal(element('image-reference').textContent,'my-app:latest');
assert.equal(element('build-button').disabled,false);
await context.chooseFile(elf(183,'tool-linux-arm64'));
assert.equal(element('architecture').textContent,'linux/arm64');
await context.chooseFile({name:'invalid.txt',size:4,slice(){return {arrayBuffer:async()=>new ArrayBuffer(4)}}});
assert.equal(element('build-button').disabled,true);
assert.equal(element('file-error').hidden,false);
await context.chooseFile(elf(999));
assert.equal(element('build-button').disabled,true);
assert.match(element('file-error').textContent,/架构/);
// A slow previous read must not overwrite a newer selection.
let finishRead;
const stale = context.chooseFile({name:'old',size:64,slice(){return {arrayBuffer:()=>new Promise(resolve=>{finishRead=resolve;})}}});
await context.chooseFile(elf(183,'new-linux-arm64'));
finishRead(await elf(62).slice().arrayBuffer());
await stale;
assert.equal(element('file-name').textContent,'new-linux-arm64');
console.log('PASS: amd64/arm64 headers, invalid files, unsupported machines, selection race.');
