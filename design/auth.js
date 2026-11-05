// Credentials are sent only to this origin's server. Never store them in web storage.
const form = document.getElementById('auth-form');
const message = document.getElementById('form-message');
const submit = document.getElementById('auth-submit');
const page = document.body.dataset.authPage;
let authState = null;
function showMessage(text, success=false) {
  message.textContent = text;
  message.classList.toggle('success', success);
}
async function initialize() {
  try {
    authState = await window.authFetch('/api/auth/state');
    if (authState.user) {location.replace('/'); return;}
    if (page === 'setup' && authState.initialized) {location.replace('/login'); return;}
    if (page === 'login') {
      document.getElementById('first-use').hidden = authState.initialized;
      document.getElementById('auth-footnote').hidden = !authState.initialized;
      if (new URLSearchParams(location.search).has('changed')) showMessage('密码已更新，请重新登录。',true);
      else if (new URLSearchParams(location.search).has('expired')) showMessage('登录已过期，请重新登录。');
    }
    submit.disabled = false;
  } catch {
    showMessage('无法连接账号服务，请刷新页面后重试。');
  }
}
document.querySelectorAll('[data-password-target]').forEach(button => {
  const input = document.getElementById(button.dataset.passwordTarget);
  const label = button.getAttribute('aria-label');
  button.addEventListener('click',() => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.setAttribute('aria-pressed',String(show));
    button.setAttribute('aria-label',show ? label.replace('显示','隐藏') : label);
  });
});
const confirm = document.getElementById('confirm-password');
if (confirm) {
  const matchPasswords = () => confirm.setCustomValidity(confirm.value && confirm.value !== form.elements.password.value ? '两次输入的密码不一致。' : '');
  confirm.addEventListener('input',matchPasswords);
  form.elements.password.addEventListener('input',matchPasswords);
}
form.addEventListener('submit',async event => {
  event.preventDefault();
  if (!authState || !form.reportValidity() || submit.disabled) return;
  showMessage('');
  const data = {username:form.elements.username.value.trim(),password:form.elements.password.value};
  if (page === 'setup') data.setup_token = form.elements.setup_token.value.trim();
  else data.remember = form.elements.remember.checked;
  submit.disabled = true;
  submit.setAttribute('aria-busy','true');
  const buttonLabel = submit.querySelector('span');
  const originalLabel = buttonLabel.textContent;
  buttonLabel.textContent = page === 'setup' ? '正在创建账号…' : '正在登录…';
  try {
    await window.authFetch(`/api/auth/${page === 'setup' ? 'setup' : 'login'}`,{
      method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':authState.csrf},body:JSON.stringify(data),
    });
    form.reset();
    location.replace('/');
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '连接失败，请稍后重试。');
    form.elements.password.value = '';
    if (confirm) confirm.value = '';
    submit.disabled = false;
    submit.removeAttribute('aria-busy');
    buttonLabel.textContent = originalLabel;
  }
});
document.getElementById('recovery-toggle')?.addEventListener('click',event => {
  const help = document.getElementById('recovery-help');
  help.hidden = !help.hidden;
  event.currentTarget.setAttribute('aria-expanded',String(!help.hidden));
});
initialize();
window.addEventListener('pageshow',event => {if(event.persisted) {form.reset(); initialize();}});
