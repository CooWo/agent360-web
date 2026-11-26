// 공통 스크립트 — 외부 라이브러리 없음.
// data-signal-id 가 있는 상태 버튼을 누르면 API 로 처리 상태를 저장하고 화면만 바꾼다.
(function () {
  function toast(msg) {
    var t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.classList.remove('show'); }, 2200);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.status-ctl button[data-status]');
    if (!btn || btn.disabled) return;
    var ctl = btn.closest('.status-ctl');
    var id = ctl.getAttribute('data-signal-id');
    var status = btn.getAttribute('data-status');
    ctl.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
    fetch('/api/agent360/signals/' + encodeURIComponent(id) + '/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: status })
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, body: j }; });
    }).then(function (res) {
      ctl.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
      if (!res.ok) { toast(res.body.detail || '저장하지 못했습니다'); return; }
      ctl.querySelectorAll('button').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-status') === status);
      });
      var chip = document.querySelector('[data-chip-for="' + id + '"]');
      if (chip) chip.classList.toggle('done', status === '해당 없음');
      toast('처리 상태: ' + status);
    }).catch(function () {
      ctl.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
      toast('네트워크 오류로 저장하지 못했습니다');
    });
  });

  // ── AI 질문: /assistant 화면 + 모든 화면 오른쪽 AI 패널 ─────────────
  // 대화 내용은 이 탭(sessionStorage)에 저장해서 화면을 옮겨도 이어진다. 서버가 escape 해서 만든 HTML 만 저장.
  var AI_KEY = 'a360.ai', AI_MAX_ITEMS = 40;
  function aiLoad() { try { return JSON.parse(sessionStorage.getItem(AI_KEY)) || { conversation: null, items: [] }; } catch (e) { return { conversation: null, items: [] }; } }
  function aiSave(st) { try { st.items = st.items.slice(-AI_MAX_ITEMS); sessionStorage.setItem(AI_KEY, JSON.stringify(st)); } catch (e) {} }
  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function chatOf(el) { var box = el.closest('.ai-dock, main'); return box && box.querySelector('.ai-chat'); }

  function initChat(chat) {
    var log = chat.querySelector('.ai-log'), form = chat.querySelector('.ai-form');
    var q = chat.querySelector('.ai-q'), send = chat.querySelector('.ai-send');
    var empty = log.querySelector('.ai-empty'), emptyHtml = empty ? empty.outerHTML : '';
    var busy = false;
    function add(cls, html, keep) {
      var e = log.querySelector('.ai-empty'); if (e) e.remove();
      var el = document.createElement('div'); el.className = 'ai-msg ' + cls; el.innerHTML = html;
      log.appendChild(el); log.scrollTop = log.scrollHeight;
      if (keep) { var st = aiLoad(); st.items.push({ cls: cls, html: html }); aiSave(st); }
      return el;
    }
    chat._add = add;
    chat._reset = function () { log.innerHTML = emptyHtml; aiSave({ conversation: null, items: [], fresh: true }); };
    aiLoad().items.forEach(function (it) { add(it.cls, it.html, false); });   // 이전 대화 복원
    function setBusy(b) { busy = b; send.disabled = b; q.disabled = b; }
    function ask(text) {
      text = (text || '').trim();
      if (!text || busy) return;
      add('q', esc(text), true);
      var t0 = Date.now(), st = aiLoad();
      var wait = add('a', '<div class="ai-wait">데이터를 조회하는 중… <span class="ai-sec">0</span>초 (보통 20초~2분)</div>', false);
      var timer = setInterval(function () { var s = wait.querySelector('.ai-sec'); if (s) s.textContent = Math.round((Date.now() - t0) / 1000); }, 1000);
      setBusy(true); q.value = '';
      fetch('/api/assistant/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, conversation: st.conversation, new: !!st.fresh })
      }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
        .then(function (res) {
          clearInterval(timer); wait.remove();
          if (!res.ok) { add('err', esc(res.body.detail || '답변을 받지 못했습니다.'), true); return; }
          var b = res.body, s2 = aiLoad();
          s2.conversation = b.conversation || s2.conversation; s2.fresh = false; aiSave(s2);
          var meta = '<div class="ai-meta"><span>' + b.secs + '초</span>' +
            (b.mode === 'single' ? '<span>한 번 묻기</span>' : '<span>이어 묻기 가능</span>') +
            (b.notes || []).map(function (n) { return '<span>' + esc(n) + '</span>'; }).join('') +
            ((b.sqls || []).length ? '<details><summary>실행된 SQL ' + b.sqls.length + '개</summary>' +
              b.sqls.map(function (s) { return '<pre>' + esc(s) + '</pre>'; }).join('') + '</details>' : '') + '</div>';
          add('a', b.html + meta, true);   // b.html 은 서버에서 escape 후 만든 HTML
        })
        .catch(function () { clearInterval(timer); wait.remove(); add('err', '네트워크 오류로 답변을 받지 못했습니다. (답을 기다리는 중에 화면을 옮기면 답이 사라집니다)', true); })
        .then(function () { setBusy(false); q.focus(); });
    }
    form.addEventListener('submit', function (e) { e.preventDefault(); ask(q.value); });
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(q.value); } });
    log.addEventListener('click', function (e) { var b = e.target.closest('[data-q]'); if (b && !b.disabled) ask(b.getAttribute('data-q')); });
  }
  document.querySelectorAll('.ai-chat').forEach(initChat);

  document.addEventListener('click', function (e) {
    var nb = e.target.closest('.ai-new');
    if (nb) { var c = chatOf(nb); if (c && c._reset) { c._reset(); toast('새 대화를 시작합니다'); } return; }
    var pb = e.target.closest('.ai-ping');
    if (pb) {
      var chat = chatOf(pb); pb.disabled = true;
      fetch('/api/assistant/ping').then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
        .then(function (res) {
          if (res.ok) toast('연결 정상: ' + res.body.agent);
          else if (chat && chat._add) chat._add('err', esc('연결 점검 실패: ' + (res.body.detail || '')), false);
        })
        .catch(function () { toast('네트워크 오류'); }).then(function () { pb.disabled = false; });
      return;
    }
    var tg = e.target.closest('.ai-dock-toggle');
    if (tg) {
      var closed = document.documentElement.classList.toggle('ai-closed');
      try { localStorage.setItem('a360.aiDock', closed ? 'closed' : 'open'); } catch (err) {}
      if (!closed) { var dq = document.querySelector('.ai-dock .ai-q'); if (dq) dq.focus(); }
    }
  });

  // ── AI 브리핑 카드: 화면을 열면 자동으로 요약을 묻는다 (같은 탭에서는 기준일까지 다시 묻지 않음) ──
  document.querySelectorAll('.ai-brief').forEach(function (card) {
    var body = card.querySelector('.ai-brief-body'), meta = card.querySelector('.ai-brief-meta');
    var again = card.querySelector('.ai-brief-again'), note = meta.textContent;
    function key() { return 'a360.brief.' + card.dataset.kind + '.' + (card.dataset.agent || '') + '.' + card.dataset.asof; }
    if (card.dataset.enabled !== '1') { again.disabled = true; return; }
    var seq = 0;
    function show(b) {
      body.innerHTML = b.html;
      meta.textContent = (b.cached ? '저장된 요약 · ' : '') + b.asked_at + ' 요약 · ' + b.secs + '초 · ' + note;
    }
    function run(refresh) {
      var t0 = Date.now(), my = ++seq, k = key(); again.disabled = true;
      body.innerHTML = '<div class="ai-wait">AI 가 요약하는 중… <span class="ai-sec">0</span>초 (보통 20초~1분)</div>';
      var timer = setInterval(function () { var s = body.querySelector('.ai-sec'); if (s) s.textContent = Math.round((Date.now() - t0) / 1000); }, 1000);
      fetch(card.dataset.url || '/api/agent360/briefing', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: card.dataset.kind, agent_id: card.dataset.agent || null, refresh: !!refresh }) })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
        .then(function (res) {
          if (my !== seq) return;                                   // 그사이 다른 상담사를 고름
          if (!res.ok) { body.innerHTML = '<div class="ai-msg err">' + esc(res.body.detail || '요약을 받지 못했습니다.') + '</div>'; return; }
          show(res.body);
          try { sessionStorage.setItem(k, JSON.stringify(res.body)); } catch (e) {}
        })
        .catch(function () { body.innerHTML = '<div class="ai-msg err">네트워크 오류로 요약을 받지 못했습니다.</div>'; })
        .then(function () { clearInterval(timer); if (my === seq) again.disabled = false; });
    }
    function start() {
      if ((card.dataset.kind === 'agent' || card.dataset.kind === 'detractor') && !card.dataset.agent) {
        seq++; again.disabled = true; meta.textContent = note;
        body.innerHTML = '<div class="muted">상담사를 고르면 요약합니다.</div>'; return;
      }
      var saved = null;
      try { saved = JSON.parse(sessionStorage.getItem(key())); } catch (e) {}
      if (saved && saved.html) { seq++; again.disabled = false; show(Object.assign(saved, { cached: true })); } else run(false);
    }
    again.addEventListener('click', function () { run(true); });
    var sel = card.dataset.follow && document.querySelector(card.dataset.follow);   // 코칭 기록: 고른 상담사를 따라감
    if (sel) sel.addEventListener('change', function () { card.dataset.agent = sel.value; start(); });
    start();
  });

  // 사용자 전환(local 전용)
  var sw = document.getElementById('devswitch');
  if (sw) sw.addEventListener('change', function () {
    location.href = '/dev/switch?email=' + encodeURIComponent(sw.value) + '&next=' + encodeURIComponent(location.pathname + location.search);
  });
})();
