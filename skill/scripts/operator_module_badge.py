"""Read one equipped module badge from guest 1920x1080 operator-detail OCR.

Input: JSON list of [text, centre_x, centre_y] from the same frame. Read-only.
"""
import argparse
import json
import re
from pathlib import Path


def badge(rows, name, branch):
    def texts(left,top,right,bottom):
        return {str(s).strip() for s,x,y in rows if left<=x<=right and top<=y<=bottom}
    if name not in texts(0,670,625,865):
        raise ValueError("operator name not verified")
    codes={s.upper().replace('-','').replace(' ','') for s in texts(1580,828,1745,895)
           if re.fullmatch(r'[A-Z]{2,4}[- ]?[XYDΔ]',s.upper())}
    grades={int(m[1]) for s in texts(1700,775,1880,842)
            if (m:=re.fullmatch(r'STAGE\s*([123])',s,re.I))}
    if codes!={branch.upper().replace('-','').replace(' ','')} or len(grades)!=1:
        raise ValueError("equipped branch or grade not verified")
    return {'operator':name,'branch':branch,'observed_grade':grades.pop()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rows',type=Path);parser.add_argument('name');parser.add_argument('branch')
    args=parser.parse_args()
    print(json.dumps(badge(json.loads(args.rows.read_text(encoding='utf-8-sig')),args.name,args.branch),ensure_ascii=False))
