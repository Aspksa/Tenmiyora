"""Reproducible real-format (but SYNTHETIC content) document fixtures.

Documents are valid OOXML/PDF containers generated without 3rd-party
writing libraries. Nothing uses private uploaded documents or networking.
Ground truth is maintained independently in document_quality_exam.py.
"""
from __future__ import annotations

from html import escape
import io
import zipfile

NS_W="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_S="http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _archive(parts):
    target=io.BytesIO()
    with zipfile.ZipFile(target,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,source in parts.items():
            z.writestr(name,source)
    return target.getvalue()


def contract_docx():
    """Long contract: 65 chapters, exceptions, warranty and contradictory terms."""
    blocks=[]
    def paragraph(line,heading=False):
        style='<w:pPr><w:pStyle w:val="Heading2"/></w:pPr>' if heading else ""
        blocks.append('<w:p>'+style+'<w:r><w:t xml:space="preserve">'+
                      escape(line)+'</w:t></w:r></w:p>')
    paragraph("Договор поставки инженерного оборудования",True)
    paragraph("Поставщик обязуется передать оборудование Покупателю в исправном состоянии.")
    paragraph("Покупатель обязан оплатить оборудование после подписания акта приёмки.")
    for i in range(1,66):
        paragraph(f"Раздел {i}. Порядок исполнения",True)
        paragraph(f"Пункт {i}.1. Стороны фиксируют состояние оборудования и журнал проверки номер {i}.")
        paragraph(f"Пункт {i}.2. Техническая спецификация по разделу {i} приведена в приложении.")
        if i==17:
            paragraph("Пункт 17.3. За исключением случаев непреодолимой силы Поставщик отвечает за просрочку доставки.")
        if i==32:
            paragraph("Пункт 32.3. Поставщик обязан устранить скрытые дефекты в течение 15 календарных дней.")
        if i==65:
            paragraph("Пункт 65.3. При условии направления письменного уведомления гарантия продлевается на 12 месяцев.")
    paragraph("Приложение А. Порядок оплаты",True)
    paragraph("Срок оплаты составляет 10 дней.")
    paragraph("Срок оплаты составляет 20 дней.")
    paragraph("Срок осмотра составляет 12 дней.")
    paragraph("Стоимость поставки составляет 200 рублей.")
    paragraph("Стоимость поставки составляет 200 шт.")
    blocks.append(
       '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Позиция</w:t></w:r></w:p></w:tc>'
       '<w:tc><w:p><w:r><w:t>Номенклатура</w:t></w:r></w:p></w:tc></w:tr>'
       '<w:tr><w:tc><w:p><w:r><w:t>01</w:t></w:r></w:p></w:tc>'
       '<w:tc><w:p><w:r><w:t>Насосный агрегат</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    )
    document=f'<w:document xmlns:w="{NS_W}"><w:body>{"".join(blocks)}</w:body></w:document>'
    return _archive({"word/document.xml":document})


def workbook_xlsx(sheets=None):
    """Multi-sheet workbook with shared strings, formulas and a hidden sheet."""
    if sheets is None:
        sheets=[
           ("Гараж",[["Техника","Количество"],["Автомобили","12"],["Гаражные карты","7"]],False),
           ("ГСМ",[["Стоимость дизельного топлива","3490.75"],["Объём топлива","230.5"],
                   ["Итого расходов","FORMULA:SUM(B1:B2)=3721.25"]],False),
           ("Табель",[["Сотрудник","Часы"],["Диспетчер","160"]],False),
           ("Архив",[["Архивный норматив","Норма 2024 года"]],True),
           ("Примечания",[["Основание исключения","Заявление утверждено только на бумаге"]],False),
        ]
    dictionary={}
    shared=[]
    def cell_value(value):
        if value.startswith("FORMULA:"):
            expr,number=value.removeprefix("FORMULA:").rsplit("=",1)
            return f"<f>{escape(expr)}</f><v>{escape(number)}</v>",""
        try:
            float(value)
        except ValueError:
            if value not in dictionary:
                dictionary[value]=len(shared)
                shared.append(value)
            return "<v>"+str(dictionary[value])+"</v>",' t="s"'
        return "<v>"+escape(value)+"</v>",""
    parts={}
    links=[]
    definitions=[]
    for number,(title,data,is_hidden) in enumerate(sheets,1):
        source=f"xl/worksheets/sheet{number}.xml"
        rows=[]
        for row_index,entries in enumerate(data,1):
            cells=[]
            for col_index,val in enumerate(entries):
                col=chr(65+col_index)
                xml,typ=cell_value(val)
                cells.append(f'<c r="{col}{row_index}"{typ}>{xml}</c>')
            rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        parts[source]=(f'<worksheet xmlns="{NS_S}"><sheetData>{"".join(rows)}</sheetData>'
                       '</worksheet>')
        state=' state="hidden"' if is_hidden else ""
        definitions.append(f'<sheet name="{escape(title,quote=True)}" sheetId="{number}" r:id="rId{number}"{state}/>')
        links.append(f'<Relationship Id="rId{number}" Type="worksheet" Target="worksheets/sheet{number}.xml"/>')
    parts["xl/workbook.xml"]=(f'<workbook xmlns="{NS_S}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(definitions)}</sheets></workbook>')
    parts["xl/_rels/workbook.xml.rels"]=(
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(links) + "</Relationships>")
    parts["xl/sharedStrings.xml"]=(f'<sst xmlns="{NS_S}">'
        + "".join(f'<si><t>{escape(x)}</t></si>' for x in shared)+"</sst>")
    return _archive(parts)


def pdf_report():
    """Eight-page valid text-layer PDF with long-distance annex evidence."""
    pages=[
        ["Document audit report","Executive summary and scope of review.",
         "The management summary does not state any warranty exclusion."],
        ["Payment terms","Invoice payment term is 14 calendar days.",
         "The invoice is issued after acceptance."],
        ["Delivery schedule","The goods must reach the depot before inspection.",
         "The route uses multiple inspection checkpoints."],
        ["Risk review","Risk exceptions are recorded in appendix C.",
         "Reviewers must not presume a missing rule is satisfied."],
        ["Audit references","Technical drawings are stored separately.",
         "The inspection committee reviewed the appendix references."],
        ["Inspection notes","The acceptance test covers pressure and flow.",
         "The quality records are available for the final inspection."],
        ["Annex C - Warranty exclusions",
         "Extended warranty excludes corrosion caused by salt water.",
         "The warranty requires written acceptance of the repair."],
        ["Appendix D - Closing statement","Final approval is dated 2026-03-12.",
         "No launch authorization code is provided in this report."],
    ]
    objects={}
    objects[1]=b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[3]=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    pages_ids=[]
    index=4
    for lines in pages:
        page_id=index;stream_id=index+1;index+=2
        pages_ids.append(page_id)
        commands=["BT","/F1 12 Tf","55 755 Td"]
        for i,line in enumerate(lines):
            if i:
                commands.append("0 -25 Td")
            value=line.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
            commands.append(f"({value}) Tj")
        commands.append("ET")
        content=("\n".join(commands)+"\n").encode("ascii")
        objects[stream_id]=(f"<< /Length {len(content)} >>\nstream\n").encode() + content + b"endstream"
        objects[page_id]=(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                        f"/Contents {stream_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>").encode()
    kids=" ".join(f"{i} 0 R" for i in pages_ids)
    objects[2]=(f"<< /Type /Pages /Count {len(pages_ids)} /Kids [{kids}] >>").encode()
    buffer=io.BytesIO()
    buffer.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets=[0]
    for idx in range(1,max(objects)+1):
        offsets.append(buffer.tell())
        buffer.write(f"{idx} 0 obj\n".encode())
        buffer.write(objects[idx])
        buffer.write(b"\nendobj\n")
    crossref=buffer.tell()
    buffer.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode())
    buffer.write(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n".encode())
    buffer.write(f"startxref\n{crossref}\n%%EOF\n".encode())
    return buffer.getvalue()
