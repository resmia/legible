function bindPage() {
  const form = document.querySelector('#scan-form');
  const input = form.querySelector('#domain');
  const button = form.querySelector('button');
  const progress = form.querySelector('#progress');
  const error = form.querySelector('#input-error');
  const another = document.querySelector('#scan-another');
  another?.addEventListener('click', () => {
    form.hidden = false;
    another.setAttribute('aria-expanded', 'true');
    input.focus();
    input.select();
  });
  document.querySelectorAll('.fix-first a').forEach(link => {
    link.addEventListener('click', () => {
      const card = document.getElementById(link.hash.slice(1));
      if (card) card.open = true;
    });
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Scanning…';
    error.hidden = true;
    input.removeAttribute('aria-invalid');
    input.removeAttribute('aria-describedby');
    progress.textContent = 'Examining public resources. Some sources may take time to respond.';
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new URLSearchParams(new FormData(form)),
      });
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (!response.ok) {
        throw new Error(page.querySelector('#input-error')?.textContent || 'The scan could not complete. Please try again.');
      }
      const main = page.querySelector('main');
      if (!main?.querySelector('article')) throw new Error('The scan did not return a report. Please try again.');
      document.querySelector('main').replaceWith(main);
      bindPage();
      const title = document.querySelector('#report-title');
      title.setAttribute('tabindex', '-1');
      title.focus();
    } catch (failure) {
      // Keep the existing report and its expanded cards until a scan succeeds.
      error.textContent = failure instanceof TypeError ? 'The scan could not complete. Check the local server and try again.' : failure.message;
      error.hidden = false;
      input.setAttribute('aria-describedby', 'input-error');
    } finally {
      button.disabled = false;
      button.textContent = 'Scan';
      form.removeAttribute('aria-busy');
      progress.textContent = '';
    }
  });
}
bindPage();
