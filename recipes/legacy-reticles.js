// Preserved website reticle geometry; angular inputs in degrees. Reviewed 2026-10-05.
function gunReticle(g, ox, oy, k, sel) {
    const W1 = '#e8eef3', P = (d, w = 1.1, c = W1) => `<path d="${d}" stroke="${c}" stroke-width="${w}" fill="none"/>`;
    const X = d => (ox + d * k).toFixed(1), Y = d => (oy + d * k).toFixed(1); // + = right / down
    const chev = (dy, hw = 0.032, hh = 0.059, c = W1) => P(`M${X(-hw)} ${Y(dy + hh)}L${X(0)} ${Y(dy)}L${X(hw)} ${Y(dy + hh)}`, 1.3, c);
    let s = '';
    if (g.reticle === 'pso1' || g.reticle === 'spp') {
      // the side scale: a tick every thousandth (0.06°) to 10 each side, every fifth long; lines beyond; the chevron
      s += P(`M${X(-1.92)} ${Y(0)}H${X(-0.73)}M${X(0.73)} ${Y(0)}H${X(1.92)}`);
      for (let i = -10; i <= 10; i++) if (i) s += P(`M${X(i * 0.06)} ${Y(0)}V${Y(i % 5 ? 0.059 : 0.118)}`, 0.9);
      s += chev(0, 0.032, 0.059, '#ffd43b');
      if (g.reticle === 'pso1') [0.205, 0.438, 0.691].forEach(d => s += chev(d));
      s += P(`M${X(0)} ${Y(g.reticle === 'pso1' ? 0.78 : 1.27)}V${Y(4)}`);
    } else if (g.reticle === 'cross') {
      s += P(`M${X(-3)} ${Y(0)}H${X(3)}M${X(0)} ${Y(-3)}V${Y(3)}`, 0.8, '#ffd43b');
      s += P(`M${X(-3)} ${Y(0)}H${X(-0.37)}M${X(0.37)} ${Y(0)}H${X(3)}M${X(0)} ${Y(-3)}V${Y(-0.34)}M${X(0)} ${Y(0.34)}V${Y(3)}`, 3);
    } else if (g.reticle === 'art2') {
      s += P(`M${X(-3)} ${Y(0)}H${X(3)}M${X(0)} ${Y(-3)}V${Y(3)}`, 0.8, '#ffd43b');
      s += P(`M${X(-3)} ${Y(0)}H${X(-0.76)}M${X(0.76)} ${Y(0)}H${X(3)}M${X(0)} ${Y(0.68)}V${Y(3)}`, 3);
    } else if (g.reticle === 'uk59') {
      s += P(`M${X(-3)} ${Y(0)}H${X(-0.34)}M${X(0.34)} ${Y(0)}H${X(3)}M${X(0)} ${Y(-3)}V${Y(-0.33)}M${X(0)} ${Y(0.49)}V${Y(3)}`, 1);
      s += chev(0, 0.125, 0.18, '#ffd43b');
    } else if (g.reticle === 'post') {
      // the 1P29's post, coming down from the top to a point: the point is the aim
      s += `<path d="M${X(-0.13)} ${Y(-4)}V${Y(-0.3)}L${X(0)} ${Y(0)}L${X(0.13)} ${Y(-0.3)}V${Y(-4)}" fill="rgba(255,212,59,.25)" stroke="#ffd43b" stroke-width="1.2"/>`;
    } else if (g.lines) {
      // range lines below the aim mark (PP-61: KPVT left, PKT right; LAV-25: HE left, AP right), the chosen one in yellow,
      // labelled in hundreds of metres
      const sx = g.side === 'left' ? -1 : 1;
      // (the aim mark and the scale above it sit at the texture's centre, which needn't be the bore's row)
      const long = g.reticle === 'pp61' ? 0.96 : 1.12, inner = g.reticle === 'pp61' ? 0 : 0.85, c = (g.centre - g.axis) / g.pxdeg;
      s += chev(c, 0.04, 0.06);
      s += P(`M${X(0)} ${Y(c)}V${Y((g.lines.at(-1)[1] - g.axis) / g.pxdeg + 0.05)}`);
      if (g.reticle === 'pp61') for (let i = -12; i <= 12; i++) s += P(`M${X(i * 0.06)} ${Y(c - 0.21)}V${Y(c - 0.21 - (i % 5 ? 0.04 : 0.08))}`, 0.8);
      else s += P(`M${X(-0.19)} ${Y(c - 0.155)}H${X(0.19)}M${X(0)} ${Y(c - 0.155)}V${Y(c - 0.4)}`);
      g.lines.forEach(([R, row, big]) => {
        const a = (row - g.axis) / g.pxdeg, on = Math.abs(a - sel) < 1e-6;
        const len = big ? long : inner + (long - inner) / 2;
        s += P(`M${X(sx * inner)} ${Y(a)}H${X(sx * len)}`, on ? 2 : 1, on ? '#ffd43b' : W1);
        if (big || on) s += `<text x="${X(sx * (len + 0.04))}" y="${(+Y(a) + 3).toFixed(1)}" fill="${on ? '#ffd43b' : W1}" font-size="9" font-family="var(--mono)"${sx < 0 ? ' text-anchor="end"' : ''}>${R / 100}</text>`;
      });
    }
    return s;
  }
