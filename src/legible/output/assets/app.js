const form = document.querySelector('form');
form.addEventListener('submit', () => {
  const button = form.querySelector('button');
  button.disabled = true;
  button.textContent = 'Scanning…';
  document.querySelector('#progress').textContent = 'Examining public resources. Some sources may take time to respond.';
  form.setAttribute('aria-busy', 'true');
});
window.addEventListener('pageshow', () => {
  form.querySelector('button').disabled = false;
  form.querySelector('button').textContent = document.querySelector('article') ? 'Rescan' : 'Scan';
  form.removeAttribute('aria-busy');
  document.querySelector('#progress').textContent = '';
});
