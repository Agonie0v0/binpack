const passwordForm = document.getElementById('password-form');
const passwordMessage = document.getElementById('password-message');
const passwordSubmit = document.getElementById('password-submit');
const confirmation = document.getElementById('confirm-password');
const freshPassword = document.getElementById('new-password');
window.sessionReady.then(state => {if(state) passwordSubmit.disabled=false;});
document.querySelectorAll('[data-password-target]').forEach(button => {
  const label = button.getAttribute('aria-label');
  button.addEventListener('click',() => {
    const input = document.getElementById(button.dataset.passwordTarget);
    const show = input.type==='password';
    input.type=show?'text':'password';
    button.setAttribute('aria-pressed',String(show));
    button.setAttribute('aria-label',show?label.replace('显示','隐藏'):label);
  });
});
const match = () => confirmation.setCustomValidity(confirmation.value && confirmation.value!==freshPassword.value?'两次输入的新密码不一致。':'');
confirmation.addEventListener('input',match); freshPassword.addEventListener('input',match);
passwordForm.addEventListener('submit',async event => {
  event.preventDefault();
  if(passwordSubmit.disabled || !passwordForm.reportValidity()) return;
  passwordMessage.textContent=''; passwordSubmit.disabled=true; passwordSubmit.textContent='正在保存…';
  try {
    await window.accountRequest('/api/auth/password',{current_password:passwordForm.elements.current_password.value,new_password:freshPassword.value});
    passwordForm.reset(); location.replace('/login?changed=1');
  } catch(error) {
    passwordMessage.textContent=error instanceof Error?error.message:'保存失败，请稍后重试。';
    passwordForm.elements.current_password.value=''; passwordSubmit.disabled=false; passwordSubmit.textContent='保存新密码';
  }
});
