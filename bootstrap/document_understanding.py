"""Структурное локальное чтение документов Tenmiyora.

Сохраняет буквальные блоки и локаторы (страница/раздел/ячейка). Ни одно
утверждение документа не считается установленной истиной. Не отправляет
содержимое в сеть. OCR — строго по явному включению и с ограничением страниц.
"""
from __future__ import annotations

from collections import defaultdict
import io
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

MAX_CHARS = 350_000
MAX_SEGMENTS = 12_000
MAX_XML_BYTES = 6_000_000
MAX_OCR_PAGES = 25
WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
DATE = re.compile(r"\b(?:\d{2}[.]\d{2}[.]\d{4}|\d{4}-\d{2}-\d{2})\b")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
EXTRA = (".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".py", ".js", ".css",
         ".bat", ".ps1", ".log")
STOP = {"какие","какая","какой","каков","где","когда","есть","что","для",
        "эта","этот","это","или","при","между","его","документ","документе",
        "напиши","покажи","найди","перечисли","мне","как","чем","из","по",
        "указан","указано","указаны","указать","назван","названа",
        "номер","номера","номеру","имеется","указано","содержит"}
CUES = (
    ("obligation", re.compile(r"\b(?:обязан\w*|должен\w*|обязуется\w*|обязательств\w*)\b", re.I)),
    ("restriction", re.compile(r"\b(?:запрещ\w*|не\s+допуска\w*|ограничива\w*|не\s+вправе)\b", re.I)),
    ("exception", re.compile(r"\b(?:за\s+исключением|кроме\s+случаев|если\s+иное|при\s+условии|в\s+случае)\b", re.I)),
    ("deadline", re.compile(r"\b(?:срок\w*|не\s+позднее|до\s+\d{1,2}[.]\d{1,2}[.]\d{4})\b", re.I)),
    ("purpose", re.compile(r"\b(?:цель\s+документа|целью\s+настоящего|предназначен\w*\s+для)\b", re.I)),
    ("party", re.compile(r"\b(?:покупател[ьяюе]|поставщик\w*|заказчик\w*|исполнитель\w*)\b", re.I)),
    ("risk", re.compile(r"\b(?:неустойк\w*|штраф\w*|риск\w*|ответственност\w*|убытк\w*)\b", re.I)),
    ("cause", re.compile(r"\b(?:вследствие|поскольку|по\s+причине|из-за)\b", re.I)),
    ("conclusion", re.compile(r"\b(?:таким\s+образом|следовательно|вывод\w*|по\s+итогам)\b", re.I)),
)
CONFLICT = re.compile(r"(?i)\b(?:срок(?:\s+оплаты)?|стоимость|цена|сумма|количество)\s+[\w\s]{0,35}?(?:составляет|равен|равна)\s+(\d+(?:[.,]\d+)?)\s*(дн(?:ей|я)|рублей|руб|шт|%)?\b")


def _text(elem):
    return "".join(el.text or "" for el in elem.iter() if el.tag in (W+"t",S+"t"))


def _safe_zip(raw):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    if sum(x.file_size for x in archive.infolist()) > MAX_XML_BYTES:
        archive.close()
        raise ValueError("Превышен безопасный объём XML в документе.")
    return archive


def _append(items,kind,locator,text,section=""):
    text=" ".join(str(text).split())
    if text:
        items.append({"kind":kind,"locator":locator,"text":text,"section":section})


def _docx(raw,items):
    with _safe_zip(raw) as arc:
        root=ET.fromstring(arc.read("word/document.xml"))
        body=root.find(".//"+W+"body")
        if body is None:
            return
        section=""
        para=0
        table=0
        for el in body:
            typ=el.tag.rsplit("}",1)[-1]
            if typ=="p":
                para+=1
                content=_text(el)
                style=el.find(".//"+W+"pStyle")
                style_name=style.get(W+"val","") if style is not None else ""
                is_heading=style_name.casefold().startswith(("heading","заголовок"))
                if is_heading and content.strip():
                    section=content.strip()
                _append(items,"heading" if is_heading else "paragraph",
                        f"Абзац {para}"+(f", {section}" if section else ""),
                        content,section)
            elif typ=="tbl":
                table+=1
                for rn,row in enumerate(el.findall(W+"tr"),1):
                    for cn,cell in enumerate(row.findall(W+"tc"),1):
                        paragraphs=[_text(p) for p in cell.findall(".//"+W+"p")]
                        content=" ".join(x for x in paragraphs if x)
                        _append(items,"table_cell",
                                f"Таблица {table}, строка {rn}, столбец {cn}",
                                content,section)
        for itemname,kind in (("word/footnotes.xml","footnote"),
                              ("word/endnotes.xml","endnote")):
            if itemname in arc.namelist():
                root=ET.fromstring(arc.read(itemname))
                for el in root:
                    number=el.get(W+"id","?")
                    _append(items,kind,f"{kind} {number}",_text(el),section)


