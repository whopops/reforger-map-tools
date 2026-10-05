"""Produce/audit arma-map inputs. --site is the application folder containing server.py.

Exports stay in --output for review; this command does not overwrite the website.
"""
import argparse
import json
from pathlib import Path
from rmtlib import events, webdata
from rmtlib.ballistics import Catalog, write_json
from rmtlib.steam import Install


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('audit', 'mortar', 'mortar-plan', 'blast', 'barrel', 'construction', 'recipes'))
    p.add_argument('--output', required=True)
    p.add_argument('--site')
    p.add_argument('--input', help='Blast summary.json or barrel run folder')
    p.add_argument('--workbench')
    args = p.parse_args(argv)
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    if args.command == 'audit':
        if not args.site:
            p.error('audit requires --site')
        report = webdata.inventory(args.site); write_json(out/'website-audit.json', report)
        events.emit('result', websiteAudit=str(out/'website-audit.json'))
        for row in report['inputs']:
            print(f'{row["name"]}: {row["files"]} files; {row["gui"]}')
        if report['unknown'] or any(not r['producerPresent'] for r in report['inputs']):
            print('Unknown files / missing producers:', report['unknown'])
            return 1
    elif args.command in ('mortar', 'mortar-plan', 'construction'):
        catalog = Catalog(Install(args.workbench)); catalog.scan()
        if args.command == 'construction':
            write_json(out/'construction-registry.json', webdata.construction(catalog))
        else:
            webdata.mortar(catalog, out, launch=args.command == 'mortar')
    elif args.command == 'recipes':
        webdata.recipes(out)
    else:
        if not args.input:
            p.error('blast/barrel requires --input')
        doc = webdata.blast(json.loads(Path(args.input).read_text(encoding='utf8'))) if args.command == 'blast' else webdata.barrel(args.input)
        write_json(out/(args.command+'-calibration.json'), doc)
    events.emit('result', websiteData=str(out.resolve()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
