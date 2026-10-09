'use strict';

const topics = ['有机化学','高分子化学','晶体化学','无机综合与结构推断','方程式与元素化学','热力学与化学平衡','电化学','动力学','分析化学'];
const slugs = ['organic','polymer','crystal','inference','elements','equilibrium','electrochemistry','kinetics','analysis'];
const slugByTopic = Object.fromEntries(topics.map((t,i) => [t,slugs[i]]));
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const editionOf = q => q.edition ?? 39;
const paperKey = q => editionOf(q) === 39 ? String(q.paper) : `${editionOf(q)}-${q.paper}`;
const editionLabel = e => String(e) === '0' ? 'Chemy 联赛' : `第${e}届`;
const chevron = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
let questions = [], presentation = {}, numbers = {}, pdfVersion = 'topic-numbering-v1';
let byId = new Map(), byTopic = new Map(), paperLabels = new Map();
let activeTopic = topics[0], selectedEdition = 'all', selectedPaper = 'all', activeQuestion = '';
let ready = false, observer, lastUrl = '', scrollLockUntil = 0;
const expandedByTopic = new Map();
const openAnswers = new Set();
let openPanelId = '', panelTrigger = null, panelScrollY = 0;
let searchIndex = null, indexPromise = null, searchTimer, searchScroll = 0;
let searchMatches = [], searchTerms = [], shownResults = 0;
let searchSignature = '';
let showingIntroduction = true;
const summaryById = new Map();