def _xlsx(raw,items):
    notes=[]
    with _safe_zip(raw) as arc:
        paths=set(arc.namelist())
        shared=[]
        if "xl/sharedStrings.xml" in paths:
            root=ET.fromstring(arc.read("xl/sharedStrings.xml"))
            shared=[_text(item) for item in root.findall(S+"si")]
        names=[]
        book="xl/workbook.xml"
        rels="xl/_rels/workbook.xml.rels"
        if book in paths and rels in paths:
            workbook=ET.fromstring(arc.read(book))
            relationships=ET.fromstring(arc.read(rels))
            targets={}
            for rel in relationships:
                key=rel.get("Id")
                target=rel.get("Target","").lstrip("/")
                if target.startswith("xl/"):
                    path=target
                else:
                    path="xl/"+target
                if ".." not in path.split("/"):
                    targets[key]=path
            for node in workbook.findall(".//"+S+"sheet"):
                source=targets.get(node.get(R+"id"))
                if source in paths:
                    names.append((source,node.get("name","Лист"),node.get("state","visible")))
        if not names:
            names=[(x,f"Лист {i+1}","visible") for i,x in enumerate(sorted(paths))
                   if re.fullmatch(r"xl/worksheets/sheet\d+\.xml",x)]
        if len(names)>30:
            notes.append("Excel содержит больше 30 листов: обработаны только первые 30.")
        for source,title,state in names[:30]:
            if state!="visible":
                # Hidden cells remain readable but explicit in their locator.
                title += " [скрытый]"
            root=ET.fromstring(arc.read(source))
            for row in root.findall(".//"+S+"sheetData/"+S+"row"):
                for cell in row.findall(S+"c"):
                    coord=cell.get("r","?")
                    form=cell.find(S+"f")
                    raw_value=cell.find(S+"v")
                    inline=cell.find(S+"is")
                    value=(raw_value.text or "") if raw_value is not None else ""
                    if cell.get("t")=="s" and value.isdigit():
                        index=int(value)
                        value=shared[index] if index<len(shared) else ""
                    elif inline is not None:
                        value=_text(inline)
                    if form is not None and form.text:
                        value=(value+" [формула: "+form.text+"]").strip()
                    _append(items,"cell",f"{title}!{coord}",value,title)
    return notes


