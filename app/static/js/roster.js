// 팀 구성 작업 공간: 표 편집(행 추가·삭제·TL 필터) → 폼 보낼 때 표 전체를 rows_json 으로 담는다.
(function () {
  const grid = document.getElementById("grid");
  if (!grid) return;
  const body = grid.tBodies[0];
  const dirty = document.getElementById("dirty");
  const filter = document.getElementById("tl-filter");
  let changed = false;

  function mark() { changed = true; if (dirty) dirty.hidden = false; }

  function rows() {
    return Array.from(body.rows).map(function (tr) {
      const r = {};
      tr.querySelectorAll("input[data-f]").forEach(function (i) { r[i.dataset.f] = i.value.trim(); });
      return r;
    }).filter(function (r) { return Object.values(r).some(Boolean); });
  }

  function applyFilter() {
    const tl = filter ? filter.value : "";
    Array.from(body.rows).forEach(function (tr) {
      const v = tr.querySelector('input[data-f="tl"]').value;
      tr.hidden = !!tl && v !== tl;
    });
  }

  document.getElementById("add-row").addEventListener("click", function () {
    const tpl = body.rows[0];
    const tr = tpl ? tpl.cloneNode(true) : null;
    if (!tr) return;
    tr.hidden = false;
    tr.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    if (filter && filter.value) tr.querySelector('input[data-f="tl"]').value = filter.value;
    body.insertBefore(tr, body.firstChild);
    tr.querySelector('input[data-f="emp_id"]').focus();
    mark();
  });

  body.addEventListener("click", function (e) {
    if (e.target.classList.contains("js-del")) { e.target.closest("tr").remove(); mark(); }
  });
  body.addEventListener("input", mark);
  if (filter) filter.addEventListener("change", applyFilter);

  document.querySelectorAll("form.js-rows").forEach(function (f) {
    f.addEventListener("submit", function () {
      f.querySelector('input[name="rows_json"]').value = JSON.stringify(rows());
      changed = false;
    });
  });
  window.addEventListener("beforeunload", function (e) {
    if (changed) { e.preventDefault(); e.returnValue = ""; }
  });
})();
