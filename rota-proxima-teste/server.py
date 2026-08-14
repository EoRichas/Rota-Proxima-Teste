#!/usr/bin/env python3
import io, json, math, mimetypes, os, urllib.parse, urllib.request, time, threading, base64, uuid
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, Table, Image

BASE_DIR=Path(__file__).resolve().parent
STATIC_DIR=BASE_DIR/'static'
HOST=os.environ.get('ROTA_HOST','0.0.0.0')
# Render define PORT automaticamente (padrao 10000). Localmente continua 8080.
PORT=int(os.environ.get('PORT') or os.environ.get('ROTA_PORT','8080'))
IS_RENDER=os.environ.get('RENDER','').strip().lower()=='true'
FORCE_SECURE_COOKIES=IS_RENDER or os.environ.get('FORCE_SECURE_COOKIES','').strip().lower() in ('1','true','yes','on')
SUPABASE_URL=os.environ.get('SUPABASE_URL','https://wzonboudahxbyzoxnehx.supabase.co').rstrip('/')
SUPABASE_KEY=os.environ.get('SUPABASE_PUBLISHABLE_KEY','sb_publishable_DEYdfPXQNKi6Eot4mZgVfA_eR5GvkS0')
REST=f'{SUPABASE_URL}/rest/v1'
AUTH=f'{SUPABASE_URL}/auth/v1'
ADMIN_FN=f'{SUPABASE_URL}/functions/v1/rota-admin'
USER_AGENT='RotaProxima/3.0'
PRIORITY_FACTOR={'urgent':.55,'high':.78,'normal':1.0,'low':1.18}
SERVICE_TYPE_LABEL={'collection':'Coleta','delivery':'Entrega'}
BUILD_ID='TESTE-BROWSER-SYNC-FOTOS-2026-08-14'

HTTP=requests.Session()
HTTP.mount('https://', HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=1))
HTTP.mount('http://', HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1))
_AUTH_CACHE={}
_AUTH_CACHE_LOCK=threading.Lock()
_AUTH_CACHE_TTL=120
_AUTH_FETCH_LOCK=threading.Lock()
_AUTH_REFRESH_LOCK=threading.Lock()
_REFRESH_RESULT_CACHE={}
_REFRESH_RESULT_TTL=15
_CEP_CACHE={}
_CEP_CACHE_LOCK=threading.Lock()
_CEP_CACHE_TTL=86400
_GEO_CACHE={}
_GEO_CACHE_LOCK=threading.Lock()
_GEO_CACHE_TTL=604800
_NOMINATIM_LOCK=threading.Lock()
_NOMINATIM_LAST=0.0


def now_iso(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def clean_cep(v): return ''.join(c for c in str(v or '') if c.isdigit())
def hms(v): return str(v or '')[:5]
def num(v):
    try: return float(v) if v not in ('',None) else None
    except: return None

def fetch_json(url,timeout=15,headers=None):
    # Reaproveita conexões TCP/TLS para serviços externos (CEP, mapa e OSRM).
    r=HTTP.get(url,headers={'User-Agent':USER_AGENT,**(headers or {})},timeout=timeout)
    r.raise_for_status()
    return r.json()

def viacep_lookup(cep):
    c=clean_cep(cep)
    if len(c)!=8: raise ValueError('CEP deve ter 8 dígitos')
    now=time.monotonic()
    with _CEP_CACHE_LOCK:
        cached=_CEP_CACHE.get(c)
        if cached and cached[0] > now:
            return dict(cached[1])
    d=fetch_json(f'https://viacep.com.br/ws/{c}/json/', timeout=8)
    if d.get('erro'): raise ValueError('CEP não encontrado')
    result={'cep':d.get('cep',''),'street':d.get('logradouro',''),'district':d.get('bairro',''),'city':d.get('localidade',''),'state':d.get('uf','')}
    with _CEP_CACHE_LOCK:
        _CEP_CACHE[c]=(now+_CEP_CACHE_TTL,dict(result))
        if len(_CEP_CACHE)>1000:
            expired=[k for k,v in _CEP_CACHE.items() if v[0] <= now]
            for k in expired:_CEP_CACHE.pop(k,None)
    return result

def _nominatim_search(q):
    # O serviço público pede baixa frequência. Serializamos chamadas para evitar
    # bloqueios/rate-limit quando uma rota possui vários PEVs ainda sem coordenadas.
    global _NOMINATIM_LAST
    with _NOMINATIM_LOCK:
        wait=1.05-(time.monotonic()-_NOMINATIM_LAST)
        if wait>0: time.sleep(wait)
        try:
            url='https://nominatim.openstreetmap.org/search?'+urllib.parse.urlencode({'q':q,'format':'jsonv2','limit':1,'countrycodes':'br'})
            d=fetch_json(url,timeout=8)
        finally:
            _NOMINATIM_LAST=time.monotonic()
    if d:return float(d[0]['lat']),float(d[0]['lon'])
    return None

def _brasilapi_cep_coords(cep):
    c=clean_cep(cep)
    if len(c)!=8:return None
    try:
        d=fetch_json(f'https://brasilapi.com.br/api/cep/v2/{c}',timeout=6)
        loc=(d or {}).get('location') or {};coords=loc.get('coordinates') or {}
        lat=num(coords.get('latitude'));lng=num(coords.get('longitude'))
        if lat is not None and lng is not None:return lat,lng
    except Exception:pass
    return None

def geocode_address_detailed(addr):
    key='|'.join(str(addr.get(k,'') or '').strip().lower() for k in ('street','number','district','city','state','cep'))
    now=time.monotonic()
    with _GEO_CACHE_LOCK:
        cached=_GEO_CACHE.get(key)
        if cached and cached[0]>now:return cached[1]
    precise=', '.join(x for x in [f"{addr.get('street','')} {addr.get('number','')}".strip(),addr.get('district',''),addr.get('city',''),addr.get('state',''),clean_cep(addr.get('cep','')),'Brasil'] if x)
    generic=', '.join(x for x in [addr.get('street',''),addr.get('district',''),addr.get('city',''),addr.get('state',''),clean_cep(addr.get('cep','')),'Brasil'] if x)
    result=None;source=None;confirmed=False
    try:
        result=_nominatim_search(precise)
        if result is not None: source='nominatim_address'; confirmed=bool(addr.get('street') and addr.get('number') and addr.get('city'))
    except Exception: result=None
    if result is None and generic!=precise:
        try:
            result=_nominatim_search(generic)
            if result is not None: source='nominatim_street'; confirmed=False
        except Exception: result=None
    if result is None:
        result=_brasilapi_cep_coords(addr.get('cep'))
        if result is not None: source='brasilapi_cep'; confirmed=False
    if result is None:raise ValueError('Não foi possível localizar o endereço no mapa. Confirme latitude/longitude no cadastro da PEV.')
    payload={'lat':float(result[0]),'lng':float(result[1]),'source':source,'confirmed':confirmed}
    with _GEO_CACHE_LOCK:_GEO_CACHE[key]=(now+_GEO_CACHE_TTL,payload)
    return payload

def geocode_address(addr):
    d=geocode_address_detailed(addr);return d['lat'],d['lng']

def haversine(a,b):
    R=6371000; p=math.pi/180; la1,lo1=a[0]*p,a[1]*p; la2,lo2=b[0]*p,b[1]*p
    x=math.sin((la2-la1)/2)**2+math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(x))

def build_fallback_matrix(points):
    d=[[haversine(a,b)*1.25 for b in points] for a in points]
    t=[[x/10 for x in row] for row in d]
    return d,t,'haversine'

def osrm_matrix(points):
    coords=';'.join(f'{p[1]:.6f},{p[0]:.6f}' for p in points)
    try:
        d=fetch_json(f'https://router.project-osrm.org/table/v1/driving/{coords}?annotations=distance,duration',timeout=20)
        if d.get('code')=='Ok' and d.get('distances') and d.get('durations'): return d['distances'],d['durations'],'osrm'
    except: pass
    return build_fallback_matrix(points)

def route_cost(order,dist,priorities,return_origin=False):
    total=0;prev=0;legs=[]
    for i in order:
        x=dist[prev][i] or 0;legs.append(x);total+=x;prev=i
    if return_origin and order: total+=dist[prev][0] or 0
    avg=max(1,sum(legs)/len(legs) if legs else 1)
    for pos,i in enumerate(order):
        p=priorities.get(i,'normal')
        if p=='urgent': total+=pos*avg*.42
        elif p=='high': total+=pos*avg*.18
        elif p=='low': total-=pos*avg*.03
    return total

def optimize_order(dist,priorities,return_origin=False,mode='best'):
    remaining=set(range(1,len(dist)));order=[];cur=0
    while remaining:
        nxt=min(remaining,key=lambda i:(dist[cur][i] if dist[cur][i] is not None else 10**12)*PRIORITY_FACTOR.get(priorities.get(i,'normal'),1))
        order.append(nxt);remaining.remove(nxt);cur=nxt
    if mode=='nearest' or len(order)<4:return order
    best=order[:];best_cost=route_cost(best,dist,priorities,return_origin);changed=True;passes=0
    while changed and passes<12:
        changed=False;passes+=1
        for i in range(len(best)-1):
            for j in range(i+2,len(best)+1):
                cand=best[:i]+list(reversed(best[i:j]))+best[j:]
                c=route_cost(cand,dist,priorities,return_origin)
                if c+.5<best_cost:best,best_cost,changed=cand,c,True
    return best

def hhmm_to_minutes(v):
    try:
        h,m=str(v or '')[:5].split(':');h=int(h);m=int(m)
        return h*60+m if 0<=h<24 and 0<=m<60 else None
    except:return None

