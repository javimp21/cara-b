// Lógica del recomendador, sin nada de interfaz: la usan la app (navegador) y la simulación (Node).
// El estado del usuario S es un objeto JSON plano (ver fresh()); todas las funciones lo reciben
// explícitamente, así se puede ejecutar el mismo código con usuarios simulados.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Recommender = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const PER_DAY = 5;
  const NOVELTY_SCALE = .35;
  const CONTROL_P = .2;          // fracción de cartas elegidas al azar en modo evaluación
  // Cada motivo actúa solo sobre el ASPECTO del sonido al que se refiere (espacios de aspects.py):
  // "no me gusta la voz" aleja canciones con esa voz/timbre, pero no las de ritmo o estilo parecidos.
  // Sin motivo (o "no me engancha") se penaliza el sonido en general.
  const ASPECT_OF = {voice: "voice", instr: "voice", rhythm: "rhythm", style: "style", prod: "prod"};
  const ASPECT_W = {voice: 1, rhythm: 1, style: 1, prod: .5};   // producción: sin validar, pesa la mitad
  const GLOBAL_NEG = .3, ASPECT_NEG = .1, ASPECT_POS = .07, ASPECT_Z0 = .5;

  const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };
  const localDate = () => new Date().toLocaleDateString("sv-SE");   // fecha local AAAA-MM-DD

  const fresh = () => ({prefs: null, seen: [], likes: [], nopes: [], known: [], blocked: [], novelty: .15,
                        langMult: {}, today: [], day: null, log: [], round: 1});

  function langWeights(p) {
    // principal = mix%, el resto se reparte 4:3:2:1 entre los extra
    const w = {[p.primary]: p.mix / 100};
    const rest = 1 - p.mix / 100, ranks = [4, 3, 2, 1].slice(0, p.extras.length);
    const tot = ranks.reduce((a, b) => a + b, 0) || 1;
    p.extras.forEach((l, i) => w[l] = rest * ranks[i] / tot);
    if (!p.extras.length) w[p.primary] = 1;
    return w;
  }

  // opts (todos opcionales; los valores por defecto son los que usa la app):
  //   likeW      peso de los "me gusta" del usuario como positivos (las semillas pesan 1 al principio)
  //   seedDecayK las semillas pierden peso al acumular "me gusta": peso = 1 / (1 + me_gusta / K). 0 = nunca
  //   seedMin    peso mínimo de las semillas
  //   mmr        diversidad dentro de la ronda: resta mmr * (parecido con lo ya servido en la ronda)
  //   exploreP   probabilidad inicial de servir una canción al azar para explorar; decae x exploreDecay por ronda
  function create(deck, opts = {}) {
    const {likeW = 1.5, seedDecayK = 0, seedMin = 0, mmr = 0, exploreP = 0, exploreDecay = 1} = opts;
    const byId = {};
    deck.tracks.forEach(t => byId[t.id] = t);
    const seeds = deck.tracks.filter(t => t.seed);
    // similitud en un aspecto, en desviaciones típicas respecto a un par cualquiera del mazo
    const zsim = (asp, a, b) => (dot(a.a[asp], b.a[asp]) - deck.aspects[asp].mu) / deck.aspects[asp].sigma;

    // learn:false = línea base sin aprendizaje (solo el gusto declarado en las semillas)
    function score(S, t, {learn = true} = {}) {
      const seedW = learn && seedDecayK ? Math.max(seedMin, 1 / (1 + S.likes.length / seedDecayK)) : 1;
      const pos = seeds.map(x => [x, seedW]).concat(learn ? S.likes.map(l => [byId[l.id], likeW]) : []);
      const sims = pos.map(([x, w]) => [dot(t.emb, x.emb) * w, x]).sort((a, b) => b[0] - a[0]);
      const top = sims.slice(0, 3);
      const simPos = top.reduce((a, b) => a + b[0], 0) / top.length;
      let neg = 0, bonus = 0;
      if (learn) {
        for (const n of S.nopes) {
          const x = byId[n.id];
          if (!n.reasons.length || n.reasons.includes("hook")) neg = Math.max(neg, GLOBAL_NEG * dot(t.emb, x.emb));
          for (const r of n.reasons) {
            const a = ASPECT_OF[r];
            if (a) neg = Math.max(neg, ASPECT_NEG * ASPECT_W[a] * Math.max(0, zsim(a, t, x) - ASPECT_Z0));
          }
        }
        for (const l of S.likes) {   // "me gusta la voz / el ritmo..." atrae lo parecido en ESE aspecto
          const x = byId[l.id];
          for (const r of l.reasons) {
            const a = ASPECT_OF[r];
            if (a) bonus = Math.max(bonus, ASPECT_POS * ASPECT_W[a] * Math.max(0, zsim(a, t, x) - ASPECT_Z0));
          }
        }
      }
      const nov = learn ? S.novelty : .15;
      return {score: simPos - neg + bonus + NOVELTY_SCALE * nov * t.novelty, nearest: sims[0][1], simPos};
    }

    function nextTrack(S, {rng = Math.random, control = false} = {}) {
      // ni artistas ya vistos ni tus semillas (colaboraciones de una semilla aparecen en tops ajenos)
      const seenArtists = new Set(S.seen.map(id => byId[id]?.artist_id));
      seeds.forEach(t => seenArtists.add(t.artist_id));
      S.blocked.forEach(b => seenArtists.add(b.id));
      const w = langWeights(S.prefs);
      for (const l in S.langMult) if (w[l]) w[l] *= S.langMult[l];
      const pool = deck.tracks.filter(t => !t.seed && !seenArtists.has(t.artist_id) &&
        (w[t.lang] || (t.lang === "?" && S.prefs.instr)));
      if (!pool.length) return null;
      // elegir idioma para esta carta: el que más "debe" según la mezcla deseada vs. lo ya servido
      const served = {};
      S.seen.forEach(id => { const l = byId[id].lang; served[l] = (served[l] || 0) + 1; });
      const n = S.seen.length + 1;
      const avail = new Set(pool.map(t => t.lang));
      let lang = null, best = -Infinity;
      for (const l in w) if (avail.has(l)) { const debt = w[l] * n - (served[l] || 0); if (debt > best) { best = debt; lang = l; } }
      // ~1 de cada 8 cartas puede ser instrumental/dudosa si se permite
      if (S.prefs.instr && avail.has("?") && (served["?"] || 0) < n / 8 && rng() < .2) lang = "?";
      const cands = pool.filter(t => t.lang === (lang ?? pool[0].lang)).map(t => ({t, ...score(S, t)}));
      // rank = puntuación para ordenar; score se conserva intacta para el log y las métricas
      for (const c of cands) c.rank = c.score;
      if (mmr && S.today.length) {        // diversidad: penaliza lo parecido a lo ya servido en esta ronda
        const served = S.today.map(id => byId[id]);
        for (const c of cands) c.rank -= mmr * Math.max(...served.map(x => dot(c.t.emb, x.emb)));
      }
      let pick, arm = "model";
      if (control) {                      // grupo de control: al azar dentro del mismo idioma
        pick = cands[Math.floor(rng() * cands.length)]; arm = "control";
      } else if (exploreP && rng() < exploreP * Math.pow(exploreDecay, S.round - 1)) {
        pick = cands[Math.floor(rng() * cands.length)]; arm = "explore";   // exploración: al azar, pero cuenta como del sistema
      } else {
        cands.sort((a, b) => b.rank - a.rank);
        // un poco de aleatoriedad entre los 3 mejores: que no salga siempre lo mismo
        pick = cands[Math.floor(rng() * Math.min(3, cands.length))];
      }
      return {...pick, arm, scoreSeed: score(S, pick.t, {learn: false}).score};
    }

    // Registra un voto: actualiza el estado (lo que aprende el sistema) y añade una entrada al log
    // v = {kind: like | nope | known-like | known-nope | known-neutral, reasons?, block?, date?}
    function vote(S, t, v, rec = {}) {
      const reasons = v.reasons || [], date = v.date || localDate();
      let counts = true;                  // ¿gasta una de las 5 del día?
      switch (v.kind) {
        case "like":
          S.likes.push({id: t.id, reasons, date}); break;
        case "nope":
          if (v.block) S.blocked.push({id: t.artist_id, name: t.artist});
          if (reasons.includes("lang") && t.lang !== "?") S.langMult[t.lang] = (S.langMult[t.lang] ?? 1) * .6;
          if (reasons.includes("famous")) S.novelty = Math.min(.6, S.novelty + .1);
          S.nopes.push({id: t.id, reasons, date}); break;
        // "ya la conocía" no es un descubrimiento: no gasta una de las 5, el artista no vuelve y se busca algo más novedoso
        case "known-like":
          S.likes.push({id: t.id, reasons: [], known: true, date}); counts = false; break;
        case "known-nope":
          S.nopes.push({id: t.id, reasons: [], known: true, date}); counts = false; break;
        case "known-neutral":
          S.known.push({id: t.id}); counts = false; break;
        default: throw new Error("voto desconocido: " + v.kind);
      }
      if (!counts) S.novelty = Math.min(.6, S.novelty + .03);
      S.seen.push(t.id);
      if (counts) S.today.push(t.id);
      S.log.push({ts: new Date().toISOString(), round: S.round, id: t.id, kind: v.kind, reasons, arm: rec.arm ?? "model",
                  score: rec.score ?? null, scoreSeed: rec.scoreSeed ?? null, simPos: rec.simPos ?? null, lang: t.lang});
      if (counts && S.today.length >= PER_DAY) S.round++;   // la ronda se completa
    }

    return {byId, score, nextTrack, vote, zsim};
  }

  // ---------------------------------------------------------------- métricas de evaluación
  const wilson = (k, n) => {              // intervalo de confianza 95 % de una proporción
    if (!n) return [0, 1];
    const z = 1.96, p = k / n, d = 1 + z * z / n;
    const c = (p + z * z / (2 * n)) / d, h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
    return [Math.max(0, c - h), Math.min(1, c + h)];
  };
  // AUC = probabilidad de que una canción que te gustó tenga más puntuación que una que no (0.5 = azar)
  function auc(entries, key) {
    const pos = entries.filter(e => e.kind === "like" && e[key] != null).map(e => e[key]);
    const neg = entries.filter(e => e.kind === "nope" && e[key] != null).map(e => e[key]);
    if (pos.length * neg.length < 10) return null;   // con menos de 10 parejas el AUC no significa nada
    let u = 0;
    for (const p of pos) for (const q of neg) u += p > q ? 1 : p === q ? .5 : 0;
    return u / (pos.length * neg.length);
  }
  const rate = es => {
    const k = es.filter(e => e.kind === "like").length;
    return {n: es.length, likes: k, rate: es.length ? k / es.length : null, ci: wilson(k, es.length)};
  };
  // Solo cuentan los votos sobre recomendaciones nuevas (me gusta / no); "ya la conocía" se aparta.
  function metrics(log) {
    const v = log.filter(e => e.kind === "like" || e.kind === "nope");
    const byRound = {};
    v.forEach(e => (byRound[e.round] ??= []).push(e));
    const model = v.filter(e => e.arm === "model"), control = v.filter(e => e.arm === "control");
    const half = Math.floor(model.length / 2);
    return {
      votes: v.length, known: log.length - v.length, overall: rate(v),
      byArm: {model: rate(model), control: rate(control)},
      byRound: Object.keys(byRound).map(Number).sort((a, b) => a - b).map(r => ({round: r, ...rate(byRound[r])})),
      firstHalf: rate(model.slice(0, half)), secondHalf: rate(model.slice(half)),
      auc: {model: auc(v, "score"), seedOnly: auc(v, "scoreSeed"),
            modelControl: auc(control, "score"), seedOnlyControl: auc(control, "scoreSeed")},
    };
  }

  return {PER_DAY, CONTROL_P, dot, fresh, langWeights, create, metrics, wilson, auc, localDate};
});
