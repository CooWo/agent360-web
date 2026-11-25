// TL별 명단 — 칸을 모아 rows_json 으로 보낸다 (입력칸엔 name 이 없어 따로 전송되지 않음).
(function () {
  var form = document.getElementById("tl-form");
  if (!form) return;
  var tls = {};
  form.querySelectorAll("tfoot td[data-g]").forEach(function (td) { tls[td.dataset.g] = td.dataset.tl; });
  var FIELDS = ["shift", "emp_id", "name", "e_name", "display_name"];

  form.addEventListener("input", function (e) {
    var el = e.target;
    if (el.tagName === "INPUT" && el.dataset.f) el.classList.toggle("changed", el.value !== el.dataset.old);
  });

  form.addEventListener("submit", function () {
    var cells = {};
    form.querySelectorAll("input[data-g]").forEach(function (el) {
      var k = el.dataset.g + ":" + el.dataset.i;
      (cells[k] = cells[k] || { g: +el.dataset.g, i: +el.dataset.i })[el.dataset.f] = el.value.trim();
    });
    var rows = Object.keys(cells).map(function (k) { return cells[k]; })
      .sort(function (a, b) { return a.g - b.g || a.i - b.i; })
      .filter(function (c) { return FIELDS.some(function (f) { return c[f]; }); })
      .map(function (c) {
        var r = { tl: tls[c.g] };
        FIELDS.forEach(function (f) { r[f] = c[f] || ""; });
        return r;
      });
    document.getElementById("rows_json").value = JSON.stringify(rows);
  });
})();