def optimize_order_with_exact_times(dist,durations,priorities,exact_times,start_minute,mode='best'):
    if start_minute is None or not exact_times:return optimize_order(dist,priorities,False,mode),[]
    remaining=set(range(1,len(dist)));timed=[]
    for idx,val in exact_times.items():
        m=hhmm_to_minutes(val)
        if m is not None and idx in remaining: timed.append((m,idx,val))
    timed.sort();timed_ids={x[1] for x in timed};order=[];warnings=[];cur=0;clock=float(start_minute)
    for appt,idx,label in timed:
        if idx not in remaining:continue
        while True:
            choices=[]
            for i in remaining:
                if i==idx or i in timed_ids:continue
                t1=(durations[cur][i] or 10**12)/60;t2=(durations[i][idx] or 10**12)/60
                if clock+t1+t2<=appt-5:
                    score=(dist[cur][i] or 10**12)*PRIORITY_FACTOR.get(priorities.get(i,'normal'),1)
                    choices.append((score,i,t1))
            if not choices:break
            _,pick,t1=min(choices);clock+=t1;order.append(pick);remaining.remove(pick);cur=pick
        arr=clock+(durations[cur][idx] or 0)/60
        if arr>appt+2:
            hh=int(arr//60)%24;mm=int(arr%60);warnings.append(f'Compromisso {label}: previsão {hh:02d}:{mm:02d}, com atraso estimado.')
        clock=max(arr,appt);order.append(idx);remaining.remove(idx);cur=idx
    while remaining:
        nxt=min(remaining,key=lambda i:(dist[cur][i] or 10**12)*PRIORITY_FACTOR.get(priorities.get(i,'normal'),1))
        clock+=(durations[cur][nxt] or 0)/60;order.append(nxt);remaining.remove(nxt);cur=nxt
    return order,warnings


def collection_report_items(token,date_from,date_to):
    routes=Supa.get('routes',token,{
        'select':'id,name,route_date,status,driver_id,profiles!routes_driver_id_fkey(name)',
        'and':f'(route_date.gte.{date_from},route_date.lte.{date_to})',
        'order':'route_date.desc,id.desc'
    })
    if not routes:return []
    route_map={int(r['id']):r for r in routes};ids=','.join(str(x) for x in route_map)
    stops=Supa.get('route_stops',token,{
        'route_id':f'in.({ids})',
        'select':'id,route_id,pev_id,request_id,sequence,status,service_type,exact_time,arrived_at,completed_at,failure_reason,driver_note,collected_weight_kg,pevs(name,street,number,district,city,state,cep,contact_name,phone,commercial_owner_id,profiles!pevs_commercial_owner_id_fkey(id,name)),scheduling_requests(requested_by,profiles!scheduling_requests_requested_by_fkey(name))',
        'order':'route_id.desc,sequence.asc'
    })
    weighing_rows=Supa.get('route_weighings',token,{'route_id':f'in.({ids})','select':'stop_id,weight_kg'}) or []
    weight_by_stop={int(w['stop_id']):w.get('weight_kg') for w in weighing_rows if w.get('stop_id') is not None}
    items=[]
    for st in stops:
        st['collected_weight_kg']=weight_by_stop.get(int(st['id']),st.get('collected_weight_kg'))
        r=route_map.get(int(st['route_id'])) or {};drv=r.get('profiles') or {};pev=st.pop('pevs',{}) or {};req=st.pop('scheduling_requests',{}) or {};requester=req.get('profiles') or {};owner=pev.pop('profiles',{}) or {}
        items.append({
            **st,'route_name':r.get('name',''),'route_date':r.get('route_date'),'route_status':r.get('status'),
            'driver_id':r.get('driver_id'),'driver_name':drv.get('name',''),
            'pev_name':pev.get('name',''),'street':pev.get('street',''),'number':pev.get('number',''),'district':pev.get('district',''),
            'city':pev.get('city',''),'state':pev.get('state',''),'cep':pev.get('cep',''),'contact_name':pev.get('contact_name',''),'contact_phone':pev.get('phone',''),
            'requested_by_name':requester.get('name',''),'commercial_owner_id':pev.get('commercial_owner_id'),'commercial_owner_name':owner.get('name','')
        })
    return items

def commercial_portfolio_summary(token):
    rows=Supa.get('pevs',token,{'deleted_at':'is.null','active':'eq.true','select':'id,commercial_owner_id,profiles!pevs_commercial_owner_id_fkey(id,name)'})
    out={}
    for row in rows:
        owner=row.get('profiles') or {};oid=str(row.get('commercial_owner_id') or '')
        if not oid:continue
        g=out.setdefault(oid,{'name':owner.get('name') or 'Comercial','pevs':0})
        g['pevs']+=1
    return out

def filter_collection_report(items,status='all',service_type='all',search='',pev='all',route='all',commercial='all'):
    q=(search or '').strip().lower()
    out=[]
    for x in items:
        if status!='all' and x.get('status')!=status:continue
        if service_type!='all' and x.get('service_type','collection')!=service_type:continue
        if pev!='all' and str(x.get('pev_id') or '')!=str(pev):continue
        if route!='all' and str(x.get('route_id') or '')!=str(route):continue
        if commercial!='all' and str(x.get('commercial_owner_id') or '')!=str(commercial):continue
        if q:
            hay=' '.join(str(x.get(k) or '') for k in ('pev_name','city','state','route_name','requested_by_name','commercial_owner_name','failure_reason','driver_note')).lower()
            if q not in hay:continue
        out.append(x)
    return out

def _pdf_text(v):
    return str(v or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def build_collections_pdf(items,date_from,date_to,filters=None):
    filters=filters or {}
    buf=io.BytesIO();styles=getSampleStyleSheet()
    green=colors.HexColor('#0B4F2F');green2=colors.HexColor('#176B43');gold=colors.HexColor('#B8860B')
    pale=colors.HexColor('#F5F8F5');line=colors.HexColor('#D8E0DA');muted=colors.HexColor('#5E6862');red=colors.HexColor('#A23A2A')
    title=ParagraphStyle('ReportTitle',parent=styles['Title'],fontName='Helvetica-Bold',fontSize=23,leading=27,textColor=green,spaceAfter=5)
    subtitle=ParagraphStyle('Subtitle',parent=styles['BodyText'],fontName='Helvetica',fontSize=8.5,leading=11,textColor=muted)
    small=ParagraphStyle('Small',parent=styles['BodyText'],fontName='Helvetica',fontSize=7.2,leading=9,textColor=colors.HexColor('#25312B'))
    small_b=ParagraphStyle('SmallB',parent=small,fontName='Helvetica-Bold',textColor=green)
    kpi_label=ParagraphStyle('KpiLabel',parent=small,fontName='Helvetica-Bold',fontSize=7.2,alignment=TA_CENTER,textColor=muted)
    kpi_num=ParagraphStyle('KpiNum',parent=styles['BodyText'],fontName='Helvetica-Bold',fontSize=17,leading=19,alignment=TA_CENTER,textColor=green)
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=28,leftMargin=28,topMargin=24,bottomMargin=34,title='Relatório Operacional de Coletas e Entregas - Cassola Ambiental')

    total=len(items);collections=sum(1 for x in items if x.get('service_type','collection')=='collection');deliveries=total-collections
    completed=sum(1 for x in items if x.get('status')=='completed');failed=sum(1 for x in items if x.get('status')=='failed');total_weight=sum(float(x.get('collected_weight_kg') or 0) for x in items);rate=round((completed/total*100),1) if total else 0
    logo_path=os.path.join(STATIC_DIR,'cassola-logo.jpeg')
    logo=Image(logo_path,width=80,height=80) if os.path.exists(logo_path) else Paragraph('CASSOLA AMBIENTAL',small_b)
    issue=datetime.now().strftime('%d/%m/%Y %H:%M')
    header_right=Table([[Paragraph('CASSOLA AMBIENTAL',ParagraphStyle('Brand',parent=title,fontSize=14,leading=16)),Paragraph(f'<b>Emitido:</b> {issue}',small)],
                        [Paragraph('Tecnologia e sustentabilidade na operação.',ParagraphStyle('BrandSub',parent=subtitle,textColor=gold)),Paragraph(f'<b>Período:</b> {date_from} a {date_to}',small)],
                        [Paragraph('Relatório Operacional de<br/>Coletas e Entregas',title),'']],colWidths=[330,135])
    header_right.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(1,0),(1,-1),'RIGHT'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),1),('BOTTOMPADDING',(0,0),(-1,-1),1)]))
    head=Table([[logo,header_right]],colWidths=[92,465]);head.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,-1),1,gold),('BOTTOMPADDING',(0,0),(-1,-1),10)]))

    status_map={'all':'Todos','completed':'Realizadas','failed':'Não realizadas','pending':'Pendentes','arrived':'No local','skipped':'Puladas'}
    type_map={'all':'Todos','collection':'Coleta','delivery':'Entrega'}
    pev_name='Todos'; commercial_name=filters.get('commercial_name') or 'Todos'
    if filters.get('pev') not in (None,'','all') and items: pev_name=items[0].get('pev_name') or 'PEV selecionada'
    if filters.get('commercial') not in (None,'','all') and items and not filters.get('commercial_name'): commercial_name=items[0].get('commercial_owner_name') or 'Comercial selecionado'
    filter_data=[[Paragraph('<b>FILTROS</b>',small_b),Paragraph(f'<b>Período</b><br/>{date_from} a {date_to}',small),Paragraph(f'<b>Comercial</b><br/>{_pdf_text(commercial_name)}',small),Paragraph(f'<b>PEV</b><br/>{_pdf_text(pev_name)}',small),Paragraph(f'<b>Tipo</b><br/>{type_map.get(filters.get("service_type","all"),"Todos")}',small),Paragraph(f'<b>Status</b><br/>{status_map.get(filters.get("status","all"),"Todos")}',small)]]
    filter_table=Table(filter_data,colWidths=[55,105,100,145,70,82]);filter_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('BOX',(0,0),(-1,-1),.6,line),('INNERGRID',(1,0),(-1,-1),.35,line),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))

    kpis=[('Visitas',total),('Coletas',collections),('Entregas',deliveries),('Realizadas',completed),('Não realizadas',failed),('Peso coletado',f'{total_weight:,.2f} kg'.replace(',','X').replace('.',',').replace('X','.'))]
    krow=[]
    for label,value in kpis:krow.append(Table([[Paragraph(label,kpi_label)],[Paragraph(str(value),kpi_num)]],colWidths=[87],rowHeights=[22,27]))
    kpi_table=Table([krow],colWidths=[91]*6);kpi_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2)]))

    story=[head,Spacer(1,12),filter_table,Spacer(1,12),kpi_table,Spacer(1,12)]
    if filters.get('show_comparison') and filters.get('commercial','all')=='all':
        grouped={}
        for oid,p in (filters.get('portfolio') or {}).items(): grouped[str(oid)]={'name':p.get('name') or 'Comercial','pevs_total':int(p.get('pevs') or 0),'pevs':set(),'visits':0,'collections':0,'deliveries':0,'completed':0,'failed':0,'weight':0}
        for x in items:
            oid=str(x.get('commercial_owner_id') or '')
            if not oid: continue
            g=grouped.setdefault(oid,{'name':x.get('commercial_owner_name') or 'Comercial','pevs_total':0,'pevs':set(),'visits':0,'collections':0,'deliveries':0,'completed':0,'failed':0,'weight':0})
            g['pevs'].add(x.get('pev_id'));g['visits']+=1
            if x.get('service_type','collection')=='collection':g['collections']+=1
            else:g['deliveries']+=1
            if x.get('status')=='completed':g['completed']+=1
            elif x.get('status')=='failed':g['failed']+=1
            g['weight']+=float(x.get('collected_weight_kg') or 0)
        if grouped:
            comp_head=ParagraphStyle('CompHead',parent=small_b,textColor=colors.white,alignment=TA_CENTER)
            comp_rows=[[Paragraph('Comercial',comp_head),Paragraph('PEVs',comp_head),Paragraph('Visitas',comp_head),Paragraph('Coletas',comp_head),Paragraph('Entregas',comp_head),Paragraph('Realizadas',comp_head),Paragraph('Taxa',comp_head),Paragraph('Peso',comp_head)]]
            for g in sorted(grouped.values(),key=lambda z:z['name'].lower()):
                r=round(g['completed']/g['visits']*100,1) if g['visits'] else 0
                comp_rows.append([Paragraph(_pdf_text(g['name']),small),str(g.get('pevs_total') or len(g['pevs'])),str(g['visits']),str(g['collections']),str(g['deliveries']),str(g['completed']),f'{r:.1f}%'.replace('.',','),f"{g['weight']:,.2f} kg".replace(',','X').replace('.',',').replace('X','.')])
            comp=Table(comp_rows,repeatRows=1,colWidths=[125,48,55,55,55,58,55,78])
            comp.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),green),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.35,line),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(1,1),(-1,-1),'CENTER'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
            story += [Paragraph('Comparativo por Comercial',ParagraphStyle('Section',parent=small_b,fontSize=10,leading=13)),Spacer(1,5),comp,Spacer(1,12)]
    if filters.get('pev') not in (None,'','all'):
        last=max((x for x in items if x.get('route_date')),key=lambda x:(str(x.get('route_date')),str(x.get('completed_at') or x.get('arrived_at') or '')),default=None)
        selected=Table([[Paragraph('<b>PEV SELECIONADO</b><br/><font size="12"><b>'+_pdf_text(pev_name)+'</b></font>',small),Paragraph(f'<b>Visitas</b><br/><font size="14"><b>{total}</b></font>',small),Paragraph(f'<b>Coletas</b><br/><font size="14"><b>{collections}</b></font>',small),Paragraph(f'<b>Entregas</b><br/><font size="14"><b>{deliveries}</b></font>',small),Paragraph(f'<b>Peso</b><br/><font size="12"><b>{total_weight:,.2f} kg</b></font>'.replace(',','X').replace('.',',').replace('X','.'),small),Paragraph(f'<b>Última visita</b><br/>{_pdf_text((last or {}).get("route_date") or "-")}',small)]],colWidths=[185,66,66,66,92,82])
        selected.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#F1F7F2')),('BOX',(0,0),(-1,-1),.7,colors.HexColor('#BFD3C5')),('INNERGRID',(1,0),(-1,-1),.35,colors.HexColor('#CAD8CE')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        story += [selected,Spacer(1,12)]

    header=['Data','Tipo','PEV / Local','Rota','Peso','Status','Observação']
    rows=[[Paragraph(h,ParagraphStyle('TH',parent=small_b,textColor=colors.white,alignment=TA_CENTER)) for h in header]]
    status_label={'completed':'Realizada','failed':'Não realizada','arrived':'No local','skipped':'Pulada','pending':'Pendente'}
    for x in items:
        note=x.get('failure_reason') or x.get('driver_note') or ''
        rows.append([Paragraph(_pdf_text(x.get('route_date')),small),Paragraph(_pdf_text(SERVICE_TYPE_LABEL.get(x.get('service_type','collection'),'Coleta')),small),Paragraph(_pdf_text(x.get('pev_name')),small),Paragraph(_pdf_text(x.get('route_name')),small),Paragraph(_pdf_text((f"{float(x.get('collected_weight_kg')):.2f} kg" if x.get('collected_weight_kg') else '-')),small),Paragraph(_pdf_text(status_label.get(x.get('status'),x.get('status'))),small),Paragraph(_pdf_text(note),small)])
    table=LongTable(rows,repeatRows=1,colWidths=[55,52,135,80,65,75,95])
    style=[('BACKGROUND',(0,0),(-1,0),green),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.3,line),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]
    for i,x in enumerate(items,start=1):
        if x.get('status')=='failed': style.append(('TEXTCOLOR',(5,i),(5,i),red))
        elif x.get('status')=='completed': style.append(('TEXTCOLOR',(5,i),(5,i),green2))
        if i%2==0: style.append(('BACKGROUND',(0,i),(-1,i),colors.HexColor('#FAFCFA')))
    table.setStyle(TableStyle(style));story.append(table)

    def footer(canvas,doc):
        canvas.saveState();w,h=A4
        canvas.setStrokeColor(gold);canvas.setLineWidth(.6);canvas.line(28,24,w-28,24)
        canvas.setFont('Helvetica',7);canvas.setFillColor(muted);canvas.drawString(28,12,'Cassola Ambiental - Relatório operacional gerado pelo Rota Próxima')
        canvas.drawRightString(w-28,12,f'Página {doc.page}');canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer);return buf.getvalue()

