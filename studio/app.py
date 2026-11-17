import argparse
import json
import os
import sys
import time
from pathlib import Path

def discover_root(home=None):
    if home: return Path(home).resolve()
    if os.environ.get('TRIPUBLISH_HOME'): return Path(os.environ['TRIPUBLISH_HOME']).resolve()
    if getattr(sys,'frozen',False):
        base=Path(sys.executable).parent
        workspace=base/'workspace.json'
        if workspace.is_file():
            relative=json.loads(workspace.read_text(encoding='utf-8')).get('workspace')
            if relative:return (base/relative).resolve()
        return base
    for p in Path(__file__).resolve().parents:
        if (p/'runtime'/'biliup').exists(): return p
    return Path.cwd()

class InstanceLock:
    def __init__(self,path):
        self.file=open(path,'a+b');self.file.seek(0)
        if self.file.read(1)==b'':self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:self.file.close();raise ValueError('这个工作目录的软件已经运行，请查看任务栏或托盘')
    def close(self):
        if not self.file.closed:self.file.close()

def main(argv=None):
    parser=argparse.ArgumentParser(description='三平台内容发布助手')
    parser.add_argument('--home');parser.add_argument('--data-dir');parser.add_argument('--port',type=int,default=19266)
    parser.add_argument('--headless',action='store_true');parser.add_argument('--self-test',action='store_true');parser.add_argument('--self-test-out')
    parser.add_argument('--ui-check-out',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    root=discover_root(args.home)
    if args.self_test:
        from PySide6 import QtCore
        import patchright,segno
        from . import __version__
        result={'ok':True,'version':__version__,'qt':QtCore.qVersion(),'python':sys.version.split()[0],'frozen':bool(getattr(sys,'frozen',False)),'root':str(root)}
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if args.self_test_out:Path(args.self_test_out).write_text(text,encoding='utf-8')
        elif sys.stdout: print(text)
        return 0
    data=Path(args.data_dir).resolve() if args.data_dir else root/'state'/'desktop'
    data.mkdir(parents=True,exist_ok=True)
    lock=None;service=None;api=None
    try:
        lock=InstanceLock(data/'instance.lock')
        from .service import Service
        from .api import ApiServer
        service=Service(root,data)
        api=ApiServer(service,args.port);api.start()
        from . import __version__
        connection={'endpoint':api.endpoint,'token_path':str(service.paths.token_path),'openapi_url':api.endpoint+'/api/v1/openapi.json','version':__version__,'docs_path':str(root/'docs')}
        (data/'connection.json').write_text(json.dumps(connection,ensure_ascii=False,indent=2),encoding='utf-8')
        if args.headless:
            if sys.stdout: print(json.dumps({'ok':True,**connection},ensure_ascii=False),flush=True)
            try:
                while True:time.sleep(0.5)
            except KeyboardInterrupt:return 0
        from .gui import run
        return run(service,dict(connection,_ui_check_out=args.ui_check_out) if args.ui_check_out else connection)
    except Exception as exc:
        from .core import redact
        message=redact(exc)
        (data/'startup-error.txt').write_text(message,encoding='utf-8')
        if args.headless:
            if sys.stderr:print(message,file=sys.stderr)
        else:
            from PySide6.QtWidgets import QApplication,QMessageBox
            app=QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None,'无法启动',message)
        return 2
    finally:
        if api:api.close()
        if service and not service.closed:service.close()
        if lock:lock.close()

if __name__=='__main__':raise SystemExit(main())
