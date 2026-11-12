"""Run with uv run --frozen python -m tools.economics --help."""

import argparse
import json
from decimal import Decimal

from server.economics import Rates, scenario


def main():
    parser = argparse.ArgumentParser(description='Scenario calculator; rates must be supplied explicitly. Tokens must include all attempts and free users.')
    for name in ('connected-minutes', 'speech-fraction', 'stt-per-minute', 'input-per-million',
                 'output-per-million', 'fixed-cost', 'free-connected-minutes-each',
                 'price', 'fee-fraction', 'fee-fixed', 'refund-fraction'):
        parser.add_argument('--'+name, type=Decimal, required=True)
    for name in ('input-tokens', 'output-tokens', 'free-registration-count'):
        parser.add_argument('--'+name, type=int, required=True)
    args = vars(parser.parse_args())
    rates = Rates(*(args.pop(k) for k in ('stt_per_minute', 'input_per_million', 'output_per_million')))
    print(json.dumps(scenario(rates=rates, **args), indent=2))


if __name__ == '__main__':
    main()