class SupaHTTPError(RuntimeError):
    def __init__(self,status,message):
        super().__init__(message)
        self.status=int(status)

class Supa:
    @staticmethod
    def headers(token=None,prefer=None):
        h={'apikey':SUPABASE_KEY,'Content-Type':'application/json'}
        if token:h['Authorization']=f'Bearer {token}'
        if prefer:h['Prefer']=prefer
        return h
    @staticmethod
    def req(method,table,token,params=None,body=None,prefer=None):
        r=HTTP.request(method,f'{REST}/{table}',headers=Supa.headers(token,prefer),params=params,json=body,timeout=20)
        if not r.ok:
            try:m=r.json().get('message') or r.json().get('error') or r.text
            except:m=r.text
            raise SupaHTTPError(r.status_code,m or f'Erro Supabase {r.status_code}')
        if not r.text:return None
        return r.json()
    @staticmethod
    def get(table,token,params=None):return Supa.req('GET',table,token,params=params)
    @staticmethod
    def insert(table,token,body):return Supa.req('POST',table,token,body=body,prefer='return=representation')
    @staticmethod
    def update(table,token,params,body):return Supa.req('PATCH',table,token,params=params,body=body,prefer='return=representation')
    @staticmethod
    def delete(table,token,params):return Supa.req('DELETE',table,token,params=params,prefer='return=representation')
    @staticmethod
    def rpc(name,token,body=None):return Supa.req('POST',f'rpc/{name}',token,body=body or {})


def upload_test_evidence(token, data_url, path_prefix):
    if not data_url or ',' not in str(data_url):
        raise ValueError('Envie uma foto válida')
    header, payload = str(data_url).split(',',1)
    if 'base64' not in header:
        raise ValueError('Formato de foto inválido')
    raw=base64.b64decode(payload,validate=True)
    if not raw or len(raw)>8*1024*1024:
        raise ValueError('A foto deve ter no máximo 8 MB')
    mime='image/jpeg'
    if header.startswith('data:image/png'):mime='image/png'
    elif header.startswith('data:image/webp'):mime='image/webp'
    ext={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}.get(mime,'jpg')
    path=f"{path_prefix}/{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.{ext}"
    r=HTTP.post(f'{SUPABASE_URL}/storage/v1/object/rota-evidencias-teste/{path}',headers={'apikey':SUPABASE_KEY,'Authorization':f'Bearer {token}','Content-Type':mime,'x-upsert':'false'},data=raw,timeout=30)
    if not r.ok:
        try:msg=r.json().get('message') or r.json().get('error') or r.text
        except:msg=r.text
        raise RuntimeError(msg or 'Falha ao salvar foto')
    return path

def route_weighings(token,route_id):
    return Supa.get('route_weighings',token,{'route_id':f'eq.{route_id}','select':'id,route_id,stop_id,pev_id,weight_kg,evidence_id,created_at','order':'created_at.asc'}) or []

def route_evidences(token,route_id):
    return Supa.get('route_evidences',token,{'route_id':f'eq.{route_id}','select':'id,route_id,stop_id,pev_id,evidence_type,storage_path,created_at','order':'created_at.asc'}) or []

def try_auto_finish_route(token,user,route_id,lat=None,lng=None):
    route=get_route_full(token,route_id)
    if not route or route.get('status')!='in_progress':return route
    if any(s.get('status') in ('pending','arrived') for s in route.get('stops',[])):return route
    completed_collections=[s for s in route.get('stops',[]) if s.get('status')=='completed' and s.get('service_type','collection')=='collection']
    weighed={int(w.get('stop_id')) for w in route.get('weighings',[]) if w.get('stop_id') is not None}
    if any(int(s['id']) not in weighed for s in completed_collections):return route
    Supa.update('routes',token,{'id':f'eq.{route_id}','status':'eq.in_progress'},{'status':'finished','finished_at':now_iso(),'finished_lat':lat,'finished_lng':lng})
    audit(token,user,'finish','route',route_id,'Rota finalizada automaticamente após conclusão das paradas e pesagens',None,None,{'automatic':True})
    route=get_route_full(token,route_id);route['auto_finished']=True
    return route

def edge(action,body=None,token=None):
    h={'apikey':SUPABASE_KEY,'Content-Type':'application/json'}
    if token:h['Authorization']=f'Bearer {token}'
    r=HTTP.post(ADMIN_FN,headers=h,json={'action':action,**(body or {})},timeout=20)
    try:d=r.json()
    except:d={'error':r.text}
    if not r.ok:raise RuntimeError(d.get('error') or f'Erro {r.status_code}')
    return d

