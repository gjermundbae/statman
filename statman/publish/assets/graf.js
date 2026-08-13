/* Statman — figurer som tegnes i sida.

   Leser spesifikasjonen fra data-graf, bytter ut PNG-en med en SVG, og kobler
   figurer med samme «link» til én felles markering: velger leseren en kommune,
   lyser den opp i alle sammen.

   Legg merke til hva som ikke står her: ingen formatering av tall, ingen
   summering, ingen opptelling. Hvert tall figuren viser kom ferdig formatert
   fra analysen. Det eneste denne fila regner ut er hvor på skjermen et merke
   skal stå — og en skalering er ombrekking, ikke en påstand om verden.

   Uten skript skjer ingenting, og da er PNG-en figuren. */
(function () {
  "use strict";

  var figurer = document.querySelectorAll("figure.graf");
  if (!figurer.length) return;

  var rolig = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var NS = "http://www.w3.org/2000/svg";

  // Fargerollene, speilet fra graf.css. Publiseringslaget har allerede
  // avvist ukjente roller, men en figur som kommer fra en gammel sakspakke
  // skal falle tilbake på noe synlig framfor å bli usynlig.
  var FARGE = {
    vekst: "var(--vekst)", fall: "var(--fall)",
    kat1: "var(--kat1)", kat2: "var(--kat2)",
    kat3: "var(--kat3)", kat4: "var(--kat4)",
    noytral: "var(--noytral)",
    skala1: "var(--skala1)", skala2: "var(--skala2)", skala3: "var(--skala3)",
    skala4: "var(--skala4)", skala5: "var(--skala5)",
    avvik1: "var(--avvik1)", avvik2: "var(--avvik2)", avvik3: "var(--avvik3)",
    avvik4: "var(--avvik4)", avvik5: "var(--avvik5)",
    mangler: "var(--mangler)"
  };
  function farge(tone) { return FARGE[tone] || FARGE.noytral; }

  /* ---------------------------------------------------------- standardverdier */
  // Spesifikasjonen skrives kompakt: felt som står på sin egen standardverdi
  // er utelatt. Da må vi fylle dem inn igjen med nøyaktig de samme verdiene —
  // ellers blir «y: 0» til «undefined», og et merke på null forsvinner i NaN.
  function tall(v, standard) { return typeof v === "number" ? v : standard; }

  function normaliser(spek) {
    function akse(a) {
      if (!a) return null;
      return {
        label: a.label || "",
        lo: tall(a.lo, 0), hi: tall(a.hi, 1),
        ticks: a.ticks || [], tick_labels: a.tick_labels || []
      };
    }
    spek.x = akse(spek.x);
    spek.y = akse(spek.y);
    spek.marks = (spek.marks || []).map(function (m) {
      return {
        label: m.label || "", group: m.group || "",
        x: tall(m.x, 0), y: tall(m.y, 0), size: tall(m.size, 1),
        tone: m.tone || "noytral",
        values: m.values || [], segments: m.segments || [],
        note: m.note || "", pin: !!m.pin,
        tones: m.tones || []
      };
    });
    spek.guides = (spek.guides || []).map(function (g) {
      return { kind: g.kind || "", at: tall(g.at, 0), labels: g.labels || [] };
    });
    spek.legend = spek.legend || [];
    spek.layers = (spek.layers || []).map(function (l) {
      return {
        key: l.key || "", label: l.label || "",
        legend: l.legend || [], caption: l.caption || ""
      };
    });
    spek.layer_label = spek.layer_label || "";
    return spek;
  }

  /* ------------------------------------------------------------- verktøy */
  function el(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) {
      e.setAttribute(k, attrs[k]);
    }
    return e;
  }
  // Etiketter er data — kommunenavn, fylkesnavn, tall fra en kilde. De settes
  // alltid som tekstnoder, aldri som markup.
  function txt(e, s) { e.textContent = s; return e; }

  function skala(d0, d1, r0, r1) {
    var f = function (v) { return r0 + (v - d0) / (d1 - d0) * (r1 - r0); };
    f.inv = function (p) { return d0 + (p - r0) / (r1 - r0) * (d1 - d0); };
    return f;
  }

  /* -------------------------------------------------------------- boblen */
  function lagBoble(vert) {
    var b = document.createElement("div");
    b.className = "graf-boble";
    b.setAttribute("role", "status");
    vert.appendChild(b);
    return b;
  }

  function fyllBoble(boble, mark) {
    boble.replaceChildren();
    var h = document.createElement("div");
    h.className = "navn";
    boble.appendChild(txt(h, mark.label));
    if (mark.group) {
      var s = document.createElement("span");
      s.className = "sted";
      boble.appendChild(txt(s, mark.group));
    }
    if (!mark.values || !mark.values.length) return;
    var dl = document.createElement("dl");
    mark.values.forEach(function (v) {
      var dt = txt(document.createElement("dt"), v.label);
      if (v.tone) dt.style.setProperty("--nokkel", farge(v.tone));
      dl.appendChild(dt);
      dl.appendChild(txt(document.createElement("dd"), v.value));
    });
    boble.appendChild(dl);
  }

  function visBoble(boble, vert, mark, klientX, klientY) {
    if (!mark) { boble.classList.remove("pa"); return; }
    fyllBoble(boble, mark);
    var ramme = vert.getBoundingClientRect();
    boble.style.left = (klientX - ramme.left) + "px";
    boble.style.top = (klientY - ramme.top) + "px";
    boble.classList.add("pa");
  }

  /* ----------------------------------------------------- markeringsgrupper */
  var grupper = {};
  function gruppe(navn) {
    if (!grupper[navn]) grupper[navn] = { valgt: null, filter: "", lyttere: [], merker: [] };
    return grupper[navn];
  }
  function meld(g) { g.lyttere.forEach(function (f) { f(g.valgt, g.filter); }); }

  function velg(g, label) {
    g.valgt = label || null;
    if (g.valgt) {
      var m = g.merker.find(function (x) { return x.label === g.valgt; });
      // Et valg utenfor avgrensningen ville lyst opp noe som ikke vises.
      // Da er det avgrensningen som viker — leseren ba sist om kommunen.
      if (m && g.filter && m.group !== g.filter) g.filter = "";
    }
    meld(g);
  }
  function filtrer(g, navn) {
    g.filter = navn || "";
    if (g.valgt) {
      var m = g.merker.find(function (x) { return x.label === g.valgt; });
      if (g.filter && m && m.group !== g.filter) g.valgt = null;
    }
    meld(g);
  }

  /* --------------------------------------------------------- akser og rutenett */
  function tegnAkser(g, spek, x, y, plott) {
    if (spek.y && spek.y.ticks) {
      spek.y.ticks.forEach(function (v, i) {
        g.appendChild(el("line", {
          class: v === 0 ? "null-linje" : "rute",
          x1: plott.v, x2: plott.h, y1: y(v), y2: y(v)
        }));
        if (spek.y.tick_labels[i] !== undefined) {
          g.appendChild(txt(el("text", {
            class: "merketall", x: plott.v - 10, y: y(v) + 4, "text-anchor": "end"
          }), spek.y.tick_labels[i]));
        }
      });
    }
    if (spek.x && spek.x.ticks) {
      spek.x.ticks.forEach(function (v, i) {
        g.appendChild(el("line", {
          class: v === 0 ? "null-linje" : "rute",
          y1: plott.t, y2: plott.b, x1: x(v), x2: x(v)
        }));
        if (spek.x.tick_labels[i] !== undefined) {
          g.appendChild(txt(el("text", {
            class: "merketall", y: plott.b + 20, x: x(v), "text-anchor": "middle"
          }), spek.x.tick_labels[i]));
        }
      });
    }
    if (spek.x && spek.x.label) {
      g.appendChild(txt(el("text", {
        class: "aksetittel", x: plott.h, y: plott.b + 44, "text-anchor": "end"
      }), spek.x.label));
    }
    if (spek.y && spek.y.label) {
      g.appendChild(txt(el("text", {
        class: "aksetittel", "text-anchor": "end",
        transform: "translate(16," + plott.t + ") rotate(-90)"
      }), spek.y.label));
    }
  }

  function tegnGuider(g, spek, x, y, plott) {
    (spek.guides || []).forEach(function (guide) {
      var linje, ax, ay, anker;
      if (guide.kind === "diagonal") {
        // x + y = at. Tegnes mellom aksekantene, ikke gjennom hele flaten.
        var x0 = spek.x.lo, x1 = spek.x.hi;
        linje = el("line", { x1: x(x0), y1: y(guide.at - x0), x2: x(x1), y2: y(guide.at - x1) });
        ax = x(x1) - 8; ay = y(guide.at - x1) - 8; anker = "end";
      } else if (guide.kind === "x") {
        linje = el("line", { x1: x(guide.at), x2: x(guide.at), y1: plott.t, y2: plott.b });
        ax = x(guide.at); ay = plott.t - 8; anker = "middle";
      } else {
        linje = el("line", { x1: plott.v, x2: plott.h, y1: y(guide.at), y2: y(guide.at) });
        ax = plott.h; ay = y(guide.at) - 8; anker = "end";
      }
      linje.setAttribute("stroke", "var(--dis)");
      linje.setAttribute("stroke-width", 1.5);
      // Stiplet bare her: en hjelpelinje *er* en terskel, og skal leses som
      // en. Rutenett og akser er heltrukne hårstreker.
      linje.setAttribute("stroke-dasharray", "1 5");
      linje.setAttribute("stroke-linecap", "round");
      g.appendChild(linje);

      var merker = guide.labels || [];
      if (merker.length === 1) {
        g.appendChild(txt(el("text", {
          class: "svak-etikett", x: ax, y: ay, "text-anchor": anker
        }), merker[0]));
      } else if (merker.length === 2) {
        g.appendChild(txt(el("text", {
          class: "merketall", x: ax - 6, y: ay, "text-anchor": "end"
        }), merker[0]));
        g.appendChild(txt(el("text", {
          class: "merketall", x: ax + 6, y: ay, "text-anchor": "start"
        }), merker[1]));
      }
    });
  }

  /* ============================================================== SPREDNING */
  function tegnSpredning(spek, vert, boble, g) {
    var B = 860, H = 600, plott = { v: 64, h: 838, t: 18, b: 544 };
    var s = el("svg", {
      viewBox: "0 0 " + B + " " + H, role: "img", "aria-label": spek.alt
    });
    var lag = el("g");
    s.appendChild(lag);

    var x = skala(spek.x.lo, spek.x.hi, plott.v, plott.h);
    var y = skala(spek.y.lo, spek.y.hi, plott.b, plott.t);

    tegnAkser(lag, spek, x, y, plott);
    tegnGuider(lag, spek, x, y, plott);

    var prikker = el("g");
    lag.appendChild(prikker);
    spek.marks.forEach(function (m) {
      m._x = x(m.x); m._y = y(m.y); m._r = 3 + 15 * (m.size || 0);
      m._el = el("circle", {
        class: "merke", cx: m._x, cy: m._y, r: m._r,
        fill: farge(m.tone), "fill-opacity": 0.62,
        // 2px flatering på overlappende merker, ikke en kantstrek rundt dem
        stroke: "var(--papir)", "stroke-width": 1.5
      });
      prikker.appendChild(m._el);
    });

    var ring = el("circle", { class: "valgt-ring", r: 0, cx: 0, cy: 0, opacity: 0 });
    var lapp = txt(el("text", { class: "etikett", "text-anchor": "middle", opacity: 0 }), "");
    lag.appendChild(ring);
    lag.appendChild(lapp);

    // Faste navn: bare de merkene analysen ba om. Aldri et tall på hver prikk.
    var faste = [];
    spek.marks.filter(function (m) { return m.pin; }).forEach(function (m) {
      var hoyre = m._x < (plott.v + plott.h) / 2;
      var t = txt(el("text", {
        class: "svak-etikett", y: m._y + 4,
        x: hoyre ? m._x + m._r + 7 : m._x - m._r - 7,
        "text-anchor": hoyre ? "start" : "end"
      }), m.label);
      lag.appendChild(t);
      faste.push([m, t]);
    });

    // Fangstflate. Leseren skal treffe nærmeste kommune, ikke en prikk på
    // åtte piksler — en punktsky uten dette er umulig å peke i.
    var flate = el("rect", {
      x: plott.v, y: plott.t, width: plott.h - plott.v, height: plott.b - plott.t,
      fill: "transparent"
    });
    lag.appendChild(flate);

    function naermest(ev) {
      var ctm = s.getScreenCTM();
      if (!ctm) return null;
      var p = s.createSVGPoint();
      p.x = ev.clientX; p.y = ev.clientY;
      p = p.matrixTransform(ctm.inverse());
      var best = null, bd = 1e9;
      spek.marks.forEach(function (m) {
        if (g.filter && m.group !== g.filter) return;
        var d = Math.hypot(m._x - p.x, m._y - p.y) - m._r;
        if (d < bd) { bd = d; best = m; }
      });
      return bd < 30 ? best : null;
    }

    flate.addEventListener("pointermove", function (ev) {
      var m = naermest(ev);
      if (!m) return visBoble(boble, vert, null);
      var r = s.getBoundingClientRect(), k = r.width / B;
      visBoble(boble, vert, m, r.left + m._x * k, r.top + (m._y - m._r) * k);
    });
    flate.addEventListener("pointerleave", function () { visBoble(boble, vert, null); });
    flate.addEventListener("click", function (ev) {
      var m = naermest(ev);
      velg(g, m ? m.label : null);
    });

    g.lyttere.push(function (valgt, filter) {
      spek.marks.forEach(function (m) {
        m._el.classList.toggle("valgt", m.label === valgt);
        m._el.classList.toggle("i-gruppe", !!filter && m.group === filter);
      });
      s.classList.toggle("dempet", !!valgt || !!filter);
      faste.forEach(function (par) {
        // Den faste etiketten viker for markeringen, ellers står navnet to ganger.
        par[1].setAttribute("opacity",
          par[0].label === valgt ? 0 : (!filter || par[0].group === filter ? 1 : 0.2));
      });
      var m = valgt && spek.marks.find(function (a) { return a.label === valgt; });
      if (m) {
        ring.setAttribute("cx", m._x); ring.setAttribute("cy", m._y);
        ring.setAttribute("r", m._r + 5); ring.setAttribute("opacity", 1);
        txt(lapp, m.label);
        lapp.setAttribute("x", Math.max(60, Math.min(B - 60, m._x)));
        lapp.setAttribute("y", m._y - m._r - 10);
        lapp.setAttribute("opacity", 1);
      } else {
        ring.setAttribute("opacity", 0);
        lapp.setAttribute("opacity", 0);
      }
    });
    return s;
  }

  /* ================================================================= STRIPE */
  function tegnStripe(spek, vert, boble, g) {
    var B = 860, H = 96, kant = 8, topp = 30, hoyde = 34;
    var s = el("svg", {
      viewBox: "0 0 " + B + " " + H, role: "img", "aria-label": spek.alt
    });
    var n = spek.marks.length;
    var x = skala(0, n - 1, kant, B - kant);

    spek.marks.forEach(function (m, i) {
      m._x = x(i);
      m._el = el("line", {
        class: "tikk", x1: m._x, x2: m._x, y1: topp, y2: topp + hoyde,
        stroke: farge(m.tone), "stroke-width": 1.6, "stroke-opacity": 0.55
      });
      s.appendChild(m._el);
    });

    // Delelinja mellom de to gruppene, med de opptalte tallene på hver side.
    // Tallene er talt i analysen — på de fulle verdiene, ikke på de avrundede
    // som står her.
    (spek.guides || []).forEach(function (guide) {
      if (guide.kind !== "x") return;
      var gx = x(guide.at);
      s.appendChild(el("line", {
        x1: gx, x2: gx, y1: topp - 8, y2: topp + hoyde + 8,
        stroke: "var(--strek-mork)", "stroke-width": 1
      }));
      var merker = guide.labels || [];
      if (merker[0]) {
        s.appendChild(txt(el("text", {
          class: "merketall", x: gx - 6, y: topp - 13, "text-anchor": "end"
        }), merker[0]));
      }
      if (merker[1]) {
        s.appendChild(txt(el("text", { class: "merketall", x: gx + 6, y: topp - 13 }), merker[1]));
      }
    });

    // Endene navngis fra x-aksens merketekster: «Lørenskog +54,7 %».
    if (spek.x && spek.x.tick_labels) {
      if (spek.x.tick_labels[0]) {
        s.appendChild(txt(el("text", {
          class: "merketall", x: kant, y: topp + hoyde + 18
        }), spek.x.tick_labels[0]));
      }
      if (spek.x.tick_labels[1]) {
        s.appendChild(txt(el("text", {
          class: "merketall", x: B - kant, y: topp + hoyde + 18, "text-anchor": "end"
        }), spek.x.tick_labels[1]));
      }
    }

    var naal = el("line", {
      y1: topp - 6, y2: topp + hoyde + 6, x1: 0, x2: 0,
      stroke: "var(--blekk)", "stroke-width": 2, opacity: 0
    });
    var lapp = txt(el("text", {
      class: "etikett", y: topp - 13, "text-anchor": "middle", opacity: 0
    }), "");
    s.appendChild(naal);
    s.appendChild(lapp);

    var flate = el("rect", { x: 0, y: 0, width: B, height: H, fill: "transparent" });
    s.appendChild(flate);

    function ved(ev) {
      var r = s.getBoundingClientRect();
      var i = Math.round(x.inv((ev.clientX - r.left) / (r.width / B)));
      return spek.marks[Math.max(0, Math.min(n - 1, i))];
    }
    flate.addEventListener("pointermove", function (ev) {
      var m = ved(ev), r = s.getBoundingClientRect();
      visBoble(boble, vert, m, ev.clientX, r.top + topp * (r.width / B));
    });
    flate.addEventListener("pointerleave", function () { visBoble(boble, vert, null); });
    flate.addEventListener("click", function (ev) { velg(g, ved(ev).label); });

    g.lyttere.push(function (valgt, filter) {
      spek.marks.forEach(function (m) {
        m._el.classList.toggle("valgt", m.label === valgt);
        m._el.classList.toggle("i-gruppe", !!filter && m.group === filter);
      });
      s.classList.toggle("dempet", !!valgt || !!filter);
      var m = valgt && spek.marks.find(function (a) { return a.label === valgt; });
      if (m) {
        naal.setAttribute("x1", m._x); naal.setAttribute("x2", m._x);
        naal.setAttribute("opacity", 1);
        txt(lapp, m.note ? m.label + " · " + m.note : m.label);
        lapp.setAttribute("x", Math.max(80, Math.min(B - 80, m._x)));
        lapp.setAttribute("opacity", 1);
      } else {
        naal.setAttribute("opacity", 0);
        lapp.setAttribute("opacity", 0);
      }
    });
    return s;
  }

  /* ================================================================= SØYLER */
  function tegnSoyler(spek, vert, boble, g) {
    var B = 860, radh = 30, mt = 34, mv = 150, mh = 30, tallkol = 58;
    var H = mt + spek.marks.length * radh + 34;
    var s = el("svg", {
      viewBox: "0 0 " + B + " " + H, role: "img", "aria-label": spek.alt
    });
    var x = skala(spek.x.lo, spek.x.hi, mv, B - mh - tallkol);
    var bunn = mt + spek.marks.length * radh;

    (spek.x.ticks || []).forEach(function (v, i) {
      s.appendChild(el("line", {
        class: v === 0 ? "null-linje" : "rute", x1: x(v), x2: x(v), y1: mt - 10, y2: bunn
      }));
      if (spek.x.tick_labels[i] !== undefined) {
        s.appendChild(txt(el("text", {
          class: "merketall", x: x(v), y: mt - 16, "text-anchor": "middle"
        }), spek.x.tick_labels[i]));
      }
    });

    spek.marks.forEach(function (m, i) {
      var y0 = mt + i * radh + 5, h = radh - 12;
      s.appendChild(txt(el("text", {
        class: "radnavn", x: mv - 12, y: y0 + h / 2 + 4, "text-anchor": "end"
      }), m.label));

      // Divergerende stabel: positive ledd vokser høyre for null, negative
      // venstre. Et negativt bidrag trekker totalen ned, og skal derfor gå
      // motsatt vei — ikke legge seg oppå det positive og skjule det.
      var hoyre = 0, venstre = 0, deler = [];
      m.segments.forEach(function (seg) {
        var tone = seg[0], v = seg[1];
        var fra = v >= 0 ? hoyre : venstre;
        var til = fra + v;
        if (v >= 0) hoyre = til; else venstre = til;
        var a = Math.min(x(fra), x(til)), b = Math.max(x(fra), x(til));
        var spalte = fra !== 0 ? 2 : 0;      // 2px flate mellom segmentene
        var r = el("rect", {
          class: "bolk", x: a + spalte, y: y0,
          width: Math.max(0, b - a - spalte), height: h,
          fill: farge(tone), rx: 2
        });
        s.appendChild(r);
        deler.push(r);
      });
      m._deler = deler;

      // Totalen i egen kolonne til høyre: alltid lesbar, aldri oppå en søyle
      // og aldri avkortet av en kort en.
      if (m.note) {
        s.appendChild(txt(el("text", {
          class: "radtall", x: B - mh, y: y0 + h / 2 + 4, "text-anchor": "end"
        }), m.note));
      }

      var treff = el("g", { tabindex: 0, role: "button" });
      txt(treff.appendChild(el("title")), m.label);
      treff.appendChild(el("rect", {
        x: 0, y: mt + i * radh, width: B, height: radh, fill: "transparent"
      }));
      s.appendChild(treff);

      function pek(klientX, klientY) {
        var r = s.getBoundingClientRect();
        visBoble(boble, vert, m, klientX, r.top + (mt + i * radh) * (r.width / B));
      }
      treff.addEventListener("pointermove", function (ev) { pek(ev.clientX, ev.clientY); });
      treff.addEventListener("pointerleave", function () { visBoble(boble, vert, null); });
      // Samme opplysning på tastaturfokus som på hover.
      treff.addEventListener("focus", function () {
        var r = treff.getBoundingClientRect();
        pek(r.left + r.width / 2, r.top);
      });
      treff.addEventListener("blur", function () { visBoble(boble, vert, null); });
      treff.addEventListener("click", function () {
        filtrer(g, g.filter === m.label ? "" : m.label);
      });
      treff.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          filtrer(g, g.filter === m.label ? "" : m.label);
        }
      });
    });

    g.lyttere.push(function (valgt, filter) {
      spek.marks.forEach(function (m) {
        var pa = !filter || m.label === filter;
        m._deler.forEach(function (r) { r.setAttribute("fill-opacity", pa ? 1 : 0.18); });
      });
    });
    return s;
  }

  /* ============================================================ FLISEDIAGRAM */
  // Squarified treemap etter Bruls, Huizing og van Wijk (2000): flatene
  // legges radvis langs den korteste kanten, og en ny flate tas med i raden
  // så lenge den gjør det verste sideforholdet bedre. Alternativet — å legge
  // dem etter hverandre i én retning — gir riktige arealer, men strimler så
  // smale at ingen kan sammenligne dem.
  //
  // Merk at dette er den eneste regningen fila gjør: verdi til flate, flate
  // til piksel. Hvilken verdi flisa har, hvilken farge den skal ha i hvert
  // lag, og hva som står i boblen, kom ferdig fra analysen.
  function verstForhold(rad, kant) {
    var s = 0, mx = 0, mn = Infinity, i;
    for (i = 0; i < rad.length; i++) {
      s += rad[i];
      if (rad[i] > mx) mx = rad[i];
      if (rad[i] < mn) mn = rad[i];
    }
    if (s <= 0 || mn <= 0) return Infinity;
    return Math.max((kant * kant * mx) / (s * s), (s * s) / (kant * kant * mn));
  }

  function squarify(deler, x, y, b, h) {
    // deler: [{verdi, ...}] sortert synkende. Returnerer [{del, x, y, b, h}].
    var ut = [], igjen = [], sum = 0, i;
    for (i = 0; i < deler.length; i++) {
      if (deler[i].verdi > 0) { igjen.push(deler[i]); sum += deler[i].verdi; }
    }
    if (sum <= 0 || b <= 0 || h <= 0) return ut;
    var skala = (b * h) / sum;
    var areal = igjen.map(function (d) { return d.verdi * skala; });

    var p = 0;
    while (p < igjen.length) {
      var kant = Math.min(b, h);
      var rad = [], best = Infinity;
      while (p + rad.length < igjen.length) {
        var kandidat = rad.concat([areal[p + rad.length]]);
        var forhold = verstForhold(kandidat, kant);
        if (rad.length === 0 || forhold <= best) { best = forhold; rad = kandidat; }
        else break;
      }
      var radsum = 0;
      for (i = 0; i < rad.length; i++) radsum += rad[i];

      if (b >= h) {
        var rb = radsum / h, cy = y;
        for (i = 0; i < rad.length; i++) {
          var ih = rad[i] / rb;
          ut.push({ del: igjen[p + i], x: x, y: cy, b: rb, h: ih });
          cy += ih;
        }
        x += rb; b -= rb;
      } else {
        var rh = radsum / b, cx = x;
        for (i = 0; i < rad.length; i++) {
          var ib = rad[i] / rh;
          ut.push({ del: igjen[p + i], x: cx, y: y, b: ib, h: rh });
          cx += ib;
        }
        y += rh; h -= rh;
      }
      p += rad.length;
    }
    return ut;
  }

  // Gruppenavnet får bare stå der det får plass. Anslaget må være et anslag:
  // om overskriften vises avgjør hvor mye høyde barna får, og den
  // beslutningen må tas før de er lagt ut — altså før noe kan måles. 6,6
  // enheter per tegn er målt på den halvfete 11,5-pikselsskriften.
  function passer(tekst, bredde) { return tekst.length * 6.6 + 8 <= bredde; }

  function tegnFliser(spek, vert, boble, g) {
    // Større viewBox enn de andre figurene, med samme sideforhold. Skriften
    // er 11 piksler i *viewBox*-enheter, så et grovere rutenett gir relativt
    // mindre tekst og dermed navn på langt flere fliser. 860 enheter ga navn
    // på seks av fire hundre; 1180 gir det på rundt tjuefem. Prisen er at
    // figuren tåler mindre nedskalering før teksten blir liten — den er
    // «full» bredde nettopp derfor, og PNG-en er der for resten.
    var B = 1180, H = 760, luft = 3, tittelhoyde = 15;
    var s = el("svg", {
      viewBox: "0 0 " + B + " " + H, role: "img", "aria-label": spek.alt
    });

    // Skravur for «ikke publisert». Egen id per figur, ellers ville to
    // figurer på samme side delt mønster og den ene mistet sitt.
    var merkelapp = "skravur-" + Math.random().toString(36).slice(2, 8);
    var defs = el("defs");
    var mnst = el("pattern", {
      id: merkelapp, width: 7, height: 7,
      patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"
    });
    mnst.appendChild(el("rect", { width: 7, height: 7, fill: "var(--mangler)" }));
    mnst.appendChild(el("line", {
      x1: 0, y1: 0, x2: 0, y2: 7, stroke: "var(--mangler-strek)", "stroke-width": 2.5
    }));
    defs.appendChild(mnst);
    s.appendChild(defs);
    function flatefyll(tone) {
      return tone === "mangler" ? "url(#" + merkelapp + ")" : farge(tone);
    }

    // To nivåer: hovedgruppene deler flaten, yrkene deler gruppa si. Uten
    // grupperingen blir 400 fliser en tilfeldig mosaikk; med den kan leseren
    // se at helse er stort før hen leser et eneste navn.
    var bolker = {}, rekke = [];
    spek.marks.forEach(function (m) {
      if (!(m.size > 0)) return;          // en flate uten areal er ikke en flate
      if (!bolker[m.group]) { bolker[m.group] = { navn: m.group, verdi: 0, barn: [] }; rekke.push(bolker[m.group]); }
      bolker[m.group].verdi += m.size;
      bolker[m.group].barn.push(m);
    });
    if (!rekke.length) throw new Error("ingen fliser med areal");
    rekke.sort(function (a, b) { return b.verdi - a.verdi; });
    rekke.forEach(function (bolk) {
      bolk.barn.sort(function (a, b) { return b.size - a.size; });
    });

    var lag = el("g");
    s.appendChild(lag);

    squarify(rekke.map(function (b) { return { verdi: b.verdi, bolk: b }; }), 0, 0, B, H)
      .forEach(function (celle) {
        var bolk = celle.del.bolk;
        var x = celle.x + luft / 2, y = celle.y + luft / 2;
        var b = Math.max(0, celle.b - luft), h = Math.max(0, celle.h - luft);
        // Gruppenavnet får en egen stripe på toppen, men bare når gruppa er
        // stor nok til at stripa ikke spiser opp flisene den navngir.
        var topp = 0;
        if (h > 46 && passer(bolk.navn, b)) {
          lag.appendChild(txt(el("text", {
            class: "flis-gruppe", x: x + 1, y: y + 11
          }), bolk.navn));
          topp = tittelhoyde;
        }
        squarify(bolk.barn.map(function (m) { return { verdi: m.size, mark: m }; }),
                 x, y + topp, b, Math.max(0, h - topp))
          .forEach(function (c) {
            var m = c.del.mark;
            m._x = c.x; m._y = c.y; m._b = c.b; m._h = c.h;
            m._el = el("rect", {
              class: "flis", x: c.x, y: c.y,
              width: Math.max(0, c.b), height: Math.max(0, c.h), rx: 1
            });
            lag.appendChild(m._el);
          });
        // Ramma tegnes alltid, også når navnet ikke fikk plass. Fire av de ti
        // gruppene har for lange navn til boksene sine, og uten ei ramme ville
        // flisene deres sett ut som en fortsettelse av nabogruppa. Hvilken
        // gruppe en flis hører til står uansett i boblen.
        lag.appendChild(el("rect", {
          class: "flis-ramme", x: x - 1, y: y - 1,
          width: b + 2, height: h + 2, rx: 2
        }));
      });

    // Etikettene legges over alle flisene, ellers ville nabofliser lagt seg
    // oppå teksten til den forrige.
    //
    // Bredden måles, ikke anslås. Her finnes ingen layout som venter på
    // svaret — en etikett som ikke får plass fjernes bare igjen — og da er
    // det ingen grunn til å gjette på tegnbredder. En avkortet etikett er
    // verre enn ingen, for den ser ut som navnet på et annet yrke.
    // getBBox krever at figuren står i dokumentet, så dette kjøres av
    // hovedløkka rett etter at den er satt inn.
    var tekster = el("g");
    lag.appendChild(tekster);
    s._etiketter = function () {
      tekster.replaceChildren();
      spek.marks.forEach(function (m) {
        if (!m._el || m._b < 30 || m._h < 15) return;
        var plass = m._b - 7;
        var navn = txt(el("text", { class: "flis-navn", x: m._x + 4, y: m._y + 12.5 }), m.label);
        tekster.appendChild(navn);
        if (navn.getBBox().width > plass) { navn.remove(); return; }
        if (m._h < 31 || !m.note) return;
        var tall = txt(el("text", { class: "flis-tall", x: m._x + 4, y: m._y + 25 }), m.note);
        tekster.appendChild(tall);
        if (tall.getBBox().width > plass) tall.remove();
      });
    };

    var valgtramme = el("rect", { class: "flis-valgt", x: 0, y: 0, width: 0, height: 0, opacity: 0 });
    lag.appendChild(valgtramme);

    // Én fangstflate framfor en lytter per flis: 400 lyttere er 400 lyttere.
    var flate = el("rect", { class: "flis-flate", x: 0, y: 0, width: B, height: H, fill: "transparent" });
    lag.appendChild(flate);

    function ved(ev) {
      var ctm = s.getScreenCTM();
      if (!ctm) return null;
      var p = s.createSVGPoint();
      p.x = ev.clientX; p.y = ev.clientY;
      p = p.matrixTransform(ctm.inverse());
      var treff = null;
      spek.marks.forEach(function (m) {
        if (!m._el) return;
        if (g.filter && m.group !== g.filter) return;
        if (p.x >= m._x && p.x <= m._x + m._b && p.y >= m._y && p.y <= m._y + m._h) treff = m;
      });
      return treff;
    }

    flate.addEventListener("pointermove", function (ev) {
      var m = ved(ev);
      if (!m) return visBoble(boble, vert, null);
      var r = s.getBoundingClientRect(), k = r.width / B;
      visBoble(boble, vert, m, r.left + (m._x + m._b / 2) * k, r.top + m._y * k);
    });
    flate.addEventListener("pointerleave", function () { visBoble(boble, vert, null); });
    flate.addEventListener("click", function (ev) {
      var m = ved(ev);
      velg(g, m && m.label !== g.valgt ? m.label : null);
    });

    // Lagbytte er bare en ny fylling per flis. Layouten ligger fast, så
    // leseren kan følge én flis gjennom alle lagene.
    s._settLag = function (i) {
      spek.marks.forEach(function (m) {
        if (!m._el) return;
        var tone = spek.layers.length ? (m.tones[i] || "mangler") : m.tone;
        m._el.setAttribute("fill", flatefyll(tone));
      });
    };
    s._settLag(0);

    g.lyttere.push(function (valgt, filter) {
      spek.marks.forEach(function (m) {
        if (!m._el) return;
        m._el.classList.toggle("valgt", m.label === valgt);
        m._el.classList.toggle("i-gruppe", !!filter && m.group === filter);
      });
      s.classList.toggle("dempet", !!valgt || !!filter);
      var m = valgt && spek.marks.find(function (a) { return a.label === valgt && a._el; });
      if (m) {
        valgtramme.setAttribute("x", m._x); valgtramme.setAttribute("y", m._y);
        valgtramme.setAttribute("width", m._b); valgtramme.setAttribute("height", m._h);
        valgtramme.setAttribute("opacity", 1);
      } else {
        valgtramme.setAttribute("opacity", 0);
      }
    });
    return s;
  }

  /* ------------------------------------------------------------ tegnforklaring */
  function fyllTegn(d, poster) {
    d.replaceChildren();
    (poster || []).forEach(function (par) {
      var w = document.createElement("span");
      var i = document.createElement("i");
      // Skravuren i figuren kan ikke gjentas i en 12 pikslers rute. Prikket
      // kantstrek gjør den samme jobben: «dette er ikke en verdi».
      if (par[0] === "mangler") {
        // Skravuren gjentas i ruta, ikke bare fargen. Ellers ville
        // tegnforklaringen vist en grå flate figuren ikke har noe sted.
        i.style.background =
          "repeating-linear-gradient(45deg, var(--mangler) 0 2px, var(--mangler-strek) 2px 4px)";
      } else {
        i.style.background = farge(par[0]);
      }
      w.appendChild(i);
      w.appendChild(document.createTextNode(par[1]));
      d.appendChild(w);
    });
  }

  function lagTegn(spek, bredde) {
    var poster = spek.layers.length ? spek.layers[0].legend : spek.legend;
    if (!poster || !poster.length) return null;
    var d = document.createElement("div");
    d.className = "graf-tegn " + (bredde === "full" ? "full" : "bred");
    fyllTegn(d, poster);
    return d;
  }

  /* ------------------------------------------------------------- styrepanelet */
  // Lagknappene, når figuren kan farges på flere måter. Knapper og ikke et
  // nedtrekk: lagene er få, og poenget er å bla mellom dem og se den samme
  // flaten skifte betydning.
  function lagLagvelger(spek, svg, tegn, tekst) {
    var felt = document.createElement("div");
    var etikett = document.createElement("label");
    felt.appendChild(txt(etikett, spek.layer_label || "Farg etter"));

    var rad = document.createElement("div");
    rad.className = "graf-lag";
    rad.setAttribute("role", "group");
    rad.setAttribute("aria-label", spek.layer_label || "Farg etter");
    var knapper = [];

    function vis(i) {
      svg._settLag(i);
      knapper.forEach(function (k, j) { k.setAttribute("aria-pressed", j === i ? "true" : "false"); });
      if (tegn) fyllTegn(tegn, spek.layers[i].legend);
      if (tekst) txt(tekst, spek.layers[i].caption);
      svg.setAttribute("aria-label", spek.alt + " Farget etter: " + spek.layers[i].label + ".");
    }

    spek.layers.forEach(function (l, i) {
      var k = document.createElement("button");
      k.type = "button";
      k.setAttribute("aria-pressed", i === 0 ? "true" : "false");
      txt(k, l.label);
      k.addEventListener("click", function () { vis(i); });
      rad.appendChild(k);
      knapper.push(k);
    });
    felt.appendChild(rad);
    vis(0);
    return felt;
  }

  function lagStyring(spek, g, svg, tegn, tekst) {
    var boks = document.createElement("div");
    boks.className = "graf-styring " + (spek.width === "full" ? "full" : "bred");

    if (spek.layers.length && svg && svg._settLag) {
      boks.appendChild(lagLagvelger(spek, svg, tegn, tekst));
    }
    if (!spek.picker) return boks;

    var id = "graf-velg-" + Math.random().toString(36).slice(2, 8);
    var felt = document.createElement("div");
    var etikett = document.createElement("label");
    etikett.htmlFor = id;
    felt.appendChild(txt(etikett, spek.picker));

    var velger = document.createElement("select");
    velger.id = id;
    var alle = document.createElement("option");
    alle.value = "";
    velger.appendChild(txt(alle, "Ingen framhevet"));

    // Gruppert på det merkene er gruppert på, og sortert på norsk — en liste
    // på 323 navn er ubrukelig i tilfeldig rekkefølge. Alternativene bygges
    // av figurens egne merker, ikke av gruppa: en søylefigur i samme gruppe
    // er en avgrensning, ikke flere kommuner å velge mellom.
    var bolker = {};
    spek.marks.forEach(function (m) { (bolker[m.group] || (bolker[m.group] = [])).push(m); });
    Object.keys(bolker).sort(function (a, b) { return a.localeCompare(b, "nb"); })
      .forEach(function (navn) {
        var mål = velger;
        if (navn) {
          mål = document.createElement("optgroup");
          mål.label = navn;
          velger.appendChild(mål);
        }
        bolker[navn].slice().sort(function (a, b) {
          return a.label.localeCompare(b.label, "nb");
        }).forEach(function (m) {
          var o = document.createElement("option");
          o.value = m.label;
          mål.appendChild(txt(o, m.note ? m.label + "  " + m.note : m.label));
        });
      });
    felt.appendChild(velger);
    boks.appendChild(felt);

    var filterVelger = null;
    if (spek.group_label) {
      var fid = id + "-f";
      var ffelt = document.createElement("div");
      var fetikett = document.createElement("label");
      fetikett.htmlFor = fid;
      ffelt.appendChild(txt(fetikett, spek.group_label));
      filterVelger = document.createElement("select");
      filterVelger.id = fid;
      var falle = document.createElement("option");
      falle.value = "";
      filterVelger.appendChild(txt(falle, "Alle"));
      Object.keys(bolker).filter(Boolean)
        .sort(function (a, b) { return a.localeCompare(b, "nb"); })
        .forEach(function (navn) {
          var o = document.createElement("option");
          o.value = navn;
          filterVelger.appendChild(txt(o, navn));
        });
      ffelt.appendChild(filterVelger);
      boks.appendChild(ffelt);
      filterVelger.addEventListener("change", function () { filtrer(g, filterVelger.value); });
    }

    var nullstill = document.createElement("button");
    nullstill.type = "button";
    boks.appendChild(txt(nullstill, "Nullstill"));
    nullstill.addEventListener("click", function () {
      g.valgt = null; g.filter = ""; meld(g);
    });

    velger.addEventListener("change", function () { velg(g, velger.value); });

    // Panelet speiler tilstanden framfor å eie den — ellers kan et klikk i
    // figuren og et valg i nedtrekket vise hver sin sannhet.
    g.lyttere.push(function (valgt, filter) {
      if (velger.value !== (valgt || "")) velger.value = valgt || "";
      if (filterVelger && filterVelger.value !== filter) filterVelger.value = filter;
    });
    return boks;
  }

  /* ------------------------------------------------------------------ start */
  // Får vi ikke tegnet, setter vi inn PNG-en i stedet. En figur som mangler er
  // verre enn en figur som bare ligger stille.
  function fallTilbake(fig) {
    var flate = fig.querySelector(".graf-flate");
    if (!flate || flate.querySelector("img") || !fig.dataset.fallback) return;
    var img = document.createElement("img");
    img.src = fig.dataset.fallback;
    img.alt = fig.dataset.alt || "";
    img.loading = "lazy";
    img.decoding = "async";
    flate.appendChild(img);
  }

  figurer.forEach(function (fig) {
    var spek, kilde = fig.querySelector("script.graf-spek");
    try {
      spek = normaliser(JSON.parse(kilde.textContent));
    } catch (e) {
      return fallTilbake(fig);
    }
    if (!spek.marks.length) return fallTilbake(fig);

    var g = gruppe(spek.link || ("_" + Math.random()));
    // Figuren som eier velgeren definerer hva gruppa handler om. Uten det
    // ville en søylefigur med fylkesnavn lagt fylker inn i kommunelista, og
    // «Oslo» hadde vært to forskjellige ting i samme gruppe.
    if (spek.picker) g.merker = spek.marks;

    var flate = fig.querySelector(".graf-flate");
    var boble = lagBoble(flate);
    var s;
    try {
      if (spek.kind === "scatter") s = tegnSpredning(spek, flate, boble, g);
      else if (spek.kind === "strip") s = tegnStripe(spek, flate, boble, g);
      else if (spek.kind === "bars") s = tegnSoyler(spek, flate, boble, g);
      else if (spek.kind === "treemap") s = tegnFliser(spek, flate, boble, g);
    } catch (e) {
      s = null;
    }
    if (!s) { boble.remove(); return fallTilbake(fig); }

    flate.insertBefore(s, boble);
    fig.classList.add("tegnet");
    // Etiketter som må måles, måles først når figuren står i dokumentet.
    if (s._etiketter) { try { s._etiketter(); } catch (e) { /* uten mål, ingen navn */ } }

    var tegn = lagTegn(spek, spek.width);
    // Bildeteksten som hører til det valgte laget, ikke til figuren. Den
    // fylles av lagvelgeren, så den lages tom her.
    var lagtekst = null;
    if (spek.layers.length) {
      lagtekst = document.createElement("p");
      lagtekst.className = "graf-lagtekst " + (spek.width === "full" ? "full" : "bred");
    }
    if (tegn) fig.parentNode.insertBefore(tegn, fig);
    if (lagtekst) fig.parentNode.insertBefore(lagtekst, fig);
    if (spek.picker || spek.layers.length) {
      fig.parentNode.insertBefore(
        lagStyring(spek, g, s, tegn, lagtekst), tegn || lagtekst || fig
      );
    }
  });

  Object.keys(grupper).forEach(function (navn) { meld(grupper[navn]); });

  // Uten bevegelse: markeringen er fortsatt der, den glir bare ikke inn.
  if (rolig) document.body.classList.add("rolig");
})();
