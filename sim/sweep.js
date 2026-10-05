// Barrido de parámetros del recomendador con usuarios sintéticos (mismos perfiles que simulate.js).
// Uso:  node sim/sweep.js [--runs 40] [--rounds 12]
const S = require("./simulate.js");

const NO_REPEAT = {like: Infinity, nope: Infinity, neutral: Infinity};
const CONFIGS = [
  {name: "sin repetir artistas", opts: {artistGap: NO_REPEAT}},
  {name: "repetir: me gusta 10 / no 60 / igual 30", opts: {}},
  {name: "repetir pronto: 5 / 30 / 15", opts: {artistGap: {like: 5, nope: 30, neutral: 15}}},
  {name: "repetir poco: 20 / 100 / 60", opts: {artistGap: {like: 20, nope: 100, neutral: 60}}},
  {name: "solo repiten los que gustan: 10 / ∞ / ∞", opts: {artistGap: {like: 10, nope: Infinity, neutral: Infinity}}},
];
const personas = Object.keys(S.PERSONAS);
const RUNS = S.RUNS;

console.log(`${RUNS} simulaciones por celda, ${S.ROUNDS} rondas. Tasa de «me gusta» (modelo, usuario que da motivos).\n`);
console.log(`| Configuración | ${personas.join(" | ")} | Media de perfiles | Media rondas 1-3 | Media rondas 4-6 |`);
console.log(`|---|${personas.map(() => "---").join("|")}|---|---|---|`);
const out = [];
for (const cfg of CONFIGS) {
  const RR = S.create(S.deck, cfg.opts);
  const cells = personas.map(p => {
    const tot = [], b1 = [], b2 = [];
    for (let k = 0; k < RUNS; k++) {
      const v = S.run(p, "modelo", 1000 * k + 17, false, true, RR);
      const m = f => { const w = v.filter(f); return w.length ? S.mean(w.map(x => +x.liked)) : null; };
      tot.push(m(() => true)); b1.push(m(x => x.round <= 3)); b2.push(m(x => x.round >= 4 && x.round <= 6));
    }
    return {tot: S.mean(tot), ci: S.ci95(tot), b1: S.mean(b1), b2: S.mean(b2)};
  });
  const avg = f => S.mean(cells.map(f));
  out.push({name: cfg.name, cells, total: avg(c => c.tot), b1: avg(c => c.b1), b2: avg(c => c.b2)});
  console.log(`| ${cfg.name} | ${cells.map(c => `${S.pct(c.tot)} (±${(c.ci * 100).toFixed(0)}; 1-3: ${S.pct(c.b1)})`).join(" | ")} | **${S.pct(avg(c => c.tot))}** | ${S.pct(avg(c => c.b1))} | ${S.pct(avg(c => c.b2))} |`);
}
require("fs").writeFileSync(require("path").join(__dirname, "sweep.json"), JSON.stringify(out, null, 1));