def audit(token,user,action,entity_type,entity_id,summary,before=None,after=None,metadata=None):
    try:Supa.insert('audit_logs',token,{'actor_id':user['id'],'action':action,'entity_type':entity_type,'entity_id':str(entity_id) if entity_id is not None else None,'summary':summary,'before_data':before,'after_data':after,'metadata':metadata or {}})
    except Exception as e:print('audit:',e)

def first(rows):return rows[0] if rows else None

def geocode_pev_and_persist(token,pev,force=False):
    if not force and pev.get('lat') is not None and pev.get('lng') is not None:
        return {'id':pev.get('id'),'lat':float(pev['lat']),'lng':float(pev['lng']),'updated':False,'confirmed':bool(pev.get('location_confirmed')),'source':'existing'}
    d=geocode_address_detailed(pev)
    Supa.update('pevs',token,{'id':f'eq.{pev["id"]}'},{'lat':d['lat'],'lng':d['lng'],'location_confirmed':d['confirmed']})
    pev['lat']=d['lat'];pev['lng']=d['lng'];pev['location_confirmed']=d['confirmed']
    return {'id':pev.get('id'),'lat':d['lat'],'lng':d['lng'],'updated':True,'confirmed':d['confirmed'],'source':d['source']}

def ensure_pev_coords(token,pev):
    if pev.get('lat') is not None and pev.get('lng') is not None:return float(pev['lat']),float(pev['lng'])
    r=geocode_pev_and_persist(token,pev);return r['lat'],r['lng']

def settings_origin(token):
    s=first(Supa.get('settings',token,{'id':'eq.1','select':'*'}))
    if not s:raise ValueError('Configure o ponto de saída')
    if s.get('origin_lat') is None or s.get('origin_lng') is None:
        lat,lng=geocode_address({'street':s.get('origin_street'),'number':s.get('origin_number'),'district':s.get('origin_district'),'city':s.get('origin_city'),'state':s.get('origin_state'),'cep':s.get('origin_cep')})
        Supa.update('settings',token,{'id':'eq.1'},{'origin_lat':lat,'origin_lng':lng});s['origin_lat']=lat;s['origin_lng']=lng
    return {'name':s.get('origin_name'),'cep':s.get('origin_cep'),'street':s.get('origin_street'),'number':s.get('origin_number'),'complement':s.get('origin_complement'),'district':s.get('origin_district'),'city':s.get('origin_city'),'state':s.get('origin_state'),'lat':float(s['origin_lat']),'lng':float(s['origin_lng'])}

def schedule_conflicts(stops):
    timed=[]
    for s in sorted(stops,key=lambda x:x.get('sequence',0)):
        m=hhmm_to_minutes(s.get('exact_time'))
        if m is not None: timed.append((m,s))
    warnings=[]
    for (ma,a),(mb,b) in zip(timed,timed[1:]):
        travel=0
        for s in stops:
            if a.get('sequence',0)<s.get('sequence',0)<=b.get('sequence',0): travel+=(float(s.get('planned_duration_s') or 0)/60)
        gap=(mb-ma) if mb>=ma else (mb+24*60-ma)
        if travel>max(0,gap-3): warnings.append(f"Conflito de horário: {a.get('pev_name','parada')} às {str(a.get('exact_time'))[:5]} e {b.get('pev_name','parada')} às {str(b.get('exact_time'))[:5]} exigem aproximadamente {round(travel)} min de deslocamento.")
    return warnings

def get_route_full(token,route_id):
    r=first(Supa.get('routes',token,{'id':f'eq.{route_id}','select':'*,profiles!routes_driver_id_fkey(name)'}))
    if not r:return None
    stops=Supa.get('route_stops',token,{'route_id':f'eq.{route_id}','select':'*,pevs(*),scheduling_requests(exact_time)','order':'sequence.asc'})
    out={**r,'driver_name':(r.get('profiles') or {}).get('name','')};out.pop('profiles',None)
    o=out.get('origin_json') or {};out['origin']=o
    mapped=[]
    for s in stops:
        p=s.pop('pevs',{}) or {};rq=s.pop('scheduling_requests',{}) or {}
        x={**s,'pev_name':p.get('name'),'street':p.get('street'),'number':p.get('number'),'complement':p.get('complement'),'district':p.get('district'),'city':p.get('city'),'state':p.get('state'),'cep':p.get('cep'),'lat':p.get('lat'),'lng':p.get('lng'),'location_confirmed':p.get('location_confirmed'),'contact_name':p.get('contact_name'),'contact_role':p.get('contact_role'),'phone':p.get('phone'),'whatsapp':p.get('whatsapp'),'notes':p.get('notes'),'exact_time':s.get('exact_time') or rq.get('exact_time') or ''}
        mapped.append(x)
    out['stops']=mapped;out['weighings']=route_weighings(token,route_id);out['evidences']=route_evidences(token,route_id);loc=Supa.get('driver_location_updates',token,{'route_id':f'eq.{route_id}','select':'lat,lng,accuracy_m,recorded_at','order':'recorded_at.desc','limit':'1'}) or [];out['last_location']=loc[0] if loc else None;out['schedule_warnings']=schedule_conflicts(mapped);out['timeline']=route_timeline(token,out);return out


def route_timeline(token,route):
    events=[]
    driver=route.get('driver_name') or 'Motorista'
    if route.get('started_at'): events.append({'type':'route_started','at':route.get('started_at'),'label':f'{driver} iniciou a rota','lat':route.get('started_lat'),'lng':route.get('started_lng')})
    for st in route.get('stops') or []:
        name=st.get('pev_name') or 'PEV';kind=SERVICE_TYPE_LABEL.get(st.get('service_type','collection'),'Coleta')
        if st.get('arrived_at'): events.append({'type':'stop_arrived','at':st.get('arrived_at'),'label':f'{driver} chegou em {name}','stop_id':st.get('id'),'pev_name':name,'lat':st.get('arrived_lat'),'lng':st.get('arrived_lng')})
        if st.get('completed_at'):
            if st.get('status')=='failed': label=f'{kind} não realizada em {name}'
            else: label=f'{kind} concluída em {name}'
            events.append({'type':'stop_failed' if st.get('status')=='failed' else 'stop_completed','at':st.get('completed_at'),'label':label,'stop_id':st.get('id'),'pev_name':name,'reason':st.get('failure_reason') or '','note':st.get('driver_note') or '','arrived_at':st.get('arrived_at'),'lat':st.get('completed_lat'),'lng':st.get('completed_lng')})
    try:
        logs=Supa.get('audit_logs',token,{'entity_type':'eq.route','entity_id':f'eq.{route.get("id")}','action':'eq.recalculate','select':'created_at,summary,metadata','order':'created_at.asc'})
        for a in logs or []:events.append({'type':'recalculate','at':a.get('created_at'),'label':'Motorista recalculou o restante da rota','metadata':a.get('metadata') or {}})
    except Exception:pass
    if route.get('finished_at'): events.append({'type':'route_finished','at':route.get('finished_at'),'label':f'{driver} finalizou a rota','lat':route.get('finished_lat'),'lng':route.get('finished_lng')})
    events.sort(key=lambda e:str(e.get('at') or ''))
    return events

def reorder_route_for_exact_times(token,route_id,start_lat=None,start_lng=None,local_time=''):
    route=get_route_full(token,route_id);pending=[s for s in route['stops'] if s['status']=='pending']
    if not pending:return []
    if start_lat is None or start_lng is None:
        o=route.get('origin') or settings_origin(token);start_lat,start_lng=o.get('lat'),o.get('lng')
    points=[(float(start_lat),float(start_lng))]
    # get_route_full already joined the PEV data, so avoid one extra database
    # lookup per stop. Only geocode/update a PEV if coordinates are missing.
    for s in pending:
        if s.get('lat') is not None and s.get('lng') is not None:
            points.append((float(s['lat']),float(s['lng'])))
        else:
            p=first(Supa.get('pevs',token,{'id':f'eq.{s["pev_id"]}','select':'*'}))
            points.append(ensure_pev_coords(token,p))
    dist,dur,_=osrm_matrix(points);pri={i+1:pending[i].get('priority','normal') for i in range(len(pending))};exact={i+1:pending[i].get('exact_time') for i in range(len(pending)) if pending[i].get('exact_time')}
    order,warnings=optimize_order_with_exact_times(dist,dur,pri,exact,hhmm_to_minutes(local_time),'best')
    fixed=len(route['stops'])-len(pending);prev=0;updates=[]
    for pos,idx in enumerate(order,start=1):
        st=pending[idx-1]
        updates.append({'id':st['id'],'sequence':fixed+pos,'planned_distance_m':dist[prev][idx] or 0,'planned_duration_s':dur[prev][idx] or 0})
        prev=idx
    Supa.rpc('apply_stop_reorder',token,{'p_route_id':route_id,'p_updates':updates})
    return warnings

