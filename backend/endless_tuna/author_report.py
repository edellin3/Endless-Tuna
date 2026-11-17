"""Paginated, searchable PDF reports with escaped source text and Unicode fonts."""
from pathlib import Path
from xml.sax.saxutils import escape
import reportlab
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

FONT='TunaReport'
pdfmetrics.registerFont(TTFont(FONT,str(Path(reportlab.__file__).parent/'fonts'/'Vera.ttf')))
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
STYLE=ParagraphStyle('record',fontName=FONT,fontSize=9,leading=13,textColor=HexColor('#17243B'),splitLongWords=True)


def text(value):
    # The bundled font covers Latin, Greek and Cyrillic; use a standard CJK font
    # for other scripts instead of dropping source characters during encoding.
    output=[]
    for char in str(value or ''):
        if ord(char)<32 and char not in '\n\t':continue
        encoded=escape(char)
        if ord(char) not in pdfmetrics.getFont(FONT).face.charToGlyph:
            encoded='<font name="STSong-Light">'+encoded+'</font>'
        output.append(encoded)
    return ''.join(output).replace('\n','<br/>')


def write_report(stream,records,*,conference,year,collection,q,status,missing_rosters):
    canvas=Canvas(stream,pagesize=(612,792),pageCompression=1)
    canvas.setTitle(f'{conference} {year} - Authors and institutions')
    canvas.setAuthor('endless tuna')
    y=0;page=0
    def new_page():
        nonlocal y,page
        if page:canvas.showPage()
        page+=1
        canvas.setFont(FONT,10);canvas.setFillColor(HexColor('#2459D3'))
        canvas.drawString(42,758,'endless tuna | Authors & institutions')
        canvas.setFont(FONT,8);canvas.setFillColor(HexColor('#53627A'))
        canvas.drawString(42,28,f'Collection: {collection}'+(' - FICTIONAL DEMO DATA' if collection=='demo' else ''))
        canvas.drawRightString(570,28,f'Page {page}')
        y=735
    def paragraph(label,value):
        nonlocal y
        pending=[Paragraph(text(label)+text(value),STYLE)]
        while pending:
            item=pending.pop(0)
            _,height=item.wrap(528,y-48)
            if height<=y-48:
                item.drawOn(canvas,42,y-height);y-=height+5
            else:
                pieces=item.split(528,y-48)
                if pieces:
                    first=pieces.pop(0);_,height=first.wrap(528,y-48)
                    first.drawOn(canvas,42,y-height);y-=height+5
                    pending=pieces+pending
                new_page()
    new_page()
    paragraph('',f'{conference} {year}')
    paragraph('Scope: ',f'Search: {q or "all records"}; institution evidence: {status or "all statuses"}. All matching pages included.')
    paragraph('',f'Papers without an author roster: {missing_rosters}. Missing institutions are shown explicitly. Extracted evidence is unverified until analyst review. Download completion does not establish complete institution coverage.')
    count=0
    for row in records:
        count+=1
        if y<180:new_page()
        paragraph('',f'{count}. {row["author"]} | Author position {row["author_position"]}')
        paragraph('Institution: ',row['institution'] or 'Not extracted')
        paragraph('Paper: ',row['paper_title'])
        paragraph('IDs: ',f'paper {row["paper_id"]}; author {row["author_id"]}')
        paragraph('Evidence status: ',row['status']+(' (unverified)' if row['status'] in ('extracted','needs_review') else ''))
        paragraph('Extraction: ',row['extraction_status'])
        if row['extraction_error']:paragraph('Extraction issue: ',row['extraction_error'])
        if row['excerpt']:
            paragraph('Source: ',f'{row["source_url"]}'+(f' | PDF page {row["page"]}' if row['page'] else ''))
            paragraph('Method: ',row['method'])
            paragraph('Evidence: ',row['excerpt'])
        y-=10
    paragraph('',f'{count} matching author-institution rows.' if count else 'No matching author records.')
    canvas.save()