function questionTitle(q, bodyText) {
  if (q.title) return q.id === 'chemy32-12-22' ? q.title.replace('5-4', `${numbers[q.id]}-4`) : q.title;
  if (!summaryById.has(q.id)) {
    const text = bodyText ?? htmlText(presentation[q.id].body);
    summaryById.set(q.id,`题干：${text.slice(0,42)}${text.length > 42 ? '…' : ''}`);
  }
  return summaryById.get(q.id);
}
function paperLabel(key) { return paperLabels.get(String(key)) || ''; }
function shortPaperLabel(q) {
  return editionOf(q) === 0 ? `第${q.paper}届联赛` : q.sourcePaperLabel || `模拟试题 ${q.paper}`;
}
function editionValues(list) { return [...new Set(list.map(editionOf))].sort((a,b) => b-a); }
function option(value, label, selected) {
  return `<option value="${escapeHtml(value)}"${String(value) === String(selected) ? ' selected' : ''}>${escapeHtml(label)}</option>`;
}
function lazyFigures(html) {
  return html.replace(/<img\b/g, '<img loading="lazy" decoding="async"');
}
function sourceLine(q) {
  return `${escapeHtml(paperLabel(paperKey(q)))} · 原第 ${q.number} 题　题目合集第 ${escapeHtml(q.questionPages)} 页 · 答案合集第 ${escapeHtml(q.answerPages)} 页${q.answerCorrectionPages ? ' · 官方答案补正第 '+escapeHtml(q.answerCorrectionPages)+' 页' : ''}`;
}
function rememberPosition() {
  history.replaceState({...history.state,scrollY:openPanelId ? panelScrollY : window.scrollY},'',location.href);
}
function writeUrl(questionId = '', push = true) {
  const url = new URL(location.href);
  url.hash = slugByTopic[activeTopic];
  for (const [key,value] of [['edition',selectedEdition],['paper',selectedPaper],['question',questionId]]) {
    if (!value || value === 'all') url.searchParams.delete(key);
    else url.searchParams.set(key,value);
  }
  if (push) { rememberPosition(); history.pushState({question:questionId},'',url); }
  else history.replaceState({...history.state,question:questionId},'',url);
  lastUrl = location.href;
}
function readUrl() {
  const params = new URLSearchParams(location.search);
  showingIntroduction = !location.hash || location.hash === '#about';
  activeTopic = topics[slugs.indexOf(location.hash.slice(1))] || topics[0];
  selectedEdition = params.get('edition') || 'all';
  selectedPaper = params.get('paper') || 'all';
  activeQuestion = params.get('question') || '';
  const q = byId.get(activeQuestion);
  if (q && q.topic === activeTopic) {
    if (selectedEdition !== 'all' && String(editionOf(q)) !== selectedEdition) selectedEdition = 'all';
    if (selectedPaper !== 'all' && paperKey(q) !== selectedPaper) selectedPaper = 'all';
  } else activeQuestion = '';
  lastUrl = location.href;
}
function currentList() {
  return (byTopic.get(activeTopic) || []).filter(q => (selectedEdition === 'all' || String(editionOf(q)) === selectedEdition) && (selectedPaper === 'all' || paperKey(q) === selectedPaper));
}
function renderFilters() {
  const all = byTopic.get(activeTopic) || [];
  const editions = editionValues(all);
  if (selectedEdition !== 'all' && !editions.map(String).includes(selectedEdition)) selectedEdition = 'all';
  const candidates = all.filter(q => selectedEdition === 'all' || String(editionOf(q)) === selectedEdition);
  const papers = [...new Set(candidates.map(paperKey))];
  if (selectedPaper !== 'all' && !papers.includes(selectedPaper)) selectedPaper = 'all';
  $('edition-select').innerHTML = option('all','全部届次',selectedEdition) + editions.map(e => option(e,editionLabel(e),selectedEdition)).join('');
  $('paper-select').innerHTML = option('all','全部试卷',selectedPaper) + papers.map(p => option(p,paperLabel(p),selectedPaper)).join('');
  $('edition-select').disabled = $('paper-select').disabled = false;
  $('number-jump').querySelector('button').disabled = false;
}
function renderDirectory(list) {
  let expanded = expandedByTopic.get(activeTopic);
  if (!expanded) {
    expanded = new Set(list.length ? [`edition-${editionOf(list[0])}`, `paper-${paperKey(list[0])}`] : []);
    expandedByTopic.set(activeTopic,expanded);
  }
  $('directory-count').textContent = `${list.length} 道题 · 点击标题定位原题`;
  $('directory-tree').innerHTML = editionValues(list).map(e => {
    const editionQs = list.filter(q => editionOf(q) === e);
    const ekey = `edition-${e}`;
    const papers = [...new Set(editionQs.map(paperKey))];
    return `<details class="edition-group" data-group="${ekey}"${expanded.has(ekey) ? ' open' : ''}><summary>${editionLabel(e)}<span class="group-count">${editionQs.length} 题</span></summary>${papers.map(p => {
      const items = editionQs.filter(q => paperKey(q) === p);
      const pkey = `paper-${p}`;
      return `<details class="paper-group" data-group="${pkey}"${expanded.has(pkey) ? ' open' : ''}><summary>${escapeHtml(shortPaperLabel(items[0]))}<span class="group-count">${items.length} 题</span></summary>${items.map(q => `<a class="directory-item" href="?question=${encodeURIComponent(q.id)}#${slugByTopic[q.topic]}" data-question="${escapeHtml(q.id)}"><span class="directory-number">专题第 ${numbers[q.id]} 题</span>${escapeHtml(questionTitle(q))}</a>`).join('')}</details>`;
    }).join('')}</details>`;
  }).join('') || '<p class="loading-note">当前筛选下没有题目，请选择其他试卷。</p>';
}
function markQuestion(id, reveal = false) {
  activeQuestion = id;
  $('directory-tree').querySelector('[aria-current="location"]')?.removeAttribute('aria-current');
  const link = $('directory-tree').querySelector(`[data-question="${CSS.escape(id)}"]`);
  if (!link) return;
  link.setAttribute('aria-current','location');
  if (reveal) {
    for (let parent = link.parentElement; parent && parent !== $('directory-tree'); parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
    const tree = $('directory-tree');
    const rect = link.getBoundingClientRect(), viewport = tree.getBoundingClientRect();
    if (rect.top < viewport.top || rect.bottom > viewport.bottom) tree.scrollTop += rect.top - viewport.top - 50;
  }
}
function render() {
  document.body.classList.toggle('show-introduction',showingIntroduction);
  $('introduction').hidden = !showingIntroduction;
  $('reading').hidden = showingIntroduction;
  document.querySelector('.skip').textContent = showingIntroduction ? '跳转到介绍' : '跳转到题目';
  if (showingIntroduction) $('about-link').setAttribute('aria-current','page');
  else $('about-link').removeAttribute('aria-current');
  $('categories').innerHTML = topics.map(t => `<button class="category" data-topic="${escapeHtml(t)}"${!showingIntroduction && t === activeTopic ? ' aria-current="page"' : ''}><span class="category-name">${t}</span><span class="count">${byTopic.get(t).length}</span></button>`).join('');
  if (showingIntroduction) {
    observer?.disconnect(); document.title = 'Chemy 化学竞赛专题题库';
    $('questions').setAttribute('aria-busy','false');
    return;
  }
  renderFilters();
  const all = byTopic.get(activeTopic) || [], list = currentList();
  document.title = `${activeTopic} · Chemy 化学竞赛专题题库`;
  $('topic-title').textContent = activeTopic;
  const range = selectedPaper !== 'all' ? paperLabel(selectedPaper) : selectedEdition !== 'all' ? editionLabel(selectedEdition) : `${new Set(list.map(paperKey)).size} 份试卷`;
  $('topic-summary').textContent = `${list.length} 道完整大题 · ${range}`;
  $('downloads').innerHTML = all.length && all.every(q => q.pdfReady) ? `<a class="download" href="downloads/${slugByTopic[activeTopic]}-questions.pdf?v=${encodeURIComponent(pdfVersion)}" download title="下载本专题全部 ${all.length} 道题，包含所有试卷">专题题目 PDF</a><a class="download" href="downloads/${slugByTopic[activeTopic]}-answers.pdf?v=${encodeURIComponent(pdfVersion)}" download title="下载本专题全部参考答案，包含所有试卷">专题答案 PDF</a>` : '';
  $('questions').innerHTML = list.map(q => {
    const score = q.points == null ? '' : `（${q.points} 分${q.percent == null ? '' : '，占 '+q.percent+'%'}）`;
    const answerOpen = openAnswers.has(q.id);
    return `<article class="question" id="${escapeHtml(q.id)}" tabindex="-1"><div class="q-meta"><span class="topic-badge">${q.topic}</span><span>专题第 ${numbers[q.id]} 题</span>${q.points == null ? '' : `<span>${q.points} 分</span>`}</div><h2 class="q-title">第 ${numbers[q.id]} 题　${presentation[q.id].titleHtml || q.titleHtml || escapeHtml(q.title)}${score}</h2><div class="q-origin">来源：${sourceLine(q)}</div><div class="q-body">${lazyFigures(presentation[q.id].body)}</div><details class="answers" data-answer="${escapeHtml(q.id)}"${answerOpen ? ' open' : ''}><summary><span>${answerOpen ? '收起' : '查看'}参考答案</span>${chevron}</summary><div class="answer-caption">原卷参考答案与评分细则</div><div class="answer-content"${answerOpen ? ' data-loaded="true"' : ''}>${answerOpen ? lazyFigures(presentation[q.id].answer) : ''}</div></details></article>`;
  }).join('') || '<section class="empty"><h2>当前筛选下没有题目</h2><p>请在目录中选择其他届次或全部试卷。</p></section>';
  $('questions').setAttribute('aria-busy','false');
  $('number-status').textContent = '';
  renderDirectory(list);
  observer?.disconnect();
  observer = new IntersectionObserver(entries => {
    if (Date.now() < scrollLockUntil) return;
    const visible = entries.filter(e => e.isIntersecting).sort((a,b) => a.boundingClientRect.top-b.boundingClientRect.top);
    if (visible[0]) markQuestion(visible[0].target.id);
  }, {rootMargin:'-140px 0px -60% 0px',threshold:0});
  document.querySelectorAll('.question').forEach(article => observer.observe(article));
  if (activeQuestion) markQuestion(activeQuestion,true);
  else if (list.length) markQuestion(list[0].id);
}
function scrollToQuestion(id, focus = true) {
  const article = $(id);
  if (!article) return;
  scrollLockUntil = Date.now()+500;
  markQuestion(id,true);
  requestAnimationFrame(() => {
    article.scrollIntoView({block:'start',behavior:'instant'});
    if (focus) article.focus({preventScroll:true});
  });
}
function navigateQuestion(id, fromSearch = false) {
  const q = byId.get(id);
  if (!q) return;
  const needsRender = showingIntroduction || q.topic !== activeTopic || !$(id);
  showingIntroduction = false;
  if (needsRender) { activeTopic = q.topic; selectedEdition = 'all'; selectedPaper = 'all'; activeQuestion = id; render(); }
  writeUrl(id);
  closePanel(false);
  if (fromSearch) $('return-search').hidden = false;
  scrollToQuestion(id);
}
function restoreUrl() {
  if (!ready || lastUrl === location.href) return;
  readUrl(); const target = activeQuestion; render(); closePanel(false);
  if (target && !showingIntroduction) scrollToQuestion(target,false);
  else requestAnimationFrame(() => window.scrollTo({top:history.state?.scrollY || 0,behavior:'instant'}));
}

// Temporary drawers are modal on small screens, with keyboard focus and scroll kept inside.
function closePanel(restoreFocus = true) {
  if (!openPanelId) return;
  const panel = $(openPanelId);
  panel.classList.remove('open'); panel.removeAttribute('role'); panel.removeAttribute('aria-modal');
  for (const el of [$('main'),document.querySelector('.site-header'),$('sidebar'),$('directory-pane')]) el.inert = false;
  $('overlay').hidden = true;
  $('topic-toggle').setAttribute('aria-expanded','false'); $('directory-toggle').setAttribute('aria-expanded','false');
  document.body.style.position = ''; document.body.style.top = ''; document.body.style.width = '';
  window.scrollTo({top:panelScrollY,behavior:'instant'});
  openPanelId = '';
  if (restoreFocus) panelTrigger?.focus({preventScroll:true});
}
function openPanel(id, trigger) {
  if (!ready) return;
  if (openPanelId === id) { closePanel(); return; }
  closePanel(false); panelScrollY = window.scrollY; panelTrigger = trigger; openPanelId = id;
  const panel = $(id);
  panel.classList.add('open'); panel.setAttribute('role','dialog'); panel.setAttribute('aria-modal','true');
  $('main').inert = true; document.querySelector('.site-header').inert = true;
  $(id === 'sidebar' ? 'directory-pane' : 'sidebar').inert = true;
  $('overlay').hidden = false; trigger.setAttribute('aria-expanded','true');
  document.body.style.position = 'fixed'; document.body.style.top = `-${panelScrollY}px`; document.body.style.width = '100%';
  panel.querySelector('button,input,select,a')?.focus();
  if (id === 'directory-pane' && activeQuestion) markQuestion(activeQuestion,true);
}

// Search uses the existing text only, without changing the original question or image data.
function normalizeText(text) {
  return text.normalize('NFKC').replace(/[−–—‐‑]/g,'-').replace(/\s+/g,' ').trim();
}
function htmlText(html) {
  const template = document.createElement('template');
  template.innerHTML = html.replace(/<\/(?:p|div|li|h[1-6]|tr)>|<br\s*\/?>/gi,'$& ');
  const extra = [...template.content.querySelectorAll('img[alt]')].map(img => img.alt).filter(alt => alt && !/原图|模拟试题.*题目|模拟试题.*答案/.test(alt)).join(' ');
  return normalizeText(template.content.textContent+' '+extra);
}
function prepareSearchIndex() {
  if (indexPromise) return indexPromise;
  indexPromise = new Promise(resolve => {
    const items = []; let offset = 0;
    function batch() {
      const end = Math.min(offset+65,questions.length);
      for (;offset<end;offset++) {
        const q = questions[offset], body = htmlText(presentation[q.id].body), title = normalizeText(questionTitle(q,body));
        items.push({q,title,body,titleLower:normalizeText(q.title || '').toLowerCase(),bodyLower:body.toLowerCase(),answer:null,answerLower:null});
      }
      if (offset < questions.length) setTimeout(batch,0);
      else { searchIndex = items; resolve(items); }
    }
    batch();
  });
  return indexPromise;
}
function refreshSearchPapers() {
  const topic = $('search-topic').value, edition = $('search-edition').value, selected = $('search-paper').value;
  const candidates = questions.filter(q => (topic === 'all' || q.topic === topic) && (edition === 'all' || String(editionOf(q)) === edition));
  const keys = [...new Set(candidates.map(paperKey))];
  $('search-paper').innerHTML = option('all','全部试卷',selected) + keys.map(key => option(key,paperLabel(key),selected)).join('');
  if (!keys.includes(selected)) $('search-paper').value = 'all';
}
function highlight(text, terms) {
  const lower = text.toLowerCase(), ranges = [];
  for (const term of terms) {
    let start = 0;
    while ((start = lower.indexOf(term,start)) !== -1) { ranges.push([start,start+term.length]); start += term.length; }
  }
  ranges.sort((a,b) => a[0]-b[0]);
  const merged = [];
  for (const range of ranges) {
    if (merged.length && range[0] <= merged[merged.length-1][1]) merged[merged.length-1][1] = Math.max(range[1],merged[merged.length-1][1]);
    else merged.push([...range]);
  }
  let result = '', cursor = 0;
  for (const [start,end] of merged) { result += escapeHtml(text.slice(cursor,start))+`<mark>${escapeHtml(text.slice(start,end))}</mark>`; cursor = end; }
  return result+escapeHtml(text.slice(cursor));
}
function snippet(item, terms) {
  const text = item.answerMatch ? item.answer : item.body;
  const lower = text.toLowerCase();
  const hits = terms.map(term => lower.indexOf(term)).filter(index => index >= 0);
  const start = Math.max(0,(hits.length ? Math.min(...hits) : 0)-34);
  const excerpt = text.slice(start,start+155);
  return (start ? '…' : '')+highlight(excerpt,terms)+(start+155<text.length ? '…' : '');
}
function appendResults(reset = false) {
  if (reset) { $('search-results').innerHTML = ''; shownResults = 0; }
  $('more-results')?.remove();
  const batch = searchMatches.slice(shownResults,shownResults+60);
  $('search-results').insertAdjacentHTML('beforeend',batch.map(item => {
    const q = item.q;
    return `<button class="search-result" data-search-question="${escapeHtml(q.id)}"><span class="result-meta">${escapeHtml(q.topic)} · 专题第 ${numbers[q.id]} 题 · ${escapeHtml(paperLabel(paperKey(q)))} · 原第 ${q.number} 题</span><span class="result-title">${highlight(item.title,searchTerms)}</span><span class="result-snippet">${item.answerMatch ? '<span class="result-answer">答案匹配：</span>' : ''}${snippet(item,searchTerms)}</span></button>`;
  }).join(''));
  shownResults += batch.length;
  if (shownResults < searchMatches.length) $('search-results').insertAdjacentHTML('beforeend',`<button id="more-results" class="more-results">继续显示（${shownResults} / ${searchMatches.length}）</button>`);
}
function searchState() {
  return {query:normalizeText($('search-input').value),topic:$('search-topic').value,edition:$('search-edition').value,paper:$('search-paper').value,answers:$('search-answers').checked};
}
async function runSearch() {
  const state = searchState(), signature = JSON.stringify(state);
  if (signature === searchSignature) return;
  const terms = [...new Set(state.query.toLowerCase().split(' ').filter(Boolean))];
  if (!terms.length) {
    searchSignature = signature; searchMatches = []; searchTerms = []; searchScroll = 0;
    $('search-status').textContent = '输入关键词，搜索全部题目。'; $('search-results').innerHTML = ''; return;
  }
  $('search-status').textContent = searchIndex ? '正在查找…' : '正在准备搜索，请稍候…';
  await prepareSearchIndex();
  if (JSON.stringify(searchState()) !== signature) return;
  const candidates = searchIndex.filter(item => (state.topic === 'all' || item.q.topic === state.topic) && (state.edition === 'all' || String(editionOf(item.q)) === state.edition) && (state.paper === 'all' || paperKey(item.q) === state.paper));
  const matches = [];
  for (const item of candidates) {
    const mainMatch = terms.every(term => item.titleLower.includes(term) || item.bodyLower.includes(term));
    let answerMatch = false;
    if (!mainMatch && state.answers) {
      if (item.answer === null) { item.answer = htmlText(presentation[item.q.id].answer); item.answerLower = item.answer.toLowerCase(); }
      answerMatch = terms.every(term => item.titleLower.includes(term) || item.bodyLower.includes(term) || item.answerLower.includes(term));
    }
    if (mainMatch || answerMatch) matches.push({...item,answerMatch,rank:(answerMatch ? 0 : 10)+terms.filter(term => item.titleLower.includes(term)).length*5});
  }
  if (JSON.stringify(searchState()) !== signature) return;
  matches.sort((a,b) => b.rank-a.rank || topics.indexOf(a.q.topic)-topics.indexOf(b.q.topic) || numbers[a.q.id]-numbers[b.q.id]);
  searchSignature = signature; searchMatches = matches; searchTerms = terms; searchScroll = 0;
  $('search-status').textContent = `找到 ${matches.length} 道题${state.answers ? '（含答案文字）' : ''}`;
  appendResults(true); $('search-results').scrollTop = 0;
  if (!matches.length) $('search-results').innerHTML = '<p class="no-results">没有找到符合条件的题目。试试减少关键词或扩大专题、届次和试卷范围。</p>';
}
function scheduleSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch,180); }
function openSearch() {
  if (!ready) return;
  closePanel(false);
  if (!$('search-dialog').open) $('search-dialog').showModal();
  document.documentElement.style.overflow = 'hidden';
  $('search-input').focus();
  requestAnimationFrame(() => { $('search-results').scrollTop = searchScroll; });
  prepareSearchIndex();
}
function closeSearch() {
  searchScroll = $('search-results').scrollTop;
  $('search-dialog').close();
}

