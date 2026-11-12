"""Check VAD against generated noise and real Piper speech; no provider calls."""
import asyncio
import audioop
import io
import json
import math
import os
import random
import runpy
import struct
import sys
import wave

from speech import Speech


async def main():
    activity_class = runpy.run_path(sys.argv[1])['AudioActivity'] if len(sys.argv) > 1 else \
        runpy.run_path(os.path.join(os.path.dirname(__file__), 'transcripts.py'))['AudioActivity']
    randomizer = random.Random(42)
    noises = {
        'silence': bytes(32000 * 3),
        'hum': b''.join(struct.pack('<h', round(4000 * math.sin(2 * math.pi * 50 * i / 16000)))
                        for i in range(48000)),
        'white_noise': b''.join(struct.pack('<h', randomizer.randint(-1000, 1000)) for _ in range(48000))}
    for name, pcm in noises.items():
        activity = activity_class()
        filtered = activity.add(pcm)
        accepted = activity.overlaps({'start': 1, 'duration': 2})
        print(json.dumps({'input': name, 'late_noise_accepted': accepted,
            'output_frames': len(filtered) // 640}), flush=True)
        assert not accepted, name

    speech = Speech()
    try:
        await speech.start()
        for language, text in [('en', 'This is a normal spoken sentence.'),
                ('ru', '\u042d\u0442\u043e \u043e\u0431\u044b\u0447\u043d\u0430\u044f \u0440\u0430\u0437\u0433\u043e\u0432\u043e\u0440\u043d\u0430\u044f \u0444\u0440\u0430\u0437\u0430.')]:
            audio = await speech.synthesize(text, language)
            with wave.open(io.BytesIO(audio)) as wav:
                pcm = audioop.ratecv(wav.readframes(wav.getnframes()), 2, 1,
                    wav.getframerate(), 16000, None)[0]
            activity = activity_class()
            activity.add(bytes(16000) + pcm + bytes(32000))
            accepted = activity.overlaps({'start': .5, 'duration': len(pcm) / 32000})
            print(json.dumps({'input': language + '_speech', 'accepted': accepted}), flush=True)
            assert accepted, language
    finally:
        await speech.close()


if __name__ == '__main__':
    asyncio.run(main())
