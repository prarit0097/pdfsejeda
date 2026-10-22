"""Notify IndexNow about public sitemap URLs after ownership-file verification.

Dry-run by default; --submit explicitly sends one batch. No Google index claim.
Reads INDEXNOW_KEY and SITE_URL from the configured environment. Never uploads
documents/results or discovers URLs outside the canonical origin.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import httpx
from app.config import settings


def payload_from_sitemap(xml,origin,key):
    import re
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}",key): raise ValueError("Configure a valid INDEXNOW_KEY first")
    urls=[node.text for node in ET.fromstring(xml).findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    if not urls or len(urls)>10000 or len(set(urls))!=len(urls): raise ValueError("Invalid sitemap URL inventory")
    for url in urls:
        if not isinstance(url,str): raise ValueError("Invalid sitemap URL")
        parsed=urlsplit(url)
        if parsed.scheme+"://"+parsed.netloc!=origin or parsed.query or parsed.fragment or unquote(parsed.path).startswith(("/api/","/result")):
            raise ValueError("Only canonical public URLs may be submitted")
    return {"host":urlsplit(origin).netloc,"key":key,"keyLocation":origin+"/indexnow-key.txt","urlList":urls}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--submit",action="store_true")
    parser.add_argument("--report",type=Path,default=ROOT/"data-qa-seo/indexnow-result.json")
    args=parser.parse_args()
    with httpx.Client(timeout=30,follow_redirects=False) as client:
        response=client.get(settings.site_url+"/sitemap.xml");response.raise_for_status()
        payload=payload_from_sitemap(response.content,settings.site_url,settings.indexnow_key)
        key_file=client.get(payload["keyLocation"]);key_file.raise_for_status()
        if key_file.text.strip()!=settings.indexnow_key: raise ValueError("Live ownership file does not match configured key")
        report={"host":payload["host"],"url_count":len(payload["urlList"]),"key_file_verified":True,"submitted":False,"meaning":"Notification acceptance is not crawling, indexing or ranking confirmation"}
        if args.submit:
            response=client.post("https://api.indexnow.org/indexnow",json=payload)
            report.update(submitted=True,http_status=response.status_code,accepted=response.status_code in (200,202))
            if not report["accepted"]: report["response_excerpt"]=response.text[:300]
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report))
        return int(args.submit and not report.get("accepted"))


if __name__=="__main__": raise SystemExit(main())
