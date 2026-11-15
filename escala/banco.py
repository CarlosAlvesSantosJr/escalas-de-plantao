"""Persistência em Postgres (Neon), para rodar sem disco próprio (ex.: Vercel).

Na Vercel cada acesso pode cair numa cópia diferente do app, e o disco é
descartável. Então tudo o que no modo arquivo fica em disco ou na memória vai
para o banco:

  escala_estado     a escala inteira (equipe, período, rascunho, escalas), um JSON só
  escala_usuarios   usuários (só o hash da matrícula)
  escala_auditoria  eventos (apagados depois de `dias_retencao` dias)
  escala_falhas     tentativas de login erradas (bloqueio vale para todas as cópias)
  escala_config     chave das sessões, gerada no primeiro acesso

As classes têm a mesma interface das versões em arquivo (RepositorioJSON,
CadastroUsuarios, Auditoria, LimiteTentativas), então o webapp não muda.

Concorrência: cada operação de escrita roda numa transação que pega uma trava
do Postgres (pg_advisory_xact_lock). Duas pessoas trocando plantões ao mesmo
tempo, mesmo em cópias diferentes do app, são atendidas uma de cada vez.
"""
from __future__ import annotations

import secrets
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from datetime import timedelta

import psycopg
from psycopg.types.json import Jsonb

from .relogio import FUSO, agora
from .repositorio import EstadoApp, dados_de_estado, estado_de_dados
from .usuarios import CadastroUsuarios, Papel, Usuario, chave_nome

ESQUEMA = """
CREATE TABLE IF NOT EXISTS escala_estado (
    id            smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    dados         jsonb NOT NULL,
    versao        bigint NOT NULL DEFAULT 1,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS escala_usuarios (
    chave          text PRIMARY KEY,
    nome           text NOT NULL,
    papel          text NOT NULL,
    matricula_hash text NOT NULL,
    ativo          boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS escala_auditoria (
    id            bigserial PRIMARY KEY,
    quando        timestamptz NOT NULL,
    tipo          text NOT NULL,
    usuario       text,
    usuario_chave text,
    descricao     text NOT NULL,
    ip            text,
    detalhes      jsonb
);
CREATE INDEX IF NOT EXISTS escala_auditoria_quando ON escala_auditoria (quando DESC, id DESC);
CREATE TABLE IF NOT EXISTS escala_falhas (
    chave  text NOT NULL,
    quando timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS escala_falhas_chave ON escala_falhas (chave, quando);
CREATE TABLE IF NOT EXISTS escala_config (
    chave text PRIMARY KEY,
    valor text NOT NULL
);
"""

_TRAVA_ESTADO = 7_192_192  # número da trava do Postgres que protege a escala


class Banco:
    """Conexões com o Postgres: uma por thread, reaproveitada entre acessos.

    O pooler da Neon fecha conexões paradas; por isso a conexão é refeita se
    ficou muito tempo sem uso ou se caiu, e as consultas simples tentam de novo
    uma vez.
    """

    OCIOSA_S = 120

    def __init__(self, url: str, criar_tabelas: bool = True):
        self.url = url
        self._local = threading.local()
        if criar_tabelas:
            with self.conexao() as c:
                c.execute(ESQUEMA)

    def _abrir(self) -> psycopg.Connection:
        # prepare_threshold=None: compatível com o pooler (PgBouncer) da Neon.
        return psycopg.connect(self.url, autocommit=True, prepare_threshold=None, connect_timeout=10)

    def _descartar(self) -> None:
        c = getattr(self._local, "conn", None)
        self._local.conn = None
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    @contextmanager
    def conexao(self):
        c = getattr(self._local, "conn", None)
        parada = time.monotonic() - getattr(self._local, "usada", 0) > self.OCIOSA_S
        if c is None or c.closed or c.broken or parada:
            self._descartar()
            c = self._local.conn = self._abrir()
        self._local.usada = time.monotonic()
        try:
            yield c
        except psycopg.OperationalError:
            self._descartar()
            raise

    def consultar(self, sql: str, params=(), um: bool = False):
        """SELECT/INSERT simples, com uma nova tentativa se a conexão tiver caído."""
        for tentativa in (1, 2):
            try:
                with self.conexao() as c:
                    cur = c.execute(sql, params)
                    if cur.description is None:
                        return None
                    return cur.fetchone() if um else cur.fetchall()
            except psycopg.OperationalError:
                if tentativa == 2:
                    raise

    def chave_sessao(self) -> str:
        """Chave secreta das sessões, criada uma vez e guardada no banco."""
        self.consultar("INSERT INTO escala_config (chave, valor) VALUES ('chave_sessao', %s) "
                       "ON CONFLICT (chave) DO NOTHING", (secrets.token_hex(32),))
        return self.consultar("SELECT valor FROM escala_config WHERE chave = 'chave_sessao'", um=True)[0]


