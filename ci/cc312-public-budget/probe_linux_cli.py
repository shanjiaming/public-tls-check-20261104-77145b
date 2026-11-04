#!/usr/bin/env python3
"""Run pinned Linux CC only against a loopback Messages stub in an offline netns.

No provider endpoint or credential is used. This observes the actual binary's
max_tokens field for the three bounded profiles; it is not model capacity or
benchmark evidence. Invoke inside a fresh `unshare --net` namespace with lo up.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time

CC_SHA='4f4178ce41d83e23341ebfbaecdbcf8ea6bf7baea0690025abe49eeec3a5d01d'
CC_BYTES=293592432
MODEL='Qwen3.8-Flash-Next'


def hash_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while part:=stream.read(1024*1024):digest.update(part)
    return digest.hexdigest()


def verify_offline():
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('Linux x86_64 required')
    # No non-loopback interface may be up; routes must not escape this netns.
    # Query the CURRENT network namespace through the kernel socket API.
    # A pre-existing sysfs mount may still reflect its original mount netns.
    interfaces=[name for _index,name in socket.if_nameindex() if name!='lo']
    if interfaces:
        raise ValueError('fresh loopback-only network namespace required')
    for path in ('/proc/net/route','/proc/net/ipv6_route'):
        if not Path(path).is_file():raise ValueError('route state unavailable')
    if len(Path('/proc/net/route').read_text().splitlines())>1:
        raise ValueError('non-loopback route detected')


class Stub(ThreadingHTTPServer):
    def __init__(self):
        self.requests=[]
        self.guard=threading.Lock()
        super().__init__(('127.0.0.1',0),Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<2_000_000:
            self.send_error(413);return
        raw=self.rfile.read(size)
        body=json.loads(raw)
        if self.path.split('?')[0]=='/v1/messages/count_tokens':
            payload=json.dumps({'input_tokens':128}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
        if self.path.split('?')[0]!='/v1/messages':
            self.send_error(404);return
        with self.server.guard:
            self.server.requests.append({'model':body.get('model'),'max_tokens':body.get('max_tokens'),
                'stream':body.get('stream'),'body_bytes':len(raw),'body_sha256':hashlib.sha256(raw).hexdigest(),
                'output_effort':(body.get('output_config') or {}).get('effort')})
        message={'id':'msg_public_cc_budget_probe','type':'message','role':'assistant','model':MODEL,
            'content':[{'type':'text','text':'OK'}],'stop_reason':'end_turn','stop_sequence':None,
            'usage':{'input_tokens':128,'output_tokens':1}}
        self.send_response(200)
        if body.get('stream') is not True:
            payload=json.dumps(message).encode();self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
        self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        frames=[('message_start',{'type':'message_start','message':{**message,'content':[],'stop_reason':None,'usage':{'input_tokens':128,'output_tokens':0}}}),
            ('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}),
            ('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'OK'}}),
            ('content_block_stop',{'type':'content_block_stop','index':0}),
            ('message_delta',{'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':1}}),
            ('message_stop',{'type':'message_stop'})]
        for event,data in frames:self.wfile.write(('event: '+event+'\ndata: '+json.dumps(data)+'\n\n').encode())
        self.wfile.flush()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    verify_offline()
    binary=args.binary.resolve(strict=True)
    if binary.stat().st_size!=CC_BYTES or hash_file(binary)!=CC_SHA:
        raise ValueError('pinned binary mismatch')
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','NO_PROXY':'127.0.0.1,localhost',
        'DISABLE_AUTOUPDATER':'1','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','ENABLE_TOOL_SEARCH':'false',
        'CLAUDE_CODE_NO_MODEL_FALLBACK':'1','CLAUDE_CODE_MAX_RETRIES':'0','CLAUDE_CODE_HUMBLE_HAMMOCK':'1',
        'CLAUDE_CODE_EFFORT_LEVEL':'max','ANTHROPIC_API_KEY':'public-loopback-placeholder','ANTHROPIC_MODEL':MODEL}
    version=subprocess.run([str(binary),'--version'],env=env,capture_output=True,timeout=30,check=True)
    if version.stdout.decode().strip()!='2.1.312 (Claude Code)':raise ValueError('CC version mismatch')
    results=[]
    with tempfile.TemporaryDirectory(prefix='cc312-public-wire-') as work:
        root=Path(work);os.chmod(root,0o700)
        for context,compact in ((65536,65536),(131072,98304),(196608,196608)):
            home=root/str(context);home.mkdir(mode=0o700)
            with Stub() as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                local={**env,'HOME':str(home),'CLAUDE_CONFIG_DIR':str(home/'config'),
                    'ANTHROPIC_BASE_URL':'http://127.0.0.1:'+str(server.server_port),
                    'CLAUDE_CODE_MAX_OUTPUT_TOKENS':'32768','CLAUDE_CODE_MAX_CONTEXT_TOKENS':str(context),
                    'CLAUDE_CODE_AUTO_COMPACT_WINDOW':str(compact)}
                command=[str(binary),'--print','--verbose','--output-format','stream-json',
                    '--model',MODEL,'--effort','max','--max-turns','1','--tools','',
                    'Reply with OK. Do not use tools. This is a public local runtime budget probe.']
                child=subprocess.Popen(command,env=local,cwd=home,stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
                try:
                    stdout,stderr=child.communicate(timeout=90)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL);stdout,stderr=child.communicate();raise ValueError('CC local stub timeout')
                finally:
                    server.shutdown();thread.join(timeout=5)
                requests=list(server.requests)
                if child.returncode!=0 or not requests or len(requests)>3:
                    raise ValueError('CC local stub did not complete once')
                if any(x['model']!=MODEL or x['max_tokens']!=32768 for x in requests):
                    raise ValueError('CC binary changed requested output budget')
                results.append({'context_tokens':context,'auto_compact_window':compact,'output_tokens':32768,'claude_exit':child.returncode,
                    'requests':requests,'stdout_bytes':len(stdout),'stderr_bytes':len(stderr),
                    'stdout_sha256':hashlib.sha256(stdout).hexdigest(),'stderr_sha256':hashlib.sha256(stderr).hexdigest()})
    report={'schema':'cc312.small-budget-local-wire.v2','binary_sha256':CC_SHA,
        'version':'2.1.312','profiles':results,'external_network_available':False,
        'real_model_called':False,'provider_capacity_verified':False}
    raw=(json.dumps(report,indent=2,sort_keys=True)+'\n').encode()
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as out:out.write(raw)
    print(json.dumps({'status':'binary_wire_verified','profiles':len(results),'real_model_called':False}))


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'status':'infra','error_type':type(e).__name__,'message':str(e)}))
        raise SystemExit(2)
