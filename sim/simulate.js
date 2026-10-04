// Simulación con usuarios sintéticos: ¿aprende de verdad el recomendador?
//
// Cada usuario tiene un gusto conocido: le gustan las canciones cuyos géneros de Deezer encajan con
// su perfil (probabilidad alta) y rara vez el resto (probabilidad baja). Los géneros son metadatos
// externos al audio, así que el gusto NO está definido con los mismos vectores que usa el sistema
// (evita una prueba circular). Se ejecuta el mismo código que la app (cache/recommender.js).
//
// Uso:  node sim/simulate.js [--runs 200] [--rounds 12]
const fs = require("fs");
const path = require("path");
const Rec = require("../cache/recommender.js");

const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? +process.argv[i + 1] : d; };
const RUNS = arg("runs", 200), ROUNDS = arg("rounds", 12);
const P_MATCH = .85, P_OTHER = .12;                       // probabilidad de "me gusta" si encaja / si no

const deck = JSON.parse(fs.readFileSync(path.join(__dirname, "../cache/deck.json"), "utf8"));
const genres = JSON.parse(fs.readFileSync(path.join(__dirname, "../cache/genres.json"), "utf8"));
const R = Rec.create(deck);

// match(t): ¿encaja la canción con el gusto?  reason: motivo que daría el usuario si le dice que no
const GENRES = (...names) => t => names.some(x => genres[t.id].genres.includes(x));
const PERSONAS = {
  "rock / indie":         {match: GENRES("Rock", "Indie Rock", "Alternativo", "Indie Rock/Rock pop"), reason: "style"},
  "latino / flamenco":    {match: GENRES("Latino", "Pop latino", "Flamenco", "Rap/Hip Hop"), reason: "style"},
  "pop indie / electro":  {match: GENRES("Pop Indie", "Electro", "Singer & Songwriter"), reason: "style"},
  // gusto por el tempo (BPM de librosa, no de los vectores del recomendador): prueba el mecanismo de motivos
  "ritmo rápido (≥125 BPM)": {match: t => t.bpm >= 125, reason: "rhythm"},
};

// generador pseudoaleatorio con semilla (resultados reproducibles)
const rng = seed => () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };

const stateFor = () => { const S = Rec.fresh(); S.prefs = {primary: "es", extras: [], mix: 100, instr: false}; S.day = "sim"; return S; };

// estrategias de recomendación
const STRATEGIES = {
  // el sistema completo, tal cual lo usa la app
  modelo: (S, r) => R.nextTrack(S, {rng: r}),
  "modelo (sin dar motivos)": (S, r) => R.nextTrack(S, {rng: r}),
  // mismo sistema pero sin aprender de los votos (solo el gusto de partida): línea base "sin aprendizaje"
  "sin aprender": (S, r) => R.nextTrack({...S, likes: [], nopes: [], novelty: .15, langMult: {}}, {rng: r}),
  // al azar dentro del idioma: línea base mínima
  azar: (S, r) => R.nextTrack(S, {rng: r, control: true}),
};

function run(persona, strategy, seed, mixedControl = false, giveReasons = true) {
  const likes = PERSONAS[persona].match, why = PERSONAS[persona].reason, r = rng(seed), S = stateFor(), votes = [];
  for (let round = 1; round <= ROUNDS; round++) {
    S.today = [];
    for (let i = 0; i < Rec.PER_DAY; i++) {
      let rec = mixedControl && r() < Rec.CONTROL_P ? R.nextTrack(S, {rng: r, control: true}) : STRATEGIES[strategy](S, r);
      if (!rec) return votes;
      if (strategy === "sin aprender" || strategy === "azar") rec = {...rec, arm: strategy === "azar" ? "control" : "model"};
      const match = likes(rec.t);
      const liked = r() < (match ? P_MATCH : P_OTHER);
      // si el usuario sabe decir por qué, dice el motivo cuando rechaza algo que no encaja con su gusto
      R.vote(S, rec.t, {kind: liked ? "like" : "nope", reasons: !liked && !match && giveReasons ? [why] : []}, rec);
      votes.push({round, liked, match});
    }
  }
  return votes;
}

