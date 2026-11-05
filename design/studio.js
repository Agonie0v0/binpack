// Real uploads and jobs. Uploaded program output is always rendered as text.
const $ = id => document.getElementById(id);
let selected = null, lastResult = null, building = false, selectionVersion = 0;
let dockerConnected = false;
const automatic = new Map();
const labels = {auto:'自动识别',alpine:'Alpine / musl',debian:'Debian / glibc'};
const delay = ms => new Promise(resolve => setTimeout(resolve,ms));
function announce(message) { $('announcement').textContent=message; $('announcement').hidden=false; }
function sync() {
  const image=$('image-name').value.trim() || 'my-app', tag=$('image-tag').value.trim() || 'latest';
  $('image-reference').textContent=`${image}:${tag}`;
  $('archive-name').textContent=`${image}_${tag}.tar`;
  $('runtime-preview').textContent=$('runtime').value==='auto' && selected?.analysis ? labels[selected.analysis.runtime] : labels[$('runtime').value];
  $('build-button').disabled=!selected || selected.status!=='ready' || building || !dockerConnected;
  $('form-status').textContent=building ? '正在处理任务' : !selected ? '先选择一个文件' : selected.status!=='ready' ? '正在识别文件' : !dockerConnected ? '请先连接 NAS Docker' : '文件已就绪';
}
function clearResult() { $('finished-actions').hidden=true; $('build-progress').hidden=true; $('status-chip').textContent=selected?'准备就绪':'等待文件'; $('status-chip').className='status-chip'+(selected?' ready':''); }
function applyAnalysis(meta) {
  selected=meta;
  const a=meta.analysis;
  $('analysis-panel').hidden=false;
  $('analysis-title').textContent=meta.status==='ready'?'识别完成':'正在读取帮助信息';
  $('analysis-summary').textContent=meta.warning || (meta.status==='ready'?a.note:'正在受限容器中分析，首次使用可能需要下载基础环境。');
  $('analysis-basis').textContent=a.basis;
  $('analysis-flags').textContent=a.flags.length?'发现的启动选项：'+a.flags.join('、'):'未确定启动参数，可在高级设置中手动补充。';
  $('analysis-help').textContent=a.help_excerpt || '';
  $('analysis-help').hidden=!a.help_excerpt;
  $('architecture').textContent='linux/'+a.arch;
  for (const [id,value] of [['port',a.port],['volume',a.volume]]) {
    if(value && (!$(id).value || automatic.get(id)===$(id).value)) { $(id).value=String(value); automatic.set(id,String(value)); }
  }
  sync();
}
async function chooseFile(file) {
  if(!file || building) return;
  const version=++selectionVersion;
  selected=null; lastResult=null; clearResult();
  $('file-error').hidden=true;
  $('analysis-panel').hidden=true;
  for(const [id,value] of automatic) if($(id).value===value) $(id).value='';
  automatic.clear();
  sync();
  try {
    if(file.size>256*1048576) throw Error('文件不能超过 256 MB。');
    const header=new DataView(await file.slice(0,64).arrayBuffer());
    if(version!==selectionVersion) return;
    if(header.byteLength<64 || header.getUint32(0)!==0x7f454c46 || header.getUint8(4)!==2 || header.getUint8(5)!==1) throw Error('请选择 Linux 64 位小端 ELF 二进制文件。');
    const arch={62:'amd64',183:'arm64'}[header.getUint16(18,true)];
    if(!arch) throw Error('仅支持 amd64 / arm64 架构。');
    $('empty-file').hidden=true; $('selected-file').hidden=false; $('dropzone').classList.add('selected');
    $('file-name').textContent=file.name; $('file-size').textContent=`${(file.size/1048576).toFixed(2)} MB`;
    $('architecture').textContent='linux/'+arch;
    $('form-status').textContent='正在上传文件…';
    if(!$('image-name').value.trim()) $('image-name').value=file.name.toLowerCase().replace(/[-_]linux.*$/i,'').replace(/[^a-z0-9._-]/g,'-').replace(/^[._-]+|[._-]+$/g,'') || 'my-app';
    const state=await window.sessionReady;
    if(!state) throw Error('请重新登录。');
    let meta=await window.authFetch('/api/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':state.csrf,'X-Filename':encodeURIComponent(file.name)},body:file});
    while(version===selectionVersion) {
      applyAnalysis(meta);
      if(meta.status==='ready') break;
      await delay(1000);
      if(version!==selectionVersion) return;
      meta=await window.authFetch('/api/uploads/'+meta.id);
    }
  } catch(error) {
    if(version!==selectionVersion) return;
    selected=null; $('binary-file').value=''; $('empty-file').hidden=false; $('selected-file').hidden=true;
    $('dropzone').classList.remove('selected'); $('architecture').textContent='选择文件后识别';
    $('file-error').textContent=error.message; $('file-error').hidden=false; sync();
  }
}
async function systemStatus() {
  try { await window.sessionReady; const state=await window.authFetch('/api/system'); dockerConnected=state.connected; $('docker-status').textContent=state.message; }
  catch(error) { dockerConnected=false; $('docker-status').textContent=error.message; }
  $('auto-import').disabled=!dockerConnected;
  if(!dockerConnected) $('auto-import').checked=false;
  sync();
}
function showJob(job) {
  lastResult=job;
  $('progress').value=job.progress; $('progress-percent').textContent=job.progress+'%';
  $('progress-message').textContent=job.message;
  const active=['queued','building','importing'].includes(job.status);
  $('build-progress').hidden=!active;
  $('status-chip').textContent=job.status==='failed'?'需要处理':active?'处理中':job.imported?'已导入':'已完成';
  $('status-chip').className='status-chip '+(job.status==='complete'?'done':'ready');
  $('finished-actions').hidden=!job.archive_ready;
  $('result-message').textContent=job.error || (job.imported?'已加入飞牛镜像库，可在 Docker 中创建容器。':'归档已生成，可下载后在 NAS 本地导入。');
  if(job.archive_ready) for(const [id,kind] of [['download-compose','compose'],['download-sha256','sha256']]) $(id).href=`/downloads/${job.id}/${kind}`;
  if(job.error) announce(job.error);
}
async function followJob(id) {
  let job;
  do {
    job=await window.authFetch('/api/jobs/'+id); showJob(job);
    if(['queued','building','importing'].includes(job.status)) await delay(1200);
  } while(['queued','building','importing'].includes(job.status));
  await refreshHistory();
  return job;
}
function link(label,href) { const node=document.createElement('a'); node.textContent=label; node.href=href; node.className='text-button'; return node; }
function action(label,callback) { const node=document.createElement('button'); node.type='button'; node.className='text-button'; node.textContent=label; node.addEventListener('click',async()=>{node.disabled=true; try{await callback();}catch(error){announce(error.message);node.disabled=false;}}); return node; }
async function refreshHistory() {
  const {jobs}=await window.authFetch('/api/jobs');
  $('history-count').textContent=jobs.length?`${jobs.length} 条记录`:'暂无记录';
  $('history-empty').hidden=jobs.length>0;
  $('history-list').replaceChildren();
  for(const job of jobs) {
    const row=document.createElement('article'); row.className='history-record real-record';
    const info=document.createElement('div'); info.className='record-info';
    const name=document.createElement('code'); name.textContent=job.reference;
    const detail=document.createElement('span'); detail.textContent=`linux/${job.arch} · ${new Date(job.created*1000).toLocaleString('zh-CN',{hour12:false})}`;
    info.append(name,detail); row.append(info);
    const status=document.createElement('span'); status.className='record-status'; status.textContent=job.status==='failed'?'需要处理':job.imported?'已导入':job.status==='complete'?'已生成':job.message;
    row.append(status);
    const actions=document.createElement('div'); actions.className='record-actions';
    if(job.archive_ready) {
      actions.append(link('镜像包',`/downloads/${job.id}/image`),link('Compose',`/downloads/${job.id}/compose`),link('校验',`/downloads/${job.id}/sha256`));
      if(!job.imported && dockerConnected && !['queued','building','importing'].includes(job.status)) actions.append(action('导入飞牛',async()=>{
        if(!confirm(`将 ${job.reference} 导入飞牛镜像库？同名标签会更新，不会启动容器。`)) return refreshHistory();
        await window.accountRequest(`/api/jobs/${job.id}/import`); await followJob(job.id);
      }));
    }
    if(!['queued','building','importing'].includes(job.status)) actions.append(action('清理',async()=>{
      if(!confirm(`清理 ${job.reference} 的记录和下载缓存？已导入的镜像和账号不受影响。`)) return refreshHistory();
      await window.accountRequest(`/api/jobs/${job.id}/delete`); await refreshHistory();
      if(lastResult?.id===job.id) {lastResult=null;clearResult();}
    }));
    row.append(actions);
    if(job.error) {const error=document.createElement('p');error.className='record-error';error.textContent=job.error;row.append(error);}
    $('history-list').append(row);
  }
}
$('binary-file').addEventListener('change',event=>chooseFile(event.target.files[0]));
$('dropzone').addEventListener('dragover',event=>{event.preventDefault();if(!building)$('dropzone').classList.add('dragover');});
$('dropzone').addEventListener('dragleave',()=>$('dropzone').classList.remove('dragover'));
$('dropzone').addEventListener('drop',event=>{event.preventDefault();$('dropzone').classList.remove('dragover');chooseFile(event.dataTransfer.files[0]);});
['image-name','image-tag','runtime','args','port','volume'].forEach(id=>$(id).addEventListener('input',()=>{clearResult();sync();}));
$('auto-import').addEventListener('change',()=>{$('output-note').textContent=$('auto-import').checked?'生成后导入本机 Docker 镜像库，同名标签会更新。':'可下载镜像包，在 NAS 的 Docker 管理中本地导入。';});
$('pack-form').addEventListener('submit',async event=>{
  event.preventDefault(); if(!selected || selected.status!=='ready' || building || !$('pack-form').reportValidity())return;
  building=true; sync();
  const controls=document.querySelectorAll('#pack-form input,#pack-form select'); controls.forEach(node=>node.disabled=true);
  try {
    const job=await window.accountRequest('/api/jobs',{upload_id:selected.id,image:$('image-name').value.trim(),tag:$('image-tag').value.trim(),runtime:$('runtime').value,args:$('args').value,port:$('port').value,volume:$('volume').value,auto_import:$('auto-import').checked});
    showJob(job); await followJob(job.id);
    // The binary has been consumed; selecting another file starts a fresh job.
    selected=null;
  } catch(error) {announce(error.message);}
  finally {building=false;controls.forEach(node=>node.disabled=false);$('auto-import').disabled=!dockerConnected;sync();}
});
$('preview-download').addEventListener('click',()=>{if(lastResult?.archive_ready) location.assign(`/downloads/${lastResult.id}/image`);});
$('refresh-history').addEventListener('click',async()=>{try{await systemStatus();await refreshHistory();}catch(error){announce(error.message);}});
$('clean-uploads').addEventListener('click',async()=>{
  if(!confirm('清理已结束分析的上传源文件？正在打包的文件、镜像包和账号都会保留。'))return;
  try {const result=await window.accountRequest('/api/uploads/clean');selected=null;sync();announce(`已清理 ${result.removed} 个上传文件。`);} catch(error){announce(error.message);}
});
document.querySelector('.help-button').addEventListener('click',event=>{const panel=$('help-panel');panel.hidden=!panel.hidden;event.currentTarget.setAttribute('aria-expanded',String(!panel.hidden));});
for(const id of ['create-link','history-link']) $(id).addEventListener('click',()=>{for(const navId of ['create-link','history-link']){$(navId).classList.toggle('active',navId===id);if(navId===id)$(navId).setAttribute('aria-current','location');else $(navId).removeAttribute('aria-current');}});
(async()=>{await window.sessionReady;await systemStatus();try{await refreshHistory();}catch(error){announce(error.message);}})();
sync();
