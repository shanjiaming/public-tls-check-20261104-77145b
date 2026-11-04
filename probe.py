#!/usr/bin/env python3
"""PUBLIC, credential-free comparison only; safe for an authorized public runner."""
import concurrent.futures
import datetime
import json
import os
import subprocess

HOSTS = ("ecs.aliyuncs.com", "ecs.ap-southeast-1.aliyuncs.com", "help.aliyun.com", "api.github.com")

def probe(host):
    env = {k:v for k,v in os.environ.items() if k.lower() not in ("http_proxy","https_proxy","all_proxy","no_proxy")}
    p = subprocess.run(["curl","--noproxy","*","--connect-timeout","5","--max-time","8","-sS","-o","/dev/null",
                        "-w","%{http_code}|%{remote_ip}|%{time_connect}|%{time_appconnect}|%{time_total}","https://"+host+"/"],
                       env=env,capture_output=True,text=True,timeout=10)
    out={"host":host,"exit":p.returncode,"error":p.stderr.strip()[:180],"at":datetime.datetime.now(datetime.timezone.utc).isoformat()}
    out.update(dict(zip(("http_status","remote_ip","tcp_seconds","tls_seconds","total_seconds"),p.stdout.strip().split("|"))))
    return out

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        checks=list(ex.map(probe,HOSTS))
    print(json.dumps({"scope":"unsigned_public_TLS_only_no_cloud_access_no_credentials","checks":checks},indent=2))
