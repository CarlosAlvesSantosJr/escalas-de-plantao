"""Os mesmos testes do webapp, rodando no modo banco (Postgres), como na Vercel.

Só rodam com um Postgres de teste disponível:
  docker run -d --rm --name escala-pg-teste -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=escala \\
         -p 127.0.0.1:55432:5432 postgres:17-alpine
  ESCALA_TESTE_BANCO=postgresql://postgres:teste@127.0.0.1:55432/escala pytest

Cada teste usa um esquema próprio do Postgres, apagado no fim.
"""
import hashlib
import json
import os
import threading
from datetime import timedelta

import pytest

URL = os.environ.get("ESCALA_TESTE_BANCO")
if not URL:
    pytest.skip("defina ESCALA_TESTE_BANCO para rodar os testes com Postgres", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")

import tests.test_webapp as base  # noqa: E402
from escala.banco import AuditoriaPostgres, Banco, CadastroPostgres, RepositorioPostgres  # noqa: E402
from escala.relogio import agora  # noqa: E402
from escala.repositorio import estado_de_dados  # noqa: E402
from escala.usuarios import Usuario  # noqa: E402
from webapp import create_app  # noqa: E402

# Reaproveita todos os testes do webapp (o `_cliente` deles é trocado abaixo).
from tests.test_webapp import *  # noqa: E402,F401,F403

# Estes leem ou gravam os arquivos diretamente; não se aplicam ao modo banco.
del test_le_arquivo_com_uma_unica_escala  # noqa: F821
del test_auditoria_guarda_so_os_ultimos_30_dias  # noqa: F821


def _url(esquema: str) -> str:
    sep = "&" if "?" in URL else "?"
    return f"{URL}{sep}options=-csearch_path%3D{esquema}"


@pytest.fixture(autouse=True)
def modo_banco(monkeypatch):
    """Troca o `_cliente` dos testes por um que cria o app ligado ao Postgres."""
    esquemas, bancos = set(), []

    def cliente_pg(caminho_dados, nome="Marcia", matricula="11111", hoje=base.HOJE):
        pasta = caminho_dados.parent
        esquema = "t_" + hashlib.sha1(str(caminho_dados).encode()).hexdigest()[:12]
        url = _url(esquema)
        if esquema not in esquemas:
            with psycopg.connect(URL, autocommit=True) as c:
                c.execute(f"DROP SCHEMA IF EXISTS {esquema} CASCADE; CREATE SCHEMA {esquema}")
            esquemas.add(esquema)
            banco = Banco(url)
            bancos.append(banco)
            base._usuarios(pasta)
            bruto = json.loads((pasta / "usuarios.json").read_text(encoding="utf-8"))
            CadastroPostgres(banco).substituir_todos([Usuario.de_dict(u) for u in bruto["usuarios"]])
            if caminho_dados.exists():  # o teste preparou um arquivo: vai para o banco (migração)
                repo = RepositorioPostgres(banco)
                with repo.lock:
                    repo.salvar(estado_de_dados(json.loads(caminho_dados.read_text(encoding="utf-8"))))
        app = create_app(banco_url=url)
        app.testing = True
        app.config["HOJE"] = lambda: hoje
        c = app.test_client()
        c.environ_base["HTTP_X_REQUESTED_WITH"] = "fetch"
        if nome:
            r = c.post("/api/login", json={"nome": nome, "matricula": matricula})
            assert r.status_code == 200, r.get_json()
        return c

    monkeypatch.setattr(base, "_cliente", cliente_pg)
    yield
    for b in bancos:
        b._descartar()
    # Conexões de cada app criado no teste: fecha antes de apagar o esquema.
    with psycopg.connect(URL, autocommit=True) as c:
        for esquema in esquemas:
            c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                      "WHERE pid <> pg_backend_pid() AND datname = current_database() "
                      "AND query NOT ILIKE '%pg_stat_activity%'")
            c.execute(f"DROP SCHEMA IF EXISTS {esquema} CASCADE")


@pytest.fixture
def client(tmp_path):
    return base._cliente(tmp_path / "dados.json")


@pytest.fixture
def banco(tmp_path):
    base._cliente(tmp_path / "dados.json", nome=None)  # cria o esquema
    esquema = "t_" + hashlib.sha1(str(tmp_path / "dados.json").encode()).hexdigest()[:12]
    b = Banco(_url(esquema))
    yield b
    b._descartar()


# --- específicos do modo banco ------------------------------------------------

def test_auditoria_no_banco_guarda_so_os_ultimos_30_dias(banco):
    aud = AuditoriaPostgres(banco)
    velho = agora() - timedelta(days=31)
    aud.importar([{"quando": velho.isoformat(), "tipo": "LOGIN", "usuario": "Ana", "descricao": "antigo"},
                  {"quando": agora().isoformat(), "tipo": "LOGIN", "usuario": "Ana", "descricao": "novo"}])
    assert aud.expurgar() == 1
    assert [e["descricao"] for e in aud.listar(usuario="ANA")] == ["novo"]


def test_versao_muda_a_cada_gravacao(client, banco):
    repo = RepositorioPostgres(banco)
    antes = repo.versao()
    assert client.put("/api/periodo", json={"inicio": "2026-11-01", "fim": "2026-11-07"}).status_code == 200
    assert repo.versao() != antes
    assert client.get("/api/versao").get_json()["versao"] == repo.versao()


def test_gravacoes_simultaneas_em_copias_diferentes_nao_se_perdem(tmp_path):
    """Duas 'cópias' do app (como duas instâncias da Vercel) gravando ao mesmo tempo."""
    adm1 = base._cliente(tmp_path / "dados.json")
    adm2 = base._cliente(tmp_path / "dados.json")
    adm1.put("/api/periodo", json={"inicio": "2026-11-01", "fim": "2026-11-07"})

    def cadastrar(cliente, prefixo):
        for i in range(8):
            r = cliente.post("/api/funcionarios", json={"nome": f"{prefixo} {'ABCDEFGH'[i]}", "cargo": "MOTORISTA"})
            assert r.status_code == 201, r.get_json()

    t1 = threading.Thread(target=cadastrar, args=(adm1, "ANA"))
    t2 = threading.Thread(target=cadastrar, args=(adm2, "BIA"))
    t1.start(); t2.start(); t1.join(); t2.join()
    nomes = [f["nome"] for f in adm1.get("/api/estado").get_json()["funcionarios"]]
    assert len(nomes) == 16  # sem a trava, uma gravação apagaria a outra


def test_chave_de_sessao_e_a_mesma_em_todas_as_copias(tmp_path):
    c1 = base._cliente(tmp_path / "dados.json")
    c2 = base._cliente(tmp_path / "dados.json", nome=None)
    cookie = c1.get_cookie("escala_sessao")
    c2.set_cookie("escala_sessao", cookie.value)
    assert c2.get("/api/eu").status_code == 200  # login feito numa cópia vale na outra


def test_bloqueio_de_login_vale_para_todas_as_copias(tmp_path):
    for _ in range(5):
        c = base._cliente(tmp_path / "dados.json", nome=None)  # cada tentativa numa cópia nova
        assert c.post("/api/login", json={"nome": "Bruna", "matricula": "0"}).status_code == 401
    c = base._cliente(tmp_path / "dados.json", nome=None)
    assert c.post("/api/login", json={"nome": "Bruna", "matricula": "22222"}).status_code == 429
