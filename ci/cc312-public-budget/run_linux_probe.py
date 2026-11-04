#!/usr/bin/env python3
"""Bounded Linux probe launcher. Existing pinned binary preferred; no model API.

This entry is for the sole CI/cloud coordinator. It never fetches credentials,
touches other jobs, or changes the host network. The probe runs in a new netns.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
CC_SHA='4f4178ce41d83e23341ebfbaecdbcf8ea6bf7baea0690025abe49eeec3a5d01d'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if sys.platform!='linux' or os.geteuid()!=0:
        raise ValueError('Linux root control required for private netns')
    for name in ('unshare','ip'):
        if not shutil.which(name):raise ValueError(name+' not installed')
    if args.output.exists():raise ValueError('new output required')
    ip=shutil.which('ip')
    entry=('import os,subprocess,sys; subprocess.run([sys.argv[1],"link","set","lo","up"],check=True); '
        'os.execv(sys.argv[2],[sys.argv[2],"-I","-B",sys.argv[3],"--binary",sys.argv[4],"--output",sys.argv[5]])')
    command=['unshare','--net',sys.executable,'-I','-B','-c',entry,ip,sys.executable,
        str(HERE/'probe_linux_cli.py'),str(args.binary),str(args.output)]
    result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=240,check=False,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})
    if result.returncode or not args.output.is_file():
        # Public probe output contains only classifications, not request text.
        sys.stdout.buffer.write(result.stdout[-2000:])
        raise ValueError('offline actual binary probe failed')
    report=json.loads(args.output.read_bytes())
    if report.get('binary_sha256')!=CC_SHA or report.get('real_model_called') is not False:
        raise ValueError('probe report identity mismatch')
    print(json.dumps({'status':'actual_linux_cli_verified','report_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
        'profile_count':len(report['profiles']),'real_model_called':False},sort_keys=True))


if __name__=='__main__':main()
