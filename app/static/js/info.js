// 상담사 INFO: 검색 · 재직정보 · TL 로 거르기 (서버 왕복 없이)
(function () {
  const grid = document.getElementById("info-grid");
  if (!grid) return;
  const q = document.getElementById("info-q");
  const st = document.getElementById("info-status");
  const tl = document.getElementById("info-tl");
  const cnt = document.getElementById("info-count");
  const rows = Array.from(grid.tBodies[0].rows).map(function (tr) {
    return { tr: tr, text: tr.textContent.toLowerCase(), status: tr.dataset.status, tl: tr.dataset.tl };
  });

  function apply() {
    const term = q.value.trim().toLowerCase();
    let n = 0;
    rows.forEach(function (r) {
      const show = (!term || r.text.indexOf(term) >= 0) && (!st.value || r.status === st.value) && (!tl.value || r.tl === tl.value);
      r.tr.hidden = !show;
      if (show) n++;
    });
    cnt.textContent = n + "명 표시";
  }

  [q, st, tl].forEach(function (el) { el.addEventListener("input", apply); });
  apply();
})();
