"""Usuários do sistema e auditoria.

Os usuários entram com o nome e a matrícula. A matrícula nunca é guardada em
texto: o arquivo de usuários só tem o hash (gerado por `usuarios_cli.py`).
Em produção esse arquivo vem de um Secret do Kubernetes, fora do código.

A auditoria é um arquivo JSON Lines: cada linha é um evento (login, logout,
alteração de plantão, ações do administrador). Eventos com mais de
`dias_retencao` dias (padrão 30) são apagados; os últimos 30 dias ficam sempre.
"""
from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


class Papel(str, Enum):
    ADMIN = "ADMIN"
    USUARIO = "USUARIO"


def chave_nome(nome: str) -> str:
    """Nome comparável: sem acento, sem espaços extras, em maiúsculas."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.split()).upper()


def limpar_matricula(matricula: str) -> str:
    return "".join(str(matricula).split())


@dataclass(frozen=True)
class Usuario:
    nome: str
    papel: Papel
    hash_matricula: str
    ativo: bool = True

    @property
    def admin(self) -> bool:
        return self.papel is Papel.ADMIN

    def para_dict(self) -> dict:
        return {"nome": self.nome, "papel": self.papel.value,
                "matricula_hash": self.hash_matricula, "ativo": self.ativo}

    @classmethod
    def de_dict(cls, d: dict) -> "Usuario":
        return cls(d["nome"], Papel(d.get("papel", "USUARIO")), d["matricula_hash"], d.get("ativo", True))


def novo_usuario(nome: str, matricula: str, papel: Papel = Papel.USUARIO) -> Usuario:
    return Usuario(" ".join(nome.split()), papel, generate_password_hash(limpar_matricula(matricula)))


# Hash de referência para gastar o mesmo tempo quando o nome não existe
# (não revela quais nomes estão cadastrados pelo tempo de resposta).
_HASH_FICTICIO = generate_password_hash("matricula-inexistente")


class CadastroUsuarios:
    def __init__(self, caminho: str | Path | None):
        self.caminho = Path(caminho) if caminho else None
        self._usuarios: dict[str, Usuario] = {}
        self._mtime: int | None = None
        self._lock = threading.Lock()

    def _recarregar(self) -> None:
        # Relido quando o arquivo muda (o Secret do Kubernetes é atualizado sem reiniciar o pod).
        if not self.caminho or not self.caminho.exists():
            self._usuarios, self._mtime = {}, None
            return
        mtime = self.caminho.stat().st_mtime_ns
        if mtime == self._mtime:
            return
        dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        lista = dados["usuarios"] if isinstance(dados, dict) else dados
        self._usuarios = {chave_nome(u.nome): u for u in map(Usuario.de_dict, lista)}
        self._mtime = mtime

    def todos(self) -> list[Usuario]:
        with self._lock:
            self._recarregar()
            return list(self._usuarios.values())

    def buscar(self, nome: str) -> Usuario | None:
        with self._lock:
            self._recarregar()
            u = self._usuarios.get(chave_nome(nome))
        return u if u and u.ativo else None

    def autenticar(self, nome: str, matricula: str) -> Usuario | None:
        u = self.buscar(nome)
        ok = check_password_hash(u.hash_matricula if u else _HASH_FICTICIO, limpar_matricula(matricula))
        return u if u and ok else None


class LimiteTentativas:
    """Bloqueia o nome/IP após muitas tentativas erradas (a matrícula é curta)."""

    def __init__(self, maximo: int = 5, janela_s: int = 15 * 60):
        self.maximo, self.janela = maximo, janela_s
        self._falhas: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recentes(self, chave: str, agora: float) -> list[float]:
        lista = [t for t in self._falhas.get(chave, []) if agora - t < self.janela]
        self._falhas[chave] = lista
        return lista

    def bloqueado_por(self, chaves: list[str]) -> int:
        """Segundos restantes de bloqueio (0 = liberado)."""
        agora = time.monotonic()
        with self._lock:
            restante = 0
            for c in chaves:
                lista = self._recentes(c, agora)
                if len(lista) >= self.maximo:
                    restante = max(restante, int(self.janela - (agora - lista[0])) + 1)
            return restante

    def falhou(self, chaves: list[str]) -> None:
        agora = time.monotonic()
        with self._lock:
            for c in chaves:
                self._recentes(c, agora).append(agora)

    def limpar(self, chaves: list[str]) -> None:
        with self._lock:
            for c in chaves:
                self._falhas.pop(c, None)


class Auditoria:
    DIAS_RETENCAO = 30

    def __init__(self, caminho: str | Path, dias_retencao: int = DIAS_RETENCAO):
        self.caminho = Path(caminho)
        self.dias_retencao = max(1, int(dias_retencao))
        self._lock = threading.Lock()
        self._proxima_limpeza = 0.0
        self.expurgar()

    def expurgar(self, agora: datetime | None = None) -> int:
        """Apaga eventos com mais de `dias_retencao` dias. Devolve quantos saíram.

        Linhas sem data legível são mantidas (melhor sobrar do que perder registro).
        A reescrita é atômica: grava num arquivo temporário e troca de uma vez.
        """
        agora = agora or datetime.now().astimezone()
        corte = agora - timedelta(days=self.dias_retencao)
        with self._lock:
            self._proxima_limpeza = time.monotonic() + 3600
            try:
                linhas = self.caminho.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return 0
            manter = [l for l in linhas if l.strip() and not _antes_de(l, corte)]
            removidos = sum(1 for l in linhas if l.strip()) - len(manter)
            if removidos:
                tmp = self.caminho.with_name(self.caminho.name + ".tmp")
                tmp.write_text("".join(l + "\n" for l in manter), encoding="utf-8")
                os.replace(tmp, self.caminho)
        return removidos

    def registrar(self, tipo: str, usuario: str | None, descricao: str, ip: str | None = None,
                  **detalhes) -> dict:
        evento = {"quando": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "tipo": tipo, "usuario": usuario, "descricao": descricao, "ip": ip}
        if detalhes:
            evento["detalhes"] = detalhes
        linha = json.dumps(evento, ensure_ascii=False)
        if time.monotonic() >= self._proxima_limpeza:  # no máximo uma limpeza por hora
            self.expurgar()
        with self._lock:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            with self.caminho.open("a", encoding="utf-8") as fp:
                fp.write(linha + "\n")
        return evento

    def ultimo(self, tipos: set[str]) -> dict | None:
        """Evento mais recente entre `tipos` (com cache enquanto o arquivo não muda)."""
        try:
            st = self.caminho.stat()
        except FileNotFoundError:
            return None
        marca = (st.st_mtime_ns, st.st_size, frozenset(tipos))
        if getattr(self, "_cache_ultimo", (None,))[0] == marca:
            return self._cache_ultimo[1]
        achado = next(iter(e for e in self._iterar_reverso() if e.get("tipo") in tipos), None)
        self._cache_ultimo = (marca, achado)
        return achado

    def _iterar_reverso(self):
        with self._lock:
            linhas = self.caminho.read_text(encoding="utf-8").splitlines()
        for linha in reversed(linhas):
            try:
                yield json.loads(linha)
            except json.JSONDecodeError:
                continue

    def listar(self, usuario: str | None = None, tipo: str | None = None,
               limite: int = 500) -> list[dict]:
        """Eventos mais recentes primeiro."""
        if not self.caminho.exists():
            return []
        alvo = chave_nome(usuario) if usuario else None
        out = []
        for ev in self._iterar_reverso():
            if alvo and chave_nome(ev.get("usuario") or "") != alvo:
                continue
            if tipo and ev.get("tipo") != tipo:
                continue
            out.append(ev)
            if len(out) >= limite:
                break
        return out


def _antes_de(linha: str, corte: datetime) -> bool:
    """True se o evento da linha é mais antigo que `corte`."""
    try:
        quando = datetime.fromisoformat(json.loads(linha)["quando"])
    except (ValueError, KeyError, TypeError):
        return False
    if quando.tzinfo is None:
        quando = quando.astimezone()
    return quando < corte
