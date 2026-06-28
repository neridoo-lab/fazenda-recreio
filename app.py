from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_file, session
from database import (
    init_db, seed_categorias, seed_admin, connect,
    verificar_usuario, registrar_log, get_all_usuarios,
    add_usuario, delete_usuario, alterar_senha, get_logs_acesso,
    sincronizar_tudo, verificar_internet
)
from datetime import datetime
import csv
from io import StringIO, BytesIO
from functools import wraps
import sqlite3
import threading
import time

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("⚠️ ReportLab não instalado. pip install reportlab")

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui_mude_para_algo_seguro'

init_db()
seed_categorias()
seed_admin()


def sincronizador_automatico():
    while True:
        try:
            if verificar_internet():
                print("🌐 Internet detectada! Sincronizando...")
                sincronizar_tudo()
            else:
                print("📡 Sem internet. Modo offline.")
            time.sleep(60)
        except Exception as e:
            print(f"Erro no sincronizador: {e}")
            time.sleep(60)


thread_sincronizacao = threading.Thread(target=sincronizador_automatico, daemon=True)
thread_sincronizacao.start()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            flash('Por favor, faça login para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            flash('Por favor, faça login para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        if session.get('tipo') != 'admin':
            flash('Acesso negado. Área restrita ao administrador.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario")
        senha = request.form.get("senha")
        user = verificar_usuario(usuario, senha)
        if user:
            session['usuario_id'] = user['id']
            session['usuario'] = user['usuario']
            session['nome'] = user['nome']
            session['tipo'] = user['tipo']
            registrar_log(usuario, f"Login realizado", request.remote_addr)
            flash(f'Bem-vindo, {user["nome"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            registrar_log(usuario, f"Tentativa de login falhou", request.remote_addr)
            flash('Usuário ou senha inválidos!', 'danger')
    return render_template("login.html")


@app.route("/logout")
def logout():
    if 'usuario' in session:
        registrar_log(session['usuario'], f"Logout realizado", request.remote_addr)
    session.clear()
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('login'))


@app.route("/")
@login_required
def dashboard():
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT nome, quantidade FROM categorias ORDER BY id")
    categorias = cursor.fetchall()
    cursor.execute("""
        SELECT tipo, categoria, quantidade, data, usuario
        FROM movimentacoes
        ORDER BY id DESC
        LIMIT 10
    """)
    ultimas = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM movimentacoes")
    total_movimentacoes = cursor.fetchone()[0]
    conn.close()
    total = sum([c[1] for c in categorias])
    total_femeas = 0
    total_machos = 0
    for c in categorias:
        if c[0] in ["Matrizes", "Novilhas", "Bezerras"]:
            total_femeas += c[1]
        elif c[0] in ["Touros", "Garrotes", "Bezerros"]:
            total_machos += c[1]
    online = verificar_internet()
    return render_template(
        "dashboard.html",
        categorias=categorias,
        ultimas=ultimas,
        total=total,
        total_femeas=total_femeas,
        total_machos=total_machos,
        total_movimentacoes=total_movimentacoes,
        usuario=session.get('nome'),
        tipo=session.get('tipo'),
        online=online
    )


@app.route("/sincronizar")
@login_required
def sincronizar_manual():
    if verificar_internet():
        enviados = sincronizar_tudo()
        flash(f"Sincronização concluída! {enviados} registros enviados.", "success")
    else:
        flash("Sem conexão com a internet. Tente novamente quando tiver sinal.", "warning")
    return redirect(url_for("dashboard"))


@app.route("/movimentacao", methods=["GET", "POST"])
@login_required
def movimentacao():
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM categorias ORDER BY id")
    categorias = [c[0] for c in cursor.fetchall()]
    if request.method == "POST":
        tipo = request.form["tipo"]
        categoria = request.form["categoria"]
        sexo = request.form.get("sexo", "")
        quantidade = int(request.form["quantidade"])
        if quantidade <= 0:
            flash("A quantidade deve ser maior que zero!", "danger")
            conn.close()
            return render_template("movimentacao.html", categorias=categorias)
        if tipo in ["Venda", "Morte", "Abate"]:
            cursor.execute("SELECT quantidade FROM categorias WHERE nome = ?", (categoria,))
            resultado = cursor.fetchone()
            estoque_atual = resultado[0] if resultado else 0
            if quantidade > estoque_atual:
                flash(f"Estoque insuficiente! Disponível: {estoque_atual}", "danger")
                conn.close()
                return render_template("movimentacao.html", categorias=categorias)
        cursor.execute("""
            INSERT INTO movimentacoes (tipo, categoria, sexo, quantidade, usuario, sincronizado)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tipo, categoria, sexo, quantidade, session.get('usuario'), 0))
        if tipo in ["Nascimento", "Compra"]:
            cursor.execute("""
                UPDATE categorias
                SET quantidade = quantidade + ?
                WHERE nome = ?
            """, (quantidade, categoria))
        else:
            cursor.execute("""
                UPDATE categorias
                SET quantidade = quantidade - ?
                WHERE nome = ?
            """, (quantidade, categoria))
        conn.commit()
        conn.close()
        registrar_log(session.get('usuario'), f"Movimentação: {tipo} - {categoria} x{quantidade}", request.remote_addr)
        flash(f"Movimentação registrada com sucesso!", "success")
        if verificar_internet():
            sincronizar_tudo()
        return redirect(url_for("dashboard"))
    conn.close()
    return render_template("movimentacao.html", categorias=categorias)


@app.route("/cadastro_inicial", methods=["GET", "POST"])
@admin_required
def cadastro_inicial():
    conn = connect()
    cursor = conn.cursor()
    if request.method == "POST":
        categorias = ["Matrizes", "Novilhas", "Bezerras", "Touros", "Garrotes", "Bezerros"]
        for categoria in categorias:
            quantidade = int(request.form[categoria])
            if quantidade < 0:
                flash(f"Quantidade negativa para {categoria}!", "danger")
                conn.close()
                return redirect(url_for("cadastro_inicial"))
            cursor.execute("""
                UPDATE categorias
                SET quantidade=?
                WHERE nome=?
            """, (quantidade, categoria))
        conn.commit()
        conn.close()
        registrar_log(session.get('usuario'), "Cadastro inicial atualizado", request.remote_addr)
        flash("Cadastro inicial atualizado com sucesso!", "success")
        return redirect(url_for("dashboard"))
    cursor.execute("SELECT nome, quantidade FROM categorias ORDER BY id")
    dados = cursor.fetchall()
    conn.close()
    return render_template("cadastro_inicial.html", dados=dados)


@app.route("/historico")
@login_required
def historico():
    conn = connect()
    cursor = conn.cursor()
    tipo = request.args.get('tipo', '')
    categoria = request.args.get('categoria', '')
    query = """
        SELECT tipo, categoria, sexo, quantidade, data, usuario
        FROM movimentacoes
        WHERE 1=1
    """
    params = []
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    movimentacoes = cursor.fetchall()
    cursor.execute("SELECT nome FROM categorias ORDER BY id")
    categorias = [c[0] for c in cursor.fetchall()]
    tipos = ["Nascimento", "Compra", "Venda", "Morte", "Abate"]
    conn.close()
    return render_template(
        "historico.html",
        movimentacoes=movimentacoes,
        categorias=categorias,
        tipos=tipos,
        filtro_tipo=tipo,
        filtro_categoria=categoria
    )


@app.route("/relatorios")
@login_required
def relatorios():
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT nome, quantidade FROM categorias ORDER BY id")
    categorias = cursor.fetchall()
    cursor.execute("""
        SELECT tipo, SUM(quantidade) as total
        FROM movimentacoes
        GROUP BY tipo
        ORDER BY tipo
    """)
    movimentacoes_por_tipo = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM movimentacoes")
    total_movimentacoes = cursor.fetchone()[0]
    cursor.execute("""
        SELECT sexo, SUM(quantidade) 
        FROM movimentacoes 
        WHERE sexo IS NOT NULL AND sexo != ''
        GROUP BY sexo
    """)
    movimentacoes_por_sexo = cursor.fetchall()
    cursor.execute("""
        SELECT usuario, acao, ip, data 
        FROM logs_acesso 
        ORDER BY id DESC 
        LIMIT 100
    """)
    logs_acesso = cursor.fetchall()
    conn.close()
    return render_template(
        "relatorios.html",
        categorias=categorias,
        movimentacoes_por_tipo=movimentacoes_por_tipo,
        total_movimentacoes=total_movimentacoes,
        movimentacoes_por_sexo=movimentacoes_por_sexo,
        logs_acesso=logs_acesso
    )


@app.route("/admin/usuarios")
@admin_required
def admin_usuarios():
    usuarios = get_all_usuarios()
    logs = get_logs_acesso(50)
    return render_template("admin_usuarios.html", usuarios=usuarios, logs=logs)


@app.route("/admin/usuario/add", methods=["POST"])
@admin_required
def admin_add_usuario():
    nome = request.form.get("nome")
    usuario = request.form.get("usuario")
    senha = request.form.get("senha")
    tipo = request.form.get("tipo", "funcionario")
    if not nome or not usuario or not senha:
        flash("Todos os campos são obrigatórios!", "danger")
        return redirect(url_for("admin_usuarios"))
    if len(senha) < 6:
        flash("A senha deve ter pelo menos 6 caracteres!", "danger")
        return redirect(url_for("admin_usuarios"))
    if add_usuario(nome, usuario, senha, tipo):
        registrar_log(session.get('usuario'), f"Adicionou usuário: {usuario}", request.remote_addr)
        flash(f"Usuário {usuario} adicionado com sucesso!", "success")
    else:
        flash(f"Erro: Usuário {usuario} já existe!", "danger")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuario/delete/<int:id>")
@admin_required
def admin_delete_usuario(id):
    sucesso, mensagem = delete_usuario(id)
    if sucesso:
        registrar_log(session.get('usuario'), f"Removeu usuário ID: {id}", request.remote_addr)
        flash(mensagem, "success")
    else:
        flash(mensagem, "danger")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuario/alterar_senha", methods=["POST"])
@admin_required
def admin_alterar_senha():
    id_usuario = request.form.get("id_usuario")
    nova_senha = request.form.get("nova_senha")
    if not id_usuario or not nova_senha:
        flash("Todos os campos são obrigatórios!", "danger")
        return redirect(url_for("admin_usuarios"))
    if len(nova_senha) < 6:
        flash("A senha deve ter pelo menos 6 caracteres!", "danger")
        return redirect(url_for("admin_usuarios"))
    alterar_senha(int(id_usuario), nova_senha)
    registrar_log(session.get('usuario'), f"Alterou senha do usuário ID: {id_usuario}", request.remote_addr)
    flash("Senha alterada com sucesso!", "success")
    return redirect(url_for("admin_usuarios"))


@app.route("/exportar/csv")
@login_required
def exportar_csv():
    conn = connect()
    cursor = conn.cursor()
    tipo = request.args.get('tipo', '')
    categoria = request.args.get('categoria', '')
    query = """
        SELECT tipo, categoria, sexo, quantidade, data, usuario
        FROM movimentacoes
        WHERE 1=1
    """
    params = []
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    movimentacoes = cursor.fetchall()
    conn.close()
    si = StringIO()
    writer = csv.writer(si, delimiter=',', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['Tipo', 'Categoria', 'Sexo', 'Quantidade', 'Data', 'Usuário'])
    for m in movimentacoes:
        writer.writerow([m[0], m[1], m[2] if m[2] else '', m[3], m[4], m[5] if m[5] else ''])
    output = si.getvalue()
    registrar_log(session.get('usuario'), "Exportou CSV", request.remote_addr)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=movimentacoes.csv"}
    )


@app.route("/exportar/pdf")
@login_required
def exportar_pdf():
    if not REPORTLAB_AVAILABLE:
        flash("Biblioteca ReportLab não está instalada. Execute: pip install reportlab", "danger")
        return redirect(url_for("historico"))
    conn = connect()
    cursor = conn.cursor()
    tipo = request.args.get('tipo', '')
    categoria = request.args.get('categoria', '')
    query = """
        SELECT tipo, categoria, sexo, quantidade, data, usuario
        FROM movimentacoes
        WHERE 1=1
    """
    params = []
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    movimentacoes = cursor.fetchall()
    cursor.execute("SELECT nome, quantidade FROM categorias ORDER BY id")
    categorias = cursor.fetchall()
    cursor.execute("""
        SELECT usuario, acao, ip, data 
        FROM logs_acesso 
        ORDER BY id DESC 
        LIMIT 50
    """)
    logs_acesso = cursor.fetchall()
    conn.close()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    elementos = []
    titulo_style = ParagraphStyle(
        'Titulo',
        parent=styles['Heading1'],
        fontSize=20,
        alignment=TA_CENTER,
        spaceAfter=20
    )
    elementos.append(Paragraph("Relatório do Rebanho - Fazenda Recreio", titulo_style))
    elementos.append(Spacer(1, 10))
    data_style = ParagraphStyle(
        'Data',
        parent=styles['Normal'],
        fontSize=12,
        alignment=TA_CENTER,
        spaceAfter=20
    )
    elementos.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", data_style))
    elementos.append(Spacer(1, 10))
    total = sum([c[1] for c in categorias])
    resumo_style = ParagraphStyle(
        'Resumo',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=10
    )
    elementos.append(Paragraph("📊 Resumo do Rebanho", resumo_style))
    dados_categorias = [['Categoria', 'Quantidade']]
    for c in categorias:
        dados_categorias.append([c[0], str(c[1])])
    dados_categorias.append(['TOTAL', str(total)])
    tabela_categorias = Table(dados_categorias, colWidths=[2*inch, 1*inch])
    tabela_categorias.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.green),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elementos.append(tabela_categorias)
    elementos.append(Spacer(1, 20))
    if movimentacoes:
        elementos.append(Paragraph("📋 Histórico de Movimentações", resumo_style))
        elementos.append(Paragraph(f"Total: {len(movimentacoes)} registros", styles['Normal']))
        elementos.append(Spacer(1, 10))
        dados_mov = [['Tipo', 'Categoria', 'Sexo', 'Quantidade', 'Data', 'Usuário']]
        for m in movimentacoes:
            sexo = m[2] if m[2] else '-'
            usuario = m[5] if m[5] else '-'
            dados_mov.append([m[0], m[1], sexo, str(m[3]), m[4], usuario])
        tabela_mov = Table(dados_mov, colWidths=[1.0*inch, 1.0*inch, 0.8*inch, 0.8*inch, 1.2*inch, 0.8*inch])
        tabela_mov.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.green),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        elementos.append(tabela_mov)
    elementos.append(Spacer(1, 20))
    elementos.append(Paragraph("👥 Relatório de Acesso dos Usuários", resumo_style))
    elementos.append(Spacer(1, 10))
    if logs_acesso:
        dados_logs = [['Usuário', 'Ação', 'IP', 'Data/Hora']]
        for log in logs_acesso:
            dados_logs.append([log[0], log[1], log[2], log[3]])
        tabela_logs = Table(dados_logs, colWidths=[1.0*inch, 2.0*inch, 0.8*inch, 1.5*inch])
        tabela_logs.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.green),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        elementos.append(tabela_logs)
    else:
        elementos.append(Paragraph("Nenhum log de acesso registrado.", styles['Normal']))
    elementos.append(Spacer(1, 30))
    rodape_style = ParagraphStyle(
        'Rodape',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey
    )
    elementos.append(Paragraph("Relatório gerado automaticamente pelo sistema Fazenda Recreio", rodape_style))
    doc.build(elementos)
    buffer.seek(0)
    registrar_log(session.get('usuario'), "Exportou PDF", request.remote_addr)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'relatorio_rebanho_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'
    )


if __name__ == "__main__":
    import socket
    def get_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return '127.0.0.1'
    ip = get_ip()
    print("=" * 50)
    print("🏡 FAZENDA RECREIO - SISTEMA DE REBANHO")
    print("=" * 50)
    print(f"📍 Acesse no celular: http://{ip}:5000")
    print(f"📍 Acesse no computador: http://127.0.0.1:5000")
    print("=" * 50)
    print("👤 Usuário: admin")
    print("🔑 Senha: admin123")
    print("=" * 50)
    print("📡 Modo: Offline + Sincronização Automática")
    print("   - Funciona sem internet")
    print("   - Sincroniza automaticamente quando tem sinal")
    print("=" * 50)
    app.run(host='0.0.0.0', debug=True, port=5000)
