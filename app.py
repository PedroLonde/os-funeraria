from flask import Flask, request, jsonify, send_from_directory, session, make_response
import sqlite3
import os
import json
import csv
import io
from datetime import datetime

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

# Em produção defina DB_PATH via variável de ambiente apontando para o volume
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'funeraria.db'))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS unidades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        ativo INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        login TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        perfil TEXT NOT NULL CHECK(perfil IN ('agente','gerente','admin')),
        unidade_id INTEGER,
        ativo INTEGER DEFAULT 1,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS servicos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        modo TEXT NOT NULL CHECK(modo IN ('unico','diversos','quantitativo')),
        requer_observacao INTEGER DEFAULT 0,
        requer_faixas INTEGER DEFAULT 0,
        ativo INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS servico_opcoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        servico_id INTEGER NOT NULL,
        nome TEXT NOT NULL,
        ativo INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS fornecedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        endereco TEXT,
        contato TEXT,
        ativo INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS fornecedor_servicos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fornecedor_id INTEGER NOT NULL,
        servico_id INTEGER NOT NULL,
        custo REAL DEFAULT 0,
        UNIQUE(fornecedor_id, servico_id)
    )''')

    # Tabela de convênios
    c.execute('''CREATE TABLE IF NOT EXISTS convenios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        ativo INTEGER DEFAULT 1
    )''')

    # Tabela principal de OS
    c.execute('''CREATE TABLE IF NOT EXISTS ordens_servico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_webluto TEXT UNIQUE NOT NULL,
        nome_falecido TEXT NOT NULL,
        horario_sepultamento TEXT,
        agente_id INTEGER NOT NULL,
        unidade_nome TEXT,
        status TEXT DEFAULT 'aberta',
        observacoes TEXT,
        convenio TEXT DEFAULT '',
        convenio_id INTEGER,
        agente_captacao_id INTEGER,
        agente_atendimento_id INTEGER,
        valor_total REAL DEFAULT 0,
        custo_total REAL DEFAULT 0,
        comissao_total REAL DEFAULT 0,
        comissao_captacao REAL DEFAULT 0,
        comissao_atendimento REAL DEFAULT 0,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
        fechado_em TEXT
    )''')

    # Migrações para bancos existentes
    for migration_sql in [
        "ALTER TABLE ordens_servico ADD COLUMN convenio TEXT DEFAULT ''",
        "ALTER TABLE ordens_servico ADD COLUMN convenio_id INTEGER",
        "ALTER TABLE ordens_servico ADD COLUMN agente_captacao_id INTEGER",
        "ALTER TABLE ordens_servico ADD COLUMN agente_atendimento_id INTEGER",
        "ALTER TABLE ordens_servico ADD COLUMN valor_total REAL DEFAULT 0",
        "ALTER TABLE ordens_servico ADD COLUMN custo_total REAL DEFAULT 0",
        "ALTER TABLE ordens_servico ADD COLUMN comissao_total REAL DEFAULT 0",
        "ALTER TABLE ordens_servico ADD COLUMN comissao_captacao REAL DEFAULT 0",
        "ALTER TABLE ordens_servico ADD COLUMN comissao_atendimento REAL DEFAULT 0",
    ]:
        try:
            c.execute(migration_sql)
        except Exception:
            pass

    # Migração: suportar perfil 'gerente' recriando a tabela usuarios se necessário
    try:
        c.execute("INSERT INTO usuarios (nome, login, senha, perfil) VALUES ('_chk_','_chk_','_chk_','gerente')")
        c.execute("DELETE FROM usuarios WHERE login='_chk_'")
        conn.commit()
    except Exception:
        try:
            c.execute('''CREATE TABLE IF NOT EXISTS usuarios_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                login TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL,
                perfil TEXT NOT NULL CHECK(perfil IN ('agente','gerente','admin')),
                unidade_id INTEGER,
                ativo INTEGER DEFAULT 1,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            c.execute('''INSERT OR IGNORE INTO usuarios_v2
                         (id, nome, login, senha, perfil, unidade_id, ativo, criado_em)
                         SELECT id, nome, login, senha,
                                CASE WHEN perfil='admin' THEN 'admin'
                                     WHEN perfil='gerente' THEN 'gerente'
                                     ELSE 'agente' END,
                                unidade_id, ativo, criado_em
                         FROM usuarios''')
            c.execute('DROP TABLE usuarios')
            c.execute('ALTER TABLE usuarios_v2 RENAME TO usuarios')
            conn.commit()
        except Exception:
            pass


    c.execute('''CREATE TABLE IF NOT EXISTS itens_os (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        os_id INTEGER NOT NULL,
        servico_id INTEGER,
        servico_nome TEXT,
        servico_modo TEXT,
        fornecedor_id INTEGER,
        fornecedor_nome TEXT,
        fornecedor_endereco TEXT,
        custo REAL DEFAULT 0,
        quantidade INTEGER DEFAULT 1,
        opcoes_selecionadas TEXT,
        faixas TEXT,
        observacao TEXT,
        motorista_id INTEGER
    )''')

    # Pagamentos vinculados a cada OS
    c.execute('''CREATE TABLE IF NOT EXISTS pagamentos_os (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        os_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        valor REAL DEFAULT 0,
        parcelas INTEGER DEFAULT 1
    )''')

    # Configurações gerais do sistema (ex: juros de cartão)
    c.execute('''CREATE TABLE IF NOT EXISTS config_sistema (
        chave TEXT PRIMARY KEY,
        valor TEXT NOT NULL DEFAULT ''
    )''')

    # Valores padrão para juros de cartão — crédito por parcela (1x a 12x) + débito
    for parcela in range(1, 13):
        c.execute("INSERT OR IGNORE INTO config_sistema (chave, valor) VALUES (?, '0')",
                  (f'juros_credito_{parcela}',))
    c.execute("INSERT OR IGNORE INTO config_sistema (chave, valor) VALUES ('juros_debito', '0')")

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

