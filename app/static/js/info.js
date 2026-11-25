// 상담사 INFO: 거르기(검색·재직정보·TL) + 시트처럼 칸 고치기 → 바뀐 칸만 모아 미리보기로 보낸다.
(function () {
  const grid = document.getElementById("info-grid");
  if (!grid) return;
  const body = grid.tBodies[0];
  const heads = Array.from(grid.tHead.rows[1].cells);
  const q = document.getElementById("info-q");
  const st = document.getElementById("info-status");
  const tl = document.getElementById("info-tl");
  const cnt = document.getElementById("info-count");
  const dirtyN = document.getElementById("info-dirty");
  const saveBtn = document.getElementById("info-save-btn");
  const changed = new Map();   // "사번|항목" → 값
  const newRows = [];          // 새 사람 tr
  let editing = null;

  function apply() {
    const term = q.value.trim().toLowerCase();
    let n = 0;
    Array.from(body.rows).forEach(function (tr) {
      const show = tr.dataset.new === "1" || ((!term || tr.textContent.toLowerCase().indexOf(term) >= 0)
        && (!st.value || tr.dataset.status === st.value) && (!tl.value || tr.dataset.tl === tl.value));
      tr.hidden = !show;
      if (show) n++;
    });
    cnt.textContent = n + "명 표시";
  }
  [q, st, tl].forEach(function (el) { el.addEventListener("input", apply); });

  function refreshDirty() {
    const n = changed.size + newRows.length;
    if (dirtyN) dirtyN.textContent = n;
    if (saveBtn) saveBtn.disabled = n === 0;
  }

  function startEdit(td) {
    if (!td.classList.contains("ed") || editing) return;
    editing = td;
    const old = td.dataset.orig !== undefined ? td.dataset.orig : td.textContent.trim();
    td.dataset.orig = old;
    const input = document.createElement("input");
    input.value = td.textContent.trim();
    if (heads[td.cellIndex] && heads[td.cellIndex].dataset.date === "1") input.placeholder = "YYYY-MM-DD";
    td.textContent = "";
    td.appendChild(input);
    input.focus();
    input.select();
    function done(save) {
      if (editing !== td) return;
      editing = null;
      const v = save ? input.value.trim() : (td.dataset.cur !== undefined ? td.dataset.cur : old);
      td.textContent = v;
      td.dataset.cur = v;
      const tr = td.parentElement;
      if (tr.dataset.new !== "1") {
        const k = tr.dataset.emp + "|" + td.dataset.f;
        if (v !== td.dataset.orig) { changed.set(k, v); td.classList.add("dirty"); }
        else { changed.delete(k); td.classList.remove("dirty"); }
      }
      refreshDirty();
    }
    input.addEventListener("blur", function () { done(true); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); done(true); td.focus(); }
      if (e.key === "Escape") { e.preventDefault(); done(false); td.focus(); }
    });
  }
  body.addEventListener("dblclick", function (e) { const td = e.target.closest("td"); if (td) startEdit(td); });
  body.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.tagName === "TD") { e.preventDefault(); startEdit(e.target); }
  });

  const add = document.getElementById("info-add");
  if (add) add.addEventListener("click", function () {
    const tr = document.createElement("tr");
    tr.dataset.new = "1";
    heads.forEach(function (h) {
      const td = document.createElement("td");
      td.dataset.f = h.dataset.f;
      const editable = h.dataset.edit === "1" || h.dataset.f === "emp_id";
      td.className = editable ? "ed dirty" : "ro";
      if (editable) td.tabIndex = 0;
      tr.appendChild(td);
    });
    body.insertBefore(tr, body.firstChild);
    newRows.push(tr);
    refreshDirty();
    startEdit(tr.cells[0]);
  });

  const form = document.getElementById("info-save");
  if (form) form.addEventListener("submit", function () {
    const cells = [];
    changed.forEach(function (v, k) { const p = k.split("|"); cells.push({ emp_id: p[0], field: p[1], value: v }); });
    const news = newRows.map(function (tr) {
      const r = {};
      Array.from(tr.cells).forEach(function (td) { if (td.textContent.trim()) r[td.dataset.f] = td.textContent.trim(); });
      return r;
    }).filter(function (r) { return Object.keys(r).length; });
    form.querySelector('input[name="payload_json"]').value = JSON.stringify({ cells: cells, new: news });
    changed.clear(); newRows.length = 0;
  });
  window.addEventListener("beforeunload", function (e) {
    if (changed.size + newRows.length) { e.preventDefault(); e.returnValue = ""; }
  });
  apply();
})();