class AppHandler(BaseHTTPRequestHandler):
    server_version='RotaProxima/3.0'
    def route_path(self):return urllib.parse.urlparse(self.path).path
    def query(self):return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
    def read_json(self):
        n=int(self.headers.get('Content-Length','0') or 0);return json.loads(self.rfile.read(n).decode() or '{}') if n else {}
    def cookies(self):
        c=SimpleCookie();c.load(self.headers.get('Cookie',''));return {k:v.value for k,v in c.items()}
    def is_secure_request(self):
        forwarded=(self.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip().lower()
        return FORCE_SECURE_COOKIES or forwarded=='https'
    def common_security_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','SAMEORIGIN')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Permissions-Policy','geolocation=(self)')
        if self.is_secure_request():
            self.send_header('Strict-Transport-Security','max-age=15552000; includeSubDomains')
    def send_json(self,obj,status=200,extra_headers=None):
        raw=json.dumps(obj,ensure_ascii=False,default=str).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.common_security_headers()
        for k,v in (getattr(self,'pending_headers',[]) or []):self.send_header(k,v)
        for k,v in (extra_headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(raw)
    def send_bytes(self,raw,content_type='application/octet-stream',status=200,filename=None):
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.common_security_headers()
        if filename:self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        for k,v in (getattr(self,'pending_headers',[]) or []):self.send_header(k,v)
        self.end_headers();self.wfile.write(raw)
    def auth_tokens(self):
        c=self.cookies();return c.get('rota_access'),c.get('rota_refresh')
    def clear_auth_headers(self):
        secure='; Secure' if self.is_secure_request() else ''
        self.pending_headers=[('Set-Cookie',f'rota_access=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}'),('Set-Cookie',f'rota_refresh=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}')]
    def set_auth_headers(self,access,refresh):
        secure='; Secure' if self.is_secure_request() else ''
        self.pending_headers=[('Set-Cookie',f'rota_access={access}; Path=/; HttpOnly; SameSite=Lax; Max-Age=3600{secure}'),('Set-Cookie',f'rota_refresh={refresh}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000{secure}')]
    def refresh(self,refresh):
        if not refresh:return None
        # Refresh tokens are single-use. Requisições paralelas do dashboard podem chegar
        # com o MESMO cookie antigo antes do navegador receber o primeiro Set-Cookie.
        # Reutilizamos por poucos segundos o resultado do primeiro refresh para evitar
        # revogação/corrida de tokens.
        with _AUTH_REFRESH_LOCK:
            now=time.monotonic()
            cached=_REFRESH_RESULT_CACHE.get(refresh)
            if cached and cached[0]>now:
                _,access,new_refresh=cached
                self.set_auth_headers(access,new_refresh)
                return access
            r=HTTP.post(f'{AUTH}/token?grant_type=refresh_token',headers={'apikey':SUPABASE_KEY,'Content-Type':'application/json'},json={'refresh_token':refresh},timeout=15)
            if not r.ok:
                try: print('[AUTH REFRESH ERROR]', r.status_code, r.json())
                except: print('[AUTH REFRESH ERROR]', r.status_code, r.text[:300])
                return None
            d=r.json();access=d['access_token'];new_refresh=d['refresh_token']
            _REFRESH_RESULT_CACHE[refresh]=(now+_REFRESH_RESULT_TTL,access,new_refresh)
            if len(_REFRESH_RESULT_CACHE)>200:
                for k,v in list(_REFRESH_RESULT_CACHE.items()):
                    if v[0]<=now:_REFRESH_RESULT_CACHE.pop(k,None)
            self.set_auth_headers(access,new_refresh)
            return access
    def current_user(self):
        access,refresh=self.auth_tokens()
        # The access-token cookie may expire before the Supabase session. If the
        # refresh cookie still exists, renew transparently instead of forcing login.
        if not access and refresh:
            access=self.refresh(refresh)
        if not access:return None
        now=time.monotonic()
        with _AUTH_CACHE_LOCK:
            cached=_AUTH_CACHE.get(access)
            if cached and cached[0]>now:
                self._access=access
                return dict(cached[1])
        def fetch_profile(tok):
            # Evita duas chamadas simultâneas ao Supabase para o mesmo primeiro carregamento.
            with _AUTH_FETCH_LOCK:
                now2=time.monotonic()
                with _AUTH_CACHE_LOCK:
                    c2=_AUTH_CACHE.get(tok)
                    if c2 and c2[0]>now2:
                        return dict(c2[1])
                try:
                    d=Supa.rpc('current_profile',tok)
                    p2=first(d) if isinstance(d,list) else d
                    if p2 and p2.get('active'):
                        with _AUTH_CACHE_LOCK:_AUTH_CACHE[tok]=(now2+_AUTH_CACHE_TTL,dict(p2))
                    return p2
                except SupaHTTPError as e:
                    # Só 401/403 indicam token inválido/sem autorização. Um 5xx é erro
                    # do banco/API e NÃO deve consumir o refresh token nem virar loop.
                    if e.status in (401,403):return None
                    print('[AUTH PROFILE ERROR]',e.status,str(e))
                    raise
        p=fetch_profile(access)
        if not p and refresh:
            old_access=access
            access=self.refresh(refresh)
            if access:
                with _AUTH_CACHE_LOCK:_AUTH_CACHE.pop(old_access,None)
                p=fetch_profile(access)
        if not p or not p.get('active'):return None
        self._access=access
        with _AUTH_CACHE_LOCK:
            _AUTH_CACHE[access]=(now+_AUTH_CACHE_TTL,dict(p))
            if len(_AUTH_CACHE)>500:
                expired=[k for k,v in _AUTH_CACHE.items() if v[0]<=now]
                for k in expired:_AUTH_CACHE.pop(k,None)
        return p
    def require_user(self,roles=None):
        u=self.current_user()
        if not u:self.send_json({'error':'Não autenticado'},401);return None
        if roles and u.get('role') not in roles:self.send_json({'error':'Sem permissão'},403);return None
        return u
    def token(self):return getattr(self,'_access',None) or self.auth_tokens()[0]
    def do_GET(self):
        p=self.route_path()
        if p.startswith('/api/'):return self.api_get(p)
        return self.static(p)
    def do_POST(self):return self.api_write('POST',self.route_path()) if self.route_path().startswith('/api/') else self.send_error(404)
    def do_PUT(self):return self.api_write('PUT',self.route_path()) if self.route_path().startswith('/api/') else self.send_error(404)
    def do_DELETE(self):return self.api_write('DELETE',self.route_path()) if self.route_path().startswith('/api/') else self.send_error(404)

    def api_get(self,path):
        try:
            if path=='/api/health':return self.send_json({'ok':True,'build':BUILD_ID,'listen':f'{HOST}:{PORT}','render':IS_RENDER,'external_url':os.environ.get('RENDER_EXTERNAL_URL','')})
            if path=='/api/setup-status':return self.send_json(edge('setup-status'))
            if path=='/api/me':return self.send_json({'user':self.current_user()})
            if path.startswith('/api/cep/'):
                # Consulta pública de CEP: apenas dados postais públicos, sem viagem ao Supabase.
                # O restante da API continua exigindo autenticação normalmente.
                cep=clean_cep(path.rsplit('/',1)[-1])
                if len(cep)!=8:
                    return self.send_json({'error':'CEP deve ter 8 dígitos'},400)
                return self.send_json(viacep_lookup(cep))
            u=self.require_user();
            if not u:return
            t=self.token();role=u['role'];q=self.query()
            if path=='/api/settings':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                return self.send_json(first(Supa.get('settings',t,{'id':'eq.1','select':'*'})))
            if path=='/api/users':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                rows=Supa.get('profiles',t,{'select':'*','order':'active.desc,name.asc'});return self.send_json({'items':rows})
            if path=='/api/drivers':
                if role not in ('admin','commercial_manager'):return self.send_json({'error':'Sem permissão'},403)
                return self.send_json({'items':Supa.get('profiles',t,{'role':'eq.driver','active':'eq.true','select':'*','order':'name.asc'})})
            if path=='/api/commercials':
                if role not in ('admin','commercial_manager'):return self.send_json({'error':'Sem permissão'},403)
                return self.send_json({'items':Supa.get('profiles',t,{'role':'eq.commercial','active':'eq.true','select':'id,name,username,active','order':'name.asc'})})
            if path=='/api/evidence-sync':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                evidences=Supa.get('route_evidences',t,{'select':'id,route_id,stop_id,pev_id,evidence_type,storage_path,created_at','order':'id.asc'}) or []
                if not evidences:return self.send_json({'items':[]})
                route_ids=sorted({int(x['route_id']) for x in evidences if x.get('route_id') is not None})
                pev_ids=sorted({int(x['pev_id']) for x in evidences if x.get('pev_id') is not None})
                evidence_ids=sorted({int(x['id']) for x in evidences if x.get('id') is not None})
                routes=Supa.get('routes',t,{'id':f'in.({",".join(map(str,route_ids))})','select':'id,name,route_date'}) if route_ids else []
                pevs=Supa.get('pevs',t,{'id':f'in.({",".join(map(str,pev_ids))})','select':'id,name'}) if pev_ids else []
                weighings=Supa.get('route_weighings',t,{'evidence_id':f'in.({",".join(map(str,evidence_ids))})','select':'evidence_id,weight_kg'}) if evidence_ids else []
                route_map={int(x['id']):x for x in (routes or [])};pev_map={int(x['id']):x for x in (pevs or [])};weight_map={int(x['evidence_id']):x.get('weight_kg') for x in (weighings or []) if x.get('evidence_id') is not None}
                items=[]
                for ev in evidences:
                    r=route_map.get(int(ev.get('route_id') or 0),{});p=pev_map.get(int(ev.get('pev_id') or 0),{})
                    items.append({**ev,'route_name':r.get('name') or f'Rota {ev.get("route_id")}','route_date':r.get('route_date'),'pev_name':p.get('name') or f'PEV {ev.get("pev_id")}','weight_kg':weight_map.get(int(ev.get('id') or 0))})
                return self.send_json({'items':items})
            if path=='/api/evidence-sync/file':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                try:eid=int((q.get('id') or ['0'])[0])
                except:return self.send_json({'error':'Evidência inválida'},400)
                ev=first(Supa.get('route_evidences',t,{'id':f'eq.{eid}','select':'id,storage_path,evidence_type'}))
                if not ev:return self.send_json({'error':'Evidência não encontrada'},404)
                storage_path=str(ev.get('storage_path') or '').strip()
                if not storage_path:return self.send_json({'error':'Arquivo da evidência não encontrado'},404)
                url=f'{SUPABASE_URL}/storage/v1/object/authenticated/rota-evidencias-teste/{urllib.parse.quote(storage_path,safe="/")}'
                rr=HTTP.get(url,headers={'apikey':SUPABASE_KEY,'Authorization':f'Bearer {t}'},timeout=30)
                if not rr.ok:
                    try:msg=rr.json().get('message') or rr.json().get('error') or rr.text
                    except:msg=rr.text
                    return self.send_json({'error':msg or 'Não foi possível baixar a foto'},rr.status_code if rr.status_code in (401,403,404) else 400)
                ctype=rr.headers.get('Content-Type') or mimetypes.guess_type(storage_path)[0] or 'application/octet-stream'
                filename=Path(storage_path).name or f'evidencia-{eid}.jpg'
                return self.send_bytes(rr.content,ctype,filename=filename)
            if path=='/api/pevs':
                if role not in ('admin','commercial_manager','commercial'):return self.send_json({'error':'Sem permissão'},403)
                params={'select':'*,profiles!pevs_commercial_owner_id_fkey(id,name)','order':'favorite.desc,name.asc'}
                if q.get('trash',['0'])[0]=='1':
                    if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                    params['deleted_at']='not.is.null'
                else:params.update({'deleted_at':'is.null','active':'eq.true'})
                rows=Supa.get('pevs',t,params);items=[]
                for x in rows:
                    owner=x.pop('profiles',{}) or {};items.append({**x,'commercial_owner_name':owner.get('name','')})
                return self.send_json({'items':items})
            if path=='/api/requests':
                if role not in ('admin','commercial_manager','commercial'):return self.send_json({'error':'Sem permissão'},403)
                params={'select':'*,pevs(name,street,number,district,city,state,cep,contact_name,contact_role,phone),profiles!scheduling_requests_requested_by_fkey(name),routes(name)','order':'requested_date.asc,id.desc'}
                if role=='commercial':params['requested_by']=f'eq.{u["id"]}'
                if q.get('status'):params['status']=f'eq.{q["status"][0]}'
                else:params['status']='neq.cancelled'
                rows=Supa.get('scheduling_requests',t,params);items=[]
                for x in rows:
                    p=x.pop('pevs',{}) or {};pr=x.pop('profiles',{}) or {};r=x.pop('routes',{}) or {};items.append({**x,**{k:p.get(k) for k in ['street','number','district','city','state','cep','contact_name','contact_role','phone']},'pev_name':p.get('name'),'requested_by_name':pr.get('name'),'route_name':r.get('name')})
                return self.send_json({'items':items})
            if path=='/api/routes':
                if role=='commercial':return self.send_json({'error':'Sem permissão'},403)
                params={'select':'*,profiles!routes_driver_id_fkey(name),route_stops(id,status)','order':'route_date.desc,id.desc'}
                if role=='driver':params['driver_id']=f'eq.{u["id"]}'
                if q.get('date'):params['route_date']=f'eq.{q["date"][0]}'
                rows=Supa.get('routes',t,params);items=[]
                for x in rows:
                    pr=x.pop('profiles',{}) or {};st=x.pop('route_stops',[]) or [];x.pop('origin_json',None);items.append({**x,'driver_name':pr.get('name',''),'completed_stops':sum(1 for z in st if z['status'] in ('completed','failed','skipped')),'total_stops':len(st)})
                return self.send_json({'items':items})
            if path.startswith('/api/routes/') and len(path.strip('/').split('/'))==3:
                if role=='commercial':return self.send_json({'error':'Sem permissão'},403)
                rid=int(path.rsplit('/',1)[-1]);r=get_route_full(t,rid)
                if not r:return self.send_json({'error':'Rota não encontrada'},404)
                if role=='driver' and r['driver_id']!=u['id']:return self.send_json({'error':'Sem permissão'},403)
                return self.send_json(r)
            if path in ('/api/reports/collections','/api/reports/collections/pdf'):
                if role not in ('admin','commercial_manager','commercial'):return self.send_json({'error':'Sem permissão'},403)
                date_from=(q.get('from') or [''])[0].strip();date_to=(q.get('to') or [''])[0].strip()
                if not date_from or not date_to:return self.send_json({'error':'Informe o período do relatório'},400)
                try:
                    d1=datetime.strptime(date_from,'%Y-%m-%d').date();d2=datetime.strptime(date_to,'%Y-%m-%d').date()
                except ValueError:return self.send_json({'error':'Período inválido'},400)
                if d1>d2:return self.send_json({'error':'A data inicial não pode ser maior que a final'},400)
                if (d2-d1).days>366:return self.send_json({'error':'O período máximo do relatório é de 367 dias'},400)
                items=collection_report_items(t,date_from,date_to)
                if path.endswith('/pdf'):
                    requested_commercial=(q.get('commercial') or ['all'])[0]
                    effective_commercial=requested_commercial if role in ('admin','commercial_manager') else str(u['id'])
                    commercial_name=u.get('name','') if role=='commercial' else ''
                    portfolio=commercial_portfolio_summary(t) if role in ('admin','commercial_manager') else {}
                    if role in ('admin','commercial_manager') and effective_commercial!='all': commercial_name=(portfolio.get(str(effective_commercial)) or {}).get('name','')
                    filters={'status':(q.get('status') or ['all'])[0],'service_type':(q.get('service_type') or ['all'])[0],'q':(q.get('q') or [''])[0],'pev':(q.get('pev') or ['all'])[0],'commercial':effective_commercial,'commercial_name':commercial_name,'show_comparison':role in ('admin','commercial_manager'),'portfolio':portfolio}
                    items=filter_collection_report(items,filters['status'],filters['service_type'],filters['q'],filters['pev'],'all',filters['commercial'])
                    raw=build_collections_pdf(items,date_from,date_to,filters)
                    return self.send_bytes(raw,'application/pdf',filename=f'relatorio-coletas-entregas-{date_from}-a-{date_to}.pdf')
                return self.send_json({'items':items})
            if path in ('/api/dashboard','/api/dashboard-pending'):
                if role not in ('admin','commercial_manager'):return self.send_json({'error':'Sem permissão'},403)
                data=Supa.rpc('dashboard_summary',t) or {}
                return self.send_json(data)
            if path=='/api/backup':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                dump={}
                for table in ['settings','profiles','pevs','scheduling_requests','routes','route_stops','audit_logs']:
                    dump[table]=Supa.get(table,t,{'select':'*','order':'id.asc'} if table not in ('settings','profiles') else {'select':'*'})
                return self.send_json({'exported_at':now_iso(),'data':dump})
            return self.send_json({'error':'Endpoint não encontrado'},404)
        except Exception as e:return self.send_json({'error':str(e)},400)

    def api_write(self,method,path):
        try:data=self.read_json()
        except Exception as e:return self.send_json({'error':f'JSON inválido: {e}'},400)
        try:
            if path=='/api/setup' and method=='POST':return self.send_json(edge('setup',data),201)
            if path=='/api/login' and method=='POST':
                d=edge('login',data);self.set_auth_headers(d['access_token'],d['refresh_token']);return self.send_json({'user':d['user']})
            if path=='/api/logout' and method=='POST':
                access,_=self.auth_tokens()
                if access:
                    try: HTTP.post(f'{AUTH}/logout',headers={'apikey':SUPABASE_KEY,'Authorization':f'Bearer {access}'},timeout=10)
                    except: pass
                self.clear_auth_headers();return self.send_json({'ok':True})
            u=self.require_user();
            if not u:return
            t=self.token();role=u['role']
            if path=='/api/change-password' and method=='POST':
                edge('change-own-password',data,t);return self.send_json({'ok':True})
            if path=='/api/users' and method=='POST':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                d=edge('create-user',data,t);return self.send_json(d,201)
            if path.startswith('/api/users/'):
                uid=path.strip('/').split('/')[2]
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                if path.endswith('/reset-password') and method=='POST':edge('reset-password',{'user_id':uid,'password':data.get('password')},t);return self.send_json({'ok':True})
                if method=='PUT':
                    old=first(Supa.get('profiles',t,{'id':f'eq.{uid}','select':'*'}));
                    if not old:return self.send_json({'error':'Usuário não encontrado'},404)
                    upd={k:data[k] for k in ['name','role','phone','active'] if k in data};
                    if uid==u['id'] and upd.get('active') is False:return self.send_json({'error':'Você não pode desativar sua própria conta'},400)
                    if uid==u['id'] and 'role' in upd and upd['role']!='admin':return self.send_json({'error':'Você não pode remover seu próprio perfil de Administrador'},400)
                    if old['role']=='admin' and (upd.get('active') is False or ('role' in upd and upd['role']!='admin')):
                        admins=Supa.get('profiles',t,{'role':'eq.admin','active':'eq.true','select':'id'});
                        if len(admins)<=1:return self.send_json({'error':'Não é possível remover ou desativar o último administrador'},400)
                    if old['role']=='driver' and upd.get('active') is False:
                        active=Supa.get('routes',t,{'driver_id':f'eq.{uid}','status':'eq.in_progress','select':'id'});
                        if active:return self.send_json({'error':'Este motorista possui rota em andamento'},409)
                    Supa.update('profiles',t,{'id':f'eq.{uid}'},upd);audit(t,u,'update','user',uid,'Usuário alterado',old,upd);return self.send_json({'ok':True})
                if method=='DELETE':
                    if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                    result=Supa.rpc('delete_user_force',t,{'p_user_id':uid});return self.send_json(result or {'ok':True})
            if path=='/api/pevs' and method=='POST':
                if role not in ('admin','commercial'):return self.send_json({'error':'Sem permissão'},403)
                if len(path.strip('/').split('/'))>3 and path.strip('/').split('/')[3]=='confirm-location' and method=='POST':
                    if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                    row=first(Supa.get('pevs',t,{'id':f'eq.{pid}','select':'id,lat,lng'}));
                    if not row or row.get('lat') is None or row.get('lng') is None:return self.send_json({'error':'PEV sem coordenadas para confirmar'},409)
                    Supa.update('pevs',t,{'id':f'eq.{pid}'},{'location_confirmed':True});audit(t,u,'confirm_location','pev',pid,'Localização da PEV confirmada manualmente');return self.send_json({'ok':True})
                # Defesa dupla: horários vazios viram None antes de chegar ao PostgreSQL.
                pev_data=dict(data)
                pev_data['service_start']=pev_data.get('service_start') or None
                pev_data['service_end']=pev_data.get('service_end') or None
                print(f'[PEV SAVE] build={BUILD_ID} via rpc/save_pev')
                row=Supa.rpc('save_pev',t,{'p_id':None,'p_data':pev_data})
                new_id=row.get('id') if isinstance(row,dict) else None;geo=None
                if new_id:
                    try:
                        saved=first(Supa.get('pevs',t,{'id':f'eq.{new_id}','select':'*'}));geo=geocode_pev_and_persist(t,saved) if saved else None
                    except Exception as e: print('[PEV GEOCODE WARNING]',e)
                return self.send_json({'id':new_id,'geocode':geo},201)
            if path=='/api/pevs/geocode-missing' and method=='POST':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                rows=Supa.get('pevs',t,{'active':'eq.true','deleted_at':'is.null','select':'*','order':'id.asc'});updated=[];failed=[]
                for pev in rows:
                    if pev.get('lat') is not None and pev.get('lng') is not None and pev.get('location_confirmed'): continue
                    try: updated.append(geocode_pev_and_persist(t,pev,force=True))
                    except Exception as e: failed.append({'id':pev.get('id'),'name':pev.get('name',''),'error':str(e)})
                audit(t,u,'geocode','pev',None,'Coordenadas/localizações pendentes atualizadas',None,None,{'updated':len(updated),'failed':len(failed)})
                return self.send_json({'ok':True,'updated':updated,'failed':failed})
            if path.startswith('/api/pevs/'):
                pid=int(path.strip('/').split('/')[2])
                if role not in ('admin','commercial'):return self.send_json({'error':'Sem permissão'},403)
                old=first(Supa.get('pevs',t,{'id':f'eq.{pid}','select':'*'}));
                if not old:return self.send_json({'error':'PEV não encontrado'},404)
                if path.endswith('/restore') and method=='POST':
                    if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                    Supa.update('pevs',t,{'id':f'eq.{pid}'},{'active':True,'deleted_at':None,'deleted_by':None});audit(t,u,'restore','pev',pid,'PEV restaurado');return self.send_json({'ok':True})
                if method=='PUT':
                    pev_data=dict(data)
                    pev_data['service_start']=pev_data.get('service_start') or None
                    pev_data['service_end']=pev_data.get('service_end') or None
                    print(f'[PEV SAVE] build={BUILD_ID} via rpc/save_pev update id={pid}')
                    Supa.rpc('save_pev',t,{'p_id':pid,'p_data':pev_data});geo=None
                    try:
                        saved=first(Supa.get('pevs',t,{'id':f'eq.{pid}','select':'*'}));geo=geocode_pev_and_persist(t,saved,force=not (pev_data.get('lat') and pev_data.get('lng'))) if saved else None
                    except Exception as e: print('[PEV GEOCODE WARNING]',e)
                    return self.send_json({'ok':True,'geocode':geo})
                if method=='DELETE':
                    reason=str(data.get('reason','')).strip()
                    if not reason:return self.send_json({'error':'Informe o motivo da exclusão'},400)
                    Supa.update('pevs',t,{'id':f'eq.{pid}'},{'active':False,'deleted_at':now_iso(),'deleted_by':u['id']});audit(t,u,'archive','pev',pid,f'PEV {old["name"]} enviado para lixeira',old,None,{'reason':reason});return self.send_json({'ok':True,'archived':True})
            if path=='/api/requests' and method=='POST':
                if role not in ('admin','commercial'):return self.send_json({'error':'Sem permissão'},403)
                item={'pev_id':int(data.get('pev_id') or 0),'requested_by':u['id'],'requested_date':data.get('requested_date'),'window_start':data.get('window_start') or None,'window_end':data.get('window_end') or None,'exact_time':data.get('exact_time') or None,'priority':data.get('priority') or 'normal','notes':data.get('notes') or '','internal_notes':data.get('internal_notes') or '','status':'pending'}
                if not item['pev_id'] or not item['requested_date']:return self.send_json({'error':'Informe PEV e data'},400)
                row=Supa.insert('scheduling_requests',t,item)[0];audit(t,u,'create','request',row['id'],'Solicitação criada',None,row);return self.send_json({'id':row['id']},201)
            if path.startswith('/api/requests/'):
                rid=int(path.strip('/').split('/')[2]);old=first(Supa.get('scheduling_requests',t,{'id':f'eq.{rid}','select':'*'}));
                if not old:return self.send_json({'error':'Solicitação não encontrada'},404)
                if method=='PUT':
                    if role not in ('admin','commercial'):return self.send_json({'error':'Sem permissão'},403)
                    if role=='commercial' and (old['requested_by']!=u['id'] or old['status']!='pending'):return self.send_json({'error':'Você só pode alterar solicitações próprias e pendentes'},403)
                    upd={k:(data.get(k) or None if k in ['window_start','window_end','exact_time'] else data.get(k)) for k in ['requested_date','window_start','window_end','exact_time','priority','notes','internal_notes'] if k in data};Supa.update('scheduling_requests',t,{'id':f'eq.{rid}'},upd);audit(t,u,'update','request',rid,'Solicitação alterada',old,upd);return self.send_json({'ok':True})
                if method=='DELETE':
                    if role not in ('admin','commercial','commercial_manager'):return self.send_json({'error':'Sem permissão'},403)
                    if role=='commercial' and old.get('requested_by')!=u['id']:return self.send_json({'error':'Você só pode excluir suas próprias solicitações'},403)
                    if role!='admin' and (old.get('route_id') is not None or old.get('status')!='pending'):
                        return self.send_json({'error':'Somente solicitações pendentes e ainda não vinculadas a uma rota podem ser excluídas'},409)
                    audit(t,u,'delete','request',rid,'Solicitação excluída definitivamente',old,None,{'admin_force':role=='admin'})
                    deleted=Supa.delete('scheduling_requests',t,{'id':f'eq.{rid}'})
                    if not deleted:return self.send_json({'error':'Não foi possível excluir a solicitação'},409)
                    return self.send_json({'ok':True})
            if path=='/api/optimize' and method=='POST':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                ids=[int(x) for x in (data.get('pev_ids') or data.get('stop_ids') or [])]
                if not ids:return self.send_json({'error':'Selecione pelo menos um PEV'},400)
                pevs=Supa.get('pevs',t,{'id':f'in.({",".join(map(str,ids))})','select':'*'});pm={p['id']:p for p in pevs};origin=settings_origin(t);points=[(origin['lat'],origin['lng'])];items=[]
                for pid in ids:
                    if pid in pm:items.append(pm[pid]);points.append(ensure_pev_coords(t,pm[pid]))
                dist,dur,source=osrm_matrix(points);meta={int(x['pev_id']):x for x in data.get('stops') or []};legacy_pri=data.get('priorities') or {};pri={i+1:meta.get(p['id'],{}).get('priority') or legacy_pri.get(str(p['id'])) or legacy_pri.get(p['id']) or p.get('default_priority','normal') for i,p in enumerate(items)};exact={i+1:meta.get(p['id'],{}).get('exact_time') for i,p in enumerate(items) if meta.get(p['id'],{}).get('exact_time')}
                order,warnings=optimize_order_with_exact_times(dist,dur,pri,exact,hhmm_to_minutes(data.get('start_time')),data.get('mode','best'));prev=0;totald=totalt=0;st=[]
                for seq,idx in enumerate(order,1):
                    p=items[idx-1];m=meta.get(p['id'],{});d=dist[prev][idx] or 0;du=dur[prev][idx] or 0;totald+=d;totalt+=du;prev=idx;st.append({**p,'pev':p,'pev_id':p['id'],'sequence':seq,'priority':m.get('priority') or legacy_pri.get(str(p['id'])) or legacy_pri.get(p['id']) or p.get('default_priority','normal'),'service_type':m.get('service_type') or 'collection','window_start':m.get('window_start') or hms(p.get('service_start')),'window_end':m.get('window_end') or hms(p.get('service_end')),'exact_time':m.get('exact_time') or '','request_id':m.get('request_id'),'distance_m':d,'duration_s':du})
                if data.get('return_origin') and order:totald+=dist[prev][0] or 0;totalt+=dur[prev][0] or 0
                return self.send_json({'origin':origin,'stops':st,'total_distance_m':totald,'total_duration_s':totalt,'source':source,'schedule_warnings':warnings})
            if path=='/api/routes' and method=='POST':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                driver=str(data.get('driver_id',''));date=data.get('route_date')
                if not driver or not date:return self.send_json({'error':'Informe data e motorista'},400)
                o=data.get('origin') or settings_origin(t)
                stops=[]
                for i,st in enumerate(data.get('stops') or [],1):
                    stops.append({
                        'pev_id':int(st['pev_id']),'request_id':st.get('request_id') or None,'sequence':i,
                        'priority':st.get('priority','normal'),'service_type':st.get('service_type') or 'collection','window_start':st.get('window_start') or None,
                        'window_end':st.get('window_end') or None,'exact_time':st.get('exact_time') or None,
                        'distance_m':st.get('distance_m') or 0,'duration_s':st.get('duration_s') or 0
                    })
                payload={
                    'name':data.get('name') or f'Rota {date}','route_date':date,'driver_id':driver,
                    'return_origin':False,'origin':o,
                    'total_distance_m':data.get('total_distance_m') or 0,'total_duration_s':data.get('total_duration_s') or 0,
                    'stops':stops
                }
                made=Supa.rpc('create_route_atomic',t,{'p_data':payload});rid=int(made['id'])
                return self.send_json(get_route_full(t,rid),201)
            if path.startswith('/api/routes/'):
                parts=path.strip('/').split('/');rid=int(parts[2]);action=parts[3] if len(parts)>3 else None
                if action=='release' and method=='POST':
                    if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                    changed=Supa.update('routes',t,{'id':f'eq.{rid}','status':'eq.draft'},{'status':'released','released_at':now_iso(),'released_by':u['id']})
                    if not changed:return self.send_json({'error':'A rota não está mais em rascunho'},409)
                    audit(t,u,'release','route',rid,'Rota liberada para motorista');return self.send_json(get_route_full(t,rid))
                if action=='start' and method=='POST':
                    if role!='driver':return self.send_json({'error':'Sem permissão'},403)
                    r=get_route_full(t,rid)
                    if not r or r['driver_id']!=u['id'] or r['status']!='released':return self.send_json({'error':'Rota não disponível para início'},409)
                    Supa.update('routes',t,{'id':f'eq.{rid}'},{'status':'in_progress','started_at':now_iso(),'started_lat':data.get('lat'),'started_lng':data.get('lng')})
                    try:
                        warnings=reorder_route_for_exact_times(t,rid,data.get('lat'),data.get('lng'),data.get('local_time',''))
                    except Exception as re:
                        print('[ROUTE START REORDER WARNING]',re);warnings=['Rota iniciada. Não foi possível recalcular a ordem automaticamente; mantenha a sequência planejada.']
                    audit(t,u,'start','route',rid,'Motorista iniciou a rota',None,None,{'schedule_warnings':warnings});x=get_route_full(t,rid);x['schedule_warnings']=warnings;return self.send_json(x)
                if action=='recalculate' and method=='POST':
                    if role!='driver':return self.send_json({'error':'Sem permissão'},403)
                    if data.get('lat') is None or data.get('lng') is None:return self.send_json({'error':'Localização atual necessária'},400)
                    warnings=reorder_route_for_exact_times(t,rid,data.get('lat'),data.get('lng'),data.get('local_time',''));audit(t,u,'recalculate','route',rid,'Rota restante recalculada',None,None,{'schedule_warnings':warnings});x=get_route_full(t,rid);x['schedule_warnings']=warnings;return self.send_json(x)
                if action=='finish' and method=='POST':
                    if role!='driver':return self.send_json({'error':'Sem permissão'},403)
                    r=try_auto_finish_route(t,u,rid,data.get('lat'),data.get('lng'))
                    if r.get('status')!='finished':
                        pending=[s for s in r.get('stops',[]) if s.get('status') in ('pending','arrived')]
                        missing=[]
                        weighed={int(w.get('stop_id')) for w in r.get('weighings',[]) if w.get('stop_id') is not None}
                        for st in r.get('stops',[]):
                            if st.get('status')=='completed' and st.get('service_type')=='collection' and int(st.get('id')) not in weighed: missing.append(st)
                        if pending:return self.send_json({'error':'Ainda existem paradas pendentes. O Administrador deve resolvê-las antes da pesagem.'},409)
                        if missing:return self.send_json({'error':'Registre todas as pesagens das coletas antes do encerramento.'},409)
                        return self.send_json({'error':'A rota será finalizada automaticamente quando todos os requisitos forem concluídos.'},409)
                    return self.send_json(r)
                if method=='DELETE' and action is None:
                    if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                    reason=str(data.get('reason','')).strip()
                    result=Supa.rpc('delete_route_atomic',t,{'p_route_id':rid,'p_reason':reason})
                    return self.send_json(result or {'ok':True})
            if path.startswith('/api/stops/') and method=='POST':
                parts=path.strip('/').split('/');sid=int(parts[2]);action=parts[3]
                stop=first(Supa.get('route_stops',t,{'id':f'eq.{sid}','select':'id,route_id,pev_id,status,service_type'}))
                if not stop:return self.send_json({'error':'Parada não encontrada'},404)
                route_id=int(stop['route_id'])
                if action=='evidence':
                    if role!='driver':return self.send_json({'error':'Sem permissão'},403)
                    expected='collection_material' if stop.get('service_type','collection')=='collection' else 'delivery_drum_location'
                    evtype=data.get('evidence_type') or expected
                    if evtype!=expected:return self.send_json({'error':'Tipo de evidência inválido para esta parada'},400)
                    storage_path=upload_test_evidence(t,data.get('image_data'),f'rota-{route_id}/pev-{stop["pev_id"]}/{evtype}')
                    ev=first(Supa.insert('route_evidences',t,{'route_id':route_id,'stop_id':sid,'pev_id':stop['pev_id'],'evidence_type':evtype,'storage_path':storage_path,'created_by':u['id']}))
                    audit(t,u,'evidence','stop',sid,'Evidência fotográfica registrada',None,None,{'evidence_type':evtype,'storage_path':storage_path})
                    return self.send_json({'ok':True,'evidence':ev})
                if action=='admin-resolve':
                    if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                    if stop.get('status') not in ('pending','arrived'):return self.send_json({'error':'Esta parada já foi resolvida'},409)
                    resolution=data.get('resolution')
                    if resolution not in ('completed','failed'):return self.send_json({'error':'Informe realizada ou não realizada'},400)
                    upd={'status':resolution,'completed_at':now_iso(),'driver_note':data.get('note') or ''}
                    if resolution=='failed':upd['failure_reason']=data.get('reason') or 'Resolvida pelo Administrador'
                    Supa.update('route_stops',t,{'id':f'eq.{sid}'},upd)
                    audit(t,u,'admin_resolve','stop',sid,'Administrador resolveu parada pendente',None,upd,{'route_id':route_id})
                    return self.send_json(try_auto_finish_route(t,u,route_id))
                if role!='driver':return self.send_json({'error':'Sem permissão'},403)
                if action not in ('arrive','complete','fail'):return self.send_json({'error':'Ação inválida'},400)
                if action=='complete':
                    expected='collection_material' if stop.get('service_type','collection')=='collection' else 'delivery_drum_location'
                    ev=Supa.get('route_evidences',t,{'stop_id':f'eq.{sid}','evidence_type':f'eq.{expected}','select':'id','limit':'1'})
                    if not ev:return self.send_json({'error':'Adicione a foto obrigatória antes de finalizar esta parada'},409)
                result=Supa.rpc('update_stop_atomic',t,{'p_stop_id':sid,'p_action':action,'p_data':data})
                return self.send_json(try_auto_finish_route(t,u,int(result['route_id']),data.get('lat'),data.get('lng')))
            if path.startswith('/api/routes/') and path.endswith('/weighings') and method=='POST':
                rid=int(path.strip('/').split('/')[2])
                if role!='driver':return self.send_json({'error':'Sem permissão'},403)
                stop_id=int(data.get('stop_id') or 0);weight=num(data.get('weight_kg'))
                if not weight or weight<=0:return self.send_json({'error':'Informe um peso válido'},400)
                stop=first(Supa.get('route_stops',t,{'id':f'eq.{stop_id}','route_id':f'eq.{rid}','select':'id,route_id,pev_id,status,service_type'}))
                if not stop or stop.get('status')!='completed' or stop.get('service_type')!='collection':return self.send_json({'error':'Pesagem disponível apenas para coleta realizada'},409)
                if Supa.get('route_weighings',t,{'stop_id':f'eq.{stop_id}','select':'id','limit':'1'}):return self.send_json({'error':'Esta coleta já possui pesagem'},409)
                storage_path=upload_test_evidence(t,data.get('image_data'),f'rota-{rid}/pev-{stop["pev_id"]}/weighing_scale')
                ev=first(Supa.insert('route_evidences',t,{'route_id':rid,'stop_id':stop_id,'pev_id':stop['pev_id'],'evidence_type':'weighing_scale','storage_path':storage_path,'created_by':u['id']}))
                Supa.insert('route_weighings',t,{'route_id':rid,'stop_id':stop_id,'pev_id':stop['pev_id'],'weight_kg':weight,'evidence_id':ev['id'],'created_by':u['id']})
                Supa.update('route_stops',t,{'id':f'eq.{stop_id}'},{'collected_weight_kg':weight})
                audit(t,u,'weighing','route',rid,f'Pesagem registrada: {weight:.3f} kg',None,None,{'stop_id':stop_id,'pev_id':stop['pev_id'],'weight_kg':weight})
                return self.send_json(try_auto_finish_route(t,u,rid,data.get('lat'),data.get('lng')))
            if path.startswith('/api/routes/') and path.endswith('/location') and method=='POST':
                rid=int(path.strip('/').split('/')[2])
                if role!='driver':return self.send_json({'error':'Sem permissão'},403)
                if data.get('lat') is None or data.get('lng') is None:return self.send_json({'error':'Localização inválida'},400)
                Supa.insert('driver_location_updates',t,{'route_id':rid,'driver_id':u['id'],'lat':data.get('lat'),'lng':data.get('lng'),'accuracy_m':data.get('accuracy')})
                return self.send_json({'ok':True})
            if path=='/api/settings' and method=='PUT':
                if role!='admin':return self.send_json({'error':'Sem permissão'},403)
                old=first(Supa.get('settings',t,{'id':'eq.1','select':'*'}));upd={k:data.get(k) for k in ['company_name','origin_name','origin_mode','origin_cep','origin_street','origin_number','origin_complement','origin_district','origin_city','origin_state']};upd['origin_lat']=num(data.get('origin_lat'));upd['origin_lng']=num(data.get('origin_lng'));upd['origin_location_confirmed']=upd['origin_lat'] is not None and upd['origin_lng'] is not None;Supa.update('settings',t,{'id':'eq.1'},upd);audit(t,u,'update','settings',1,'Configurações alteradas',old,upd);return self.send_json({'ok':True})
            return self.send_json({'error':'Endpoint não encontrado'},404)
        except RuntimeError as e:
            msg=str(e);print(f'[API ERROR] {method} {path}: {msg}');status=409 if 'duplicate key' in msg.lower() or 'violates unique' in msg.lower() or 'já existe' in msg.lower() else 400;return self.send_json({'error':msg},status)
        except Exception as e:
            print(f'[API ERROR] {method} {path}: {type(e).__name__}: {e}')
            return self.send_json({'error':str(e)},400)

    def static(self,path):
        if path=='/':path='/index.html'
        rel=Path(path.lstrip('/'))
        target=(STATIC_DIR/rel).resolve()
        try:target.relative_to(STATIC_DIR.resolve())
        except:return self.send_error(403)
        if not target.is_file():return self.send_error(404)
        data=target.read_bytes();ctype=mimetypes.guess_type(str(target))[0] or 'application/octet-stream';self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-cache' if target.name in ('index.html','app.js','service-worker.js','sw.js') else 'public, max-age=3600');self.common_security_headers();self.end_headers();self.wfile.write(data)
    def log_message(self,fmt,*args): print(f'[{datetime.now().strftime("%H:%M:%S")}] {self.address_string()} - {fmt%args}')

class RotaHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    request_queue_size=64

def main():
    print('='*58)
    print(f'ROTA PROXIMA - BUILD {BUILD_ID}')
    if IS_RENDER:
        print(f'Rota Próxima + Supabase no Render: {os.environ.get("RENDER_EXTERNAL_URL","URL publica sera exibida pelo Render")}')
    else:
        print(f'Rota Próxima + Supabase em http://localhost:{PORT}')
    print(f'Escutando em: {HOST}:{PORT} (IPv4)')
    print('Banco remoto: Supabase Sao Paulo. routes.db nao e utilizado.')
    print('Supabase: sessao com refresh automatico, PEV via RPC e rotas atomicas.')
    print('='*58)
    RotaHTTPServer((HOST,PORT),AppHandler).serve_forever()

if __name__=='__main__':main()
