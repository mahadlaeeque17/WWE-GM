// Stage 3 — intersect the female master index (stage 1) with the promotion-year
// sweep (stage 2) to produce the era roster.
//
// A wrestler qualifies if she appears in the female index AND has at least one
// WWE/WCW/ECW promotion-year between 1980 and 2000.
//
// Output is deliberately compact: this payload has to come back through a tool
// response, so it is aggregated per wrestler rather than per promotion-year.

(function () {
  const female = new Map(window.__s1.rows.map((r) => [r.id, r]));

  // wrestler id -> aggregate
  const agg = new Map();

  for (const rec of window.__s2.records) {
    if (!female.has(rec.id)) continue;

    let a = agg.get(rec.id);
    if (!a) {
      const f = female.get(rec.id);
      a = {
        id: rec.id,
        name: f.name,
        born: f.birthday,
        from: f.birthplace,
        rating: f.rating,
        votes: f.votes,
        promos: {},          // promo -> {y0, y1, m, w, l, d}
        matches: 0,
        wins: 0,
        losses: 0,
        draws: 0,
        names: new Set(),
      };
      agg.set(rec.id, a);
    }

    a.names.add(rec.name);   // the name used in that promotion-year

    let p = a.promos[rec.promo];
    if (!p) p = a.promos[rec.promo] = { y0: rec.year, y1: rec.year, m: 0, w: 0, l: 0, d: 0 };
    p.y0 = Math.min(p.y0, rec.year);
    p.y1 = Math.max(p.y1, rec.year);
    p.m += rec.matches;
    p.w += rec.wins;
    p.l += rec.losses;
    p.d += rec.draws;

    a.matches += rec.matches;
    a.wins += rec.wins;
    a.losses += rec.losses;
    a.draws += rec.draws;
  }

  // Shrink the rating toward the site mean so low-vote entries stop outranking
  // heavily-voted ones. M = prior weight in votes, C = site mean.
  const M = 25, C = 6.0;

  const out = [...agg.values()].map((a) => ({
    ...a,
    names: [...a.names],
    adj: a.rating ? +(((a.votes * a.rating) + M * C) / (a.votes + M)).toFixed(2) : null,
  }));

  out.sort((x, y) => (y.votes || 0) - (x.votes || 0));

  window.__s3 = out;
  return JSON.stringify({
    qualified: out.length,
    totalFemaleIndexed: female.size,
    promotionYearRecords: window.__s2.records.length,
  });
})();
