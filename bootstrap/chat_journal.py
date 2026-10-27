"""Local lossless chat journal and bounded, non-authoritative lexical analysis.

The journal stores exact UTF-8 message text. Analysis is deliberately not a
fact extractor: words and keywords are observations, not verified beliefs.
No external API requests and no model-generated recollections.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading

WORDS=re.compile(r"[^\W_]+(?:[-'][^\W_]+)*",re.UNICODE)
MAX_TEXT=2_000_000
MAX_PREVIEW=32

class ChatJournal:
    def __init__(self,root):
        self.path=Path(root)/"chat_journal.sqlite3"
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS turns(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    text TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    time TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS analysis(
                    turn_id INTEGER PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
                    word_count INTEGER NOT NULL,
                    unique_word_count INTEGER NOT NULL,
                    keywords_json TEXT NOT NULL,
                    confidence TEXT NOT NULL DEFAULT 'unverified');
                CREATE INDEX IF NOT EXISTS turns_role_time ON turns(role,time);
            """)

    def _db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @staticmethod
    def analyze(text):
        tokens=[x.group(0).casefold() for x in WORDS.finditer(text)]
        frequencies={}
        for token in tokens:
            frequencies[token]=frequencies.get(token,0)+1
        keywords=sorted(frequencies,key=lambda x:(-frequencies[x],x))[:MAX_PREVIEW]
        return {"word_count":len(tokens),"unique_word_count":len(frequencies),
                "keywords":keywords,"confidence":"unverified"}

    def append(self,role,text,time):
        if role not in ("user","assistant") or not isinstance(text,str) or len(text)>MAX_TEXT:
            raise ValueError("Invalid chat journal message")
        if not isinstance(time,str) or len(time)>64:
            raise ValueError("Invalid message timestamp")
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest()
        info=self.analyze(text)
        with self.lock,self._db() as db:
            cursor=db.execute("INSERT INTO turns(role,text,digest,time) VALUES(?,?,?,?)",
                              (role,text,digest,time))
            db.execute("INSERT INTO analysis(turn_id,word_count,unique_word_count,keywords_json,confidence) VALUES(?,?,?,?,?)",
                       (cursor.lastrowid,info["word_count"],info["unique_word_count"],
                        json.dumps(info["keywords"],ensure_ascii=False),info["confidence"]))
        return {"id":cursor.lastrowid,"sha256":digest,**info}

    def verify(self):
        with self.lock,self._db() as db:
            records=db.execute("SELECT id,text,digest FROM turns ORDER BY id").fetchall()
        return {"records":len(records),"integrity":all(
            hashlib.sha256(row[1].encode("utf-8")).hexdigest()==row[2]
            for row in records)}

    def clear(self):
        with self.lock,self._db() as db:
            db.execute("DELETE FROM analysis")
            db.execute("DELETE FROM turns")

    def records(self):
        with self.lock,self._db() as db:
            return [{"role":r[0],"content":r[1],"time":r[2]}
                    for r in db.execute("SELECT role,text,time FROM turns ORDER BY id")]
