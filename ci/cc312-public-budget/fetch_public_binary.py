#!/usr/bin/env python3
"""Fetch only the public, fixed Claude Code Linux binary for a synthetic probe."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import platform
import tarfile
import urllib.request

URL='https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/-/claude-code-linux-x64-2.1.312.tgz'
SRI='oj55HL9uasLWzym5eZNgC8xyk0N0H4hw8WdN0DeDuAlquhs2d4hhkQVZcRKvJarBB37IU9bbEGXZwtuhsex6EQ=='
SIZE=293592432
SHA='4f4178ce41d83e23341ebfbaecdbcf8ea6bf7baea0690025abe49eeec3a5d01d'
MAX=400000000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('unexpected redirect')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if platform.system()!='Linux' or platform.machine()!='x86_64':raise ValueError('Linux x86_64 required')
    root=a.output
    root.mkdir(mode=0o700)
    archive=root/'package.tgz'
    fd=os.open(archive,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    digest=hashlib.sha512();total=0
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with os.fdopen(fd,'wb') as out,opener.open(urllib.request.Request(URL,headers={'Accept-Encoding':'identity'}),timeout=30) as response:
        if response.status!=200 or response.geturl()!=URL:raise ValueError('unexpected download source')
        while part:=response.read(1024*1024):
            total+=len(part)
            if total>MAX:raise ValueError('package size bound exceeded')
            digest.update(part);out.write(part)
        out.flush();os.fsync(out.fileno())
    if digest.digest()!=base64.b64decode(SRI,validate=True):raise ValueError('public archive integrity mismatch')
    with tarfile.open(archive,'r:gz') as package:
        members=package.getmembers()
        if len(members)>16:raise ValueError('unexpected package inventory')
        targets=[x for x in members if x.name=='package/claude']
        if len(targets)!=1 or not targets[0].isfile() or targets[0].size!=SIZE:raise ValueError('fixed binary absent')
        source=package.extractfile(targets[0]);target=root/'claude'
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o700)
        binary=hashlib.sha256();count=0
        with os.fdopen(fd,'wb') as out:
            while part:=source.read(1024*1024):
                count+=len(part)
                if count>SIZE:raise ValueError('binary size bound exceeded')
                binary.update(part);out.write(part)
            out.flush();os.fsync(out.fileno())
        if count!=SIZE or binary.hexdigest()!=SHA:raise ValueError('fixed binary integrity mismatch')
    print('Public fixed CC2.1.312 binary verified; no execution during download.')


if __name__=='__main__':main()
