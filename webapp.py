"""Frontend web do Sistema de Escalas (Flask + SPA em static/).

Acesso com login (nome + matrícula):
- ADMIN: tudo (equipe, período, geração, revisão, PDF, importar/exportar, auditoria).
- USUARIO: vê a escala confirmada e troca profissionais nos plantões dela.
Toda alteração na escala confirmada vai para a auditoria.
"""
from __future__ import annotations

import csv
import io
import json
import os
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, g, jsonify, redirect, request, session

from escala.algoritmo import gerar_escala
from escala.avaliacao import ResultadoEscala, avaliar_escala, candidatos
from escala.dominio import Cargo, Escala, Funcionario, Periodo, Status, Turno, normalizar_nome
from escala.relatorio_pdf import gerar_pdf, ler_dados_embutidos
from escala.repositorio import (EstadoApp, RepositorioJSON, escala_de_dict, escala_para_dict,
                                periodo_para_dict)
from escala.usuarios import Auditoria, CadastroUsuarios, LimiteTentativas, Usuario

BASE_DIR = Path(__file__).resolve().parent
MAX_DIAS = 92
FORMATO_EXPORTACAO = "escala-samu"
EVENTOS_DA_ESCALA = {"PLANTAO_ALTERADO", "ESCALA_CONFIRMADA"}
DOW = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# Rotas acessíveis sem login.
ROTAS_PUBLICAS = {"/login", "/login.html", "/api/login", "/saude"}
# Rotas da API liberadas para o perfil USUARIO (o resto exige ADMIN).
API_USUARIO = {("GET", "/api/eu"), ("POST", "/api/logout"), ("GET", "/api/versao"),
               ("GET", "/api/estado"), ("GET", "/api/escala"), ("PATCH", "/api/escala"),
               ("GET", "/api/escala/candidatos")}


class ErroDeNegocio(Exception):
    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.status = status


# --- serialização -------------------------------------------------------

def funcionario_json(f: Funcionario, com_disponibilidade: bool = True) -> dict:
    d = {"id": f.id, "nome": f.nome, "cargo": f.cargo.value}
    d["disponibilidade"] = ({f"{dia.isoformat()}|{t.value}": s.value
                             for (dia, t), s in f.disponibilidade.items()}
                            if com_disponibilidade else {})
    return d


def estado_json(estado: EstadoApp, completo: bool = True) -> dict:
    return {
        "periodo": periodo_para_dict(estado.periodo) if estado.periodo else None,
        "funcionarios": [funcionario_json(f, completo) for f in estado.funcionarios],
    }


def resultado_json(r: ResultadoEscala) -> dict:
    cores = r.cores

    def membro(f):
        return {"id": f.id, "nome": f.nome, "cor": cores[f.id]} if f else None

    return {
        "periodo": periodo_para_dict(r.periodo),
        "cobertura": r.cobertura,
        "plantoes": [{"data": p.data.isoformat(), "turno": p.turno.value,
                      "enfermeiro": membro(p.enfermeiro), "motorista": membro(p.motorista),
                      "editados": sorted(c.value for c in p.editados)}
                     for p in r.plantoes],
        "vagas": [{"data": v.data.isoformat(), "turno": v.turno.value,
                   "cargo": v.cargo.value, "motivo": v.motivo} for v in r.vagas],
        "conflitos": [{"data": c.data.isoformat(), "turno": c.turno.value, "cargo": c.cargo.value,
                       "id": c.funcionario.id, "nome": c.funcionario.nome, "motivo": c.motivo}
                      for c in r.conflitos],
        "estatisticas": [{"id": s.funcionario.id, "nome": s.funcionario.nome,
                          "cargo": s.funcionario.cargo.value, "cor": cores[s.funcionario.id],
                          "total": s.total, "dias": s.dias, "noites": s.noites,
                          "fins_de_semana": s.fins_de_semana,
                          "preferenciais_atendidas": s.preferenciais_atendidas}
                         for s in r.estatisticas],
    }


