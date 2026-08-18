// Stage 1 — master index of every female wrestler in the cagematch DB.
//
// Runs INSIDE the cagematch.net page context (paste via browser javascript_tool).
// This matters: cagematch sits behind a Sucuri WAF that 307s scripted requests
// (curl / server-side fetch) with no body. An in-page fetch() inherits the
// browser's challenge cookie and gets full HTML back.
//
// Pacing is deliberate — ~700ms between requests. This is a hobbyist site run by
// one person. Harvest once, cache to disk, never re-hit for a re-parse.

(function () {
  const PAGE_SIZE = 100;
  const DELAY_MS = 700;

  window.__s1 = { done: false, pages: 0, rows: [], errors: [] };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Each result row: rank | gimmick(link) | birthday | birthplace | height | weight | promotion | rating | votes
  function parseRows(html) {
    const out = [];
    for (const tr of html.matchAll(/<tr class="TRow\d"[\s\S]*?<\/tr>/g)) {
      const row = tr[0];
      const link = row.match(/\?id=2&amp;nr=(\d+)&amp;gimmick=([^"]+)"/);
      if (!link) continue;
      const cells = [...row.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((m) =>
        m[1].replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim()
      );
      out.push({
        id: parseInt(link[1], 10),
        name: decodeURIComponent(link[2].replace(/\+/g, ' ')),
        birthday: cells[2] || null,
        birthplace: cells[3] || null,
        height_cm: cells[4] ? parseInt(cells[4], 10) || null : null,
        weight_kg: cells[5] ? parseInt(cells[5], 10) || null : null,
        rating: cells[7] ? parseFloat(cells[7]) || null : null,
        votes: cells[8] ? parseInt(cells[8], 10) || null : null,
      });
    }
    return out;
  }

  (async () => {
    let offset = 0;
    let total = null;

    while (total === null || offset < total) {
      try {
        const res = await fetch(`/?id=2&view=workers&gender=f&s=${offset}`, {
          credentials: 'include',
        });
        const html = await res.text();

        if (total === null) {
          const m = html.match(/total (\d+) items/);
          total = m ? parseInt(m[1], 10) : 0;
          window.__s1.total = total;
        }

        const rows = parseRows(html);
        if (!rows.length) break; // ran off the end
        window.__s1.rows.push(...rows);
        window.__s1.pages++;
      } catch (e) {
        window.__s1.errors.push(`offset ${offset}: ${e.message}`);
      }

      offset += PAGE_SIZE;
      await sleep(DELAY_MS);
    }

    // de-dupe defensively; cagematch can repeat a worker across sort boundaries
    const seen = new Set();
    window.__s1.rows = window.__s1.rows.filter((r) =>
      seen.has(r.id) ? false : (seen.add(r.id), true)
    );
    window.__s1.done = true;
  })();

  return 'stage1 started';
})();
