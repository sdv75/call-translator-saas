"""Development stdio client. Child receives no OAuth/provider credentials."""

import asyncio
import base64
import json
import os
import struct
import sys
import time
from pathlib import Path


class NativeProbeClient:
    def __init__(self):
        self.process=None;self.identifier=0;self.lock=asyncio.Lock();self.timings=[]

    async def start(self,voice_root):
        environment={key:value for key,value in os.environ.items() if key in ('SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA')}
        environment['PATH']='';environment['PYTHONUTF8']='1';environment['CT_LOCAL_VOICE_ROOT']=str(voice_root.resolve())
        self.process=await asyncio.create_subprocess_exec(sys.executable,'-m','local_component.call_translator_local',
            cwd=Path(__file__).resolve().parents[1],env=environment,stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)

    async def request(self,command,**payload):
        async with self.lock:
            started=time.perf_counter()
            self.identifier+=1;identifier=self.identifier
            body=json.dumps({'id':identifier,'type':command,**payload}).encode('utf-8')
            self.process.stdin.write(struct.pack('<I',len(body))+body);await self.process.stdin.drain()
            chunks=[]
            async with asyncio.timeout(180):
                while True:
                    size=struct.unpack('<I',await self.process.stdout.readexactly(4))[0]
                    if not 0<size<=1024*1024:raise ValueError('Invalid native frame size')
                    message=json.loads(await self.process.stdout.readexactly(size))
                    if message.get('id')!=identifier or message.get('error'):raise ValueError('Native command failed')
                    if message.get('type')=='audio-chunk':
                        if message.get('index')!=len(chunks):raise ValueError('Invalid native audio order')
                        chunks.append(message['data']);continue
                    if message.get('type')=='audio-end':
                        data=base64.b64decode(''.join(chunks),validate=True)
                        if len(data)!=message['bytes'] or len(chunks)!=message['chunks']:raise ValueError('Native WAV mismatch')
                        self.timings.append({'command':command,'seconds':round(time.perf_counter()-started,3)})
                        return data
                    self.timings.append({'command':command,'seconds':round(time.perf_counter()-started,3)})
                    return message

    async def close(self):
        if not self.process:return
        try:
            self.process.stdin.close()
            await asyncio.wait_for(self.process.wait(),timeout=10)
        except Exception:
            if self.process.returncode is None:self.process.kill();await self.process.wait()
