"""Check the installed SaaS host with its normal runtime and voice folders."""
import json
import os
import struct
import subprocess
import winreg
from pathlib import Path

def main():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Google\Chrome\NativeMessagingHosts\org.call_translator.saas.local') as key:
        manifest_path=Path(winreg.QueryValueEx(key,'')[0])
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    executable=manifest_path.parent/manifest['path']
    allowed={'SYSTEMROOT','WINDIR','TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE','COMSPEC','PATH','PATHEXT'}
    environment={key:value for key,value in os.environ.items() if key.upper() in allowed}
    body=json.dumps({'id':1,'type':'status'}).encode()
    result=subprocess.run([str(executable)],input=struct.pack('<I',len(body))+body,capture_output=True,env=environment,timeout=120)
    report={'exit_code':result.returncode,'component_replied':False}
    if len(result.stdout)>=4:
        size=struct.unpack('<I',result.stdout[:4])[0]
        if size==len(result.stdout)-4:
            response=json.loads(result.stdout[4:])
            report.update(component_replied=response.get('protocol')==1,ready=response.get('ready'),
                          reason=response.get('reason'),error_code=response.get('error'),voice_count=len(response.get('voices',[])))
    if result.returncode:
        stderr=result.stderr.decode('utf-8',errors='replace')
        report['runtime_launch_failed']='could not run program' in stderr or 'project execution failed' in stderr
    print(json.dumps(report))

if __name__=='__main__':
    try:main()
    except Exception as error:print(json.dumps({'diagnostic_failed':type(error).__name__}))