function navigateTopic(topic) {
  if (!ready) return;
  closePanel(false); showingIntroduction = false; activeTopic = topic; selectedEdition = 'all'; selectedPaper = 'all'; activeQuestion = '';
  render(); writeUrl(); window.scrollTo({top:0,behavior:'instant'}); $('reading').focus({preventScroll:true});
}
$('categories').addEventListener('click',event => {
  const button = event.target.closest('[data-topic]');
  if (button) navigateTopic(button.dataset.topic);
});
document.querySelector('.intro-browse').addEventListener('click',event => { if (ready) { event.preventDefault(); navigateTopic(topics[0]); } });
for (const link of [document.querySelector('.site-brand'),$('about-link')]) link.addEventListener('click',event => {
  if (!ready) return;
  event.preventDefault(); closePanel(false); rememberPosition();
  const url = new URL(location.href); url.hash = 'about';
  for (const key of ['edition','paper','question']) url.searchParams.delete(key);
  history.pushState({},'',url); lastUrl = location.href;
  showingIntroduction = true; activeQuestion = ''; render(); window.scrollTo({top:0,behavior:'instant'}); $('introduction').focus({preventScroll:true});
});
document.querySelector('.skip').addEventListener('click',event => {
  event.preventDefault(); const target = $(showingIntroduction ? 'introduction' : 'reading'); target.focus(); target.scrollIntoView({block:'start'});
});
for (const [id,key] of [['edition-select','edition'],['paper-select','paper']]) $(id).addEventListener('change',event => {
  if (key === 'edition') { selectedEdition = event.target.value; selectedPaper = 'all'; }
  else selectedPaper = event.target.value;
  activeQuestion = ''; render(); writeUrl();
  if (openPanelId) panelScrollY = 0;
  else window.scrollTo({top:0,behavior:'instant'});
});
$('directory-tree').addEventListener('click',event => {
  const link = event.target.closest('[data-question]');
  if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) { event.preventDefault(); navigateQuestion(link.dataset.question); }
});
$('directory-tree').addEventListener('toggle',event => {
  const group = event.target.dataset.group;
  if (!group || !expandedByTopic.has(activeTopic)) return;
  const expanded = expandedByTopic.get(activeTopic);
  if (event.target.open) expanded.add(group); else expanded.delete(group);
},true);
$('number-jump').addEventListener('submit',event => {
  event.preventDefault();
  const input = normalizeText($('question-number').value).replace(/^第\s*|\s*题$/g,'');
  const q = /^\d+$/.test(input) ? byTopic.get(activeTopic)?.find(q => numbers[q.id] === Number(input)) : null;
  if (!q) { $('number-status').textContent = `请输入本专题的题号（1～${byTopic.get(activeTopic)?.length || 0}）。`; return; }
  navigateQuestion(q.id);
});
$('questions').addEventListener('toggle',event => {
  const detail = event.target, id = detail.dataset.answer;
  if (!id) return;
  detail.querySelector('summary span').textContent = `${detail.open ? '收起' : '查看'}参考答案`;
  if (detail.open) {
    openAnswers.add(id); const content = detail.querySelector('.answer-content');
    if (!content.dataset.loaded) { content.innerHTML = lazyFigures(presentation[id].answer); content.dataset.loaded = 'true'; }
  } else openAnswers.delete(id);
},true);
$('topic-toggle').addEventListener('click',event => openPanel('sidebar',event.currentTarget));
$('directory-toggle').addEventListener('click',event => openPanel('directory-pane',event.currentTarget));
document.querySelectorAll('[data-close-panel]').forEach(button => button.addEventListener('click',() => closePanel()));
$('overlay').addEventListener('click',() => closePanel());
window.addEventListener('resize',() => {
  if (openPanelId && ((openPanelId === 'sidebar' && innerWidth > 760) || innerWidth >= 1200)) closePanel();
});
document.addEventListener('keydown',event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch(); }
  if (event.key === 'Escape' && $('search-dialog').open) { event.preventDefault(); closeSearch(); return; }
  if (!openPanelId) return;
  if (event.key === 'Escape') { event.preventDefault(); closePanel(); }
  if (event.key === 'Tab') {
    const items = [...$(openPanelId).querySelectorAll('button,input,select,a,summary')].filter(el => el.getClientRects().length && !el.disabled);
    const first = items[0], last = items[items.length-1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
});
$('search-launch').addEventListener('click',openSearch); $('return-search').addEventListener('click',openSearch);
$('search-close').addEventListener('click',closeSearch);
$('search-dialog').addEventListener('cancel',() => { searchScroll = $('search-results').scrollTop; });
$('search-dialog').addEventListener('close',() => { document.documentElement.style.overflow = ''; });
$('search-dialog').addEventListener('click',event => { if (event.target === $('search-dialog')) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeSearch(); } });
$('search-form').addEventListener('submit',event => { event.preventDefault(); clearTimeout(searchTimer); runSearch(); });
$('search-input').addEventListener('input',scheduleSearch);
for (const id of ['search-topic','search-edition','search-paper','search-answers']) $(id).addEventListener('change',() => {
  if (id === 'search-topic' || id === 'search-edition') refreshSearchPapers();
  scheduleSearch();
});
$('search-results').addEventListener('click',event => {
  const button = event.target.closest('[data-search-question]');
  if (button) { closeSearch(); navigateQuestion(button.dataset.searchQuestion,true); }
  if (event.target.closest('#more-results')) { const previous = shownResults; appendResults(); $('search-results').querySelectorAll('.search-result')[previous]?.focus({preventScroll:true}); }
});
window.addEventListener('popstate',restoreUrl); window.addEventListener('hashchange',restoreUrl);

