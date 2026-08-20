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
    function format(f) {
      if (!f) return null;
      return {
        decimals: tall(f.decimals, 0), factor: tall(f.factor, 1),
        suffix: f.suffix || "", sign: !!f.sign
      };
    }
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
        tones: m.tones || [],
        points: m.points || [], point_labels: m.point_labels || [],
        series: m.series || []
      };
    });
    spek.guides = (spek.guides || []).map(function (g) {
      return { kind: g.kind || "", at: tall(g.at, 0), labels: g.labels || [] };
    });
    spek.legend = spek.legend || [];
    spek.layers = (spek.layers || []).map(function (l) {
      return {
        key: l.key || "", label: l.label || "",
        legend: l.legend || [], caption: l.caption || "",
        // Feltene under styrer tidslinja. De er analysens regel, ikke
        // rendererens: grensene, ordene og presisjonen står i sakspakken.
        rule: l.rule || "",
        edges: l.edges || [],
        format: format(l.format),
        level_label: l.level_label || "",
        level_format: format(l.level_format),
        floor: typeof l.floor === "number" ? l.floor : null,
        span: l.span || [],
        missing_label: l.missing_label || "",
        floor_label: l.floor_label || ""
      };
    });
    spek.layer_label = spek.layer_label || "";
    spek.timeline = spek.timeline ? {
      labels: spek.timeline.labels || [],
      label: spek.timeline.label || "",
      note: spek.timeline.note || "",
      from_point: tall(spek.timeline.from_point, 0),
      to_point: tall(spek.timeline.to_point, 0)
    } : null;
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
    boble.classList.add("pa");

    // Boblen er midtstilt over punktet. Uten grenser havner den utenfor
    // figuren når punktet ligger nær en kant — på en telefon betyr det
    // utenfor skjermen: et trykk på flisa lengst til venstre satte den på
    // -107 piksler. Vi holder den innenfor, og snur den under punktet når
    // det ikke er høyde igjen over. Dette er ombrekking, ikke en påstand om
    // tallene: det som står i boblen er det samme uansett hvor den havner.
    var ramme = vert.getBoundingClientRect();
    var egen = boble.getBoundingClientRect();
    var halv = egen.width / 2, luft = 6;
    var x = klientX - ramme.left;
    var y = klientY - ramme.top;
    if (ramme.width > egen.width + luft * 2) {
      x = Math.max(halv + luft, Math.min(ramme.width - halv - luft, x));
    }
    boble.classList.toggle("under", y - egen.height - 14 < 0);
    boble.style.left = x + "px";
    boble.style.top = y + "px";
  }

  /* ------------------------------------------------------------- berøring */
  // En berøringsskjerm har ingen peker som svever, så «hold musa over» finnes
  // ikke der. Løsningen er ikke å gjette på skjermbredde — et nettbrett på
  // 1400 piksler er fortsatt berøring, og en mus koblet til det er fortsatt
  // en mus — men å se på hva slags peker hendelsen faktisk kom fra.
  //
  // To ting må håndteres, og de trekker hver sin vei:
  //
  //   * pointermove fyrer hele veien mens en finger drar for å *rulle*. Uten
  //     filteret blinker boblen fram og tilbake gjennom hele rullingen.
  //   * pointerleave fyrer når fingeren løftes, altså rett etter hvert trykk.
  //     Uten filteret ville boblen vist seg og forsvunnet i samme bevegelse.
  //
  // Derfor: på berøring styrer trykket alene, og boblen blir stående til
  // neste trykk. På mus er alt som før.
  function erBeroring(ev) { return !!ev && ev.pointerType === "touch"; }

  function paaPeker(el, handler) {
    el.addEventListener("pointermove", function (ev) {
      if (erBeroring(ev)) return;
      handler(ev);
    });
  }

  function paaPekerUt(el, handler) {
    el.addEventListener("pointerleave", function (ev) {
      if (erBeroring(ev)) return;
      handler(ev);
    });
  }

  /* ================================================================ TIDSLINJE */
  // Her, og bare her, regner fila ut noe annet enn en piksel.
  //
  // Grunnen er at svaret ikke finnes på forhånd. Med elleve punkter er det
  // 55 fra/til-kombinasjoner per lag, og analysen kan ikke skrive ut en
  // ferdig farge og en ferdig setning for hver av dem uten at
  // spesifikasjonen blir en oppslagstabell på flere hundre kilobyte.
  //
  // Så analysen sier regelen i stedet for svaret: hvilken serie som måles,
  // om det er nivået eller endringen, hvor grensene mellom trinnene går,
  // hvor lite et yrke kan være før en prosent slutter å bety noe, hvor
  // mange desimaler tallet tåler, og hva som skal stå når målingen mangler.
  // Ingenting av det velges her. Det som skjer her er en divisjon, en
  // sammenligning og en avrunding.

  // Laget rekker ikke nødvendigvis like langt som skinna — sykefraværet er
  // årlig og ligger et år etter bestanden. Stillingen klemmes inn i
  // rekkevidden når den leses, og den globale stillingen røres ikke: bytter
  // leseren tilbake til et lag som rekker lenger, står håndtaket der hen
  // satte det.
  function klem(lag, i) {
    if (!lag.span || lag.span.length !== 2) return i;
    return Math.max(lag.span[0], Math.min(lag.span[1], i));
  }

  // Måling eller mangel, med grunnen til mangelen. De to grunnene er ikke
  // det samme: «ikke publisert» er kilden som tier, «ikke sammenlignbar» er
  // vi som lar være å regne. Ordene for begge kommer fra laget.
  function maaling(lag, mark, li, fra, til) {
    var s = mark.series[li];
    if (!s || !s.length) return { v: null, ord: lag.floor_label || lag.missing_label };
    var b = s[klem(lag, til)];
    if (b === null || b === undefined) return { v: null, ord: lag.missing_label };
    if (lag.rule !== "change") return { v: b, ord: "" };

    var a = s[klem(lag, fra)];
    if (a === null || a === undefined) return { v: null, ord: lag.missing_label };
    // En endring fra ingenting er ikke en prosent, uansett hvor mange som kom til.
    if (!(a > 0)) return { v: null, ord: lag.floor_label || lag.missing_label };
    // Grensen prøves mot begge endene: hvilke yrker som er små endrer seg.
    if (lag.floor !== null && (a < lag.floor || b < lag.floor)) {
      return { v: null, ord: lag.floor_label };
    }
    return { v: b / a - 1, ord: "" };
  }

  // Nivået i det ene punktet, uavhengig av om laget måler nivå eller endring.
  // Et endringslag som oppgir level_label viser begge deler i boblen.
  function nivaa(lag, mark, li, til) {
    var s = mark.series[li];
    if (!s || !s.length) return null;
    var v = s[klem(lag, til)];
    return (v === null || v === undefined) ? null : v;
  }

  // Trinnet en verdi havner på. Samme regning som analysen gjør for PNG-en:
  // første trinn der verdien er mindre enn grensen.
  function trinn(lag, v) {
    if (v === null) return "mangler";
    var i = 0;
    while (i < lag.edges.length && v >= lag.edges[i]) i++;
    return lag.legend[i] ? lag.legend[i][0] : "mangler";
  }

  // Tallet skrevet slik laget ba om det. Mellomrommet mellom tusenene er
  // hardt, så «170 281» ikke brekker over to linjer midt i tallet.
  var formatterere = {};
  function formater(f, v) {
    if (!f || v === null) return "";
    var nokkel = f.decimals + "|" + f.factor;
    if (!formatterere[nokkel]) {
      formatterere[nokkel] = new Intl.NumberFormat("nb-NO", {
        minimumFractionDigits: f.decimals, maximumFractionDigits: f.decimals
      });
    }
    var x = v * f.factor;
    // To rettelser på det nb-NO gir oss, og begge handler om at sida skal
    // skrive tall på én måte og ikke to. Skilletegnet mellom tusenene blir
    // et hardt mellomrom, så «170 281» ikke brekker midt i tallet. Og
    // minustegnet blir bindestreken analysen bruker: U+2212 er penere, men
    // da står PNG-en og boblen med hvert sitt minus for det samme tallet.
    var s = formatterere[nokkel].format(x)
      .replace(/\s/g, " ")
      .replace(/−/g, "-");
    // Fortegnet settes på alt som ikke allerede har ett. Det er den samme
    // regelen som Pythons «+»-format, og den er valgt fordi det er den
    // resten av sakspakken bruker — ikke fordi «+0,0 %» er pent.
    if (f.sign && s.charAt(0) !== "-") s = "+" + s;
    return s + f.suffix;
  }

  // Det boblen viser når tidslinja styrer: hvert lag med sin verdi i det
  // punktet leseren står på. Uten dette ville boblen vist siste kvartal mens
  // flaten var farget etter 2018.
  function tidsavlesninger(spek, mark, fra, til) {
    var ut = [];
    spek.layers.forEach(function (lag, li) {
      if (lag.level_label && lag.level_format) {
        var n = nivaa(lag, mark, li, til);
        ut.push({
          label: lag.level_label,
          value: n === null ? lag.missing_label : formater(lag.level_format, n)
        });
      }
      var m = maaling(lag, mark, li, fra, til);
      ut.push({
        label: lag.label,
        value: m.v === null ? m.ord : formater(lag.format, m.v),
        // Nøkkelfargen i boblen er den flisa faktisk har i det laget. Da
        // slipper leseren å bytte lag for å se hvor et tall ligger på skalaen.
        tone: m.v === null ? "" : trinn(lag, m.v)
      });
    });
    return ut;
  }

  /* ------------------------------------------------------------ selve skinna */
  // Bygget av vanlige elementer og ikke av SVG: dette er en betjening, ikke
  // en figur. Håndtakene er knapper med role="slider", så piltastene virker
  // uten at vi finner opp tastaturet på nytt.
  //
  // Bare endene av skinna er navngitt, og lesningen står over håndtakene.
  // Elleve årstall langs skinna kolliderer med hverandre på en smal skjerm,
  // og en etikett som overlapper naboetiketten er verre enn ingen.
  function lagTidslinje(spek, ved) {
    var tid = spek.timeline, n = tid.labels.length;
    var stand = { fra: tid.from_point, til: tid.to_point, lag: spek.layers[0] };

    var felt = document.createElement("div");
    felt.className = "graf-tid";
    if (tid.label) felt.appendChild(txt(document.createElement("label"), tid.label));

    var skinne = document.createElement("div");
    skinne.className = "graf-skinne";
    felt.appendChild(skinne);

    var lesning = document.createElement("span");
    lesning.className = "graf-lesning";
    skinne.appendChild(lesning);

    var spor = document.createElement("span");
    spor.className = "graf-spor";
    skinne.appendChild(spor);

    // Den delen av skinna laget ikke rekker over. Vises bare når det er en.
    var ute = document.createElement("span");
    ute.className = "graf-spor-ute";
    skinne.appendChild(ute);

    var valgt = document.createElement("span");
    valgt.className = "graf-spor-valgt";
    skinne.appendChild(valgt);

    function pst(i) { return n < 2 ? 0 : (i / (n - 1)) * 100; }

    for (var i = 0; i < n; i++) {
      var t = document.createElement("span");
      t.className = "graf-tikk";
      t.style.left = pst(i) + "%";
      skinne.appendChild(t);
    }
    var ende0 = txt(document.createElement("span"), tid.labels[0]);
    ende0.className = "graf-ende start";
    var ende1 = txt(document.createElement("span"), tid.labels[n - 1]);
    ende1.className = "graf-ende slutt";
    skinne.appendChild(ende0);
    skinne.appendChild(ende1);

    function haandtak(rolle) {
      var h = document.createElement("button");
      h.type = "button";
      h.className = "graf-haandtak " + rolle;
      h.setAttribute("role", "slider");
      h.setAttribute("aria-valuemin", 0);
      h.setAttribute("aria-valuemax", n - 1);
      skinne.appendChild(h);
      return h;
    }
    var hFra = haandtak("fra"), hTil = haandtak("til");

    // Hvilke stillinger som er lovlige i det aktive laget.
    function grenser() {
      var lag = stand.lag;
      if (lag && lag.span && lag.span.length === 2) return [lag.span[0], lag.span[1]];
      return [0, n - 1];
    }
    function endring() { return !!stand.lag && stand.lag.rule === "change"; }
    function kl(i, g) { return Math.max(g[0], Math.min(g[1], i)); }

    // Stillingen slik det aktive laget kan bruke den. `stand` røres ikke:
    // et lag som rekker kortere enn skinna skal ikke stjele stillingen
    // leseren satte i et lag som rekker lenger.
    function normalisert() {
      var g = grenser(), fra = kl(stand.fra, g), til = kl(stand.til, g);
      if (!endring()) return { fra: fra, til: til };
      // En periode med null lengde er ikke en periode. Uten dette kan
      // leseren stille inn 2026–2026 og få «omtrent uendret» på hvert
      // eneste yrke — et svar som ser ut som et funn.
      if (fra >= til) {
        if (til > g[0]) fra = til - 1;
        else { fra = g[0]; til = Math.min(g[1], g[0] + 1); }
      }
      return { fra: fra, til: til };
    }

    function tegn() {
      var g = grenser(), na = normalisert();
      var fra = na.fra, til = na.til, to = endring();

      hFra.hidden = !to;
      hFra.style.left = pst(fra) + "%";
      hTil.style.left = pst(til) + "%";
      hFra.setAttribute("aria-valuenow", fra);
      hTil.setAttribute("aria-valuenow", til);
      hFra.setAttribute("aria-valuetext", tid.labels[fra]);
      hTil.setAttribute("aria-valuetext", tid.labels[til]);
      hFra.setAttribute("aria-label", (tid.label || "Tidspunkt") + ", fra");
      hTil.setAttribute("aria-label", (tid.label || "Tidspunkt") + (to ? ", til" : ""));

      // Det fylte spennet står bare i et endringslag. Et tidspunkt er ikke
      // et spenn, og en fylt strekning fra skinnestart fram til håndtaket
      // ville sagt «fram til 2019» om noe som gjelder 2019.
      var a = pst(fra), b = pst(til);
      valgt.hidden = !to;
      valgt.style.left = a + "%";
      valgt.style.width = Math.max(0, b - a) + "%";

      var utenfor = g[1] < n - 1;
      ute.hidden = !utenfor;
      if (utenfor) {
        ute.style.left = pst(g[1]) + "%";
        ute.style.width = (100 - pst(g[1])) + "%";
      }

      var ord = to ? tid.labels[fra] + "–" + tid.labels[til] : tid.labels[til];
      txt(lesning, ord);
      // Lesningen står midt over spennet, eller rett over håndtaket når det
      // bare er ett.
      lesning.style.left = (to ? (a + b) / 2 : b) + "%";

      ved(fra, til, ord);
    }

    // Håndtakene kan ikke krysse hverandre, og i et endringslag kan de
    // heller ikke møtes.
    function sett(hvem, i) {
      var g = grenser(), na = normalisert();
      i = kl(Math.round(i), g);
      if (hvem === "fra") stand.fra = endring() ? Math.min(i, na.til - 1) : i;
      else stand.til = endring() ? Math.max(i, na.fra + 1) : i;
      tegn();
    }

    function indeksVed(klientX) {
      var r = skinne.getBoundingClientRect();
      if (r.width <= 0) return 0;
      return ((klientX - r.left) / r.width) * (n - 1);
    }

    [["fra", hFra], ["til", hTil]].forEach(function (par) {
      var hvem = par[0], h = par[1];
      var drar = false;
      h.addEventListener("pointerdown", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        h.focus();
        drar = true;
        h.classList.add("drar");
        // Fangsten er det som gjør at draget følger med når pekeren går
        // utenfor de femten pikslene håndtaket er. Den er en forbedring og
        // ikke en forutsetning: mislykkes den, drar `drar` lasset videre.
        try { h.setPointerCapture(ev.pointerId); } catch (e) { /* uten fangst, fortsatt drag */ }
      });
      h.addEventListener("pointermove", function (ev) {
        if (!drar) return;
        sett(hvem, indeksVed(ev.clientX));
      });
      function slipp(ev) {
        drar = false;
        try {
          if (h.hasPointerCapture(ev.pointerId)) h.releasePointerCapture(ev.pointerId);
        } catch (e) { /* var aldri fanget */ }
        h.classList.remove("drar");
      }
      h.addEventListener("pointerup", slipp);
      h.addEventListener("pointercancel", slipp);
      h.addEventListener("keydown", function (ev) {
        var na = hvem === "fra" ? stand.fra : stand.til, g = grenser(), steg = null;
        if (ev.key === "ArrowLeft" || ev.key === "ArrowDown") steg = na - 1;
        else if (ev.key === "ArrowRight" || ev.key === "ArrowUp") steg = na + 1;
        else if (ev.key === "PageDown") steg = na - 5;
        else if (ev.key === "PageUp") steg = na + 5;
        else if (ev.key === "Home") steg = g[0];
        else if (ev.key === "End") steg = g[1];
        if (steg === null) return;
        ev.preventDefault();
        sett(hvem, steg);
      });
    });

    // Klikk på skinna flytter det nærmeste håndtaket dit. Uten dette må
    // leseren treffe en sirkel på fjorten piksler for å komme i gang.
    skinne.addEventListener("pointerdown", function (ev) {
      var i = indeksVed(ev.clientX);
      var hvem = endring() && Math.abs(i - stand.fra) < Math.abs(i - stand.til) ? "fra" : "til";
      (hvem === "fra" ? hFra : hTil).focus();
      sett(hvem, i);
    });

    if (tid.note) {
      var note = txt(document.createElement("p"), tid.note);
      note.className = "graf-tid-note";
      felt.appendChild(note);
    }

    // Lagvelgeren kaller denne når leseren bytter lag: rekkevidden og
    // antallet håndtak følger laget, stillingen følger leseren.
    felt._settLag = function (lag) { stand.lag = lag; tegn(); };
    felt._nullstill = function () {
      stand.fra = tid.from_point;
      stand.til = tid.to_point;
      tegn();
    };
    return felt;
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

    function visVed(ev) {
      var m = naermest(ev);
      if (!m) { visBoble(boble, vert, null); return null; }
      var r = s.getBoundingClientRect(), k = r.width / B;
      visBoble(boble, vert, m, r.left + m._x * k, r.top + (m._y - m._r) * k);
      return m;
    }
    paaPeker(flate, visVed);
    paaPekerUt(flate, function () { visBoble(boble, vert, null); });
    flate.addEventListener("click", function (ev) {
      // Trykket viser boblen *og* velger. På mus er visningen allerede gjort
      // av pointermove; på berøring er dette den eneste sjansen.
      velg(g, (visVed(ev) || {}).label || null);
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
    function visVed(ev) {
      var m = ved(ev), r = s.getBoundingClientRect();
      visBoble(boble, vert, m, ev.clientX, r.top + topp * (r.width / B));
      return m;
    }
    paaPeker(flate, visVed);
    paaPekerUt(flate, function () { visBoble(boble, vert, null); });
    flate.addEventListener("click", function (ev) { velg(g, visVed(ev).label); });

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
      paaPeker(treff, function (ev) { pek(ev.clientX, ev.clientY); });
      paaPekerUt(treff, function () { visBoble(boble, vert, null); });
      // Samme opplysning på tastaturfokus som på hover.
      treff.addEventListener("focus", function () {
        var r = treff.getBoundingClientRect();
        pek(r.left + r.width / 2, r.top);
      });
      treff.addEventListener("blur", function () { visBoble(boble, vert, null); });
      treff.addEventListener("click", function (ev) {
        var r = treff.getBoundingClientRect();
        pek(ev.clientX || r.left + r.width / 2, ev.clientY || r.top);
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

  /* ================================================================= LINJER */
  // Hvert merke er én serie, ikke ett punkt. Linja tegnes gjennom punktene
  // slik de kom; ingen utjevning, ingen interpolering av hull. Et hull i
  // dataene skal se ut som et hull, ikke som en rett strekning.
  function tegnLinjer(spek, vert, boble, g) {
    var B = 860, H = 520, plott = { v: 62, h: 782, t: 18, b: 462 };
    var s = el("svg", {
      viewBox: "0 0 " + B + " " + H, role: "img", "aria-label": spek.alt
    });
    var lag = el("g");
    s.appendChild(lag);

    var x = skala(spek.x.lo, spek.x.hi, plott.v, plott.h);
    var y = skala(spek.y.lo, spek.y.hi, plott.b, plott.t);

    tegnAkser(lag, spek, x, y, plott);
    tegnGuider(lag, spek, x, y, plott);

    var linjer = el("g");
    lag.appendChild(linjer);
    spek.marks.forEach(function (m) {
      m._pkt = m.points.map(function (p) { return [x(p[0]), y(p[1])] });
      m._el = el("polyline", {
        class: "linje",
        points: m._pkt.map(function (p) { return p[0] + "," + p[1] }).join(" "),
        fill: "none", stroke: farge(m.tone),
        "stroke-width": m.pin ? 2.6 : 1.5,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        "stroke-opacity": m.pin ? 1 : 0.55
      });
      linjer.appendChild(m._el);
    });

    // Navn ved siste punkt, bare på de linjene analysen ba om. En
    // tegnforklaring ved siden av tvinger leseren til å matche farger;
    // navnet der linja slutter gjør ikke det.
    var faste = [];
    spek.marks.filter(function (m) { return m.pin && m._pkt.length; }).forEach(function (m) {
      var sist = m._pkt[m._pkt.length - 1];
      var t = txt(el("text", {
        class: "etikett", x: sist[0] + 8, y: sist[1] + 4
      }), m.label);
      lag.appendChild(t);
      faste.push([m, t]);
    });

    var ring = el("circle", { class: "valgt-ring", r: 4, cx: 0, cy: 0, opacity: 0 });
    lag.appendChild(ring);

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
        m._pkt.forEach(function (q, i) {
          var d = Math.hypot(q[0] - p.x, q[1] - p.y);
          if (d < bd) { bd = d; best = { mark: m, i: i, x: q[0], y: q[1] }; }
        });
      });
      return bd < 40 ? best : null;
    }

    function visVed(ev) {
      var treff = naermest(ev);
      if (!treff) { ring.setAttribute("opacity", 0); visBoble(boble, vert, null); return null; }
      ring.setAttribute("cx", treff.x);
      ring.setAttribute("cy", treff.y);
      ring.setAttribute("opacity", 1);
      var r = s.getBoundingClientRect(), k = r.width / B;
      // Boblen får punktteksten som undertittel, og merkets faste avlesninger
      // under. Begge deler kom ferdig formatert fra analysen.
      visBoble(boble, vert, {
        label: treff.mark.label,
        group: treff.mark.point_labels[treff.i] || "",
        values: treff.mark.values
      }, r.left + treff.x * k, r.top + treff.y * k);
      return treff;
    }
    paaPeker(flate, visVed);
    paaPekerUt(flate, function () {
      ring.setAttribute("opacity", 0);
      visBoble(boble, vert, null);
    });
    flate.addEventListener("click", function (ev) {
      var treff = visVed(ev);
      velg(g, treff && treff.mark.label !== g.valgt ? treff.mark.label : null);
    });

    g.lyttere.push(function (valgt, filter) {
      spek.marks.forEach(function (m) {
        var pa = m.label === valgt;
        m._el.classList.toggle("valgt", pa);
        m._el.classList.toggle("i-gruppe", !!filter && m.group === filter);
        // Den valgte linja løftes fram med tykkelse, ikke bare med farge.
        m._el.setAttribute("stroke-width", pa ? 3.2 : (m.pin ? 2.6 : 1.5));
        m._el.setAttribute("stroke-opacity", pa ? 1 : (m.pin ? 1 : 0.55));
      });
      s.classList.toggle("dempet", !!valgt || !!filter);
      faste.forEach(function (par) {
        par[1].setAttribute("opacity", !valgt || par[0].label === valgt ? 1 : 0.25);
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
  // beslutningen må tas før de er lagt ut — altså før noe kan måles. 0,58
  // av skriftstørrelsen per tegn er målt på den halvfete skriften i
  // .flis-gruppe. Endrer du den, mål på nytt — et for lavt anslag lar de
  // lengste gruppenavnene renne ut over nabogruppa.
  function passer(tekst, bredde, skrift) {
    return tekst.length * skrift * 0.58 + 8 <= bredde;
  }

  // Et flisediagram er bredt og lavt på en skjerm og høyt og smalt på en
  // telefon — ikke fordi det er moderne, men fordi 400 flater i 375 × 242
  // piksler er 227 kvadratpiksler hver, og ingen finger treffer det. Et
  // stående utsnitt gir dobbelt så mye flate til de samme flisene.
  //
  // Skriftstørrelsene følger med, og de står her og ikke i CSS fordi
  // oppsettet trenger dem *før* noe er tegnet: hvor høy tittelstripa blir,
  // og om gruppenavnet i det hele tatt får plass, avgjøres av dem.
  // Skriften oppgis i den *rendrede* størrelsen vi vil ha, og regnes om til
  // viewBox-enheter etter hvor mye figuren faktisk skaleres. Da er en
  // gruppeoverskrift 16 piksler på en 1440 piksler bred skjerm og 16 piksler
  // på en telefon — i stedet for 16 og 4, som er det en fast enhetsstørrelse
  // gir. Konsekvensen er at teksten tar *flere enheter* på en liten skjerm og
  // dermed at færre flisenavn får plass, og det er riktig vei: et navn som
  // ikke kan leses er ikke verdt flata det dekker.
  function flisemaal(bredde) {
    var staaende = bredde < 700;
    var B = staaende ? 760 : 1180;
    var enhet = B / Math.max(bredde, 1);
    function px(maal) { return Math.round(maal * enhet * 10) / 10; }
    return {
      B: B, H: staaende ? 1010 : 760,
      gruppe: px(16), navn: px(13.5), tall: px(11.5), tittel: px(21)
    };
  }

  function tegnFliser(spek, vert, boble, g) {
    // Større viewBox enn de andre figurene, med samme sideforhold. Skriften
    // er 11 piksler i *viewBox*-enheter, så et grovere rutenett gir relativt
    // mindre tekst og dermed navn på langt flere fliser. 860 enheter ga navn
    // på seks av fire hundre; 1180 gir det på rundt tjuefem. Prisen er at
    // figuren tåler mindre nedskalering før teksten blir liten — den er
    // «full» bredde nettopp derfor, og PNG-en er der for resten.
    var maal = flisemaal(vert.getBoundingClientRect().width);
    var B = maal.B, H = maal.H, luft = 3, tittelhoyde = maal.tittel;
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
        if (h > tittelhoyde * 2.9 && passer(bolk.navn, b, maal.gruppe)) {
          var tittel = txt(el("text", {
            class: "flis-gruppe", x: x + 1, y: y + tittelhoyde * 0.72
          }), bolk.navn);
          tittel.style.fontSize = maal.gruppe + "px";
          lag.appendChild(tittel);
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
        if (!m._el || m._b < maal.navn * 2.6 || m._h < maal.navn * 1.3) return;
        var plass = m._b - 7;
        var navn = txt(el("text", {
          class: "flis-navn", x: m._x + 4, y: m._y + maal.navn * 1.09
        }), m.label);
        navn.style.fontSize = maal.navn + "px";
        tekster.appendChild(navn);
        if (navn.getBBox().width > plass) { navn.remove(); return; }
        if (m._h < maal.navn * 2.7 || !m.note) return;
        var tall = txt(el("text", {
          class: "flis-tall", x: m._x + 4, y: m._y + maal.navn * 2.17
        }), m.note);
        tall.style.fontSize = maal.tall + "px";
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

    // Med tidslinje er ikke merkets faste avlesninger sanne lenger — de
    // gjelder siste punkt, og leseren kan stå hvor som helst. Da bygges
    // boblen av lagene i stedet, i den stillingen håndtakene faktisk står.
    function peket(m) {
      if (!spek.timeline) return m;
      return {
        label: m.label, group: m.group,
        values: tidsavlesninger(spek, m, stilling.fra, stilling.til)
      };
    }

    function visVed(ev) {
      var m = ved(ev);
      if (!m) { visBoble(boble, vert, null); return null; }
      var r = s.getBoundingClientRect(), k = r.width / B;
      visBoble(boble, vert, peket(m), r.left + (m._x + m._b / 2) * k, r.top + m._y * k);
      return m;
    }
    paaPeker(flate, visVed);
    paaPekerUt(flate, function () { visBoble(boble, vert, null); });
    flate.addEventListener("click", function (ev) {
      // Ett trykk gjør begge deler: viser tallene og markerer flisa. Å treffe
      // samme flis igjen fjerner markeringen, men lar boblen stå — fingeren
      // peker fortsatt på den.
      var m = visVed(ev);
      velg(g, m && m.label !== g.valgt ? m.label : null);
    });

    // Lagbytte er bare en ny fylling per flis. Layouten ligger fast — den
    // følger bestanden i siste punkt og rører seg ikke når leseren drar i
    // tidslinja. Det er et valg: en flate som puster med tida ville vært
    // vakrere å se på, men da kan man ikke følge én flis gjennom hverken
    // lagene eller årene, og det er nettopp det figuren er til for.
    var stilling = { lag: 0, fra: 0, til: 0 };
    if (spek.timeline) {
      stilling.fra = spek.timeline.from_point;
      stilling.til = spek.timeline.to_point;
    }

    s._settLag = function (i, fra, til) {
      stilling.lag = i;
      if (fra !== undefined) { stilling.fra = fra; stilling.til = til; }
      var lag = spek.layers[i];
      spek.marks.forEach(function (m) {
        if (!m._el) return;
        var tone;
        if (spek.timeline && lag) {
          tone = trinn(lag, maaling(lag, m, i, stilling.fra, stilling.til).v);
        } else {
          tone = spek.layers.length ? (m.tones[i] || "mangler") : m.tone;
        }
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
  function lagLagvelger(spek, bytt) {
    var felt = document.createElement("div");
    var etikett = document.createElement("label");
    felt.appendChild(txt(etikett, spek.layer_label || "Farg etter"));

    var rad = document.createElement("div");
    rad.className = "graf-lag";
    rad.setAttribute("role", "group");
    rad.setAttribute("aria-label", spek.layer_label || "Farg etter");
    var knapper = [];

    function vis(i) {
      knapper.forEach(function (k, j) { k.setAttribute("aria-pressed", j === i ? "true" : "false"); });
      bytt(i);
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

    // Lagvelgeren og tidslinja styrer den samme figuren, og må derfor dele
    // hvilket lag som er aktivt. Panelet eier den tilstanden; ingen av de
    // to holder sin egen kopi av den.
    var kanLag = spek.layers.length && svg && svg._settLag;
    var aktivt = 0, lesning = "", tidslinje = null;

    function oppdater(fra, til) {
      svg._settLag(aktivt, fra, til);
      // Blindeteksten skal si det samme som figuren viser — hvilket lag, og
      // hvilket tidspunkt leseren står på.
      svg.setAttribute("aria-label",
        spek.alt + " Farget etter: " + spek.layers[aktivt].label +
        (lesning ? ". Tidspunkt: " + lesning : "") + ".");
    }

    function bytt(i) {
      aktivt = i;
      if (tegn) fyllTegn(tegn, spek.layers[i].legend);
      if (tekst) txt(tekst, spek.layers[i].caption);
      // Tidslinja tegner seg selv på nytt og kaller oppdater den veien, så
      // rekkevidde og figur aldri kan komme i utakt.
      if (tidslinje) tidslinje._settLag(spek.layers[i]);
      else oppdater();
    }

    if (kanLag && spek.timeline) {
      tidslinje = lagTidslinje(spek, function (fra, til, tekstlesning) {
        lesning = tekstlesning;
        oppdater(fra, til);
      });
    }
    if (kanLag) {
      boks.appendChild(lagLagvelger(spek, bytt));
      if (tidslinje) boks.appendChild(tidslinje);
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
      if (tidslinje) tidslinje._nullstill();
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
      else if (spek.kind === "line") s = tegnLinjer(spek, flate, boble, g);
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
