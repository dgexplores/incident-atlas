const $ = (selector) => document.querySelector(selector);
const svgNS = 'http://www.w3.org/2000/svg';
let workspace = null, selected = null, busy = false;
const colors = ['#245db7', '#087f78', '#a05b18', '#7960ad'];
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function svg(tag, attrs) { const node = document.createElementNS(svgNS, tag); for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value); return node; }
function notice(text, error = false) { $('#status').textContent = text; $('#status').classList.toggle('error', error); }
async function api(path, body) {
  const response = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
  let data; try { data = await response.json(); } catch { throw Error('The service returned an unreadable response. Try again shortly.'); }
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the selected exercise and try again.');
  return data;
}
function renderChart() {
  const canvas = svg('svg', {viewBox: '0 0 1000 250', role: 'img', 'aria-label': workspace.chart_metric ? `${workspace.chart_metric} across observed services by sample index` : 'Latency across four services, over 100 synthetic minutes'});
  const max = Math.max(workspace.chart_metric ? 100 : 200, ...workspace.chart.flatMap(series => series.points.map(point => point.value))) * 1.1;
  const lastSample = Math.max(1, ...workspace.chart.flatMap(series => series.points.map(p => p.minute)));
  const x = minute => 58 + minute / lastSample * 912, y = value => 210 - value / max * 180;
  canvas.append(svg('rect', {x: 58, y: 20, width: x(Math.min(workspace.baseline_points || 50, lastSample)) - 58, height: 190, fill: '#f0f5fb'}));
  const label = svg('text', {x: 70, y: 38, fill: '#596d7d', 'font-size': 14}); label.textContent = 'Baseline'; canvas.append(label);
  for (let i = 0; i <= 4; i++) {
    const value = max * i / 4, top = y(value);
    canvas.append(svg('line', {x1: 58, y1: top, x2: 970, y2: top, stroke: '#e0e7ee'}));
    const text = svg('text', {x: 48, y: top + 5, fill: '#596d7d', 'text-anchor': 'end', 'font-size': 14}); text.textContent = Math.round(value); canvas.append(text);
  }
  [0, 0.2, 0.4, 0.6, 0.8, 1].map(fraction => Math.round(fraction * lastSample)).forEach(minute => { const text = svg('text', {x: x(minute), y: 237, fill: '#596d7d', 'text-anchor': 'middle', 'font-size': 14}); text.textContent = `${minute}${workspace.chart_metric ? '' : 'm'}`; canvas.append(text); });
  workspace.chart.forEach((series, index) => { canvas.append(svg('polyline', {points: series.points.map(point => `${x(point.minute)},${y(point.value)}`).join(' '), fill: 'none', stroke: colors[index % colors.length], 'stroke-width': 2.5, 'stroke-linejoin': 'round'})); });
  $('#chart').setAttribute('aria-label', workspace.chart_metric ? `${workspace.chart_metric} across observed services by sample index` : 'Service latency over 100 synthetic minutes');
  $('#chart').replaceChildren(canvas);
  $('#legend').replaceChildren(); workspace.chart.forEach((series, index) => { const span = el('span'), icon = svg('svg', {width: 15, height: 5, 'aria-hidden': 'true'}); icon.append(svg('line', {x1: 0, y1: 2, x2: 15, y2: 2, stroke: colors[index % colors.length], 'stroke-width': 3})); span.append(icon, el('span', series.service)); $('#legend').append(span); });
}
function renderQueue() {
  const list = $('#incident-list'); list.replaceChildren();
  const incidents = workspace.incidents.filter(incident => $('#filter').value === 'all' || incident.state === $('#filter').value);
  if (!incidents.length) { const empty = el('div', undefined, 'empty'); empty.append(el('h2', workspace.incidents.length ? 'No incidents in this state' : 'No sustained anomalies'), el('p', workspace.incidents.length ? 'Choose another filter to continue your investigation.' : 'No sustained change met the detector rules. Inspect the baseline and workload before treating this as proof of health.')); list.append(empty); }
  incidents.forEach(incident => {
    const button = el('button', undefined, `incident-card${selected === incident.id ? ' selected' : ''}`); button.type = 'button'; button.setAttribute('aria-pressed', selected === incident.id ? 'true' : 'false');
    const badges = el('div', undefined, 'badges'); badges.append(el('span', incident.severity.toUpperCase(), `badge ${incident.severity}`), el('span', incident.state, `badge ${incident.state}`));
    button.append(badges, el('h3', incident.title), el('p', `${incident.services.join(' → ')}`), el('p', `${incident.evidence.length} findings · ${workspace.chart_metric ? "sample" : "minute"} ${incident.start_minute}–${incident.end_minute}`));
    button.addEventListener('click', () => selectIncident(incident.id)); list.append(button);
  });
}
function renderDetail(incident) {
  const panel = $('#detail'); panel.replaceChildren();
  const heading = el('div', undefined, 'panel-heading'), lead = el('div'), badges = el('div', undefined, 'badges');
  badges.append(el('span', incident.severity.toUpperCase(), `badge ${incident.severity}`), el('span', incident.state, `badge ${incident.state}`));
  lead.append(badges, el('h2', incident.title), el('p', `${workspace.chart_metric ? "Sample" : "Minute"} ${incident.start_minute}–${incident.end_minute} · ${incident.services.length} affected services`, 'subline')); heading.append(lead); panel.append(heading);
  const body = el('div', undefined, 'detail-body');
  incident.hypotheses.forEach(hypothesis => { const card = el('article', undefined, 'hypothesis'); card.append(el('span', hypothesis.strength, 'badge'), el('h3', hypothesis.title)); const basis = el('p'); basis.append(el('strong', 'Evidence: '), document.createTextNode(hypothesis.basis.join(' · '))); const next = el('p'); next.append(el('strong', 'Next check: '), document.createTextNode(hypothesis.next_check)); card.append(basis, next); body.append(card); });
  body.append(el('p', incident.limitation, 'limitation'), el('h3', 'Observed signals', 'evidence-title'));
  const evidence = el('div', undefined, 'evidence');
  incident.evidence.forEach(item => { const row = el('article', undefined, 'evidence-row'); row.append(el('strong', `${item.service} / ${item.metric}`), el('span', `${item.peak.toFixed(1)} ${item.unit}`, 'value'), el('small', `${item.id} · ${item.observations} sustained observations`), el('small', `Baseline ${item.baseline.toFixed(1)} ${item.unit} · robust z ${item.robust_z}`)); evidence.append(row); }); body.append(evidence);
  const form = el('form', undefined, 'review'); form.append(el('h3', 'Record a review'), el('p', 'Changes affect this investigation record only. They do not run a command or change infrastructure.'));
  const stateLabel = el('label', 'Investigation state'); stateLabel.htmlFor = 'review-state'; const state = el('select'); state.id = 'review-state'; for (const value of ['open', 'investigating', 'resolved']) { const option = el('option', value); option.value = value; option.selected = value === incident.state; state.append(option); }
  const noteLabel = el('label', 'Review note (optional)'); noteLabel.htmlFor = 'review-note'; const note = el('textarea'); note.id = 'review-note'; note.maxLength = 1500; note.placeholder = 'What did you check? What evidence is still missing?';
  const save = el('button', 'Save review', 'primary'); save.type = 'submit'; const feedback = el('p'); feedback.setAttribute('role', 'status');
  form.append(stateLabel, state, noteLabel, note, save, feedback);
  form.addEventListener('submit', async event => { event.preventDefault(); save.disabled = true; feedback.textContent = 'Saving…'; try { const updated = await api(`/api/incidents/${incident.id}/review`, {state: state.value, note: note.value}); workspace.incidents.find(item => item.id === incident.id).state = updated.state; renderQueue(); renderDetail(updated); notice('Review saved. The exercise state is stored for this browser session.'); } catch (error) { feedback.textContent = error.message; save.disabled = false; } });
  body.append(modelPanel(incident));
  body.append(form, el('h3', 'Review history', 'evidence-title')); const events = el('ol', undefined, 'events'); incident.events.forEach(event => { const item = el('li'); const time = el('time', new Date(event.created).toLocaleString()); time.dateTime = event.created; item.append(time, document.createTextNode(event.message)); events.append(item); }); body.append(events); panel.append(body);
}
async function selectIncident(id) {
  selected = id; renderQueue(); $('#detail').replaceChildren(el('div', 'Loading evidence…', 'empty'));
  try { const data = await api(`/api/incidents/${id}`); if (selected === id) renderDetail(data); } catch (error) { $('#detail').replaceChildren(el('div', error.message, 'empty')); }
}
async function renderWorkspace(data) {
  workspace = data; selected = null; if (data.seed !== null) $('#scenario').value = data.scenario; $('#filter').value = 'all';
  $('#observations').textContent = data.metrics_observed.toLocaleString(); $('#findings').textContent = data.findings.length; $('#incidents-count').textContent = data.incidents.length; renderChart(); renderQueue();
  notice(`${data.scenario_title} · ${data.mode}${data.seed === null ? '' : ` · seed ${data.seed}`}`);
  $('#scope-caption').textContent = data.chart_metric ? `${data.chart.length} observed services · uploaded data` : 'Four services · five metrics';
  $('#baseline-value').textContent = `${data.baseline_points || 50} ${data.chart_metric ? 'samples' : 'min'}`;
  $('#baseline-caption').textContent = 'Frozen opening window; not updated by later faults';
  $('#chart-title').textContent = data.chart_metric ? `${data.chart_metric}: observed changes by sample` : 'Service latency: find where it changed.';
  if (data.chart_metric) { $('#chart-caption').replaceChildren(el('span', `Average capture cadence: ${data.sample_interval_seconds.toFixed(2)} seconds. X axis: sample index.`), el('span', 'Uploaded values are not independently authenticated.')); } else { $('#chart-caption').replaceChildren(el('span', 'Opening 50 minutes establish each metric’s baseline.'), el('span', 'Faults begin at minute 60 in fault scenarios.')); }
  if (data.incidents.length) await selectIncident(data.incidents[0].id); else { const empty = el('div', undefined, 'empty'); empty.append(el('h2', 'A quiet system is a useful result.'), el('p', 'No incident met the current detector rules. Check whether the baseline represents a healthy workload.')); $('#detail').replaceChildren(empty); }
}
$('#filter').addEventListener('change', () => { if (workspace) renderQueue(); });
$('#replay').addEventListener('click', async () => { if (busy) return; busy = true; $('#replay').disabled = true; notice('Generating telemetry and running the detector…'); try { await renderWorkspace(await api('/api/exercises', {scenario: $('#scenario').value, seed: 42})); } catch (error) { notice(error.message, true); } finally { busy = false; $('#replay').disabled = false; } });
api('/api/workspace').then(renderWorkspace).catch(error => notice(`${error.message} Reload to retry.`, true));