# AUTH
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    user = conn.execute('''SELECT u.*, un.nome as unidade_nome
                           FROM usuarios u LEFT JOIN unidades un ON u.unidade_id = un.id
                           WHERE u.login=? AND u.senha=? AND u.ativo=1''',
                        (data['login'], data['senha'])).fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        session['user_nome'] = user['nome']
        session['user_perfil'] = user['perfil']
        session['user_unidade'] = user['unidade_nome'] or ''
        return jsonify({'ok': True, 'nome': user['nome'], 'perfil': user['perfil'],
                        'id': user['id'], 'unidade': user['unidade_nome'] or ''})
    return jsonify({'ok': False, 'msg': 'Login ou senha incorretos'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({'ok': False}), 401
    return jsonify({'ok': True, 'id': session['user_id'], 'nome': session['user_nome'],
                    'perfil': session['user_perfil'], 'unidade': session.get('user_unidade', '')})

def require_auth(perfis=None):
    if 'user_id' not in session:
        return False
    if perfis and session['user_perfil'] not in perfis:
        return False
    return True

# UNIDADES
@app.route('/api/unidades', methods=['GET'])
def listar_unidades():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT * FROM unidades WHERE ativo=1 ORDER BY nome").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/unidades', methods=['POST'])
def criar_unidade():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    try:
        conn = get_db()
        conn.execute("INSERT INTO unidades (nome) VALUES (?)", (data['nome'],))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'msg': 'Unidade já existe'}), 400

