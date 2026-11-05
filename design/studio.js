// Interactive design preview. No network uploads, execution, or real image builds.
const $ = id => document.getElementById(id);
let selected = null;
let lastResult = null;
let building = false;
let selectionVersion = 0;
const labels = {auto:'自动识别',alpine:'Alpine',debian:'Debian'};

function announce(message) {
  $('announcement').textContent = message;
  $('announcement').hidden = false;
}
function sync() {
  const image = $('image-name').value.trim() || 'my-app';
  const tag = $('image-tag').value.trim() || 'latest';
  $('image-reference').textContent = `${image}:${tag}`;
  $('archive-name').textContent = `${image}_${tag}.tar`;
  $('runtime-preview').textContent = labels[$('runtime').value];
  $('build-button').disabled = !selected || building;
  $('form-status').textContent = building ? '正在演示打包流程' : selected ? '一切就绪，可以开始' : '先选择一个文件';
}
function clearResult() {
  $('finished-actions').hidden = true;
  $('build-progress').hidden = true;
  $('status-chip').textContent = selected ? '准备就绪' : '等待文件';
  $('status-chip').className = 'status-chip' + (selected ? ' ready' : '');
}
function showSelected(file) {
  selected = file;
  $('empty-file').hidden = true;
  $('selected-file').hidden = false;
  $('dropzone').classList.add('selected');
  $('file-name').textContent = file.name;
  $('file-size').textContent = file.example ? '24.8 MB · 示例文件' : `${(file.size / 1048576).toFixed(2)} MB`;
  $('architecture').textContent = file.arch;
  $('file-error').hidden = true;
  if (!$('image-name').value.trim()) {
    $('image-name').value = file.name.replace(/-linux.*$/i,'').replace(/[^a-z0-9._-]/g,'-').replace(/^[._-]+|[._-]+$/g,'') || 'my-app';
  }
  clearResult(); sync();
}
async function chooseFile(file) {
  if (!file || building) return;
  const version = ++selectionVersion;
  try {
    const header = new DataView(await file.slice(0,64).arrayBuffer());
    if (version !== selectionVersion) return;
    if (header.byteLength < 64 || header.getUint32(0) !== 0x7f454c46 || header.getUint8(4) !== 2 || header.getUint8(5) !== 1) throw Error('请选择 Linux 64 位小端 ELF 二进制文件。');
    const machine = header.getUint16(18,true);
    const arch = {62:'linux/amd64',183:'linux/arm64'}[machine];
    if (!arch) throw Error('这个架构尚不在当前界面预览的支持范围内。');
    showSelected({name:file.name,size:file.size,arch,example:false});
  } catch (error) {
    if (version !== selectionVersion) return;
    selected = null;
    $('binary-file').value = '';
    $('empty-file').hidden = false;
    $('selected-file').hidden = true;
    $('dropzone').classList.remove('selected');
    $('architecture').textContent = '选择文件后识别';
    $('file-error').textContent = error instanceof Error ? error.message : '读取文件失败，请重新选择。';
    $('file-error').hidden = false;
    clearResult(); sync();
  }
}
$('binary-file').addEventListener('change',event => chooseFile(event.target.files[0]));
$('dropzone').addEventListener('dragover',event => {event.preventDefault(); if(!building) $('dropzone').classList.add('dragover');});
$('dropzone').addEventListener('dragleave',() => $('dropzone').classList.remove('dragover'));
$('dropzone').addEventListener('drop',event => {event.preventDefault(); $('dropzone').classList.remove('dragover'); chooseFile(event.dataTransfer.files[0]);});
['image-name','image-tag','runtime','args','port','volume'].forEach(id => $(id).addEventListener('input',() => {clearResult(); sync();}));
$('load-example').addEventListener('click',() => {
  if(building) return;
  ++selectionVersion;
  showSelected({name:'my-app-linux-amd64',size:26004684,arch:'linux/amd64',example:true});
  announce('已载入示例，可以点击“生成镜像包”查看交互效果。此流程不会构建真实镜像。');
});
$('pack-form').addEventListener('submit',async event => {
  event.preventDefault();
  if(!selected || building || !$('pack-form').reportValidity()) return;
  building = true;
  document.querySelectorAll('form input,form select,#load-example').forEach(element => element.disabled = true);
  sync();
  $('finished-actions').hidden = true;
  $('status-chip').textContent = '演示中';
  $('status-chip').className = 'status-chip ready';
  $('build-progress').hidden = false;
  for (const [value,message] of [[15,'模拟接收文件'],[45,'模拟生成镜像'],[80,'模拟校验归档'],[100,'演示完成']]) {
    $('progress').value = value;
    $('progress-percent').textContent = `${value}%`;
    $('progress-message').textContent = message;
    await new Promise(resolve => setTimeout(resolve,550));
  }
  building = false;
  document.querySelectorAll('form input,form select,#load-example').forEach(element => element.disabled = false);
  $('build-progress').hidden = true;
  $('finished-actions').hidden = false;
  $('status-chip').textContent = '演示完成';
  $('status-chip').className = 'status-chip done';
  $('history-image').textContent = $('image-reference').textContent;
  lastResult = {image:$('image-reference').textContent,archive:$('archive-name').textContent,arch:selected.arch};
  $('history-detail').hidden = true;
  $('history-download').setAttribute('aria-expanded','false');
  $('history-empty').hidden = true;
  $('history-record').hidden = false;
  $('history-count').textContent = '1 条演示记录';
  sync();
  $('form-status').textContent = '演示已完成';
  announce('交互演示完成。正式版接入打包服务后，才会产生可下载的镜像包。');
});
$('preview-download').addEventListener('click',() => announce('这是界面预览，尚未生成可下载的镜像包。'));
$('history-download').addEventListener('click',() => {
  if (!lastResult) return;
  const detail = $('history-detail');
  detail.textContent = `${lastResult.image} · ${lastResult.arch} · ${lastResult.archive}。这是独立保存的演示摘要，未生成实际归档。`;
  detail.hidden = !detail.hidden;
  $('history-download').setAttribute('aria-expanded',String(!detail.hidden));
});
$('refresh-history').addEventListener('click',() => announce('当前仅有本次预览的演示记录，正式版将读取 NAS 上的打包历史。'));
document.querySelector('.help-button').addEventListener('click',event => {
  const panel = $('help-panel'); panel.hidden = !panel.hidden;
  event.currentTarget.setAttribute('aria-expanded',String(!panel.hidden));
});
for (const id of ['create-link','history-link']) $(id).addEventListener('click',() => {
  for (const navId of ['create-link','history-link']) {
    $(navId).classList.toggle('active',navId===id);
    if(navId===id) $(navId).setAttribute('aria-current','location'); else $(navId).removeAttribute('aria-current');
  }
});
sync();
