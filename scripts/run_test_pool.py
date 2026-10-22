"""One-command isolated regression pool with stage logs and JSON/JUnit evidence.

python scripts/run_test_pool.py
python scripts/run_test_pool.py --include-network  # optional public fixture fetches

Never runs the exhaustive pool against production or reuses the developer's data.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent.parent


def stop(process):
    if process.poll() is not None: return
    if os.name=="nt":
        subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    else:
        os.killpg(process.pid,signal.SIGTERM)
    try: process.wait(timeout=15)
    except subprocess.TimeoutExpired: process.kill();process.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-network",action="store_true")
    parser.add_argument("--output",type=Path,default=ROOT/"data-qa-pool"/"runs")
    args=parser.parse_args()
    run_dir=args.output.resolve()/datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(parents=True)
    report={"started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"platform":platform.platform(),"python":sys.version,"stages":[],"excluded_scope":["accounts/billing","cloud integrations","email signing"],"limitations":["Generated fixture coverage, not arbitrary-document fidelity or all option combinations","Physical cameras and non-Chromium browsers not exercised","External public fixture fetches run only with --include-network"]}
    with tempfile.TemporaryDirectory(prefix="pdfnova-pool-") as folder:
        env={**os.environ,"NO_DOTENV":"1","DATA_DIR":str(Path(folder)/"server"),"TASKS_PER_HOUR":"0","ALLOW_PRIVATE_URLS":"0","PYTHONUNBUFFERED":"1","PYTHONUTF8":"1","POOL_TOOL_FILTER":"","POOL_UI_MOBILE":"0"}
        with socket.socket() as sock: sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        base=f"http://127.0.0.1:{port}"
        kwargs={"creationflags":subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=="nt" else {"start_new_session":True}
        with (run_dir/"server.log").open("wb") as log:
            server=subprocess.Popen([sys.executable,"-m","uvicorn","app.main:app","--host","127.0.0.1","--port",str(port),"--no-access-log"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,**kwargs)
            try:
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    if server.poll() is not None: raise RuntimeError("Isolated server exited; inspect server.log")
                    try:
                        with urllib.request.urlopen(base+"/api/tools",timeout=1) as r: tools=json.load(r)
                        break
                    except OSError: time.sleep(.2)
                else: raise RuntimeError("Isolated server did not become ready")
                report["canonical_tool_count"]=len(tools)
                report["declared_option_count"]=sum(len(t["options"]) for t in tools)
                report["tool_inventory"]=[{"type":t["type"],"page":"/"+t["slug"],"option_fields":[o["name"] for o in t["options"]]} for t in tools]
                stages=[
                    ("python",["-m","coverage","run","--branch","--source=app","-m","pytest","tests","-q","--tb=short",f"--junitxml={run_dir/'pytest.xml'}"],600),
                    ("all-tool-ui",["scripts/tool_ui_regression.py",base],1800),
                    ("all-tool-ui-mobile",["scripts/tool_ui_regression.py",base],1800),
                    ("shared-features",["scripts/shared_feature_regression.py",base],300),
                    ("browser",["scripts/browser_regression.py",base],600),
                    ("editor",["scripts/editor_regression.py"],600),
                    ("signature",["scripts/signature_regression.py",base],300),
                    ("signature-cleanup",["scripts/signature_cleanup_regression.py",base],180),
                    ("concurrency",["scripts/concurrency_regression.py",base],300),
                ]
                if args.include_network: stages.append(("network-smoke",["scripts/smoke_test.py",base],600))
                for name,command,timeout in stages:
                    print("RUN",name,flush=True);started=time.monotonic();started_epoch=time.time()
                    stage_env={**env,"DATA_DIR":str(Path(folder)/name),"EDITOR_BASE_URL":base,"COVERAGE_FILE":str(run_dir/".coverage")}
                    if name=="all-tool-ui-mobile": stage_env["POOL_UI_MOBILE"]="1"
                    with (run_dir/(name+".log")).open("wb") as stage_log:
                        process=subprocess.Popen([sys.executable,*command],cwd=ROOT,env=stage_env,stdout=stage_log,stderr=subprocess.STDOUT,**kwargs)
                        try: code=process.wait(timeout=timeout); status="passed" if code==0 else "failed"
                        except subprocess.TimeoutExpired: stop(process);code=None;status="timeout"
                        finally:
                            if process.poll() is None: stop(process)
                    entry={"stage":name,"status":status,"exit_code":code,"seconds":round(time.monotonic()-started,2),"log":name+".log"}
                    if name=="python" and (run_dir/"pytest.xml").exists():
                        suites=ET.parse(run_dir/"pytest.xml").getroot()
                        entry["junit"]={k:sum(int(s.get(k,0)) for s in suites.iter("testsuite")) for k in ("tests","failures","errors","skipped")}
                        with (run_dir/"coverage.log").open("wb") as coverage_log:
                            generated=subprocess.run([sys.executable,"-m","coverage","json","-o",str(run_dir/"coverage.json")],cwd=ROOT,env=stage_env,stdout=coverage_log,stderr=subprocess.STDOUT,timeout=30)
                        if generated.returncode==0:
                            entry["coverage"]=json.loads((run_dir/"coverage.json").read_text(encoding="utf-8"))["totals"]
                        else:
                            entry["status"]="failed";entry["coverage_error"]="Coverage report generation failed"
                    report["stages"].append(entry)
                    artifacts={"all-tool-ui-mobile":(ROOT/"data-qa-pool/tool-ui-mobile-results.json","tool-ui-mobile-results.json"),"all-tool-ui":(ROOT/"data-qa-pool/tool-ui-results.json","tool-ui-results.json"),"browser":(ROOT/"data-qa-browser/results.json","browser-results.json"),"shared-features":(ROOT/"data-qa-pool/shared-feature-results.json","shared-feature-results.json")}
                    if name in artifacts:
                        src,dest=artifacts[name]
                        if src.exists() and src.stat().st_mtime>=started_epoch:
                            (run_dir/dest).write_bytes(src.read_bytes())
                    (run_dir/"results.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
                    print(entry["status"].upper(),name,entry["seconds"],"s",flush=True)
            finally: stop(server)
    report["finished_utc"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["status"]="passed" if report["stages"] and all(s["status"]=="passed" for s in report["stages"]) else "failed"
    (run_dir/"results.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("REPORT",run_dir/"results.json",flush=True)
    return 0 if report["status"]=="passed" else 1


if __name__=="__main__": raise SystemExit(main())
