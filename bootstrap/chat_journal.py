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
from chat_evidence import compare
from chat_semantic import candidates, validate_claim

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
                CREATE TABLE IF NOT EXISTS candidates(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, polarity INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'unverified');
                CREATE INDEX IF NOT EXISTS candidates_turn ON candidates(turn_id);
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
            if role=="user":
                for item in candidates(text):
                    db.execute("INSERT INTO candidates(turn_id,kind,start,end,fingerprint,polarity,status) VALUES(?,?,?,?,?,?,?)",
                               (cursor.lastrowid,item["kind"],item["start"],item["end"],
                                item["key"],item["polarity"],item["status"]))
        return {"id":cursor.lastrowid,"sha256":digest,**info}

    def verify(self):
        with self.lock,self._db() as db:
            records=db.execute("SELECT id,text,digest FROM turns ORDER BY id").fetchall()
        return {"records":len(records),"integrity":all(
            hashlib.sha256(row[1].encode("utf-8")).hexdigest()==row[2]
            for row in records)}

    def clear(self):
        with self.lock,self._db() as db:
            db.execute("DELETE FROM candidates")
            db.execute("DELETE FROM analysis")
            db.execute("DELETE FROM turns")

    def records(self):
        with self.lock,self._db() as db:
            return [{"role":r[0],"content":r[1],"time":r[2]}
                    for r in db.execute("SELECT role,text,time FROM turns ORDER BY id")]


    def reflection(self):
        """Read-only diagnostics; never includes the raw message text."""
        with self.lock,self._db() as db:
            rows=[{"turn_id":r[0],"kind":r[1],"start":r[2],"end":r[3],
                   "key":r[4],"polarity":r[5],"status":r[6]}
                  for r in db.execute("SELECT turn_id,kind,start,end,fingerprint,polarity,status FROM candidates ORDER BY id DESC LIMIT 200")]
        rows.reverse()
        with self.lock,self._db() as db:
            source={r[0]:(r[1],r[2]) for r in db.execute(
                "SELECT id,text,digest FROM turns WHERE id IN (SELECT DISTINCT turn_id FROM candidates)")}
        verified=[]
        for item in rows:
            record=source.get(item["turn_id"])
            if record is None:
                continue
            text,stored_digest=record
            if hashlib.sha256(text.encode("utf-8")).hexdigest()!=stored_digest:
                continue
            claim={k:item[k] for k in ("kind","start","end","key","polarity","status")}
            if validate_claim(text,claim):
                verified.append(item)
        return {"candidates":len(verified),
                "unverified":sum(x["status"]=="unverified" for x in verified),
                "conflicts":compare(verified),"automatic_facts":0,
                "invalid_evidence":len(rows)-len(verified)}

    def evidence(self,turn_id):
        """Read exact evidence locally, only when explicitly requested."""
        with self.lock,self._db() as db:
            row=db.execute("SELECT role,text,digest,time FROM turns WHERE id=?",(turn_id,)).fetchone()
        if row is None:
            return None
        return {"role":row[0],"content":row[1],"sha256":row[2],"time":row[3]}
