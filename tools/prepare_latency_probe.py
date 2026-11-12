"""Prepare fixed synthetic prefix fixtures and measure warm local synthesis."""
import audioop
import base64
import io
import json
import time
import wave
from pathlib import Path
from local_component.call_translator_local.engine import Engine
from local_component.call_translator_local.voices import VoiceStore


def main():
    trust=json.loads(Path('local_component/call_translator_local/catalog-trust.json').read_text(encoding='utf-8'))
    store=VoiceStore(Path('build/local-voices'),trust)
    engine=Engine()
    fixtures={}
    report={}
    try:
        for direction,voice_id,phrase in [('outgoing','ru-basic','Последняя фраза проверки: я вас хорошо слышу.'),
                                          ('incoming','uk-basic','Остання фраза перевірки: я вас добре чую.')]:
            voice,folder=store.resolve(voice_id)
            start=time.perf_counter();engine.smoke(voice,folder)
            warmup=round((time.perf_counter()-start)*1000)
            start=time.perf_counter();audio=engine.render(voice,folder,phrase)
            elapsed=round((time.perf_counter()-start)*1000)
            Path(f'build/latency-fixture-{voice["language"]}.wav').write_bytes(audio)
            with wave.open(io.BytesIO(audio),'rb') as wav:
                pcm,_=audioop.ratecv(wav.readframes(wav.getnframes()),2,1,wav.getframerate(),16000,None)
            fixtures[direction]=base64.b64encode(pcm).decode('ascii')
            report[direction]={'warmup_ms':warmup,'warm_tts_ms':elapsed,'audio_ms':len(pcm)//32}
    finally:
        engine.close()
    Path('build/stream-resilience-stdin.py').write_text('FIXTURES = '+repr(fixtures)+'\n'+Path('tools/probe_stream_resilience.py').read_text(encoding='utf-8'),encoding='utf-8')
    Path('build/local-latency-probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