def avaliar(estado: EstadoApp, e: Escala) -> ResultadoEscala:
    return avaliar_escala(estado.funcionarios, e.periodo, e.plantoes)


def escala_json(estado: EstadoApp, e: Escala | None, completo: bool = True) -> dict | None:
    """Escala avaliada. Sem `completo` (perfil USUARIO), sai sem os conflitos com as
    regras e sem a distribuição de plantões por profissional, que são do ADM."""
    if e is None:
        return None
    dados = resultado_json(avaliar(estado, e))
    dados["confirmada_em"] = e.confirmada_em.isoformat(timespec="minutes") if e.confirmada_em else None
    if not completo:
        dados["conflitos"] = []
        dados["estatisticas"] = [{k: s[k] for k in ("id", "nome", "cargo", "cor")} for s in dados["estatisticas"]]
    return dados


def exportacao(e: Escala) -> dict:
    """Arquivo autocontido da escala, que pode ser importado em outra instalação."""
    return {"formato": FORMATO_EXPORTACAO, "versao": 1, **escala_para_dict(e)}


def _parse_data(valor) -> date:
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise ErroDeNegocio(f"Data inválida: {valor!r}")


def _parse_enum(enum_cls, valor):
    try:
        return enum_cls(valor)
    except ValueError:
        raise ErroDeNegocio(f"Valor inválido: {valor!r}")


def _quando(dia: date, turno: Turno) -> str:
    return f"{DOW[dia.weekday()]} {dia:%d/%m} {turno.value}"


def _segredo(diretorio: Path) -> str:
    """Chave das sessões: variável de ambiente ou, na falta, um arquivo gerado no volume."""
    if chave := os.environ.get("ESCALA_SECRET_KEY"):
        return chave
    arquivo = diretorio / ".secret_key"
    if not arquivo.exists():
        diretorio.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(secrets.token_hex(32), encoding="utf-8")
    return arquivo.read_text(encoding="utf-8").strip()


def _ligado(var: str) -> bool:
    return os.environ.get(var, "").lower() in ("1", "true", "sim", "yes")


# --- aplicação ----------------------------------------------------------

