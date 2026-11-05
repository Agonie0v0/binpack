// One error boundary for every authentication request, including proxy failures.
window.authFetch = async (path,options={}) => {
  let response;
  try {
    response = await fetch(path,{cache:'no-store',credentials:'same-origin',...options});
  } catch {
    throw Error('无法连接账号服务，请检查网络后重试。');
  }
  let result;
  try {
    result = await response.json();
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw Error();
  } catch {
    throw Object.assign(Error('账号服务暂时不可用，请稍后重试。'),{status:response.status});
  }
  if (!response.ok) {
    const message = typeof result.error === 'string' ? result.error : '操作未完成，请稍后重试。';
    throw Object.assign(Error(message),{status:response.status});
  }
  return result;
};
