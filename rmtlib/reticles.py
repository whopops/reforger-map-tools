"""Website's calibrated legacy reticle sketches as standalone SVG assets.

Same angular geometry as shot-core.js gunReticle, reviewed 2026-10-05.
Coordinates are degrees right/down, converted to display pixels by k.
"""
from xml.sax.saxutils import escape


def drawing(g, ox=512, oy=512, k=128, selected=None):
    white = '#e8eef3'
    def x(deg): return f'{ox+deg*k:.1f}'
    def y(deg): return f'{oy+deg*k:.1f}'
    def path(d, width=1.1, colour=white):
        return f'<path d="{d}" stroke="{colour}" stroke-width="{width}" fill="none"/>'
    def chevron(dy, hw=.032, hh=.059, colour=white):
        return path(f'M{x(-hw)} {y(dy+hh)}L{x(0)} {y(dy)}L{x(hw)} {y(dy+hh)}', 1.3, colour)
    s = ''; kind = g.get('reticle')
    if kind in ('pso1', 'spp'):
        s += path(f'M{x(-1.92)} {y(0)}H{x(-.73)}M{x(.73)} {y(0)}H{x(1.92)}')
        for i in range(-10, 11):
            if i:
                s += path(f'M{x(i*.06)} {y(0)}V{y(.059 if i%5 else .118)}', .9)
        s += chevron(0, colour='#ffd43b')
        if kind == 'pso1':
            for dy in (.205, .438, .691): s += chevron(dy)
        s += path(f'M{x(0)} {y(.78 if kind=="pso1" else 1.27)}V{y(4)}')
    elif kind in ('cross', 'art2'):
        s += path(f'M{x(-3)} {y(0)}H{x(3)}M{x(0)} {y(-3)}V{y(3)}', .8, '#ffd43b')
        if kind == 'cross':
            s += path(f'M{x(-3)} {y(0)}H{x(-.37)}M{x(.37)} {y(0)}H{x(3)}M{x(0)} {y(-3)}V{y(-.34)}M{x(0)} {y(.34)}V{y(3)}', 3)
        else:
            s += path(f'M{x(-3)} {y(0)}H{x(-.76)}M{x(.76)} {y(0)}H{x(3)}M{x(0)} {y(.68)}V{y(3)}', 3)
    elif kind == 'uk59':
        s += path(f'M{x(-3)} {y(0)}H{x(-.34)}M{x(.34)} {y(0)}H{x(3)}M{x(0)} {y(-3)}V{y(-.33)}M{x(0)} {y(.49)}V{y(3)}', 1)
        s += chevron(0, .125, .18, '#ffd43b')
    elif kind == 'post':
        s += f'<path d="M{x(-.13)} {y(-4)}V{y(-.3)}L{x(0)} {y(0)}L{x(.13)} {y(-.3)}V{y(-4)}" fill="rgba(255,212,59,.25)" stroke="#ffd43b" stroke-width="1.2"/>'
    elif g.get('lines'):
        side = -1 if g.get('side') == 'left' else 1
        long, inner = (.96, 0) if kind == 'pp61' else (1.12, .85)
        centre = (g['centre']-g['axis'])/g['pxdeg']
        s += chevron(centre, .04, .06)
        s += path(f'M{x(0)} {y(centre)}V{y((g["lines"][-1][1]-g["axis"])/g["pxdeg"]+.05)}')
        if kind == 'pp61':
            for i in range(-12, 13):
                s += path(f'M{x(i*.06)} {y(centre-.21)}V{y(centre-.21-(.04 if i%5 else .08))}', .8)
        else:
            s += path(f'M{x(-.19)} {y(centre-.155)}H{x(.19)}M{x(0)} {y(centre-.155)}V{y(centre-.4)}')
        for line in g['lines']:
            distance, row = line[:2]; big = bool(line[2]) if len(line) > 2 else False
            angle = (row-g['axis'])/g['pxdeg']
            on = selected is not None and abs(angle-selected)<1e-6
            length = long if big else inner+(long-inner)/2
            colour = '#ffd43b' if on else white
            s += path(f'M{x(side*inner)} {y(angle)}H{x(side*length)}', 2 if on else 1, colour)
            if big or on:
                anchor = ' text-anchor="end"' if side < 0 else ''
                s += f'<text x="{x(side*(length+.04))}" y="{float(y(angle))+3:.1f}" fill="{colour}" font-size="9" font-family="monospace"{anchor}>{distance/100:g}</text>'
    return s


def svg(name, definition):
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><title>'+escape(name)+'</title>'+drawing(definition)+'</svg>'
