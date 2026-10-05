"""Browse installed weapon/vehicle/ammunition prefabs and measure custom projectile flight.

scan and inspect read addon files without starting the game. run loads selected mod dependencies,
records flights with the existing RMT_FireTest entity and saves a separate dataset.
"""
import argparse
from rmtlib import ballistics, events
from rmtlib.steam import Install


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cmd', choices=('scan', 'inspect', 'run'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--workbench')
    parser.add_argument('--resource')
    parser.add_argument('--addon')
    parser.add_argument('--weapon')
    parser.add_argument('--weapon-addon')
    parser.add_argument('--name', default='custom-round')
    parser.add_argument('--coefficient', type=float, default=1)
    parser.add_argument('--duration', type=float, default=10)
    parser.add_argument('--height', type=float, default=5000)
    parser.add_argument('--world', default='EmptyEden')
    parser.add_argument('--calm-only', action='store_true')
    args = parser.parse_args(argv)
    catalog = ballistics.Catalog(Install(args.workbench))
    records = catalog.scan()
    if args.cmd == 'scan':
        ballistics.write_json(args.output, records)
        events.emit('result', ballisticsCatalog=args.output)
        print(f'{len(records)} prefabs -> {args.output}')
    else:
        if not args.resource:
            parser.error('inspect/run needs --resource')
        if args.cmd == 'inspect':
            report = catalog.inspect(args.resource, args.addon)
            ballistics.write_json(args.output, report)
            events.emit('result', ballisticsInspection=args.output)
            print(f'Found {len(report["projectiles"])} projectile candidates; details: {args.output}')
        else:
            ballistics.capture(catalog, args.resource, args.addon, args.weapon, args.weapon_addon,
                args.name, args.output, args.duration, args.coefficient, not args.calm_only, args.world, args.height)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
