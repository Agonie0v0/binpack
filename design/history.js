// History has its own page; it never depends on the creation form or preview.
const $ = id => document.getElementById(id);
const activeJob = job => ['queued','building','importing'].includes(job.status);
let dockerConnected = false, refreshTimer;
function announce(message) { $('announcement').textContent=message; $('announcement').hidden=false; }
function link(label,href) { const node=document.createElement('a'); node.textContent=label; node.href=href; node.className='text-button'; return node; }
function action(label,callback) {
  const node=document.createElement('button');
  node.type='button'; node.className='text-button'; node.textContent=label;
  node.addEventListener('click',async()=>{
    node.disabled=true;
    try { await callback(); } catch(error) { announce(error.message); }
    finally { node.disabled=false; }
  });
  return node;
}
async function refreshHistory() {
  clearTimeout(refreshTimer);
  $('refresh-history').disabled=true;
  try {
    const state=await window.sessionReady;
    if(!state) return;
    // Docker being unavailable must not prevent downloading existing archives.
    try { dockerConnected=(await window.authFetch('/api/system')).connected; }
    catch { dockerConnected=false; }
    const {jobs}=await window.authFetch('/api/jobs');
    $('announcement').hidden=true;
    $('history-detail').hidden=true;
    $('history-count').textContent=jobs.length?`${jobs.length} 条记录`:'暂无记录';
    $('history-empty').hidden=jobs.length>0;
    $('history-list').replaceChildren();
    for(const job of jobs) {
      const row=document.createElement('article'); row.className='history-record real-record';
      const info=document.createElement('div'); info.className='record-info';
      const name=document.createElement('code'); name.textContent=job.reference;
      const detail=document.createElement('span'); detail.textContent=`linux/${job.arch} · ${new Date(job.created*1000).toLocaleString('zh-CN',{hour12:false})}`;
      info.append(name,detail); row.append(info);
      const status=document.createElement('span'); status.className='record-status';
      status.textContent=job.status==='failed'?'需要处理':job.imported?'已导入':job.status==='complete'?'已生成':job.message;
      row.append(status);
      const actions=document.createElement('div'); actions.className='record-actions';
      if(job.archive_ready) {
        actions.append(link('镜像包',`/downloads/${job.id}/image`),link('Compose',`/downloads/${job.id}/compose`),link('校验',`/downloads/${job.id}/sha256`));
        if(!job.imported && dockerConnected && !activeJob(job)) actions.append(action('导入飞牛',async()=>{
          if(!confirm(`将 ${job.reference} 导入飞牛镜像库？同名标签会更新，不会启动容器。`)) return;
          await window.accountRequest(`/api/jobs/${job.id}/import`);
          await refreshHistory();
        }));
      }
      if(!activeJob(job)) actions.append(action('清理',async()=>{
        if(!confirm(`清理 ${job.reference} 的记录和下载缓存？已导入的镜像和账号不受影响。`)) return;
        await window.accountRequest(`/api/jobs/${job.id}/delete`);
        await refreshHistory();
      }));
      row.append(actions);
      if(job.error) {const error=document.createElement('p');error.className='record-error';error.textContent=job.error;row.append(error);}
      $('history-list').append(row);
    }
    if(jobs.some(activeJob)) refreshTimer=setTimeout(refreshHistory,2000);
  } catch(error) {
    $('history-detail').hidden=false;
    $('history-detail').textContent='读取记录失败，请点击“刷新记录”重试。';
    announce(error.message);
  } finally { $('refresh-history').disabled=false; }
}
$('refresh-history').addEventListener('click',refreshHistory);
$('clean-uploads').addEventListener('click',async event=>{
  if(!confirm('清理已结束分析的上传源文件？正在打包的文件、镜像包和账号都会保留。')) return;
  event.currentTarget.disabled=true;
  try {const result=await window.accountRequest('/api/uploads/clean');announce(`已清理 ${result.removed} 个上传文件。`);}
  catch(error) {announce(error.message);}
  finally { $('clean-uploads').disabled=false; }
});
window.addEventListener('pagehide',()=>clearTimeout(refreshTimer));
refreshHistory();
