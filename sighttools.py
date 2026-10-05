"""Discover optics/iron sights, extract reticles and export calibrated website sketches."""
import argparse
import json
from pathlib import Path
from rmtlib import sights, events
from rmtlib.ballistics import Catalog, write_json
from rmtlib.steam import Install


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('scan', 'inspect', 'export'))
    p.add_argument('--output', required=True)
    p.add_argument('--workbench')
    p.add_argument('--resource')
    p.add_argument('--addon')
    p.add_argument('--spec', help='Saved calibration JSON (export does not require game/Tools)')
    args = p.parse_args(argv)
    if args.command == 'export':
        if not args.spec:
            p.error('export requires --spec')
        spec = json.loads(Path(args.spec).read_text(encoding='utf8'))
        # A saved package can be re-exported after moving it.
        if spec.get('image') and not Path(spec['image']).is_absolute():
            spec['image'] = str(Path(args.spec).resolve().parent/spec['image'])
        dest = sights.export(spec, args.output)
        events.emit('result', sightExport=dest)
    else:
        catalog = Catalog(Install(args.workbench)); catalog.scan()
        if args.command == 'scan':
            report = sights.discover(catalog); write_json(args.output, report)
            events.emit('result', sightCatalog=args.output)
            print(f'{len(report["records"])} sight-bearing prefabs; {len(report["warnings"])} source warnings')
        else:
            if not args.resource:
                p.error('inspect requires --resource')
            report = sights.extract(catalog, args.resource, args.addon, args.output)
            events.emit('result', sightInspection=str(Path(args.output)/'inspection.json'))
            print(f'{len(report["sights"])} sight components extracted')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
