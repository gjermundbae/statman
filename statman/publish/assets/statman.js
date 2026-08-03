/* Statman — publiseringslaget.
   Fire små ting: lesefremdrift, tall som teller opp, figurer som glir inn,
   tabeller som kan sorteres. Ingenting her endrer et tall, og sida er fullt
   lesbar uten skript i det hele tatt. */
(function () {
  "use strict";

  var rolig = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (rolig) document.body.classList.add("rolig");

  /* ------------------------------------------------------ lesefremdrift */
  var stripe = document.getElementById("fremdrift");
  if (stripe) {
    var ventende = false;
    var tegn = function () {
      ventende = false;
      var h = document.documentElement;
      var strekk = h.scrollHeight - h.clientHeight;
      var del = strekk > 0 ? h.scrollTop / strekk : 0;
      stripe.style.width = Math.min(100, Math.max(0, del * 100)).toFixed(2) + "%";
    };
    addEventListener("scroll", function () {
      if (!ventende) { ventende = true; requestAnimationFrame(tegn); }
    }, { passive: true });
    addEventListener("resize", tegn, { passive: true });
    tegn();
  }

  /* --------------------------------------------------------- norske tall */
  // "+707 095", "14,4 %", "−22,1 %" -> {før, tall, desimaler, etter}
  // Tallet får ikke slutte på mellomrom — ellers spiser det opp det harde
  // mellomrommet foran «%» og «øre», og enheten klistrer seg til tallet.
  var TALL = /^(.*?)(\d(?:[\d\s]*\d)?(?:,\d+)?)(.*)$/s;

  function les(tekst) {
    var m = TALL.exec(tekst);
    if (!m) return null;
    var rå = m[2].replace(/\s/g, "").replace(",", ".");
    var verdi = parseFloat(rå);
    if (!isFinite(verdi)) return null;
    var komma = m[2].indexOf(",");
    return {
      før: m[1],
      verdi: verdi,
      desimaler: komma === -1 ? 0 : m[2].length - komma - 1,
      etter: m[3]
    };
  }

  function skriv(del, verdi) {
    return del.før + verdi.toLocaleString("nb-NO", {
      minimumFractionDigits: del.desimaler,
      maximumFractionDigits: del.desimaler
    }) + del.etter;
  }

  /* ------------------------------------------- nøkkeltall som teller opp */
  function tell(el) {
    var del = les(el.textContent);
    if (!del) return;
    var start = performance.now();
    var varighet = 900;
    var steg = function (nå) {
      var t = Math.min(1, (nå - start) / varighet);
      var lettet = 1 - Math.pow(1 - t, 3);
      el.textContent = skriv(del, del.verdi * lettet);
      if (t < 1) requestAnimationFrame(steg);
      else el.textContent = skriv(del, del.verdi);
    };
    requestAnimationFrame(steg);
  }

  /* ------------------------------------------------ avsløring ved scroll */
  var mål = document.querySelectorAll(".avslor");
  if (!rolig && "IntersectionObserver" in window) {
    var kikker = new IntersectionObserver(function (poster) {
      poster.forEach(function (post) {
        if (!post.isIntersecting) return;
        post.target.classList.add("synlig");
        post.target.querySelectorAll(".tall").forEach(tell);
        kikker.unobserve(post.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
    mål.forEach(function (el) { kikker.observe(el); });
  } else {
    mål.forEach(function (el) { el.classList.add("synlig"); });
  }

  /* ---------------------------------------------------- sorterbare tabeller */
  document.querySelectorAll("table[data-sorterbar]").forEach(function (tabell) {
    var kropp = tabell.tBodies[0];
    if (!kropp) return;
    var opprinnelig = Array.prototype.slice.call(kropp.rows);

    tabell.querySelectorAll("thead th").forEach(function (th, kol) {
      th.classList.add("h");
      th.tabIndex = 0;
      th.setAttribute("role", "button");

      var sorter = function () {
        var vei = th.dataset.vei === "ned" ? "opp" : th.dataset.vei === "opp" ? "" : "ned";
        tabell.querySelectorAll("thead th").forEach(function (annen) {
          delete annen.dataset.vei;
          annen.removeAttribute("aria-sort");
        });

        if (!vei) {
          opprinnelig.forEach(function (rad) { kropp.appendChild(rad); });
          return;
        }
        th.dataset.vei = vei;
        th.setAttribute("aria-sort", vei === "ned" ? "descending" : "ascending");

        var retning = vei === "ned" ? -1 : 1;
        var rader = Array.prototype.slice.call(kropp.rows);
        rader.sort(function (a, b) {
          var ta = a.cells[kol].textContent.trim();
          var tb = b.cells[kol].textContent.trim();
          var na = les(ta), nb = les(tb);
          // Bare tallsortering når hele kolonneparet er tall. Ellers
          // ville «Nes» og «1806» blitt sammenlignet på hver sin skala.
          if (na && nb && /^[^\p{L}]*$/u.test(ta.replace(/[%\s]/g, ""))) {
            var fa = /^\s*[-−]/.test(ta) ? -na.verdi : na.verdi;
            var fb = /^\s*[-−]/.test(tb) ? -nb.verdi : nb.verdi;
            return (fa - fb) * retning;
          }
          return ta.localeCompare(tb, "nb") * retning;
        });
        rader.forEach(function (rad) { kropp.appendChild(rad); });
      };

      th.addEventListener("click", sorter);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sorter(); }
      });
    });
  });
})();
