"""User-selected transcript folders; never reads browser profiles or account data."""
import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

FOLDER = 'Call_Translator_Stennograms'


def powershell(script, folder=None, timeout=300):
    executable = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    environment=dict(os.environ)
    environment['CT_TRANSCRIPT_FOLDER']=str(folder) if folder else ''
    return subprocess.run([str(executable), '-NoProfile', '-STA', '-EncodedCommand',
        base64.b64encode(script.encode('utf-16le')).decode('ascii')], capture_output=True,
        timeout=timeout, env=environment, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)


def choose_folder(initial=None):
    script = """$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$dialog=New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description='Call Translator - transcript folder'
$dialog.ShowNewFolderButton=$true
if($env:CT_TRANSCRIPT_FOLDER){$dialog.SelectedPath=$env:CT_TRANSCRIPT_FOLDER}
try {if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){
[Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($dialog.SelectedPath)))
}} finally {$dialog.Dispose()}
"""
    result = powershell(script,initial)
    value = result.stdout.strip()
    return Path(base64.b64decode(value).decode('utf-8')) if value else None


def open_folder(root):
    # Shell can reuse a minimized Explorer window. Restore/maximize and activate
    # the exact folder window rather than only launching its process.
    powershell("""$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class FolderWindow {
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int command);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,IntPtr p);
[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
[DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a,uint b,bool attach);
}
'@
$shell=New-Object -ComObject Shell.Application
$root=$env:CT_TRANSCRIPT_FOLDER.TrimEnd('\\')
$shell.Explore($root)
for($attempt=0;$attempt -lt 60;$attempt++){
 foreach($window in @($shell.Windows())){
  try{$path=([Uri]$window.LocationURL).LocalPath.TrimEnd('\\')}catch{continue}
  if($path -ine $root){continue}
  $handle=[IntPtr]$window.HWND
  $current=[FolderWindow]::GetCurrentThreadId()
  $foreground=[FolderWindow]::GetWindowThreadProcessId([FolderWindow]::GetForegroundWindow(),[IntPtr]::Zero)
  $attached=$false
  try{
   if($current -ne $foreground){$attached=[FolderWindow]::AttachThreadInput($current,$foreground,$true)}
   [void][FolderWindow]::ShowWindow($handle,3)
   [void][FolderWindow]::BringWindowToTop($handle)
   if([FolderWindow]::SetForegroundWindow($handle)){exit 0}
  }finally{if($attached){[void][FolderWindow]::AttachThreadInput($current,$foreground,$false)}}
 }
 Start-Sleep -Milliseconds 100
}
throw 'Could not activate transcript folder window'
""",root,timeout=20)


class TranscriptFolders:
    def __init__(self, settings):
        self.settings = Path(settings)

    def root(self):
        data=json.loads(self.settings.read_text(encoding='utf-8')) if self.settings.is_file() else {}
        return Path(data['custom']) if data.get('custom') else None

    def status(self):
        root=self.root()
        return {'custom':root is not None, 'path':str(root) if root else None}

    def configure(self, folder):
        root=(folder if folder.name==FOLDER else folder/FOLDER) if folder else None
        if root:
            if not root.is_absolute():raise ValueError('Absolute folder required')
            root.mkdir(parents=True,exist_ok=True)
        self.settings.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.settings.with_suffix('.tmp')
        temporary.write_text(json.dumps({'custom':str(root) if root else None}),encoding='utf-8')
        os.replace(temporary,self.settings)
        return self.status()

    def write(self, day, filename, html):
        root=self.root()
        if root is None or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError('Invalid destination')
        if not re.fullmatch(r'CallTranslator_[A-Za-z0-9_-]+\.html',filename):raise ValueError('Invalid filename')
        if not isinstance(html,str) or not html.startswith('<!doctype html>') or len(html.encode('utf-8'))>900000:
            raise ValueError('Invalid transcript')
        root=root.resolve();folder=root/day
        folder.mkdir(parents=True,exist_ok=True)
        destination=folder/filename
        if not destination.resolve().is_relative_to(root) or destination.is_symlink():raise ValueError('Unsafe destination')
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=folder,delete=False) as stream:
                temporary=Path(stream.name);stream.write(html);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,destination)
        finally:
            if temporary is not None and temporary.exists():temporary.unlink()

    def current(self, downloaded=None):
        root=self.root()
        if root is None:
            # The extension supplies only an actual completed Chrome download.
            path=Path(downloaded or '')
            root=next((parent for parent in path.parents if parent.name==FOLDER),None)
            if root is None or not root.is_absolute():raise ValueError('Unknown downloads folder')
        if not root.is_dir():raise ValueError('Folder unavailable')
        return root

    def open(self, downloaded=None):
        open_folder(self.current(downloaded))