# --- escala -------------------------------------------------------------

class _TravaEstado:
    """`with repo.lock:` abre uma transação e trava a escala até o fim do bloco."""

    def __init__(self, banco: Banco):
        self.banco = banco
        self._local = threading.local()

    @property
    def conexao_atual(self) -> psycopg.Connection | None:
        return getattr(self._local, "conn", None)

    def __enter__(self):
        if self.conexao_atual is not None:  # reentrante, como o RLock do modo arquivo
            self._local.nivel += 1
            return self
        pilha = ExitStack()
        try:
            conn = pilha.enter_context(self.banco.conexao())
            pilha.enter_context(conn.transaction())  # commit no fim; rollback se der erro
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_TRAVA_ESTADO,))
        except BaseException:
            pilha.__exit__(*sys.exc_info())
            raise
        self._local.conn, self._local.nivel, self._local.pilha = conn, 1, pilha
        return self

    def __exit__(self, tipo, valor, tb):
        self._local.nivel -= 1
        if self._local.nivel:
            return False
        pilha, self._local.conn, self._local.pilha = self._local.pilha, None, None
        pilha.__exit__(tipo, valor, tb)
        return False


class RepositorioPostgres:
    def __init__(self, banco: Banco):
        self.banco = banco
        self.lock = _TravaEstado(banco)

    def _executar(self, sql: str, params=(), um=False):
        conn = self.lock.conexao_atual
        if conn is None:
            return self.banco.consultar(sql, params, um=um)
        cur = conn.execute(sql, params)
        return cur.fetchone() if um else None

    def carregar(self) -> EstadoApp:
        linha = self._executar("SELECT dados FROM escala_estado WHERE id = 1", um=True)
        return estado_de_dados(linha[0]) if linha else EstadoApp()

    def versao(self) -> str:
        linha = self.banco.consultar("SELECT versao FROM escala_estado WHERE id = 1", um=True)
        return str(linha[0]) if linha else "0"

    def salvar(self, estado: EstadoApp) -> None:
        self.salvar_dados(dados_de_estado(estado))

    def salvar_dados(self, dados: dict) -> None:
        self._executar(
            "INSERT INTO escala_estado (id, dados) VALUES (1, %s) "
            "ON CONFLICT (id) DO UPDATE SET dados = EXCLUDED.dados, "
            "versao = escala_estado.versao + 1, atualizado_em = now()", (Jsonb(dados),))

    def dados_brutos(self) -> dict | None:
        linha = self._executar("SELECT dados FROM escala_estado WHERE id = 1", um=True)
        return linha[0] if linha else None


# --- usuários -----------------------------------------------------------

class CadastroPostgres(CadastroUsuarios):
    """Usuários no banco. Relidos a cada `ttl_s` segundos (uma desativação vale em até 30 s)."""

    def __init__(self, banco: Banco, ttl_s: float = 30):
        super().__init__(None)
        self.banco, self.ttl = banco, ttl_s
        self._validade = 0.0

    def _recarregar(self) -> None:
        if time.monotonic() < self._validade:
            return
        linhas = self.banco.consultar("SELECT nome, papel, matricula_hash, ativo FROM escala_usuarios")
        self._usuarios = {chave_nome(n): Usuario(n, Papel(p), h, a) for n, p, h, a in linhas}
        self._validade = time.monotonic() + self.ttl

    def substituir_todos(self, usuarios: list[Usuario]) -> None:
        with self.banco.conexao() as c, c.transaction():
            c.execute("DELETE FROM escala_usuarios")
            for u in usuarios:
                c.execute("INSERT INTO escala_usuarios (chave, nome, papel, matricula_hash, ativo) "
                          "VALUES (%s, %s, %s, %s, %s)",
                          (chave_nome(u.nome), u.nome, u.papel.value, u.hash_matricula, u.ativo))
        self._validade = 0.0


# --- tentativas de login --------------------------------------------------