def _pdf(raw,items):
    """Read PDF pages independently, preserving page locators and partial failures."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ["Требуется необязательный пакет pypdf для чтения PDF."]
    reader=PdfReader(io.BytesIO(raw), strict=False)
    notes=[]
    use_ocr=os.environ.get("TENMIYORA_OCR_ENABLED","0").strip().lower() in ("1","true","yes")
    # OCR rendering is expensive; only initialise the renderer on demand.
    pdf_renderer=None
    total_pages=len(reader.pages)
    for index in range(total_pages):
        if len(items)>=MAX_SEGMENTS:
            notes.append("PDF обработан не полностью: предел количества блоков.")
            break
        try:
            text=reader.pages[index].extract_text() or ""
        except Exception as error:
            text=""
            notes.append("Ошибка текстового слоя страницы "+str(index+1)+": "+type(error).__name__)
        if not text.strip() and use_ocr and index<MAX_OCR_PAGES:
            try:
                import pypdfium2
                import pytesseract
                if pdf_renderer is None:
                    pdf_renderer=pypdfium2.PdfDocument(raw)
                image=pdf_renderer[index].render(scale=1.5).to_pil()
                text=pytesseract.image_to_string(image,lang="rus+eng",timeout=15)
            except Exception as error:
                notes.append("OCR страницы "+str(index+1)+" не выполнен: "+type(error).__name__)
        if not text.strip():
            notes.append(f"Страница {index+1} не содержит доступного текста.")
            continue
        # Split long single-block pages so the question matcher can find facts
        # in the middle and end, not just at the beginning of a page.
        blocks=re.split(r"\\n\\s*\\n",text)
        refined=[]
        for block in blocks:
            lines=[line.strip() for line in block.splitlines() if line.strip()]
            # Individual complete statements must not be conflated into a
            # single cited claim (especially separate monetary/term rows).
            if len(lines)>1 and all(
                    len(line)>=12 and re.search(r"[.!?;:]$",line) for line in lines):
                refined.extend(lines)
            else:
                refined.append(block)
        blocks=refined
        number=0
        for block in blocks:
            block=block.strip()
            if not block:
                continue
            # No truncation: preserve every character in independently indexed
            # segments until the global document coverage limit is reached.
            for start in range(0,len(block),1800):
                number+=1
                _append(items,"page",f"Страница {index+1}, блок {number}",block[start:start+1800])
                if len(items)>=MAX_SEGMENTS:
                    notes.append("PDF обработан не полностью: предел количества блоков.")
                    break
            if len(items)>=MAX_SEGMENTS:
                break
    if total_pages>MAX_OCR_PAGES and use_ocr:
        notes.append("OCR ограничен первыми 25 страницами; остальные страницы доступны при наличии текстового слоя.")
    return notes

def extract_segments(name,raw):
    """Output: exact text excerpts + coverage notes, never guessed contents."""
    ext=Path(name).suffix.lower()
    items=[]
    notes=[]
    try:
        if ext==".docx":
            _docx(raw,items)
        elif ext==".xlsx":
            notes.extend(_xlsx(raw,items))
        elif ext==".pdf":
            notes.extend(_pdf(raw,items))
        elif ext in EXTRA:
            from knowledge import extract_text
            plain,status=extract_text(name,raw)
            if status!="готово":
                notes.append(status)
            if len(raw.decode("utf-8-sig",errors="replace"))>MAX_CHARS:
                notes.append("Анализ неполный: исходный текст превышает 350 000 символов.")
            section=""
            for i,line in enumerate(plain.splitlines(),1):
                if line.lstrip().startswith(("# ","## ","### ")):
                    section=line.strip("# ").strip()
                _append(items,"line",f"Строка {i}",line,section)
        else:
            notes.append("Формат не поддерживается для структурного анализа.")
    except (ValueError,KeyError,zipfile.BadZipFile,ET.ParseError,OverflowError,OSError) as error:
        notes.append("Не удалось структурно прочитать файл: "+type(error).__name__)
    except Exception as error:
        notes.append("Неожиданная ошибка формата: "+type(error).__name__)
    included=[]
    length=0
    for row in items:
        additional=len(row["text"])
        if len(included)>=MAX_SEGMENTS or length+additional>MAX_CHARS:
            notes.append("Анализ неполный: достигнут предел объёма текста или блоков.")
            break
        included.append(row)
        length+=additional
    return {"segments":included,"notes":list(dict.fromkeys(notes)),
            "complete":not notes,"characters":length}


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS document_segments(
          id INTEGER PRIMARY KEY,
          file_id TEXT NOT NULL REFERENCES files(id),
          file_sha TEXT NOT NULL,
          ordinal INTEGER NOT NULL,
          kind TEXT NOT NULL,
          locator TEXT NOT NULL,
          section TEXT NOT NULL,
          excerpt TEXT NOT NULL,
          UNIQUE(file_id,ordinal)
        );
        CREATE INDEX IF NOT EXISTS idx_document_segment_file
          ON document_segments(file_id,ordinal);
        CREATE TABLE IF NOT EXISTS document_coverage(
          file_id TEXT PRIMARY KEY REFERENCES files(id),
          file_sha TEXT NOT NULL,
          is_complete INTEGER NOT NULL,
          characters INTEGER NOT NULL,
          notes TEXT NOT NULL
        );
    """)


def remove(db,file_id):
    db.execute("DELETE FROM document_segments WHERE file_id=?",(file_id,))
    db.execute("DELETE FROM document_coverage WHERE file_id=?",(file_id,))


