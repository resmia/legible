// A minimal DOM harness exercises client behavior without network or browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
  return {hidden: false, disabled: false, textContent: '', attrs: {}, handlers: {},
    addEventListener(type, handler) { this.handlers[type] = handler; },
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; },
    focus() { this.focused = true; }, select() { this.selected = true; }};
}
const input = element(), button = element(), progress = element(), error = element();
const another = element(), form = element(), title = element(), card = element();
form.hidden = true;
form.action = 'http://127.0.0.1:8765/scan';
form.querySelector = selector => ({'#domain': input, button, '#progress': progress, '#input-error': error})[selector];
let replaced = 0, response, parsed;
const main = {replaceWith(value) { assert.equal(value, nextMain); replaced++; }};
const nextMain = {querySelector: () => ({})};
const link = {...element(), hash: '#key-issuance'};
const document = {
  querySelector: selector => ({'#scan-form': form, '#scan-another': another, main, '#report-title': title})[selector],
  querySelectorAll: () => [link], getElementById: id => id === 'key-issuance' ? card : null,
};
const context = {document, URLSearchParams, FormData: class {}, TypeError, Error,
  DOMParser: class {parseFromString() { return parsed; }}, fetch: async () => response};
vm.runInNewContext(fs.readFileSync('src/legible/output/assets/app.js', 'utf8'), context);
(async () => {
  another.handlers.click();
  assert.equal(form.hidden, false);
  assert.equal(another.attrs['aria-expanded'], 'true');
  assert.ok(input.focused && input.selected);
  link.handlers.click();
  assert.equal(card.open, true);
  const submit = () => form.handlers.submit({preventDefault() {}});
  for (const status of [400, 403, 409, 500]) {
    response = {ok: false, status, text: async () => ''};
    parsed = {querySelector: () => ({textContent: `Error ${status}`})};
    await submit();
    assert.equal(replaced, 0);
    assert.equal(error.textContent, `Error ${status}`);
    assert.equal(error.hidden, false);
    assert.equal(button.disabled, false);
    assert.equal(card.open, true);
  }
  context.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await submit();
  assert.equal(replaced, 0);
  assert.match(error.textContent, /Check the local server/);
  // The old report remains present while the next response is pending.
  let resolve;
  context.fetch = () => new Promise(done => { resolve = done; });
  const pending = submit();
  assert.equal(replaced, 0);
  assert.equal(button.disabled, true);
  assert.equal(form.attrs['aria-busy'], 'true');
  parsed = {querySelector: () => nextMain};
  resolve({ok: true, text: async () => ''});
  await pending;
  assert.equal(replaced, 1);
  assert.ok(title.focused);
  assert.equal(button.disabled, false);
  assert.equal(progress.textContent, '');
  assert.equal(form.attrs['aria-busy'], undefined);
  console.log('Browser interaction harness passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
