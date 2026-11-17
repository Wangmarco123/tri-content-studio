import base64
import ctypes
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PLATFORMS = ('bilibili','douyin','xiaohongshu')
TABLES = ('assets','drafts','evidence','jobs','events','versions','campaigns')

def now(): return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
def uid(prefix): return prefix+'_'+uuid.uuid4().hex[:16]
def file_hash(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def redact(value):
    text=str(value)
    # Remove the complete authorization value before generic key/value matching.
    text=re.sub(r'(?i)Bearer\s+[^\s\"\',}]+','Bearer [REDACTED]',text)
    text=re.sub(r'(?im)\b((?:authorization|cookie|set-cookie)\s*:\s*)[^\r\n]+',r'\1[REDACTED]',text)
    keys=r'(?:authorization|cookie|api[_-]?key|access[_-]?token|refresh[_-]?token|sessionid|sessdata|bduss|bili_jct|qrcode_key)'
    text=re.sub(r'(?i)([\"\']'+keys+r'[\"\']\s*:\s*)([\"\'])(?:\\.|(?!\2).)*?\2',r'\1"[REDACTED]"',text)
    return re.sub(r'(?i)(\b'+keys+r'\s*[=:]\s*)[^\s,;\}\]]+',r'\1[REDACTED]',text)

class Store:
    def __init__(self,data_dir):
        self.path=Path(data_dir)/'catalog.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self._transaction_depth=0
        self.db=sqlite3.connect(str(self.path),check_same_thread=False,timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        for table in TABLES:
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        self.db.commit()
    def list(self,table):
        if table not in TABLES: raise ValueError('未知数据集合')
        with self.lock: return [json.loads(r[0]) for r in self.db.execute(f'SELECT body FROM {table} ORDER BY rowid DESC')]
    def get(self,table,record_id):
        if table not in TABLES: raise ValueError('未知数据集合')
        with self.lock:
            row=self.db.execute(f'SELECT body FROM {table} WHERE id=?',(record_id,)).fetchone()
            if not row: raise ValueError('记录不存在：'+str(record_id))
            return json.loads(row[0])
    def put(self,table,record):
        if table not in TABLES: raise ValueError('未知数据集合')
        with self.lock:
            self.db.execute(f'INSERT INTO {table}(id,body) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(record['id'],json.dumps(record,ensure_ascii=False)))
            if not self._transaction_depth: self.db.commit()
        return record
    @contextmanager
    def transaction(self):
        with self.lock:
            outer=self._transaction_depth==0
            if outer: self.db.execute('BEGIN IMMEDIATE')
            self._transaction_depth+=1
            try:
                yield
            except BaseException:
                if outer: self.db.rollback()
                raise
            else:
                if outer: self.db.commit()
            finally:
                self._transaction_depth-=1
    def update(self,table,record_id,changes):
        with self.lock:
            record=self.get(table,record_id);record.update(changes);record['updated_at']=now()
            return self.put(table,record)
    def close(self):
        with self.lock: self.db.close()

class Paths:
    def __init__(self,project_root,data_dir=None):
        self.project_root=Path(project_root).resolve()
        self.data_dir=Path(data_dir or self.project_root/'state'/'desktop').resolve()
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.token_path=self.data_dir/'api-token.txt'
        if not self.token_path.exists():
            self.token_path.write_text(secrets.token_urlsafe(32),encoding='ascii')
            try: os.chmod(self.token_path,0o600)
            except OSError: pass
        self.token=self.token_path.read_text(encoding='ascii').strip()

def protect_secret(text):
    if os.name!='nt': raise ValueError('此版本的密钥保存需要 Windows DPAPI')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
    raw=text.encode('utf-8');buf=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
    inp=Blob(len(raw),buf);out=Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inp),'TriPublish',None,None,None,0,ctypes.byref(out)):
        raise ValueError('Windows密钥保护失败')
    try: return base64.b64encode(ctypes.string_at(out.pbData,out.cbData)).decode('ascii')
    finally: ctypes.windll.kernel32.LocalFree(out.pbData)

def unprotect_secret(text):
    if not text: return ''
    if os.name!='nt': return ''
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
    raw=base64.b64decode(text);buf=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
    inp=Blob(len(raw),buf);out=Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp),None,None,None,None,0,ctypes.byref(out)):
        raise ValueError('无法解密当前用户的模型密钥，请重新设置')
    try: return ctypes.string_at(out.pbData,out.cbData).decode('utf-8')
    finally: ctypes.windll.kernel32.LocalFree(out.pbData)