def store(db,file_id,sha,result):
    remove(db,file_id)
    db.executemany("""INSERT INTO document_segments
        (file_id,file_sha,ordinal,kind,locator,section,excerpt)
        VALUES(?,?,?,?,?,?,?)""",[
        (file_id,sha,i+1,row["kind"],row["locator"],row["section"],row["text"])
        for i,row in enumerate(result["segments"])])
    db.execute("""INSERT INTO document_coverage(file_id,file_sha,is_complete,characters,notes)
                  VALUES(?,?,?,?,?)""",
               (file_id,sha,int(result["complete"]),result["characters"],
                __import__("json").dumps(result["notes"],ensure_ascii=False)))


def _tokens(text):
    return [x.replace("ё","е") for x in WORD.findall(unicodedata.normalize(
        "NFKC",text).casefold()) if len(x)>=3 and x not in STOP]


def _matched(query,text):
    q=set(_tokens(query))
    t=set(_tokens(text))
    if not q or not t:
        return 0
    return sum(1 for word in q if word in t or
               (len(word)>=5 and any(item.startswith(word[:5]) for item in t)))


def _category(text):
    return [key for key,regex in CUES if regex.search(text)]


def findings(db,file_id,limit=80):
    rows=db.execute("""SELECT ordinal,kind,locator,section,excerpt
        FROM document_segments WHERE file_id=? ORDER BY ordinal""",(file_id,))
    result=[]
    for row in rows:
        tags=_category(row["excerpt"])
        dates=DATE.findall(row["excerpt"])
        if tags or dates:
            result.append({
                "segment":row["ordinal"],"locator":row["locator"],
                "categories":tags+ (["date"] if dates else []),
                "dates":dates[:8],"quote":row["excerpt"][:1000]
            })
        if len(result)>=limit:
            break
    return result


def possible_conflicts(db,file_id,limit=20):
    groups=defaultdict(list)
    for row in db.execute("""SELECT ordinal,locator,section,excerpt
        FROM document_segments WHERE file_id=? ORDER BY ordinal""",(file_id,)):
        match=CONFLICT.search(row["excerpt"])
        if not match:
            continue
        # Same phrasing except for number, within the same section: signal
        # review, not proof of legal or semantic contradiction.
        phrase=CONFLICT.sub("<VALUE>",row["excerpt"].casefold())
        prefix=tuple(_tokens(phrase)[:14])
        unit=(match.group(2) or "").casefold()
        if unit.startswith("дн"):
            unit="days"
        elif unit.startswith("руб"):
            unit="rub"
        key=(row["section"],prefix,unit)
        groups[key].append((match.group(1),row))
    result=[]
    for matches in groups.values():
        values={v for v,_ in matches}
        if len(values)<2:
            continue
        left=matches[0][1]
        right=next(row for v,row in matches if v!=matches[0][0])
        result.append({
            "kind":"possible_numeric_conflict","verified":False,
            "evidence":[{"segment":x["ordinal"],"locator":x["locator"],
                         "quote":x["excerpt"]} for x in (left,right)]
        })
        if len(result)>=limit:
            break
    return result