@app.route('/api/unidades/<int:uid>', methods=['PUT'])
def editar_unidade(uid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE unidades SET nome=?, ativo=? WHERE id=?",
                 (data['nome'], data.get('ativo', 1), uid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# USUÁRIOS
@app.route('/api/usuarios', methods=['GET'])
def listar_usuarios():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()
    rows = conn.execute('''SELECT u.id, u.nome, u.login, u.perfil, u.ativo, u.unidade_id,
                           un.nome as unidade_nome
                           FROM usuarios u LEFT JOIN unidades un ON u.unidade_id = un.id
                           ORDER BY u.nome''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/usuarios', methods=['POST'])
def criar_usuario():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    try:
        conn = get_db()
        conn.execute("INSERT INTO usuarios (nome, login, senha, perfil, unidade_id) VALUES (?, ?, ?, ?, ?)",
                     (data['nome'], data['login'], data['senha'], data['perfil'],
                      data.get('unidade_id') or None))
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
    conn.execute("UPDATE usuarios SET nome=?, perfil=?, ativo=?, unidade_id=? WHERE id=?",
                 (data['nome'], data['perfil'], data.get('ativo', 1),
                  data.get('unidade_id') or None, uid))
    if data.get('senha'):
        conn.execute("UPDATE usuarios SET senha=? WHERE id=?", (data['senha'], uid))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'], f"Editou usuário ID {uid}")
    return jsonify({'ok': True})

@app.route('/api/agentes')
def listar_agentes():
    """Retorna agentes e admins ativos — usado nos selects de Captação/Atendimento."""
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT id, nome FROM usuarios WHERE perfil IN ('agente','gerente','admin') AND ativo=1 ORDER BY nome"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/motoristas')
def listar_motoristas():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT id, nome FROM usuarios WHERE perfil='motorista' AND ativo=1 ORDER BY nome").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# SERVIÇOS
@app.route('/api/servicos', methods=['GET'])
def listar_servicos():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT * FROM servicos WHERE ativo=1 ORDER BY nome").fetchall()
    result = []
    for r in rows:
        s = dict(r)
        opcoes = conn.execute("SELECT * FROM servico_opcoes WHERE servico_id=? AND ativo=1 ORDER BY nome",
                              (r['id'],)).fetchall()
        s['opcoes'] = [dict(o) for o in opcoes]
        result.append(s)
    conn.close()
    return jsonify(result)

@app.route('/api/servicos', methods=['POST'])
def criar_servico():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    try:
        conn = get_db()
        conn.execute("INSERT INTO servicos (nome, modo, requer_observacao, requer_faixas) VALUES (?, ?, ?, ?)",
                     (data['nome'], data['modo'], data.get('requer_observacao', 0), data.get('requer_faixas', 0)))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'msg': 'Serviço já existe'}), 400

@app.route('/api/servicos/<int:sid>', methods=['PUT'])
def editar_servico(sid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE servicos SET nome=?, modo=?, requer_observacao=?, requer_faixas=?, ativo=? WHERE id=?",
                 (data['nome'], data['modo'], data.get('requer_observacao', 0),
                  data.get('requer_faixas', 0), data.get('ativo', 1), sid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/servicos/<int:sid>/opcoes', methods=['POST'])
def criar_opcao(sid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO servico_opcoes (servico_id, nome) VALUES (?, ?)", (sid, data['nome']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/servicos/opcoes/<int:oid>', methods=['DELETE'])
def deletar_opcao(oid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()
    conn.execute("UPDATE servico_opcoes SET ativo=0 WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/servicos/<int:sid>/fornecedores')
def fornecedores_do_servico(sid):
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute('''SELECT f.id, f.nome, f.endereco, fs.custo, fs.id as fs_id
                           FROM fornecedores f
                           JOIN fornecedor_servicos fs ON fs.fornecedor_id = f.id
                           WHERE fs.servico_id=? AND f.ativo=1 ORDER BY f.nome''', (sid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# FORNECEDORES
@app.route('/api/fornecedores', methods=['GET'])
def listar_fornecedores():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT * FROM fornecedores WHERE ativo=1 ORDER BY nome").fetchall()
    result = []
    for r in rows:
        f = dict(r)
        servs = conn.execute('''SELECT fs.id as fs_id, fs.custo, s.id as servico_id, s.nome as servico_nome
                                FROM fornecedor_servicos fs
                                JOIN servicos s ON fs.servico_id = s.id
                                WHERE fs.fornecedor_id=? AND s.ativo=1 ORDER BY s.nome''',
                             (r['id'],)).fetchall()
        f['servicos'] = [dict(s) for s in servs]
        result.append(f)
    conn.close()
    return jsonify(result)

@app.route('/api/fornecedores', methods=['POST'])
def criar_fornecedor():
    if not require_auth(['admin', 'agente']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO fornecedores (nome, endereco, contato) VALUES (?, ?, ?)",
                 (data['nome'], data.get('endereco', ''), data.get('contato', '')))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/fornecedores/<int:fid>', methods=['PUT'])
def editar_fornecedor(fid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE fornecedores SET nome=?, endereco=?, contato=?, ativo=? WHERE id=?",
                 (data['nome'], data.get('endereco', ''), data.get('contato', ''), data.get('ativo', 1), fid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/fornecedores/<int:fid>/servicos', methods=['POST'])
def vincular_servico(fid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    try:
        conn = get_db()
        conn.execute("INSERT INTO fornecedor_servicos (fornecedor_id, servico_id, custo) VALUES (?, ?, ?)",
                     (fid, data['servico_id'], data.get('custo', 0)))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'msg': 'Serviço já vinculado'}), 400

@app.route('/api/fornecedores/servicos/<int:fsid>', methods=['PUT'])
def editar_vinculo(fsid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE fornecedor_servicos SET custo=? WHERE id=?", (data['custo'], fsid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/fornecedores/servicos/<int:fsid>', methods=['DELETE'])
def desvincular_servico(fsid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()
    conn.execute("DELETE FROM fornecedor_servicos WHERE id=?", (fsid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# CONVÊNIOS
@app.route('/api/convenios', methods=['GET'])
def listar_convenios():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT * FROM convenios WHERE ativo=1 ORDER BY nome").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/convenios', methods=['POST'])
def criar_convenio():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    try:
        conn = get_db()
        conn.execute("INSERT INTO convenios (nome) VALUES (?)", (data['nome'],))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'msg': 'Convênio já existe'}), 400

@app.route('/api/convenios/<int:cid>', methods=['PUT'])
def editar_convenio(cid):
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE convenios SET nome=?, ativo=? WHERE id=?",
                 (data['nome'], data.get('ativo', 1), cid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ORDENS DE SERVIÇO
@app.route('/api/os', methods=['GET'])
def listar_os():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    perfil_user = session.get('user_perfil', '')
    where_clause = "WHERE os.status != 'concluida'" if perfil_user == 'agente' else ""
    rows = conn.execute(f'''SELECT os.*, u.nome as agente_nome,
                           u2.nome as agente_captacao_nome,
                           u3.nome as agente_atendimento_nome
                           FROM ordens_servico os
                           JOIN usuarios u ON os.agente_id = u.id
                           LEFT JOIN usuarios u2 ON os.agente_captacao_id = u2.id
                           LEFT JOIN usuarios u3 ON os.agente_atendimento_id = u3.id
                           {where_clause}
                           ORDER BY os.criado_em DESC''').fetchall()
    result = []
    for r in rows:
        os_dict = dict(r)
        itens = conn.execute('''SELECT i.*, u.nome as motorista_nome
                                FROM itens_os i LEFT JOIN usuarios u ON i.motorista_id = u.id
                                WHERE i.os_id=?''', (r['id'],)).fetchall()
        os_dict['itens'] = [dict(i) for i in itens]
        # Inclui formas de pagamento
        pagamentos = conn.execute('SELECT * FROM pagamentos_os WHERE os_id=? ORDER BY id',
                                  (r['id'],)).fetchall()
        os_dict['pagamentos'] = [dict(p) for p in pagamentos]
        result.append(os_dict)
    conn.close()
    return jsonify(result)

def salvar_itens(conn, os_id, itens):
    for item in itens:
        conn.execute('''INSERT INTO itens_os
            (os_id, servico_id, servico_nome, servico_modo, fornecedor_id, fornecedor_nome,
             fornecedor_endereco, custo, quantidade, opcoes_selecionadas, faixas, observacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (os_id, item.get('servico_id'), item.get('servico_nome', ''), item.get('servico_modo', ''),
             item.get('fornecedor_id'), item.get('fornecedor_nome', ''), item.get('fornecedor_endereco', ''),
             item.get('custo', 0), item.get('quantidade', 1),
             json.dumps(item.get('opcoes_selecionadas', []), ensure_ascii=False),
             json.dumps(item.get('faixas', []), ensure_ascii=False),
             item.get('observacao', '')))

def salvar_pagamentos(conn, os_id, pagamentos):
    """Insere as formas de pagamento de uma OS."""
    for p in pagamentos:
        conn.execute('''INSERT INTO pagamentos_os (os_id, tipo, valor, parcelas)
                        VALUES (?, ?, ?, ?)''',
                     (os_id, p.get('tipo', 'pix'),
                      float(p.get('valor', 0)),
                      int(p.get('parcelas', 1))))

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
    # Resolve nome do convênio a partir do ID
    convenio_id = data.get('convenio_id') or None
    convenio_nome = ''
    if convenio_id:
        row_conv = conn.execute("SELECT nome FROM convenios WHERE id=?", (convenio_id,)).fetchone()
        if row_conv:
            convenio_nome = row_conv['nome']

    c.execute('''INSERT INTO ordens_servico
                 (id_webluto, nome_falecido, horario_sepultamento, agente_id, unidade_nome,
                  observacoes, convenio, convenio_id, agente_captacao_id, agente_atendimento_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (data['id_webluto'], data['nome_falecido'], data.get('horario_sepultamento', ''),
               session['user_id'], session.get('user_unidade', ''), data.get('observacoes', ''),
               convenio_nome, convenio_id,
               data.get('agente_captacao_id') or None,
               data.get('agente_atendimento_id') or None))
    os_id = c.lastrowid
    salvar_itens(conn, os_id, data.get('itens', []))
    salvar_pagamentos(conn, os_id, data.get('pagamentos', []))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'],
                  f"Criou OS {data['id_webluto']} — {data['nome_falecido']}")
    return jsonify({'ok': True, 'os_id': os_id})

@app.route('/api/os/<int:os_id>', methods=['PUT'])
def editar_os(os_id):
    if not require_auth(['agente', 'admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    os_ant = dict(conn.execute("SELECT * FROM ordens_servico WHERE id=?", (os_id,)).fetchone())
    if session.get('user_perfil') == 'agente' and os_ant.get('status') != 'aberta':
        conn.close()
        return jsonify({'ok': False, 'msg': 'Agente só pode editar OS com status aberta'}), 403
    if 'id_webluto' in data:
        existe = conn.execute("SELECT id FROM ordens_servico WHERE id_webluto=? AND id!=?",
                              (data['id_webluto'], os_id)).fetchone()
        if existe:
            conn.close()
            return jsonify({'ok': False, 'msg': f"ID '{data['id_webluto']}' já está em uso"}), 400
    # Resolve nome do convênio a partir do ID
    convenio_id = data.get('convenio_id') or None
    convenio_nome = ''
    if convenio_id:
        row_conv = conn.execute("SELECT nome FROM convenios WHERE id=?", (convenio_id,)).fetchone()
        if row_conv:
            convenio_nome = row_conv['nome']

    conn.execute('''UPDATE ordens_servico
                    SET id_webluto=?, nome_falecido=?, horario_sepultamento=?, observacoes=?,
                        convenio=?, convenio_id=?, agente_captacao_id=?, agente_atendimento_id=?
                    WHERE id=?''',
                 (data['id_webluto'], data['nome_falecido'],
                  data.get('horario_sepultamento', ''), data.get('observacoes', ''),
                  convenio_nome, convenio_id,
                  data.get('agente_captacao_id') or None,
                  data.get('agente_atendimento_id') or None,
                  os_id))
    conn.execute("DELETE FROM itens_os WHERE os_id=?", (os_id,))
    salvar_itens(conn, os_id, data.get('itens', []))
    conn.execute("DELETE FROM pagamentos_os WHERE os_id=?", (os_id,))
    salvar_pagamentos(conn, os_id, data.get('pagamentos', []))
    conn.commit()
    registrar_log(session['user_id'], session['user_nome'], f"Editou OS ID {os_id}", dados_ant=os_ant)
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/os/<int:os_id>/fechar', methods=['POST'])
def fechar_os(os_id):
    if not require_auth(['gerente', 'admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()

    # Pagamentos → Valor Total
    pagamentos = conn.execute("SELECT * FROM pagamentos_os WHERE os_id=?", (os_id,)).fetchall()
    valor_total = sum(float(p['valor'] or 0) for p in pagamentos)

    # Itens → Custo de Serviços
    itens = conn.execute("SELECT * FROM itens_os WHERE os_id=?", (os_id,)).fetchall()
    custo_servicos = sum(
        float(i['custo'] or 0) * (int(i['quantidade'] or 1) if i['servico_modo'] == 'quantitativo' else 1)
        for i in itens
    )

    # Configurações de juros
    config = {r['chave']: r['valor'] for r in conn.execute("SELECT chave, valor FROM config_sistema").fetchall()}
    custo_juros = 0.0
    jd = float(config.get('juros_debito', 0) or 0) / 100
    for p in pagamentos:
        v = float(p['valor'] or 0)
        if p['tipo'] == 'credito':
            parc = min(max(int(p['parcelas'] or 1), 1), 12)
            taxa = float(config.get(f'juros_credito_{parc}', 0) or 0) / 100
            custo_juros += v * taxa
        elif p['tipo'] == 'debito':
            custo_juros += v * jd

    custo_total       = custo_servicos + custo_juros
    comissao_total    = (valor_total - custo_total) * 0.04
    comissao_captacao    = comissao_total * 0.5
    comissao_atendimento = comissao_total * 0.5

    conn.execute('''UPDATE ordens_servico
                    SET status='concluida', fechado_em=?,
                        valor_total=?, custo_total=?,
                        comissao_total=?, comissao_captacao=?, comissao_atendimento=?
                    WHERE id=?''',
                 (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                  valor_total, custo_total,
                  comissao_total, comissao_captacao, comissao_atendimento,
                  os_id))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'], f"Fechou OS ID {os_id}")
    return jsonify({'ok': True})

@app.route('/api/os/<int:os_id>/concluir', methods=['POST'])
def concluir_os(os_id):
    """Agente marca OS como concluída (estado intermediário antes da finalização)."""
    if not require_auth(['agente', 'admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()
    conn.execute("UPDATE ordens_servico SET status='concluido' WHERE id=? AND status='aberta'", (os_id,))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'], f"Marcou OS ID {os_id} como concluído")
    return jsonify({'ok': True})

@app.route('/api/item/<int:item_id>/atribuir', methods=['POST'])
def atribuir_motorista(item_id):
    if not require_auth(['motorista', 'admin', 'agente']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE itens_os SET motorista_id=? WHERE id=?", (data.get('motorista_id'), item_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# EXPORTACAO
@app.route('/api/exportar', methods=['GET'])
def exportar():
    if not require_auth(['admin', 'gerente']):
        return jsonify({'ok': False}), 403
    data_ini      = request.args.get('data_ini', '')
    data_fim      = request.args.get('data_fim', '')
    fornecedor_id = request.args.get('fornecedor', '')
    servico_id    = request.args.get('servico', '')
    convenio_id   = request.args.get('convenio', '')
    agente_id     = request.args.get('agente', '')
    conn = get_db()
    sql = (
        "SELECT os.id_webluto, os.nome_falecido, os.horario_sepultamento, "
        "os.criado_em, os.status, os.unidade_nome, "
        "u.nome AS agente, "
        "os.convenio, "
        "u2.nome AS agente_captacao_nome, "
        "u3.nome AS agente_atendimento_nome, "
        "os.valor_total, os.custo_total, "
        "os.comissao_total, os.comissao_captacao, os.comissao_atendimento, "
        "i.servico_nome, i.fornecedor_nome, i.fornecedor_endereco, "
        "i.custo AS item_custo, i.quantidade, m.nome AS motorista "
        "FROM ordens_servico os "
        "JOIN usuarios u ON os.agente_id = u.id "
        "LEFT JOIN usuarios u2 ON os.agente_captacao_id = u2.id "
        "LEFT JOIN usuarios u3 ON os.agente_atendimento_id = u3.id "
        "JOIN itens_os i ON i.os_id = os.id "
        "LEFT JOIN usuarios m ON i.motorista_id = m.id "
        "WHERE 1=1"
    )
    params = []
    if data_ini:
        sql += " AND DATE(os.criado_em) >= ?"
        params.append(data_ini)
    if data_fim:
        sql += " AND DATE(os.criado_em) <= ?"
        params.append(data_fim)
    if fornecedor_id:
        sql += " AND i.fornecedor_id = ?"
        params.append(fornecedor_id)
    if servico_id:
        sql += " AND i.servico_id = ?"
        params.append(servico_id)
    if convenio_id:
        sql += " AND os.convenio_id = ?"
        params.append(convenio_id)
    if agente_id:
        sql += " AND (os.agente_captacao_id = ? OR os.agente_atendimento_id = ?)"
        params.extend([agente_id, agente_id])
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    def fmt_val(v):
        return "{:.2f}".format(float(v)).replace('.', ',') if v is not None else '0,00'

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'ID Web Luto', 'Falecido', 'Horario Sepultamento', 'Data OS', 'Status', 'Unidade',
        'Agente', 'Convenio', 'Agente Captacao', 'Agente Atendimento',
        'Valor Total OS (R$)', 'Custo Total OS (R$)',
        'Comissao Total (R$)', 'Comissao Captacao (R$)', 'Comissao Atendimento (R$)',
        'Servico', 'Fornecedor', 'Endereco', 'Custo Item (R$)', 'Quantidade', 'Motorista'
    ])
    for r in rows:
        writer.writerow([
            r['id_webluto'], r['nome_falecido'], r['horario_sepultamento'] or '',
            r['criado_em'][:10], r['status'], r['unidade_nome'] or '',
            r['agente'], r['convenio'] or '',
            r['agente_captacao_nome'] or '', r['agente_atendimento_nome'] or '',
            fmt_val(r['valor_total']), fmt_val(r['custo_total']),
            fmt_val(r['comissao_total']), fmt_val(r['comissao_captacao']), fmt_val(r['comissao_atendimento']),
            r['servico_nome'], r['fornecedor_nome'], r['fornecedor_endereco'],
            fmt_val(r['item_custo']), r['quantidade'], r['motorista'] or ''
        ])
    bom = u'\ufeff'
    resp = make_response(bom + output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=relatorio_os.csv'
    return resp

# LOGS
@app.route('/api/logs')
def listar_logs():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    conn = get_db()
    rows = conn.execute("SELECT * FROM logs ORDER BY data_hora DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# CONFIGURACOES DO SISTEMA
@app.route('/api/config', methods=['GET'])
def get_config():
    if not require_auth():
        return jsonify({'ok': False}), 401
    conn = get_db()
    rows = conn.execute("SELECT chave, valor FROM config_sistema").fetchall()
    conn.close()
    return jsonify({r['chave']: r['valor'] for r in rows})

@app.route('/api/config', methods=['PUT'])
def set_config():
    if not require_auth(['admin']):
        return jsonify({'ok': False}), 403
    data = request.json
    conn = get_db()
    for chave, valor in data.items():
        conn.execute("INSERT OR REPLACE INTO config_sistema (chave, valor) VALUES (?, ?)",
                     (chave, str(valor)))
    conn.commit()
    conn.close()
    registrar_log(session['user_id'], session['user_nome'], "Atualizou configuracoes do sistema")
    return jsonify({'ok': True})

@app.route('/')
@app.route('/<path:path>')
def index(path=''):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(base_dir, 'index.html')

if __name__ == '__main__':
    init_db()
    print("Banco inicializado")
    print("Admin: login=admin / senha=admin123")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