class LimitePostgres:
    """Mesmo bloqueio do LimiteTentativas, mas contado no banco (vale para todas as cópias)."""

    def __init__(self, banco: Banco, maximo: int = 5, janela_s: int = 15 * 60):
        self.banco, self.maximo, self.janela = banco, maximo, janela_s

    def bloqueado_por(self, chaves: list[str]) -> int:
        linhas = self.banco.consultar(
            "SELECT count(*), EXTRACT(EPOCH FROM min(quando) + make_interval(secs => %s) - now()) "
            "FROM escala_falhas WHERE chave = ANY(%s) AND quando > now() - make_interval(secs => %s) "
            "GROUP BY chave", (self.janela, chaves, self.janela))
        restantes = [int(seg) + 1 for n, seg in linhas if n >= self.maximo]
        return max(restantes, default=0)

    def falhou(self, chaves: list[str]) -> None:
        with self.banco.conexao() as c:
            c.execute("DELETE FROM escala_falhas WHERE quando < now() - interval '1 day'")
            for ch in chaves:
                c.execute("INSERT INTO escala_falhas (chave) VALUES (%s)", (ch,))

    def limpar(self, chaves: list[str]) -> None:
        self.banco.consultar("DELETE FROM escala_falhas WHERE chave = ANY(%s)", (chaves,))


# --- auditoria ------------------------------------------------------------

def _evento(quando, tipo, usuario, descricao, ip, detalhes) -> dict:
    quando = quando.astimezone(FUSO) if FUSO else quando.astimezone()
    ev = {"quando": quando.isoformat(timespec="seconds"), "tipo": tipo, "usuario": usuario,
          "descricao": descricao, "ip": ip}
    if detalhes:
        ev["detalhes"] = detalhes
    return ev


_COLUNAS = "quando, tipo, usuario, descricao, ip, detalhes"


class AuditoriaPostgres:
    DIAS_RETENCAO = 30

    def __init__(self, banco: Banco, dias_retencao: int = DIAS_RETENCAO):
        self.banco = banco
        self.dias_retencao = max(1, int(dias_retencao))
        self._proxima_limpeza = 0.0

    def expurgar(self, agora_=None) -> int:
        self._proxima_limpeza = time.monotonic() + 3600
        corte = (agora_ or agora()) - timedelta(days=self.dias_retencao)
        with self.banco.conexao() as c:
            return c.execute("DELETE FROM escala_auditoria WHERE quando < %s", (corte,)).rowcount

    def registrar(self, tipo: str, usuario: str | None, descricao: str, ip: str | None = None,
                  **detalhes) -> dict:
        if time.monotonic() >= self._proxima_limpeza:  # no máximo uma limpeza por hora
            self.expurgar()
        quando = agora().replace(microsecond=0)
        self.banco.consultar(
            "INSERT INTO escala_auditoria (quando, tipo, usuario, usuario_chave, descricao, ip, detalhes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (quando, tipo, usuario, chave_nome(usuario) if usuario else None, descricao, ip,
             Jsonb(detalhes) if detalhes else None))
        return _evento(quando, tipo, usuario, descricao, ip, detalhes)

    def ultimo(self, tipos: set[str]) -> dict | None:
        linha = self.banco.consultar(
            f"SELECT {_COLUNAS} FROM escala_auditoria WHERE tipo = ANY(%s) "
            "ORDER BY quando DESC, id DESC LIMIT 1", (sorted(tipos),), um=True)
        return _evento(*linha) if linha else None

    def listar(self, usuario: str | None = None, tipo: str | None = None,
               limite: int = 500) -> list[dict]:
        """Eventos mais recentes primeiro."""
        filtros, params = [], []
        if usuario:
            filtros.append("usuario_chave = %s")
            params.append(chave_nome(usuario))
        if tipo:
            filtros.append("tipo = %s")
            params.append(tipo)
        onde = f"WHERE {' AND '.join(filtros)}" if filtros else ""
        linhas = self.banco.consultar(
            f"SELECT {_COLUNAS} FROM escala_auditoria {onde} ORDER BY quando DESC, id DESC LIMIT %s",
            (*params, limite))
        return [_evento(*l) for l in linhas]

    def importar(self, eventos: list[dict]) -> int:
        """Copia eventos de um auditoria.jsonl (migração do modo arquivo)."""
        from datetime import datetime
        with self.banco.conexao() as c, c.transaction():
            for ev in eventos:
                quando = datetime.fromisoformat(ev["quando"])
                if quando.tzinfo is None:
                    quando = quando.replace(tzinfo=FUSO) if FUSO else quando.astimezone()
                u = ev.get("usuario")
                c.execute(
                    "INSERT INTO escala_auditoria (quando, tipo, usuario, usuario_chave, descricao, ip, detalhes) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (quando, ev["tipo"], u, chave_nome(u) if u else None, ev.get("descricao", ""),
                     ev.get("ip"), Jsonb(ev["detalhes"]) if ev.get("detalhes") else None))
        return len(eventos)
