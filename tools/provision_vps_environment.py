"""Provision only new SaaS settings over verified SSH; never copy an env file."""

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from server.config import Settings

REMOTE = r'''
import json, os
from pathlib import Path
values=json.load(__import__('sys').stdin)
expected={'CT_PUBLIC_URL','CT_HOST','CT_PORT','CT_DATABASE','CT_VOICE_CATALOG','CT_DOWNLOAD_ROOT','CT_EXPERIMENTAL_AUDIO','CT_GOOGLE_CLIENT_ID','CT_GOOGLE_CLIENT_SECRET','CT_DEEPGRAM_KEY','CT_GROQ_KEY'}
if set(values)!=expected: raise SystemExit('Unexpected configuration fields')
path=Path('/etc/call-translator-saas.env')
if path.exists(): raise SystemExit('Existing SaaS environment must be reviewed first')
lines=[]
for key,value in values.items():
    if not isinstance(value,str) or any(ord(char)<32 for char in value): raise SystemExit('Invalid configuration value')
    lines.append(key+'="'+value.replace('\\','\\\\').replace('"','\\"')+'"')
fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w',encoding='utf-8') as stream: stream.write('\n'.join(lines)+'\n')
print('{"server_environment_created":true,"local_env_file_copied":false}')
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key',type=Path,required=True)
    parser.add_argument('--target',required=True)
    args=parser.parse_args()
    settings=Settings.from_env()
    if not all((settings.google_client_id,settings.google_client_secret,settings.deepgram_key,settings.groq_key)):
        raise SystemExit('New SaaS provider/Google settings are incomplete')
    base='/home/projects/call-translator-saas'
    values={'CT_PUBLIC_URL':'https://ppsbot.pp.ua/call-translator-saas','CT_HOST':'127.0.0.1','CT_PORT':'5086',
        'CT_DATABASE':base+'/shared/accounts.sqlite3','CT_VOICE_CATALOG':base+'/current/catalog/voices.signed.json',
        'CT_DOWNLOAD_ROOT':base+'/current/downloads','CT_EXPERIMENTAL_AUDIO':'1',
        'CT_GOOGLE_CLIENT_ID':settings.google_client_id,'CT_GOOGLE_CLIENT_SECRET':settings.google_client_secret,
        'CT_DEEPGRAM_KEY':settings.deepgram_key,'CT_GROQ_KEY':settings.groq_key}
    command=f'UV_CACHE_DIR={base}/tools/uv-cache UV_PYTHON_INSTALL_DIR={base}/tools/python {base}/tools/uv run --no-project --python 3.11.9 python -c '+shlex.quote(REMOTE)
    result=subprocess.run([str(Path('.tools/deploy-tools/plink.exe').resolve()),'-batch','-ssh','-i',str(args.key),args.target,command],
        input=json.dumps(values).encode(),capture_output=True,timeout=240)
    if result.returncode: raise SystemExit('Server environment provisioning failed; sensitive output suppressed')
    print(json.dumps(json.loads(result.stdout)))


if __name__=='__main__': main()
