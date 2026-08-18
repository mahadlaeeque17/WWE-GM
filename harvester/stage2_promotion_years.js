// Stage 2 — per-promotion, per-year win/loss records for 1980-2000.
//
// This is the backbone of roster construction. `?id=8&nr=<pid>&page=17&year=YYYY`
// returns every worker who wrestled for that promotion in that year, with their
// record. So one sweep yields BOTH:
//   - the roster and tenure (which years she appeared, and for whom)
//   - the win/loss record, already scoped to promotion and year
//
// Why not the worker search's `promotion=` filter: it only covers ACTIVE
// promotions (WCW/ECW return zero), and even for WWE it reflects current
// association rather than history — it omitted Lita, Chyna, Ivory, Moolah and
// Wendi Richter. See PLAN.md.
//
// Row format: rank | worker(link) | matches | wins | win% | losses | loss% | draws | draw%

(function () {
  const PROMOTIONS = { WWE: 1, WCW: 2, ECW: 3 };
  const YEAR_FROM = 1980;
  const YEAR_TO = 2000;
  const DELAY_MS = 700;
  const PAGE_SIZE = 100;

  window.__s2 = { done: false, fetches: 0, records: [], errors: [], emptyYears: [] };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function parseRows(html, promo, year) {
    const out = [];
    for (const tr of html.matchAll(/<tr class="TRow\d"[\s\S]*?<\/tr>/g)) {
      const row = tr[0];
      const link = row.match(/\?id=2&amp;nr=(\d+)&amp;name=([^"]+)"/);
      if (!link) continue;
      const cells = [...row.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((m) =>
        m[1].replace(/<[^>]+>/g, '').replace(/&nbsp;/g, '').trim()
      );
      const num = (i) => {
        const v = parseInt(cells[i], 10);
        return isNaN(v) ? 0 : v;
      };
      out.push({
        id: parseInt(link[1], 10),
        name: decodeURIComponent(link[2].replace(/\+/g, ' ')),
        promo: promo,
        year: year,
        matches: num(2),
        wins: num(3),
        losses: num(5),
        draws: num(7),
      });
    }
    return out;
  }

  (async () => {
    for (const [promo, pid] of Object.entries(PROMOTIONS)) {
      for (let year = YEAR_FROM; year <= YEAR_TO; year++) {
        let offset = 0;
        let total = null;

        while (total === null || offset < total) {
          try {
            const res = await fetch(
              `/?id=8&nr=${pid}&page=17&year=${year}&s=${offset}`,
              { credentials: 'include' }
            );
            const html = await res.text();
            window.__s2.fetches++;

            if (total === null) {
              const m = html.match(/total (\d+) items/);
              total = m ? parseInt(m[1], 10) : 0;
              if (!total) {
                window.__s2.emptyYears.push(`${promo} ${year}`);
                break;
              }
            }

            const rows = parseRows(html, promo, year);
            if (!rows.length) break;
            window.__s2.records.push(...rows);
          } catch (e) {
            window.__s2.errors.push(`${promo} ${year} @${offset}: ${e.message}`);
            break;
          }
          offset += PAGE_SIZE;
          await sleep(DELAY_MS);
        }
        await sleep(DELAY_MS);
      }
    }
    window.__s2.done = true;
  })();

  return 'stage2 started';
})();
