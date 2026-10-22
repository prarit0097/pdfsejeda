from html.parser import HTMLParser

class Head(HTMLParser):
    def __init__(self,text):
        super().__init__();self.meta={};self.canonical=[];self.jsonld=[];self.current=None;self.title="";self.h1=0
        self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="meta": self.meta[a.get("name",a.get("property"))]=a.get("content")
        if tag=="link" and a.get("rel")=="canonical":self.canonical.append(a["href"])
        if tag=="title":self.current="title"
        if tag=="script" and a.get("type")=="application/ld+json":self.current="json";self.jsonld.append("")
        if tag=="h1":self.h1+=1
    def handle_endtag(self,tag):
        if tag in ("title","script"):self.current=None
    def handle_data(self,data):
        if self.current=="title":self.title+=data
        if self.current=="json":self.jsonld[-1]+=data


