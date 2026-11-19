(() => {
  document.addEventListener('click', event => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest('.text-toggle');
    if (!button) return;
    const wrapper = button.closest('.folded-text');
    const expand = button.getAttribute('aria-expanded') !== 'true';
    wrapper.querySelector('.text-preview').hidden = expand;
    wrapper.querySelector('.text-full').hidden = !expand;
    button.setAttribute('aria-expanded', String(expand));
    button.textContent = expand ? 'Show less' : 'Show all';
  });

  const exportButton = document.getElementById('exportReviewDecisions');
  if (!exportButton) return;
  const rows = () => document.querySelectorAll('#findingsContainer .finding[data-finding-id]');
  const currentIds = () => new Set(Array.from(rows()).map(row => row.dataset.findingId));
  const state = new Map();
  const actions = new Set(['fix', 'accept_risk', 'defer', 'false_positive', 'duplicate']);
  const initialIds = currentIds();
  for (const decision of {{ review_decisions | tojson }}) {
    if (decision && initialIds.has(decision.finding_id) && actions.has(decision.action)) {
      const value = {finding_id:decision.finding_id, action:decision.action, rationale:typeof decision.rationale === 'string' ? decision.rationale : ''};
      for (const key of ['severity_feedback', 'resolve_thread', 'ticket', 'assignee', 'due_date']) {
        if (Object.prototype.hasOwnProperty.call(decision, key)) value[key] = decision[key];
      }
      state.set(decision.finding_id, value);
    }
  }
  function count() {
    const current = currentIds();
    const selected = Array.from(state.values()).filter(value => current.has(value.finding_id) && actions.has(value.action)).length;
    document.getElementById('reviewDecisionCount').textContent = selected + (selected === 1 ? ' decision' : ' decisions');
  }
  function restore() {
    rows().forEach(row => {
      const value = state.get(row.dataset.findingId);
      if (!value) return;
      row.querySelector('.review-action').value = value.action;
      row.querySelector('.review-rationale').value = value.rationale;
    });
    count();
  }
  function remember(event) {
    if (!(event.target instanceof Element)) return;
    if (!event.target.matches('.review-action, .review-rationale')) return;
    const row = event.target.closest('.finding[data-finding-id]');
    const findingId = row.dataset.findingId;
    state.set(findingId, {...state.get(findingId), finding_id:findingId, action:row.querySelector('.review-action').value, rationale:row.querySelector('.review-rationale').value});
    count();
  }
  document.addEventListener('change', remember);
  document.addEventListener('input', remember);
  document.addEventListener('report:render', restore);
  exportButton.addEventListener('click', () => {
    const current = currentIds();
    const decisions = Array.from(state.values()).filter(value => current.has(value.finding_id) && actions.has(value.action));
    const payload = {report:document.title, triaged_at:new Date().toISOString(), decisions};
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'triage-decisions.json';
    link.click();
    URL.revokeObjectURL(url);
  });
  restore();
})();