def create_app(caminho_dados: str | Path | None = None, caminho_usuarios: str | Path | None = None,
               caminho_auditoria: str | Path | None = None) -> Flask:
    caminho_dados = Path(caminho_dados or os.environ.get("ESCALA_DADOS") or BASE_DIR / "dados_escala.json")
    pasta = caminho_dados.parent
    caminho_usuarios = caminho_usuarios or os.environ.get("ESCALA_USUARIOS") or pasta / "usuarios.json"
    caminho_auditoria = caminho_auditoria or os.environ.get("ESCALA_AUDITORIA") or pasta / "auditoria.jsonl"

    app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="")
    app.config.update(
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        SECRET_KEY=_segredo(pasta),
        SESSION_COOKIE_NAME="escala_sessao",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_ligado("ESCALA_COOKIE_SEGURO"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.environ.get("ESCALA_SESSAO_HORAS", "12"))),
    )
    if _ligado("ESCALA_ATRAS_DE_PROXY"):
        # Atrás do Ingress: usa o IP real do cliente e o esquema (https) originais.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    repo = RepositorioJSON(caminho_dados)
    cadastro = CadastroUsuarios(caminho_usuarios)
    auditoria = Auditoria(caminho_auditoria)
    tentativas = LimiteTentativas()
    def registrar(tipo: str, descricao: str, **detalhes) -> None:
        usuario = g.usuario.nome if getattr(g, "usuario", None) else detalhes.pop("usuario", None)
        auditoria.registrar(tipo, usuario, descricao, request.remote_addr, **detalhes)

    # --- autenticação e permissões ---------------------------------------

    @app.before_request
    def _autorizar():
        caminho = request.path
        g.usuario = None
        if caminho in ROTAS_PUBLICAS:
            return None
        protegida = caminho.startswith("/api/") or caminho in ("/", "/index.html")
        if not protegida:
            return None  # css, js, imagens
        usuario = cadastro.buscar(session.get("usuario", "")) if session.get("usuario") else None
        if usuario is None:
            session.clear()
            if caminho.startswith("/api/"):
                return jsonify(erro="Sua sessão expirou. Entre novamente."), 401
            return redirect("/login")
        g.usuario = usuario
        if not caminho.startswith("/api/"):
            return None
        # Proteção contra CSRF: o navegador não envia este cabeçalho em formulários de outro site.
        if request.method not in ("GET", "HEAD") and request.headers.get("X-Requested-With") != "fetch":
            return jsonify(erro="Requisição recusada."), 403
        if not usuario.admin and (request.method, caminho) not in API_USUARIO:
            return jsonify(erro="Seu perfil só permite alterar plantões da escala confirmada."), 403
        return None

    @app.after_request
    def _cabecalhos(resp: Response):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/") or request.path in ("/", "/index.html", "/login"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def usuario_json(u: Usuario) -> dict:
        return {"nome": u.nome, "papel": u.papel.value, "admin": u.admin}

    @app.get("/login")
    def pagina_login():
        if session.get("usuario") and cadastro.buscar(session["usuario"]):
            return redirect("/")
        return app.send_static_file("login.html")

    @app.post("/api/login")
    def login():
        if request.headers.get("X-Requested-With") != "fetch":
            return jsonify(erro="Requisição recusada."), 403
        corpo = request.get_json(silent=True) or {}
        nome = str(corpo.get("nome", ""))[:80].strip()
        matricula = str(corpo.get("matricula", ""))[:40]
        if not nome or not matricula.strip():
            raise ErroDeNegocio("Informe o nome e a matrícula.")
        chaves = [f"nome:{nome.upper()}", f"ip:{request.remote_addr}"]
        if espera := tentativas.bloqueado_por(chaves):
            registrar("LOGIN_BLOQUEADO", "Acesso bloqueado por excesso de tentativas", usuario=nome)
            minutos = max(1, round(espera / 60))
            raise ErroDeNegocio(f"Muitas tentativas sem sucesso. Tente de novo em {minutos} min.", 429)
        if not cadastro.todos():
            raise ErroDeNegocio("Nenhum usuário cadastrado nesta instalação. Crie o arquivo de usuários "
                                "com usuarios_cli.py (veja o README).", 503)
        usuario = cadastro.autenticar(nome, matricula)
        if usuario is None:
            tentativas.falhou(chaves)
            registrar("LOGIN_FALHOU", "Tentativa de acesso com nome ou matrícula incorretos", usuario=nome)
            raise ErroDeNegocio("Nome ou matrícula incorretos.", 401)
        tentativas.limpar(chaves)
        session.clear()
        session.permanent = True
        session["usuario"] = usuario.nome
        g.usuario = usuario
        registrar("LOGIN", "Entrou no sistema")
        return jsonify(usuario_json(usuario))

    @app.post("/api/logout")
    def logout():
        registrar("LOGOUT", "Saiu do sistema")
        session.clear()
        return "", 204

    @app.get("/api/eu")
    def eu():
        return jsonify(usuario_json(g.usuario))

    @app.get("/api/versao")
    def versao():
        """Consulta leve feita a cada poucos segundos para manter as telas atualizadas."""
        try:
            st = caminho_dados.stat()
            v = f"{st.st_mtime_ns}-{st.st_size}"
        except FileNotFoundError:
            v = "0"
        # Última mudança na escala confirmada: as telas avisam quem alterou o quê.
        ultima = auditoria.ultimo(EVENTOS_DA_ESCALA)
        if ultima:  # o IP fica só na auditoria do ADM
            ultima = {k: val for k, val in ultima.items() if k != "ip"}
        # `usuario`: dono da sessão. Se outra pessoa entrar no mesmo navegador, o cookie
        # muda para todas as abas; a tela compara e recarrega com o perfil certo.
        return jsonify(versao=v, ultima=ultima, usuario=g.usuario.nome)

    # --- persistência -----------------------------------------------------

    def transacao(func):
        """Carrega o estado, executa a operação e persiste, tudo sob lock."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            with repo.lock:
                estado = repo.carregar()
                resposta = func(estado, *args, **kwargs)
                repo.salvar(estado)
                return resposta
        return wrapper

    def exigir_periodo(estado: EstadoApp) -> Periodo:
        if not estado.periodo:
            raise ErroDeNegocio("Defina o período da escala primeiro.")
        if not estado.funcionarios:
            raise ErroDeNegocio("Cadastre a equipe antes de gerar a escala.")
        return estado.periodo

    @app.errorhandler(ErroDeNegocio)
    def _erro_negocio(e: ErroDeNegocio):
        return jsonify(erro=str(e)), e.status

    @app.errorhandler(ValueError)
    def _erro_validacao(e: ValueError):
        return jsonify(erro=str(e)), 400

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/saude")
    def saude():
        return jsonify(status="ok")

    @app.get("/api/estado")
    def obter_estado():
        admin = g.usuario.admin
        with repo.lock:
            estado = repo.carregar()
            return jsonify(**estado_json(estado, completo=admin),
                           rascunho=escala_json(estado, estado.rascunho) if admin else None,
                           escala=escala_json(estado, estado.escala, completo=admin))

    @app.put("/api/periodo")
    @transacao
    def definir_periodo(estado: EstadoApp):
        corpo = request.get_json(force=True)
        estado.periodo = Periodo(_parse_data(corpo.get("inicio")), _parse_data(corpo.get("fim")))
        if estado.periodo.total_dias > MAX_DIAS:
            raise ErroDeNegocio(f"O período máximo é de {MAX_DIAS} dias.")
        # Rascunho de outro período não serve mais; a escala final é mantida.
        if estado.rascunho and estado.rascunho.periodo != estado.periodo:
            estado.rascunho = None
        registrar("PERIODO_DEFINIDO", f"Período definido: {estado.periodo.inicio:%d/%m/%Y} a "
                                      f"{estado.periodo.fim:%d/%m/%Y}")
        return jsonify(estado_json(estado))

    @app.post("/api/funcionarios")
    @transacao
    def criar_funcionario(estado: EstadoApp):
        corpo = request.get_json(force=True)
        nome = normalizar_nome(corpo.get("nome", ""))
        if estado.nome_em_uso(nome):
            raise ErroDeNegocio(f"Já existe um profissional chamado {nome}.", 409)
        f = Funcionario(nome, _parse_enum(Cargo, corpo.get("cargo")))
        estado.funcionarios.append(f)
        registrar("FUNCIONARIO_ADICIONADO", f"Adicionou {f.nome} ({f.cargo.rotulo})")
        return jsonify(funcionario_json(f)), 201

    @app.put("/api/funcionarios/<id_>")
    @transacao
    def atualizar_funcionario(estado: EstadoApp, id_: str):
        corpo = request.get_json(force=True)
        f = _buscar(estado, id_)
        nome = normalizar_nome(corpo.get("nome", ""))
        if estado.nome_em_uso(nome, ignorar_id=id_):
            raise ErroDeNegocio(f"Já existe um profissional chamado {nome}.", 409)
        antes = f"{f.nome} ({f.cargo.rotulo})"
        f.nome = nome
        f.cargo = _parse_enum(Cargo, corpo.get("cargo"))
        registrar("FUNCIONARIO_ALTERADO", f"Alterou {antes} para {f.nome} ({f.cargo.rotulo})")
        return jsonify(funcionario_json(f))

    @app.delete("/api/funcionarios/<id_>")
    @transacao
    def remover_funcionario(estado: EstadoApp, id_: str):
        f = _buscar(estado, id_)
        estado.funcionarios.remove(f)
        registrar("FUNCIONARIO_REMOVIDO", f"Removeu {f.nome} da equipe")
        return "", 204

    @app.patch("/api/funcionarios/<id_>/disponibilidade")
    @transacao
    def alterar_disponibilidade(estado: EstadoApp, id_: str):
        """Corpo: lista de {data, turno, status}. Aplica todas em lote."""
        f = _buscar(estado, id_)
        alteracoes = request.get_json(force=True)
        if not isinstance(alteracoes, list):
            raise ErroDeNegocio("Envie uma lista de alterações.")
        for a in alteracoes:
            f.definir_status(_parse_data(a.get("data")), _parse_enum(Turno, a.get("turno")),
                             _parse_enum(Status, a.get("status")))
        registrar("DISPONIBILIDADE_ALTERADA",
                  f"Alterou a disponibilidade de {f.nome} ({len(alteracoes)} turno(s))")
        return jsonify(funcionario_json(f))

    # --- edição de posições (revisão e escala confirmada) -----------------

    def aplicar_alteracoes(estado: EstadoApp, escala: Escala, alteracoes, conferir: bool) -> list[dict]:
        """Aplica [{data, turno, cargo, funcionario_id, editado?, esperado?}] e devolve o que mudou.

        Com `conferir`, o campo `esperado` (id de quem o cliente viu na posição)
        precisa bater com o atual: evita sobrescrever a troca feita por outra pessoa.
        """
        if not isinstance(alteracoes, list):
            raise ErroDeNegocio("Envie uma lista de alterações.")
        # Quem já está na escala pode voltar ao lugar (desfazer), mesmo fora da equipe.
        pessoas = {**escala.pessoas(), **{f.id: f for f in estado.funcionarios}}
        mudancas = []
        for a in alteracoes:
            cargo = _parse_enum(Cargo, a.get("cargo"))
            dia, turno = _parse_data(a.get("data")), _parse_enum(Turno, a.get("turno"))
            try:
                plantao = escala.plantao(dia, turno)
            except KeyError:
                raise ErroDeNegocio("Turno fora do período da escala.")
            atual = plantao.equipe.get(cargo)
            if conferir and "esperado" in a and (atual.id if atual else None) != (a["esperado"] or None):
                raise ErroDeNegocio(
                    f"{_quando(dia, turno)} acabou de ser alterado por outra pessoa "
                    f"(agora: {atual.nome if atual else 'vago'}). A tela foi atualizada; confira e tente de novo.",
                    409)
            f = None
            if fid := a.get("funcionario_id"):
                f = pessoas.get(fid) or _buscar(estado, fid)
                if f.cargo is not cargo:
                    raise ErroDeNegocio(f"{f.nome} está cadastrado(a) em {f.cargo.rotulo} e não pode "
                                        f"ocupar a vaga de {cargo.rotulo}.")
            plantao.equipe[cargo] = f
            if a.get("editado", True):
                plantao.editados.add(cargo)
            else:
                plantao.editados.discard(cargo)
            if (atual.id if atual else None) != (f.id if f else None):
                mudancas.append({"data": dia.isoformat(), "turno": turno.value, "cargo": cargo.value,
                                 "antes": atual.nome if atual else None, "depois": f.nome if f else None,
                                 "rotulo": f"{_quando(dia, turno)} · {cargo.rotulo}: "
                                           f"{atual.nome if atual else 'VAGO'} → {f.nome if f else 'VAGO'}"})
        return mudancas

    def candidatos_json(estado: EstadoApp, escala: Escala):
        dia = _parse_data(request.args.get("data"))
        turno = _parse_enum(Turno, request.args.get("turno"))
        cargo = _parse_enum(Cargo, request.args.get("cargo"))
        admin = g.usuario.admin  # o total de plantões de cada um é informação do ADM
        return jsonify([{"id": c.funcionario.id, "nome": c.funcionario.nome,
                         "total": c.total if admin else None,
                         "preferencial": c.preferencial, "impedimentos": c.impedimentos}
                        for c in candidatos(estado.funcionarios, escala.plantoes, dia, turno, cargo)])

    # --- revisão (rascunho) ---------------------------------------------

    def exigir_rascunho(estado: EstadoApp) -> Escala:
        if not estado.rascunho:
            raise ErroDeNegocio("Não há escala em revisão. Gere uma proposta primeiro.", 404)
        return estado.rascunho

    @app.get("/api/rascunho")
    def obter_rascunho():
        with repo.lock:
            estado = repo.carregar()
            return jsonify(escala_json(estado, estado.rascunho))

    @app.post("/api/rascunho")
    @transacao
    def gerar_rascunho(estado: EstadoApp):
        periodo = exigir_periodo(estado)
        estado.rascunho = Escala(periodo, gerar_escala(estado.funcionarios, periodo).plantoes)
        registrar("PROPOSTA_GERADA", f"Gerou uma proposta de escala para {periodo.inicio:%d/%m/%Y} a "
                                     f"{periodo.fim:%d/%m/%Y}")
        return jsonify(escala_json(estado, estado.rascunho))

    @app.patch("/api/rascunho")
    @transacao
    def editar_rascunho(estado: EstadoApp):
        """Corpo: lista de {data, turno, cargo, funcionario_id (null = vago), editado?}."""
        rascunho = exigir_rascunho(estado)
        aplicar_alteracoes(estado, rascunho, request.get_json(force=True), conferir=False)
        return jsonify(escala_json(estado, rascunho))

    @app.delete("/api/rascunho")
    @transacao
    def descartar_rascunho(estado: EstadoApp):
        estado.rascunho = None
        registrar("REVISAO_DESCARTADA", "Descartou a escala em revisão")
        return "", 204

    @app.get("/api/rascunho/candidatos")
    def listar_candidatos():
        with repo.lock:
            estado = repo.carregar()
        return candidatos_json(estado, exigir_rascunho(estado))

    # --- escala final ----------------------------------------------------

    def exigir_escala(estado: EstadoApp) -> Escala:
        if not estado.escala:
            raise ErroDeNegocio("Nenhuma escala confirmada. Revise e confirme a escala primeiro.", 404)
        return estado.escala

    @app.get("/api/escala")
    def obter_escala():
        with repo.lock:
            estado = repo.carregar()
            return jsonify(escala_json(estado, estado.escala, completo=g.usuario.admin))

    @app.patch("/api/escala")
    @transacao
    def alterar_plantao(estado: EstadoApp):
        """Troca profissionais direto na escala confirmada (perfil USUARIO e ADMIN), com auditoria."""
        final = exigir_escala(estado)
        mudancas = aplicar_alteracoes(estado, final, request.get_json(force=True), conferir=True)
        for m in mudancas:
            registrar("PLANTAO_ALTERADO", m.pop("rotulo"), **m)
        return jsonify(escala_json(estado, final, completo=g.usuario.admin))

    @app.get("/api/escala/candidatos")
    def listar_candidatos_escala():
        with repo.lock:
            estado = repo.carregar()
        return candidatos_json(estado, exigir_escala(estado))

    @app.post("/api/escala")
    @transacao
    def confirmar_escala(estado: EstadoApp):
        """Confirma o rascunho em revisão como a escala final."""
        rascunho = exigir_rascunho(estado)
        rascunho.confirmada_em = datetime.now()
        estado.escala, estado.rascunho = rascunho, None
        registrar("ESCALA_CONFIRMADA", f"Confirmou a escala de {rascunho.periodo.inicio:%d/%m/%Y} a "
                                       f"{rascunho.periodo.fim:%d/%m/%Y}")
        return jsonify(escala_json(estado, estado.escala))

    @app.post("/api/escala/editar")
    @transacao
    def editar_escala(estado: EstadoApp):
        """Abre uma cópia da escala final para revisão, substituindo o rascunho atual."""
        final = exigir_escala(estado)
        copia, _ = escala_de_dict(escala_para_dict(final), estado.funcionarios)
        copia.confirmada_em = None
        estado.rascunho, estado.periodo = copia, final.periodo
        return jsonify(rascunho=escala_json(estado, copia), estado=estado_json(estado))

    @app.post("/api/escala/importar")
    @transacao
    def importar_escala(estado: EstadoApp):
        """Recebe um .json exportado ou um PDF gerado pelo sistema e o abre para revisão."""
        arquivo = request.files.get("arquivo")
        if not arquivo:
            raise ErroDeNegocio("Selecione um arquivo para importar.")
        conteudo = arquivo.read()
        try:
            if conteudo.startswith(b"%PDF"):
                dados = ler_dados_embutidos(conteudo)
                if dados is None:
                    raise ErroDeNegocio("Este PDF não traz os dados da escala. Só é possível importar "
                                        "PDFs baixados desta versão do sistema.")
            else:
                dados = json.loads(conteudo.decode("utf-8"))
            if not isinstance(dados, dict) or dados.get("formato") != FORMATO_EXPORTACAO:
                raise ErroDeNegocio("O arquivo não é uma escala exportada por este sistema.")
            escala, novos = escala_de_dict(dados, estado.funcionarios, incluir_ausentes=True)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise ErroDeNegocio(f"Arquivo de escala inválido ou corrompido ({e}).")
        if escala.periodo.total_dias > MAX_DIAS:
            raise ErroDeNegocio(f"O período máximo é de {MAX_DIAS} dias.")
        escala.confirmada_em = None
        estado.rascunho, estado.periodo = escala, escala.periodo
        registrar("ESCALA_IMPORTADA", f"Importou a escala do arquivo {arquivo.filename}")
        return jsonify(rascunho=escala_json(estado, escala), estado=estado_json(estado),
                       adicionados=[f.nome for f in novos])

    def _nome_arquivo(e: Escala, ext: str) -> str:
        return f"escala_samu_{e.periodo.inicio:%Y%m%d}_{e.periodo.fim:%Y%m%d}.{ext}"

    def _download(corpo, mimetype: str, nome: str) -> Response:
        return Response(corpo, mimetype=mimetype,
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    @app.get("/api/escala.pdf")
    def exportar_pdf():
        with repo.lock:
            estado = repo.carregar()
        final = exigir_escala(estado)
        pdf = gerar_pdf(avaliar(estado, final), dados=exportacao(final))
        registrar("PDF_GERADO", "Baixou o PDF da escala")
        return _download(pdf, "application/pdf", _nome_arquivo(final, "pdf"))

    @app.get("/api/escala.json")
    def exportar_json():
        with repo.lock:
            estado = repo.carregar()
        final = exigir_escala(estado)
        corpo = json.dumps(exportacao(final), indent=2, ensure_ascii=False)
        registrar("ESCALA_EXPORTADA", "Exportou a escala (arquivo .json)")
        return _download(corpo, "application/json", _nome_arquivo(final, "json"))

    # --- auditoria (ADMIN) -------------------------------------------------

    def _eventos():
        limite = min(int(request.args.get("limite", 1000)), 20000)
        return auditoria.listar(usuario=request.args.get("usuario") or None,
                                tipo=request.args.get("tipo") or None, limite=limite)

    @app.get("/api/auditoria")
    def listar_auditoria():
        return jsonify(eventos=_eventos(), usuarios=sorted(u.nome for u in cadastro.todos()))

    @app.get("/api/auditoria.csv")
    def exportar_auditoria():
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";")
        w.writerow(["Quando", "Usuário", "Evento", "Descrição", "IP"])
        for ev in _eventos():
            w.writerow([ev.get("quando"), ev.get("usuario") or "", ev.get("tipo"),
                        ev.get("descricao"), ev.get("ip") or ""])
        nome = f"auditoria_escala_{datetime.now():%Y%m%d_%H%M}.csv"
        # BOM para o Excel abrir os acentos corretamente.
        return _download("﻿" + saida.getvalue(), "text/csv; charset=utf-8", nome)

    return app


def _buscar(estado: EstadoApp, id_: str) -> Funcionario:
    try:
        return estado.funcionario(id_)
    except KeyError:
        raise ErroDeNegocio("Profissional não encontrado.", 404)


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
