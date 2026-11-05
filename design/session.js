// Every HTML/JS route and future operation is also checked by the server.
window.sessionReady = window.authFetch('/api/auth/state')
  .then(state => {
    if (!state.user) {location.replace('/login?expired=1'); return null;}
    document.querySelectorAll('[data-account-name]').forEach(element => element.textContent = state.user);
    document.querySelectorAll('[data-account-avatar]').forEach(element => element.textContent = state.user.slice(0,2).toUpperCase());
    return state;
  }).catch(() => {location.replace('/login'); return null;});
window.accountRequest = async (path,data={}) => {
  const state = await window.sessionReady;
  if (!state) throw Error('请重新登录。');
  try {
    return await window.authFetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(data)});
  } catch (error) {
    if (error.status === 401) location.replace('/login?expired=1');
    throw error;
  }
};
document.querySelectorAll('[data-logout]').forEach(button => button.addEventListener('click',async () => {
  button.disabled = true;
  try {await window.accountRequest('/api/auth/logout'); location.replace('/login');}
  catch {button.disabled=false; button.textContent='退出失败，点击重试';}
}));
window.addEventListener('pageshow',event => {if(event.persisted) location.reload();});
document.querySelectorAll('.account-menu').forEach(menu => {
  const summary=menu.querySelector('summary');
  menu.addEventListener('toggle',()=>summary.setAttribute('aria-expanded',String(menu.open)));
  document.addEventListener('click',event=>{if(!menu.contains(event.target)) menu.open=false;});
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && menu.open){menu.open=false;summary.focus();}});
});