async function loadLibrary() {
  try {
    const [data,numbering,display] = await Promise.all(['questions.json','numbering.json','presentation.json'].map(async path => {
      const response = await fetch(path); if (!response.ok) throw new Error('题库加载失败'); return response.json();
    }));
    questions = data; presentation = display; numbers = numbering.numberById; pdfVersion = numbering.version || pdfVersion;
    if (questions.some(q => !Number.isInteger(numbers[q.id]) || !presentation[q.id]?.body || !presentation[q.id]?.answer)) throw new Error('编号与题库不一致');
    byId = new Map(questions.map(q => [q.id,q])); byTopic = new Map(topics.map(t => [t,questions.filter(q => q.topic === t)]));
    for (const q of questions) paperLabels.set(paperKey(q),editionOf(q) === 0 ? `第${q.paper}届 Chemy 联赛` : `第${editionOf(q)}届 · ${q.sourcePaperLabel || '模拟试题 '+q.paper}`);
    $('library-status').textContent = `${questions.length} 道题 · ${new Set(questions.map(paperKey)).size} 份试卷`;
    $('search-topic').innerHTML = option('all','全部专题','all')+topics.map(t => option(t,t,'all')).join('');
    $('search-edition').innerHTML = option('all','全部届次','all')+editionValues(questions).map(e => option(e,editionLabel(e),'all')).join('');
    refreshSearchPapers(); ready = true; $('search-launch').disabled = false;
    readUrl(); const target = activeQuestion; render();
    if (!showingIntroduction) writeUrl(target,false);
    if (target && !showingIntroduction) scrollToQuestion(target,false);
  } catch (error) {
    ready = false; $('search-launch').disabled = true;
    $('topic-summary').textContent = '题库尚未加载完成';
    $('library-status').innerHTML = '题库暂时无法加载。<br><button id="retry-library">重新加载</button>';
    $('retry-library').addEventListener('click',() => { $('library-status').textContent = '正在重新加载题库…'; loadLibrary(); });
    $('directory-tree').innerHTML = '<p class="loading-note">题库加载后显示目录。</p>';
    $('questions').setAttribute('aria-busy','false');
    $('questions').innerHTML = '<section class="load-error"><h2>题目暂时无法加载</h2><p>请检查网络后重试。</p><button id="retry-load">重新加载</button></section>';
    $('retry-load').addEventListener('click',() => { $('questions').setAttribute('aria-busy','true'); $('questions').innerHTML = '<p class="loading-note">正在重新加载题库…</p>'; loadLibrary(); });
  }
}
loadLibrary();
