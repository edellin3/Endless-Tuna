"""Inspect actual downloaded acceptance artifacts, without model/network access."""
import argparse
import io
import json
import zipfile
from openpyxl import load_workbook
from pypdf import PdfReader

parser=argparse.ArgumentParser();parser.add_argument('workbook');parser.add_argument('bundle');args=parser.parse_args()
wb=load_workbook(args.workbook,read_only=True,data_only=False)
expected=['Conferences','Papers','Paper Authors','Affiliations','Sources','Missing PDFs','Review Queue']
assert wb.sheetnames==expected
rows={name:list(wb[name].values) for name in wb.sheetnames}
assert all(cell.data_type!='f' for sheet in wb for row in sheet for cell in row)
headers=rows['Papers'][0];paper_ids={row[headers.index('paper_id')] for row in rows['Papers'][1:]}
assert len(paper_ids)>=5
ah=rows['Paper Authors'][0]
assert all(row[ah.index('paper_id')] in paper_ids for row in rows['Paper Authors'][1:])
assert len(rows['Missing PDFs'])-1>=2
with zipfile.ZipFile(args.bundle) as archive:
    assert 'manifest.json' in archive.namelist() and 'missing-files.csv' in archive.namelist()
    manifest=json.loads(archive.read('manifest.json'))
    assert manifest['scope']['collection_scope']=='conference'
    included=[i for i in manifest['items'] if i['status']=='included']
    assert len(included)>=3
    for item in included:
        assert item['paper_id'] in paper_ids
        assert not item['archive_name'].startswith('/') and '..' not in item['archive_name'].split('/')
        assert len(PdfReader(io.BytesIO(archive.read(item['archive_name']))).pages)>0
print(json.dumps({'sheets':wb.sheetnames,'workbook_unique_papers':len(paper_ids),'bundle_included_papers':len(included),'bundle_missing_papers':len(manifest['items'])-len(included),'all_formula_cells_absent':True}))
