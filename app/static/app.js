const form = document.querySelector('#audit-form');
const fileInput = document.querySelector('#files');
const fileList = document.querySelector('#file-list');
const dropZone = document.querySelector('#drop-zone');
const submitButton = document.querySelector('#submit-button');
const loading = document.querySelector('#loading');
const errorBox = document.querySelector('#error');
const results = document.querySelector('#results');

const labels = {
  verified: 'Verified',
  false: 'False',
  partly_supported: 'Partly supported',
  outdated: 'Outdated',
  cannot_confirm: 'Cannot confirm',
};

fileInput.addEventListener('change', () => {
  const names = [...fileInput.files].map((file) => file.name);
  fileList.textContent = names.length ? names.join(' · ') : '';
});

for (const name of ['dragenter', 'dragover']) {
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add('dragging');
  });
}
for (const name of ['dragleave', 'drop']) {
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragging');
  });
}
dropZone.addEventListener('drop', (event) => {
  if (event.dataTransfer?.files?.length) {
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event('change'));
  }
});

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function renderEvidence(item) {
  const card = node('article', 'evidence-card');
  card.append(node('div', 'evidence-kicker', `SOURCE · ${item.id}`));
  if (item.publisher === 'User-provided text') {
    card.append(node('span', 'source-context', 'User-provided source text'));
  } else {
    const href = safeUrl(item.url);
    if (!href) return null;
    const title = node('a', '', item.title || item.publisher || 'Open source');
    title.href = href;
    title.target = '_blank';
    title.rel = 'noopener noreferrer';
    card.append(title, node('span', 'publisher', item.publisher || 'Source'));
  }
  if (item.excerpt) card.append(node('p', '', item.excerpt));
  return card;
}

function renderResponse(data) {
  if (!data || !Array.isArray(data.claims) || !Array.isArray(data.evidence)) {
    throw new Error('The server returned an unexpected result. Please try again.');
  }
  const evidenceById = new Map(data.evidence.filter((item) => typeof item?.id === 'string').map((item) => [item.id, item]));
  results.replaceChildren();

  const header = node('div', 'results-head');
  const titleBlock = document.createElement('div');
  titleBlock.append(node('div', 'step-label', 'CHECK COMPLETE'));
  titleBlock.append(node('h2', '', `${data.claims.length} ${data.claims.length === 1 ? 'claim' : 'claims'} checked`));
  titleBlock.append(node('p', '', 'Read the explanation and open the evidence before sharing.'));
  header.append(titleBlock);
  if (data.engine_metadata?.verifier) header.append(node('span', 'engine-note', data.engine_metadata.verifier === 'unavailable' ? 'Verifier unavailable' : 'Evidence check'));
  results.append(header);

  if (Array.isArray(data.warnings) && data.warnings.length) {
    const list = node('ul', 'warning-list');
    data.warnings.forEach((warning) => list.append(node('li', '', warning)));
    results.append(list);
  }

  for (const claim of data.claims) {
    const status = Object.hasOwn(labels, claim?.verdict) ? claim.verdict : 'cannot_confirm';
    const card = node('article', 'claim-card');
    const top = node('div', 'claim-top');
    top.append(node('p', 'claim-text', claim?.claim || 'Claim text unavailable'));
    top.append(node('span', `verdict-pill ${status}`, labels[status]));
    card.append(top);
    card.append(node('p', 'explanation', claim?.explanation || 'No explanation was returned.'));
    card.append(node('div', 'explanation-label', claim?.explanation_label === 'AI-drafted explanation' ? 'AI-drafted · grounded in listed evidence' : 'Evidence-based explanation'));

    const linked = Array.isArray(claim?.evidence_ids)
      ? [...new Set(claim.evidence_ids)].map((id) => evidenceById.get(id)).filter(Boolean)
      : [];
    if (linked.length) {
      const list = node('div', 'evidence-list');
      linked.forEach((item) => {
        const rendered = renderEvidence(item);
        if (rendered) list.append(rendered);
      });
      if (list.childElementCount) card.append(list);
    } else {
      card.append(node('p', 'explanation-label', 'No evidence sources were linked to this claim.'));
    }
    results.append(card);
  }
  results.append(node('div', 'result-foot', 'ForwardCheck provides an evidence-based aid, not a guarantee. Sources may be incomplete or change over time. For health, financial, legal, or safety decisions, check the original authoritative source.'));
  results.classList.remove('hidden');
  results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.classList.add('hidden');
  results.classList.add('hidden');
  loading.classList.remove('hidden');
  submitButton.disabled = true;
  const body = new FormData(form);
  body.set('consent', document.querySelector('#consent').checked ? 'true' : 'false');
  body.set('enable_web_search', document.querySelector('#web-search').checked ? 'true' : 'false');
  try {
    const response = await fetch('/api/audits', { method: 'POST', body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || 'The check could not be completed.');
    renderResponse(payload);
  } catch (error) {
    errorBox.textContent = error instanceof Error ? error.message : 'The check could not be completed.';
    errorBox.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
    submitButton.disabled = false;
  }
});