def answer(db,file_id,question,limit=5):
    if not isinstance(question,str) or not 3<=len(question.strip())<=600:
        raise ValueError("Вопрос должен содержать от 3 до 600 символов.")
    coverage=db.execute("""SELECT * FROM document_coverage WHERE file_id=?""",
                        (file_id,)).fetchone()
    if not coverage:
        raise ValueError("Документ не проиндексирован: загрузите его заново.")
    if "противореч" in question.casefold():
        clashes=possible_conflicts(db,file_id)
        return {"status":"potential_conflicts" if clashes else "not_found",
                "answer":"Обнаружены возможные несовпадения числовых условий. Нужна проверка контекста."
                         if clashes else "Прямых сопоставимых числовых расхождений не найдено; это не доказывает отсутствия иных противоречий.",
                "citations":[],"possible_conflicts":clashes,
                "complete":bool(coverage["is_complete"]),
                "limitations":__import__("json").loads(coverage["notes"])}
    tags=[]
    for trigger,key in (("обязан","obligation"),("обязательств","obligation"),
                        ("срок","deadline"),("дат","date"),("цель","purpose"),
                        ("огранич","restriction"),("исключени","exception"),
                        ("сторон","party"),("риск","risk"),("штраф","risk"),
                        ("причин","cause"),("вывод","conclusion")):
        if trigger in question.casefold():
            tags.append(key)
    scored=[]
    meaningful=set(_tokens(question))
    # A single incidental word ("номер", "отчёт", "срок") is not enough
    # evidence for a multi-concept question. A correct refusal is safer
    # than inventing an answer from one token of overlap.
    required=2 if len(meaningful)>=3 else 1
    for row in db.execute("""SELECT ordinal,kind,locator,section,excerpt FROM
        document_segments WHERE file_id=? ORDER BY ordinal""",(file_id,)):
        matched=_matched(question,row["excerpt"]+" "+row["section"])
        extra=sum(2 for tag in tags if tag in _category(row["excerpt"]) or
                  (tag=="date" and DATE.search(row["excerpt"])))
        if meaningful and matched>=required:
            scored.append((matched+extra,row))
    # Таблицы Excel: ответ на вопрос о названии показателя должен
    # включать его значение с соседней ячейки той же строки и того же
    # листа, а не только цитату заголовка или цифры с другого листа.
    by_sheet_row=defaultdict(list)
    for _,row in scored:
        if row["kind"]=="cell":
            address=re.fullmatch(r"(.+)!([A-Z]{1,3})([1-9][0-9]*)",row["locator"])
            if address:
                by_sheet_row[(address.group(1),address.group(3))].append(row)
    # Include unmatched adjacent cells too, but only when their labeled
    # partner already has a strong lexical match.
    if by_sheet_row:
        all_cells=db.execute("""SELECT ordinal,kind,locator,section,excerpt
            FROM document_segments WHERE file_id=? AND kind='cell'""",(file_id,)).fetchall()
        for row in all_cells:
            address=re.fullmatch(r"(.+)!([A-Z]{1,3})([1-9][0-9]*)",row["locator"])
            if address:
                group=(address.group(1),address.group(3))
                if group in by_sheet_row and not any(
                        prev["ordinal"]==row["ordinal"] for prev in by_sheet_row[group]):
                    by_sheet_row[group].append(row)
    scored.sort(key=lambda pair:(-pair[0],pair[1]["ordinal"]))
    selected=[]
    used=set()
    for score,row in scored:
        if row["ordinal"] in used:
            continue
        selected.append(row)
        used.add(row["ordinal"])
        if row["kind"]=="cell" and score>=1:
            addr=re.fullmatch(r"(.+)!([A-Z]{1,3})([1-9][0-9]*)",row["locator"])
            if addr:
                for neighbor in sorted(by_sheet_row.get((addr.group(1),addr.group(3)),[]),
                                       key=lambda n:n["ordinal"])[:6]:
                    if neighbor["ordinal"] not in used:
                        selected.append(neighbor)
                        used.add(neighbor["ordinal"])
        if len(selected)>=max(1,min(limit,10)):
            break
    top=selected[:max(1,min(limit,10))]
    citations=[{"segment":row["ordinal"],"locator":row["locator"],
                "quote":row["excerpt"][:1500]} for row in top]
    return {"status":"found" if citations else "not_found",
            "answer":("Найдены фрагменты исходного документа; выводы требуют проверки контекста."
                      if citations else "В доступном тексте нет достаточных оснований для ответа."),
            "citations":citations,"possible_conflicts":[],
            "complete":bool(coverage["is_complete"]),
            "limitations":__import__("json").loads(coverage["notes"])}


def overview(db,file_id):
    row=db.execute("""SELECT f.name,f.sha256,c.is_complete,c.characters,c.notes
        FROM files f JOIN document_coverage c ON c.file_id=f.id AND c.file_sha=f.sha256
        WHERE f.id=?""",(file_id,)).fetchone()
    if not row:
        raise ValueError("Документ не найден или пока не проиндексирован.")
    count=db.execute("SELECT COUNT(*) FROM document_segments WHERE file_id=?",(file_id,)).fetchone()[0]
    from document_deep_analysis import batches
    estimate=sum(1 for _ in batches(db.execute(
        "SELECT ordinal,locator,excerpt FROM document_segments WHERE file_id=? ORDER BY ordinal",
        (file_id,))))
    return {"file_id":file_id,"name":row["name"],"sha256":row["sha256"],
            "estimated_model_calls":estimate,
            "segment_count":count,"characters":row["characters"],
            "complete":bool(row["is_complete"]),
            "limitations":__import__("json").loads(row["notes"]),
            "findings":findings(db,file_id),"possible_conflicts":possible_conflicts(db,file_id)}
