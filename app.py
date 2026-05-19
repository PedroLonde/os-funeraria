from flask import Flask, request, jsonify, send_from_directory, session, make_response
import sqlite3
import os
import json
from datetime import datetime
import csv
import io

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'funeraria_secret_key_2024')

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    return '', 204

DB_PATH = 'funeraria.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        login TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        perfil TEXT NOT NULL CHECK(perfil IN ('agente','motorista','visualizador','admin')),
        ativo INTEGER DEFAULT 1,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS fornecedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        tipo_servico TEXT,
        contato TEXT,
        ativo INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS ordens_servico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_webluto TEXT UNIQUE NOT NULL,
        agente_id INTEGER NOT NULL,
        status TEXT DEFAULT 'aberta',
        observacoes TEXT,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(agente_id) REFERENCES usuarios(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS itens_os (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        os_id INTEGER NOT NULL,
        tipo_servico TEXT NOT NULL,
        fornecedor_id INTEGER,
        fornecedor_nome TEXT,
        local_execucao TEXT,
        motorista_id INTEGER,
        status TEXT DEFAULT 'pendente',
        observacao TEXT,
        FOREIGN KEY(os_id) REFERENCES ordens_servico(id),
        FOREIGN KEY(motorista_id) REFERENCES usuarios(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        usuario_nome TEXT,
        acao TEXT NOT NULL,
        tabela TEXT,
        registro_id INTEGER,
        dados_anteriores TEXT,
        dados_novos TEXT,
        data_hora TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute("SELECT id FROM usuarios WHERE login='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO usuarios (nome, login, senha, perfil) VALUES (?, ?, ?, ?)",
                  ('Administrador', 'admin', 'admin123', 'admin'))

    conn.commit()
    conn.close()

def registrar_log(usuario_id, usuario_nome, acao, tabela=None, registro_id=None, dados_ant=None, dados_nov=None):
    conn = get_db()
    conn.execute('''INSERT INTO logs (usuario_id, usuario_nome, acao, tabela, registro_id, dados_anteriores, dados_novos)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                 (usuario_id, usuario_nome, acao, tabela, registro_id,
                  json.dumps(dados_ant, ensure_ascii=False) if dados_ant else None,
                  json.dumps(dados_nov, ensure_ascii=False) if dados_nov else None))
    conn.commit()
    conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE login=? AND senha=? AND ativo=1",
                        (data['login'], data['senha'])).fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        session['user_nome'] = user['nome']
        session['user_perfil'] = user['perfil']
        return jsonify({'ok': True, 'nome': user['nome'], 'perfil': user['perfil'], 'id': user['id']})
    return jsonify({'ok': False, 'msg': 'Login ou senha incorretos'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({'ok': False}), 401
    return jsonify({'ok': True, 'id': session['user_id'], 'nome': session['user_nome'], 'perfil': session['user_perfil']})

def require_auth(perfis=None):
    if 'user_id' not in session:
        return False
    if perfis and session['user_perfil'] not in perfis:
        return False
    return True

@app.route('/api/usuarios', methods=['GET'])
def listar_usuarios():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()
    rows = conn.execute("SELECT id, nome, login, perfil, ativo FROM usuarios ORDER BY nome").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/usuarios', methods=['POST'])
def criar_usuario():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    try:
        conn = get_db()
        conn.execute("INSERT INTO usuarios (nome, login, senha, perfil) VALUES (?, ?, ?, ?)",
                     (data['nome'], data['login'], data['senha'], data['perfil']))
        conn.commit()
        conn.close()
        registrar_log(session['user_id'], session['user_nome'], f"Criou usuário {data['nome']}")
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'msg': 'Login já existe'}), 400

@app.route('/api/usuarios/<int:uid>', methods=['PUT'])
def editar_usuario(uid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE usuarios SET nome=?, perfil=?, ativo=? WHERE id=?",
                 (data['nome'], data['perfil'], data.get('ativo', 1), uid))
    if data.get('senha'):
        conn.execute("UPDATE usuarios SET senha=? WHERE id=?", (data['senha'], uid))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'], f"Editou usuário ID {uid}")
    return jsonify({'ok': True})

@app.route('/api/motoristas')
def listar_motoristas():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT id, nome FROM usuarios WHERE perfil='motorista' AND ativo=1 ORDER BY nome").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/agentes')
def listar_agentes():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT id, nome FROM usuarios WHERE perfil='agente' AND ativo=1 ORDER BY nome").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/fornecedores', methods=['GET'])
def listar_fornecedores():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT * FROM fornecedores WHERE ativo=1 ORDER BY nome").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/fornecedores', methods=['POST'])
def criar_fornecedor():
    if not require_auth(['admin', 'agente']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO fornecedores (nome, tipo_servico, contato) VALUES (?, ?, ?)",
                 (data['nome'], data.get('tipo_servico', ''), data.get('contato', '')))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'], f"Criou fornecedor {data['nome']}")
    return jsonify({'ok': True})

@app.route('/api/fornecedores/<int:fid>', methods=['PUT'])
def editar_fornecedor(fid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE fornecedores SET nome=?, tipo_servico=?, contato=?, ativo=? WHERE id=?",
                 (data['nome'], data.get('tipo_servico',''), data.get('contato',''), data.get('ativo',1), fid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/os', methods=['GET'])
def listar_os():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute('''
        SELECT os.*, u.nome as agente_nome
        FROM ordens_servico os
        JOIN usuarios u ON os.agente_id = u.id
        ORDER BY os.criado_em DESC
    ''').fetchall()
    result = []
    for r in rows:
        os_dict = dict(r)
        itens = conn.execute('''
            SELECT i.*, u.nome as motorista_nome
            FROM itens_os i
            LEFT JOIN usuarios u ON i.motorista_id = u.id
            WHERE i.os_id = ?
        ''', (r['id'],)).fetchall()
        os_dict['itens'] = [dict(i) for i in itens]
        result.append(os_dict)
    conn.close()
    return jsonify(result)

@app.route('/api/os', methods=['POST'])
def criar_os():
    if not require_auth(['agente', 'admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    existe = conn.execute("SELECT id FROM ordens_servico WHERE id_webluto=?", (data['id_webluto'],)).fetchone()
    if existe:
        conn.close()
        return jsonify({'ok': False, 'msg': f"ID Web Luto '{data['id_webluto']}' já está cadastrado"}), 400
    c = conn.cursor()
    c.execute('''INSERT INTO ordens_servico (id_webluto, agente_id, observacoes)
                 VALUES (?, ?, ?)''',
              (data['id_webluto'], session['user_id'], data.get('observacoes', '')))
    os_id = c.lastrowid
    for item in data.get('itens', []):
        c.execute('''INSERT INTO itens_os (os_id, tipo_servico, fornecedor_id, fornecedor_nome, local_execucao, observacao)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (os_id, item['tipo_servico'], item.get('fornecedor_id'), item.get('fornecedor_nome',''),
                   item.get('local_execucao',''), item.get('observacao','')))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'], f"Criou OS Web Luto {data['id_webluto']}", 'ordens_servico', os_id)
    return jsonify({'ok': True, 'os_id': os_id})

@app.route('/api/os/<int:os_id>', methods=['PUT'])
def editar_os(os_id):
    if not require_auth(['agente', 'admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    os_ant = dict(conn.execute("SELECT * FROM ordens_servico WHERE id=?", (os_id,)).fetchone())
    itens_ant = [dict(i) for i in conn.execute("SELECT * FROM itens_os WHERE os_id=?", (os_id,)).fetchall()]
    if 'id_webluto' in data:
        existe = conn.execute("SELECT id FROM ordens_servico WHERE id_webluto=? AND id!=?",
                              (data['id_webluto'], os_id)).fetchone()
        if existe:
            conn.close()
            return jsonify({'ok': False, 'msg': f"ID Web Luto '{data['id_webluto']}' já está em uso"}), 400
    conn.execute('''UPDATE ordens_servico SET id_webluto=?, observacoes=?, status=?
                    WHERE id=?''',
                 (data['id_webluto'], data.get('observacoes',''), data.get('status','aberta'), os_id))
    conn.execute("DELETE FROM itens_os WHERE os_id=?", (os_id,))
    for item in data.get('itens', []):
        conn.execute('''INSERT INTO itens_os (os_id, tipo_servico, fornecedor_id, fornecedor_nome, local_execucao, motorista_id, status, observacao)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                     (os_id, item['tipo_servico'], item.get('fornecedor_id'), item.get('fornecedor_nome',''),
                      item.get('local_execucao',''), item.get('motorista_id'), item.get('status','pendente'), item.get('observacao','')))
    conn.commit()
    os_nov = dict(conn.execute("SELECT * FROM ordens_servico WHERE id=?", (os_id,)).fetchone())
    itens_nov = [dict(i) for i in conn.execute("SELECT * FROM itens_os WHERE os_id=?", (os_id,)).fetchall()]
    conn.close()
    registrar_log(session['user_id'], session['user_nome'],
                  f"Editou OS ID {os_id}", 'ordens_servico', os_id,
                  {'os': os_ant, 'itens': itens_ant},
                  {'os': os_nov, 'itens': itens_nov})
    return jsonify({'ok': True})

@app.route('/api/item/<int:item_id>/atribuir', methods=['POST'])
def atribuir_motorista(item_id):
    if not require_auth(['motorista', 'admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    item_ant = dict(conn.execute("SELECT * FROM itens_os WHERE id=?", (item_id,)).fetchone())
    conn.execute("UPDATE itens_os SET motorista_id=?, status=? WHERE id=?",
                 (data.get('motorista_id'), data.get('status', 'em_andamento'), item_id))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'],
                  f"Atribuiu/atualizou item ID {item_id}", 'itens_os', item_id,
                  item_ant, {'motorista_id': data.get('motorista_id'), 'status': data.get('status')})
    return jsonify({'ok': True})

@app.route('/api/exportar', methods=['GET'])
def exportar():
    if not require_auth(['admin', 'visualizador', 'agente']):
        return jsonify({'ok': False}), 403
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')
    fornecedor = request.args.get('fornecedor', '')
    conn = get_db()
    query = '''
        SELECT os.id_webluto, os.criado_em, os.status as status_os,
               u.nome as agente,
               i.tipo_servico, i.fornecedor_nome, i.local_execucao,
               i.status as status_item,
               m.nome as motorista
        FROM ordens_servico os
        JOIN usuarios u ON os.agente_id = u.id
        JOIN itens_os i ON i.os_id = os.id
        LEFT JOIN usuarios m ON i.motorista_id = m.id
        WHERE 1=1
    '''
    params = []
    if data_ini:
        query += " AND DATE(os.criado_em) >= ?"
        params.append(data_ini)
    if data_fim:
        query += " AND DATE(os.criado_em) <= ?"
        params.append(data_fim)
    if fornecedor:
        query += " AND LOWER(i.fornecedor_nome) LIKE ?"
        params.append(f'%{fornecedor.lower()}%')
    rows = conn.execute(query, params).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID Web Luto', 'Data OS', 'Status OS', 'Agente', 'Tipo Serviço', 'Fornecedor', 'Local', 'Status Item', 'Motorista'])
    for r in rows:
        writer.writerow([r['id_webluto'], r['criado_em'][:10], r['status_os'],
                         r['agente'], r['tipo_servico'], r['fornecedor_nome'],
                         r['local_execucao'], r['status_item'], r['motorista'] or ''])
    resp = make_response('\ufeff' + output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=relatorio_os.csv'
    return resp

@app.route('/api/logs')
def listar_logs():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()
    rows = conn.execute("SELECT * FROM logs ORDER BY data_hora DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/')
@app.route('/<path:path>')
def index(path=''):
    return send_from_directory('templates', 'index.html')

if __name__ == '__main__':
    init_db()
    print("✓ Banco inicializado")
    print("✓ Admin padrão: login=admin / senha=admin123")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