function modelPanel(incident) {
  const area = el('section', undefined, 'model-panel');
  area.append(el('h3', 'Evidence and runbooks'), el('p', 'Local runbook matching is always available. Optional model assistance sends these metric findings to the configured provider; it never executes suggested actions.'));
  const references = el('div'); area.append(references);
  api(`/api/incidents/${incident.id}/context`).then(context => {
    for (const book of context.runbooks) { const article = el('article'); article.append(el('strong', book.title), el('p', book.text)); references.append(article); }
  }).catch(error => references.append(el('p', error.message)));
  const label = el('label', 'Operator token for optional model call'); label.htmlFor = 'operator-token';
  const token = el('input'); token.id = 'operator-token'; token.type = 'password'; token.autocomplete = 'off';
  const button = el('button', 'Request model-assisted hypothesis', 'primary'); button.type = 'button';
  const feedback = el('div'); feedback.setAttribute('role', 'status');
  button.addEventListener('click', async () => {
    if (!token.value) { feedback.textContent = 'Enter the server operator token. Model calls are disabled until a provider is configured.'; return; }
    button.disabled = true; feedback.textContent = 'Checking supplied evidence with the configured model…';
    try {
      const response = await fetch(`/api/incidents/${incident.id}/explain`, {method: 'POST', headers: {'X-Atlas-Token': token.value}});
      token.value = ''; const data = await response.json(); if (!response.ok) throw Error(data.detail || 'Model assistance failed.');
      feedback.replaceChildren(el('h3', data.hypothesis), el('p', `Evidence: ${data.evidence_ids.join(', ')}. Runbooks: ${data.runbook_ids.join(', ')}.`));
      const list = el('ul'); data.next_checks.forEach(check => list.append(el('li', check))); feedback.append(list, el('p', data.limitation));
    } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
  }); area.append(label, token, button, feedback); return area;
}
$('#telemetry-form').addEventListener('submit', async event => {
  event.preventDefault(); const input = $('#telemetry-file'), file = input.files[0]; if (!file || busy) return;
  if (file.size > 1048576) { notice('Telemetry JSON must be at most 1 MiB.', true); return; }
  busy = true; const button = event.currentTarget.querySelector('button'); button.disabled = true;
  try { notice('Validating measurements and running the detector…'); await renderWorkspace(await api('/api/telemetry', JSON.parse(await file.text()))); }
  catch (error) { notice(error.message, true); } finally { busy = false; button.disabled = false; }
});
