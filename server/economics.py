"""Internal usage hooks and explicit-rate scenario calculations.

No prices are hardcoded or approved here. Record STT after actual successful
provider sends, and each translation attempt's returned usage independently.
Reasoning tokens are a subset of output tokens, never billed twice.
"""

import time
from dataclasses import dataclass
from decimal import Decimal

from .accounting import Accounting


def nonnegative_int(value):
    if type(value) is not int or value < 0:
        raise ValueError('Expected a nonnegative integer')
    return value


@dataclass(frozen=True)
class Rates:
    stt_per_minute: Decimal
    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self):
        for value in (self.stt_per_minute, self.input_per_million, self.output_per_million):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError('Explicit finite nonnegative Decimal rates required')


class Usage:
    def __init__(self, store: Accounting):
        self.store = store

    def _record(self, table, event_id, values):
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
            raise ValueError('Stable provider event ID required')
        # Table names are hardcoded internally; never derived from request data.
        with self.store.transaction():
            previous = self.store.db.execute(f'SELECT * FROM {table} WHERE event_id=?', (event_id,)).fetchone()
            if previous:
                if previous[1:-1] != tuple(values):
                    raise ValueError('Conflicting usage event')
                return False
            args = (event_id, *values, int(time.time()))
            self.store.db.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in args)})", args)
            return True

    def stt_sent(self, event_id: str, call: str, direction: str, audio_ms: int):
        if direction not in ('incoming', 'outgoing'):
            raise ValueError('Invalid direction')
        return self._record('stt_usage', event_id, (call, direction, nonnegative_int(audio_ms)))

    def translation(self, event_id: str, call: str, usage: dict, *, retry=False):
        incoming = nonnegative_int(usage['prompt_tokens'])
        outgoing = nonnegative_int(usage['completion_tokens'])
        reasoning = nonnegative_int(usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0))
        if reasoning > outgoing or type(retry) is not bool:
            raise ValueError('Invalid reasoning or retry usage')
        return self._record('translation_usage', event_id, (call, incoming, outgoing, reasoning, int(retry)))

    def report(self, rates: Rates):
        stt = dict(self.store.db.execute('SELECT direction, sum(audio_ms) FROM stt_usage GROUP BY direction').fetchall())
        tokens = self.store.db.execute('SELECT coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0), coalesce(sum(reasoning_tokens),0), coalesce(sum(retry),0) FROM translation_usage').fetchone()
        speech = self.store.db.execute('SELECT coalesce(sum(speech_ms),0) FROM calls').fetchone()[0]
        api_cost = (Decimal(sum(stt.values()))/60000*rates.stt_per_minute
                    + Decimal(tokens[0])/1000000*rates.input_per_million
                    + Decimal(tokens[1])/1000000*rates.output_per_million)
        return {'speech_ms': speech, 'stt_incoming_ms': stt.get('incoming', 0),
                'stt_outgoing_ms': stt.get('outgoing', 0), 'input_tokens': tokens[0],
                'output_tokens': tokens[1], 'reasoning_tokens': tokens[2], 'retry_attempts': tokens[3],
                'estimated_api_cost_usd': str(api_cost),
                'estimated_api_cost_per_speech_minute_usd': str(api_cost*60000/speech) if speech else None,
                'measurement_complete': False}


def scenario(*, connected_minutes: Decimal, speech_fraction: Decimal, rates: Rates,
             input_tokens: int, output_tokens: int, fixed_cost: Decimal,
             free_registration_count: int, free_connected_minutes_each: Decimal,
             price: Decimal, fee_fraction: Decimal, fee_fixed: Decimal,
             refund_fraction: Decimal):
    decimals = (connected_minutes, speech_fraction, fixed_cost, free_connected_minutes_each,
                price, fee_fraction, fee_fixed, refund_fraction)
    if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in decimals):
        raise ValueError('Finite nonnegative Decimal inputs required')
    if speech_fraction > 1 or fee_fraction > 1 or refund_fraction > 1:
        raise ValueError('Fractions must be in [0,1]')
    nonnegative_int(input_tokens)
    nonnegative_int(output_tokens)
    nonnegative_int(free_registration_count)
    # Both streams consume STT, even while the customer's silence is free.
    stt_minutes = 2*(connected_minutes+free_registration_count*free_connected_minutes_each)
    api = stt_minutes*rates.stt_per_minute + Decimal(input_tokens)/1000000*rates.input_per_million + Decimal(output_tokens)/1000000*rates.output_per_million
    net = price*(1-refund_fraction)*(1-fee_fraction)-fee_fixed
    return {'source': 'scenario_not_measurement', 'speech_minutes': str(connected_minutes*speech_fraction),
            'stt_minutes': str(stt_minutes), 'estimated_api_cost_usd': str(api),
            'net_revenue_usd': str(net), 'margin_after_fixed_usd': str(net-api-fixed_cost)}
