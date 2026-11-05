"""Generator for the hand-made rail GTFS in pipeline/travel/rail_gtfs/ (output is committed CSV).

Usage: pdftotext -layout <LNR Bletchley-Bedford PDF> lnr.txt; python3 make_rail_gtfs.py lnr.txt rail_gtfs
PDF: https://www.londonnorthwesternrailway.co.uk/media/44855/download (valid 18 May-11 Dec 2026).
Marston Vale Mon-Fri trains are transcribed train by train. Thameslink / EMR Bedford-Luton are
MODELLED headway templates (frequencies.txt, exact_times=1) from the Summer 2026 weekday pattern."""
import re,sys,csv
lines=open(sys.argv[1]).read().split('\n'); out=sys.argv[2]
NAME2ID={"Bletchley":"9100BLTCHLY","Fenny Stratford":"9100FSTR","Bow Brickhill":"9100BOWBRKH","Woburn Sands":"9100WOBURNS","Aspley Guise":"9100ASPLEYG","Ridgmont":"9100RIDGMNT","Lidlington":"9100LDLNGTN","Millbrook":"9100MLBRKB","Stewartby":"9100STWRTBY","Kempston Hardwick":"9100KMPSTNH","Bedford St Johns":"9100BESJOHN","Bedford":"9100BEDFDM"}
pages=[];cur=None
for l in lines:
    m=re.match(r'\f?(Mondays to Fridays|Saturdays) \(Valid',l)
    if m: cur={'day':m.group(1),'dir':None,'rows':[]};pages.append(cur);continue
    if cur is None: continue
    if cur['dir'] is None and ('Bletchley – Bedford' in l or 'Bedford – Bletchley' in l): cur['dir']=l.strip()
    cur['rows'].append(l)
trips=[]
for p in pages:
    if p['day']!='Mondays to Fridays': continue
    rows={}
    for l in p['rows']:
        m=re.match(r'\s*(?:\) )?([A-Za-z ]+?) ([ad])\s',l)
        if not m: continue
        rows.setdefault((m.group(1).strip(),m.group(2)),[(mm.start(),mm.group()) for mm in re.finditer(r'\b\d{4}\b',l)])
    for pos,_ in rows.get(('Kempston Hardwick','d'),[]):
        def at(key):
            for pp,tt in rows.get(key,[]):
                if abs(pp-pos)<=1: return tt
        nb = p['dir'].startswith('Bletchley')
        order=list(NAME2ID) if nb else list(NAME2ID)[::-1]
        st=[]
        for i,n in enumerate(order):
            first=i==0; last=i==len(order)-1
            t=at((n,'a')) if last else at((n,'d'))
            if t: st.append((NAME2ID[n],t))
        trips.append(('NB' if nb else 'SB',st))
def hms(t,base=None):
    h,m=int(t[:2]),int(t[2:])
    return f"{h:02d}:{m:02d}:00"
T=[];ST=[];F=[]
for i,(d,st) in enumerate(trips):
    tid=f"MV_{d}_{st[0][1]}"
    T.append(("MV","WKDY",tid,"Bedford" if d=="NB" else "Bletchley"))
    for seq,(sid,t) in enumerate(st,1): ST.append((tid,hms(t),hms(t),sid,seq))
# Modelled frequency services (offsets in minutes from first stop)
def tmpl(route,tid,head,start,stops,bands):
    T.append((route,"WKDY",tid,head))
    h,m=map(int,start.split(':')); s=h*60+m
    for seq,(sid,o) in enumerate(stops,1):
        x=s+o; ST.append((tid,f"{x//60:02d}:{x%60:02d}:00",f"{x//60:02d}:{x%60:02d}:00",sid,seq))
    for a,b,hw in bands: F.append((tid,a,b,hw*60,1))
TL_SB=[("9100BEDFDM",0),("9100FLITWCK",10),("9100HRLG",14),("9100LEAGRVE",20),("9100LUTON",25),("9100LUTOAPY",28)]
TL_NB=[("9100LUTOAPY",0),("9100LUTON",3),("9100LEAGRVE",7),("9100HRLG",13),("9100FLITWCK",17),("9100BEDFDM",29)]
EM_SB=[("9100BEDFDM",0),("9100LUTON",15),("9100LUTOAPY",18)]
EM_NB=[("9100LUTOAPY",0),("9100LUTON",3),("9100BEDFDM",18)]
tmpl("TLB","TL_SB_day","Luton Airport Parkway","05:16",TL_SB,[("05:16:00","21:47:00",15)])
tmpl("TLB","TL_SB_late","Luton Airport Parkway","22:14",TL_SB,[("22:14:00","23:45:00",30)])
tmpl("TLB","TL_NB_day","Bedford","05:31",TL_NB,[("05:31:00","22:56:00",15)])
tmpl("TLB","TL_NB_late","Bedford","23:10",TL_NB,[("23:10:00","24:56:00",15)])
tmpl("EMC","EM_SB_day","Luton Airport Parkway","06:10",EM_SB,[("06:10:00","21:11:00",30)])
tmpl("EMC","EM_SB_2211","Luton Airport Parkway","22:11",EM_SB,[])
tmpl("EMC","EM_SB_2303","Luton Airport Parkway","23:03",EM_SB,[])
tmpl("EMC","EM_NB_day","Bedford","06:07",EM_NB,[("06:07:00","22:38:00",30)])
def w(name,hdr,rows):
    with open(f"{out}/{name}","w",newline="") as f:
        c=csv.writer(f,lineterminator="\n"); c.writerow(hdr); c.writerows(rows)
w("trips.txt",["route_id","service_id","trip_id","trip_headsign"],T)
w("stop_times.txt",["trip_id","arrival_time","departure_time","stop_id","stop_sequence"],ST)
w("frequencies.txt",["trip_id","start_time","end_time","headway_secs","exact_times"],F)
print(len(T),"trips",len(ST),"stop_times",len(F),"freq bands; MV trips:",sum(1 for t in T if t[0]=="MV"))
