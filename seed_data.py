# -*- coding: utf-8 -*-
import sqlite3, os

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'funeraria.db'))
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

servicos = [
    ('Tanatopraxia',      'unico'),
    ('Ornamentação',      'unico'),
    ('Embalsamamento',    'unico'),
    ('Coroa',             'quantitativo'),
    ('Arranjo de Flores', 'quantitativo'),
]
for nome, modo in servicos:
    c.execute('INSERT OR IGNORE INTO servicos (nome, modo, requer_observacao, requer_faixas) VALUES (?,?,0,0)', (nome, modo))
    c.execute('UPDATE servicos SET modo=? WHERE nome=?', (modo, nome))
conn.commit()
print('OK Servicos')

def sid(nome):
    row = c.execute('SELECT id FROM servicos WHERE nome=?', (nome,)).fetchone()
    return row['id'] if row else None

fornecedores = [
    ('VMC', [('Tanatopraxia', 200.0), ('Ornamentação', 200.0)]),
    ('Ailton', [('Coroa', 125.0)]),
    ('Egnalos', [('Tanatopraxia', 200.0), ('Ornamentação', 202.0), ('Coroa', 120.0), ('Arranjo de Flores', 50.0), ('Embalsamamento', 350.0)]),
    ('Infinita', [('Tanatopraxia', 200.0), ('Ornamentação', 160.0)]),
    ('Jacson', [('Coroa', 110.0)]),
]

for nome_forn, links in fornecedores:
    c.execute('INSERT OR IGNORE INTO fornecedores (nome) VALUES (?)', (nome_forn,))
    conn.commit()
    forn_id = c.execute('SELECT id FROM fornecedores WHERE nome=?', (nome_forn,)).fetchone()['id']
    for sn, custo in links:
        s_id = sid(sn)
        if not s_id:
            print(f'  AVISO: servico nao encontrado — {sn}')
            continue
        c.execute('INSERT OR IGNORE INTO fornecedor_servicos (fornecedor_id, servico_id, custo) VALUES (?,?,?)', (forn_id, s_id, custo))
        c.execute('UPDATE fornecedor_servicos SET custo=? WHERE fornecedor_id=? AND servico_id=?', (custo, forn_id, s_id))
    conn.commit()
    print(f'  OK {nome_forn}')

conn.close()
print('Tudo pronto!')