const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const ci95 = a => { const m = mean(a), sd = Math.sqrt(a.reduce((x, y) => x + (y - m) ** 2, 0) / (a.length - 1)); return 1.96 * sd / Math.sqrt(a.length); };
const pct = x => (x * 100).toFixed(0) + "%";
const BLOCKS = [[1, 3], [4, 6], [7, 9], [10, 12]].filter(([a]) => a <= ROUNDS);

const nonSeed = deck.tracks.filter(t => !t.seed && t.lang === "es");
console.log(`Mazo: ${nonSeed.length} canciones en español (${new Set(nonSeed.map(t => t.artist_id)).size} artistas). ` +
  `${RUNS} simulaciones por celda, ${ROUNDS} rondas de ${Rec.PER_DAY} votos. P(me gusta | encaja) = ${P_MATCH}, P(me gusta | no encaja) = ${P_OTHER}\n`);

const results = {};
for (const persona of Object.keys(PERSONAS)) {
  const cover = nonSeed.filter(t => PERSONAS[persona].match(t)).length;
  console.log(`### Perfil «${persona}»: encaja el ${pct(cover / nonSeed.length)} del mazo (${cover} canciones)`);
  const rows = [];
  for (const strategy of Object.keys(STRATEGIES)) {
    const per = BLOCKS.map(() => []);
    const all = [];
    for (let k = 0; k < RUNS; k++) {
      const v = run(persona, strategy, 1000 * k + 17, false, strategy !== "modelo (sin dar motivos)");
      BLOCKS.forEach(([a, b], bi) => { const w = v.filter(x => x.round >= a && x.round <= b); if (w.length) per[bi].push(mean(w.map(x => +x.liked))); });
      all.push(mean(v.map(x => +x.liked)));
    }
    rows.push({strategy, per: per.map(p => p.length ? [mean(p), ci95(p)] : null), all: [mean(all), ci95(all)]});
  }
  console.log(`| Estrategia | ${BLOCKS.map(([a, b]) => `Rondas ${a}-${b}`).join(" | ")} | Total |`);
  console.log(`|---|${BLOCKS.map(() => "---").join("|")}|---|`);
  for (const r of rows) console.log(`| ${r.strategy} | ${r.per.map(p => p ? `${pct(p[0])} ±${(p[1] * 100).toFixed(0)}` : "—").join(" | ")} | ${pct(r.all[0])} ±${(r.all[1] * 100).toFixed(0)} |`);
  results[persona] = {cobertura: cover / nonSeed.length, filas: rows};

  // la evaluación de la app (modo evaluación: 1 de cada 5 al azar) sobre el log de estas simulaciones
  const logs = [];
  for (let k = 0; k < RUNS; k++) {
    const S = stateFor(), r = rng(7000 + k), likes = PERSONAS[persona].match, why = PERSONAS[persona].reason;
    for (let round = 1; round <= ROUNDS; round++) {
      S.today = [];
      for (let i = 0; i < Rec.PER_DAY; i++) {
        const rec = R.nextTrack(S, {rng: r, control: r() < Rec.CONTROL_P}); if (!rec) break;
        const match = likes(rec.t), liked = r() < (match ? P_MATCH : P_OTHER);
        R.vote(S, rec.t, {kind: liked ? "like" : "nope", reasons: !liked && !match ? [why] : []}, rec);
      }
    }
    logs.push(...S.log);
  }
  const m = Rec.metrics(logs);
  console.log(`\nMétricas de la pestaña «Evaluación» sobre estas simulaciones (modo evaluación activado):`);
  console.log(`- Aciertos: modelo ${pct(m.byArm.model.rate)} (${m.byArm.model.n} votos) vs. control al azar ${pct(m.byArm.control.rate)} (${m.byArm.control.n} votos)`);
  console.log(`- AUC solo en las de control (sin sesgo de selección): con aprendizaje ${m.auc.modelControl.toFixed(2)} vs. sin aprender ${m.auc.seedOnlyControl.toFixed(2)}\n`);
  results[persona].evaluacion = {modelo: m.byArm.model.rate, control: m.byArm.control.rate, aucControl: m.auc.modelControl, aucSinAprender: m.auc.seedOnlyControl};
}
fs.writeFileSync(path.join(__dirname, "results.json"), JSON.stringify({runs: RUNS, rounds: ROUNDS, results}, null, 1));
