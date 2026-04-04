from flask import Flask, render_template, request, jsonify, make_response
import sqlite3, os, json
from urllib.parse import quote as _quote
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ahpc_civil1.db')

app.jinja_env.filters['urlencode'] = lambda s: _quote(str(s), safe='')
app.jinja_env.filters['tojson']    = lambda v: json.dumps(v, ensure_ascii=False)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def query(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

# ── RUTAS ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as t FROM registros")
    total = cur.fetchone()['t']
    cur.execute("SELECT MIN(anio) as mn, MAX(anio) as mx FROM registros WHERE anio IS NOT NULL AND anio >= 1883 AND anio <= 1925")
    rango = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT causa) as t FROM registros WHERE causa IS NOT NULL AND causa != ''")
    causas = cur.fetchone()['t']
    cur.execute("""SELECT causa, COUNT(*) as t FROM registros
                   WHERE causa IS NOT NULL AND causa != ''
                   GROUP BY causa ORDER BY t DESC LIMIT 12""")
    top_causas = [dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT (anio/10*10) as decada, COUNT(*) as t FROM registros
                   WHERE anio IS NOT NULL GROUP BY decada ORDER BY decada""")
    por_decada = [dict(r) for r in cur.fetchall()]
    conn.close()
    return render_template('index.html',
        total=total, anio_inicio=rango['mn'], anio_fin=rango['mx'],
        causas=causas, top_causas=top_causas, por_decada=por_decada)

@app.route('/buscar')
def buscar():
    partes_pre = request.args.get('partes', '')
    causa_pre  = request.args.get('causa', '')
    return render_template('buscar.html', partes_pre=partes_pre, causa_pre=causa_pre)

@app.route('/api/buscar')
def api_buscar():
    partes     = request.args.get('partes', '').strip()
    causa      = request.args.get('causa', '').strip()
    anio_desde = request.args.get('anio_desde', '').strip()
    anio_hasta = request.args.get('anio_hasta', '').strip()
    legajo     = request.args.get('legajo', '').strip()
    expediente = request.args.get('expediente', '').strip()
    texto      = request.args.get('texto', '').strip()
    page       = int(request.args.get('page', 1))
    per_page   = 50
    offset     = (page - 1) * per_page

    if texto:
        sql = """SELECT r.id, r.anio, r.legajo, r.expediente, r.partes, r.causa
                 FROM registros r
                 WHERE r.id IN (SELECT rowid FROM registros_fts WHERE registros_fts MATCH ?)
                 ORDER BY r.partes ASC, r.anio ASC LIMIT ? OFFSET ?"""
        count_sql = "SELECT COUNT(*) as t FROM registros WHERE id IN (SELECT rowid FROM registros_fts WHERE registros_fts MATCH ?)"
        rows      = query(sql, (texto, per_page, offset))
        count_row = query(count_sql, (texto,))
    else:
        cond   = ["1=1"]
        params = []
        if partes:
            cond.append("partes LIKE ?"); params.append(f"%{partes}%")
        if causa:
            cond.append("causa LIKE ?");  params.append(f"%{causa}%")
        if anio_desde:
            cond.append("anio >= ?");     params.append(int(anio_desde))
        if anio_hasta:
            cond.append("anio <= ?");     params.append(int(anio_hasta))
        if legajo:
            cond.append("legajo = ?");    params.append(legajo)
        if expediente:
            cond.append("expediente = ?"); params.append(expediente)
        where     = " AND ".join(cond)
        sql       = f"""SELECT id, anio, legajo, expediente, partes, causa
                        FROM registros WHERE {where}
                        ORDER BY partes ASC, anio ASC LIMIT ? OFFSET ?"""
        count_sql = f"SELECT COUNT(*) as t FROM registros WHERE {where}"
        rows      = query(sql, params + [per_page, offset])
        count_row = query(count_sql, params)

    total     = count_row[0]['t'] if count_row else 0
    registros = [dict(r) for r in rows]
    return jsonify({'total': total, 'page': page, 'per_page': per_page, 'registros': registros})

@app.route('/api/causas-autocomplete')
def causas_autocomplete():
    q = request.args.get('q', '').strip().upper()
    if len(q) < 2:
        return jsonify([])
    rows = query("""SELECT causa, COUNT(*) as t FROM registros
                    WHERE UPPER(causa) LIKE ?
                    GROUP BY causa ORDER BY t DESC LIMIT 12""", (f"%{q}%",))
    return jsonify([{'causa': r['causa'], 'total': r['t']} for r in rows])

@app.route('/api/partes-autocomplete')
def partes_autocomplete():
    q = request.args.get('q', '').strip().upper()
    if len(q) < 2:
        return jsonify([])
    rows = query("""SELECT partes, COUNT(*) as t FROM registros
                    WHERE UPPER(partes) LIKE ?
                    GROUP BY partes ORDER BY t DESC LIMIT 12""", (f"{q}%",))
    return jsonify([{'partes': r['partes'], 'total': r['t']} for r in rows])

@app.route('/detalle/<int:rid>')
def detalle(rid):
    rows = query("SELECT * FROM registros WHERE id = ?", (rid,))
    if not rows:
        return "Registro no encontrado", 404
    reg = dict(rows[0])
    # Otros expedientes con el mismo apellido (excluye el actual)
    apellido = reg['partes'].split(',')[0].strip() if reg['partes'] else ''
    otros_partes = []
    if apellido:
        otros_partes = query("""SELECT id, anio, legajo, expediente, partes, causa
                                FROM registros WHERE partes LIKE ? AND id != ?
                                ORDER BY partes ASC, anio ASC LIMIT 50""",
                             (f"{apellido}%", rid))
    return render_template('detalle.html', reg=reg,
                           otros_partes=[dict(r) for r in otros_partes],
                           apellido=apellido)

@app.route('/causa/<path:nombre>')
def por_causa(nombre):
    rows = query("""SELECT id, anio, legajo, expediente, partes, causa
                    FROM registros WHERE causa = ?
                    ORDER BY anio ASC, partes ASC""", (nombre,))
    if not rows:
        return "Causa no encontrada", 404
    return render_template('por_causa.html', causa=nombre, registros=[dict(r) for r in rows])

@app.route('/estadisticas')
def estadisticas():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""SELECT (anio/10*10) as decada, COUNT(*) as total
                   FROM registros WHERE anio IS NOT NULL
                   GROUP BY decada ORDER BY decada""")
    por_decada = [dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT causa, COUNT(*) as total FROM registros
                   WHERE causa IS NOT NULL GROUP BY causa ORDER BY total DESC LIMIT 30""")
    top_causas = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) as t FROM registros"); total = cur.fetchone()['t']
    cur.execute("SELECT COUNT(DISTINCT causa) as t FROM registros WHERE causa IS NOT NULL"); total_causas = cur.fetchone()['t']
    cur.execute("SELECT COUNT(DISTINCT legajo) as t FROM registros WHERE legajo IS NOT NULL"); total_legajos = cur.fetchone()['t']
    conn.close()
    return render_template('estadisticas.html',
        por_decada=por_decada, top_causas=top_causas,
        total=total, total_causas=total_causas, total_legajos=total_legajos)

@app.route('/api/exportar-pdf')
def exportar_pdf():
    partes     = request.args.get('partes', '').strip()
    causa      = request.args.get('causa', '').strip()
    anio_desde = request.args.get('anio_desde', '').strip()
    anio_hasta = request.args.get('anio_hasta', '').strip()
    texto      = request.args.get('texto', '').strip()

    if texto:
        rows = query("""SELECT id, anio, legajo, expediente, partes, causa FROM registros
                        WHERE id IN (SELECT rowid FROM registros_fts WHERE registros_fts MATCH ?)
                        ORDER BY partes ASC, anio ASC LIMIT 500""", (texto,))
    else:
        cond = ["1=1"]; params = []
        if partes:     cond.append("partes LIKE ?");   params.append(f"%{partes}%")
        if causa:      cond.append("causa LIKE ?");    params.append(f"%{causa}%")
        if anio_desde: cond.append("anio >= ?");       params.append(int(anio_desde))
        if anio_hasta: cond.append("anio <= ?");       params.append(int(anio_hasta))
        where = " AND ".join(cond)
        rows  = query(f"""SELECT id, anio, legajo, expediente, partes, causa
                          FROM registros WHERE {where}
                          ORDER BY partes ASC, anio ASC LIMIT 500""", params)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    cell  = ParagraphStyle('cell', fontSize=7, leading=9)
    title = ParagraphStyle('t', fontSize=13, leading=16, alignment=TA_CENTER, fontName='Helvetica-Bold')
    sub   = ParagraphStyle('s', fontSize=8, leading=11, alignment=TA_CENTER)

    elements = [
        Paragraph("ARCHIVO HISTÓRICO DE LA PROVINCIA DE CÓRDOBA", title),
        Paragraph("Juzgado Civil Capital 1° Nominación · Índice Onomástico de Expedientes (1883–1925)", sub),
        Spacer(1, .2*inch),
    ]
    data = [['Año', 'Legajo', 'Expte.', 'Partes', 'Causa']]
    for r in rows:
        data.append([
            str(r['anio'] or ''),
            str(r['legajo'] or ''),
            str(r['expediente'] or ''),
            Paragraph(str(r['partes'] or ''), cell),
            Paragraph(str(r['causa'] or ''), cell),
        ])
    t = Table(data, colWidths=[35, 42, 38, 300, 140])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0), colors.HexColor('#2a1a0a')),
        ('TEXTCOLOR',     (0,0), (-1,0), colors.HexColor('#e8d0a0')),
        ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,0), 8),
        ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
        ('ALIGN',         (3,1), (4,-1), 'LEFT'),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('GRID',          (0,0), (-1,-1), .5, colors.HexColor('#cccccc')),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#fdf6ec')]),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    doc.build(elements)
    pdf = buffer.getvalue(); buffer.close()
    resp = make_response(pdf)
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = 'inline; filename=ahpc_civil1.pdf'
    return resp

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5005)
