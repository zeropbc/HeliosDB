// HeliosDB progressive search — enhancement only, never required.
// Mounts into #search-mount on index.html. If anything fails (no JS, blocked
// fetch, unexpected DOM), the mount stays :empty and CSS hides it. This script
// never touches anything outside its own mount point.
try {
  (function () {
    var mount = document.getElementById("search-mount");
    if (!mount) return;

    var input = document.createElement("input");
    input.type = "search";
    input.placeholder = "Search names, designations, discoverers…";
    input.setAttribute("aria-label", "Search bodies");
    var list = document.createElement("ul");
    mount.appendChild(input);
    mount.appendChild(list);

    var index = null;
    var timer = null;

    function esc(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }

    function render(q) {
      list.innerHTML = "";
      if (!index || !q) return;
      var terms = q.trim().toLowerCase().split(/\s+/);
      var hits = [];
      for (var i = 0; i < index.length && hits.length < 20; i++) {
        var b = index[i];
        var hay = [b.name, b.id, b.classification, b.parent_id || ""]
          .concat(b.aliases || []).join(" ").toLowerCase();
        var ok = true;
        for (var t = 0; t < terms.length; t++) {
          if (hay.indexOf(terms[t]) === -1) { ok = false; break; }
        }
        if (ok) hits.push(b);
      }
      for (var h = 0; h < hits.length; h++) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = "bodies/" + hits[h].id + ".html";
        a.textContent = hits[h].name + " · " + hits[h].classification +
          (hits[h].parent_id ? " · ⟡ " + hits[h].parent_id : "");
        li.appendChild(a);
        list.appendChild(li);
      }
      void esc;
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value;
      timer = setTimeout(function () { render(q); }, 120);
    });

    fetch("data/index.json")
      .then(function (r) { if (!r.ok) throw new Error("index fetch failed"); return r.json(); })
      .then(function (data) { index = data; render(input.value); })
      .catch(function () { index = null; list.innerHTML = ""; });
  })();
} catch (e) { /* search is optional — page works without it */ }
