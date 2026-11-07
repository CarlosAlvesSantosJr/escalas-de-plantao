"""Persistência em JSON.

Lê o formato antigo (campo "tipo", sem "id", sem período) e grava o novo.
Guarda também o rascunho em revisão e as escalas confirmadas (uma por
período: o mês atual, o seguinte e as anteriores). Arquivos antigos, com uma
única "escala", continuam sendo lidos.
A gravação é atômica (arquivo temporário + rename) para não corromper os
dados se o processo cair no meio da escrita.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .dominio import (Cargo, Escala, Funcionario, Periodo, Plantao, Status, Turno,
                      normalizar_nome)


MAX_ESCALAS = 12  # escalas confirmadas guardadas (as mais antigas saem)


@dataclass
class EstadoApp:
    funcionarios: list[Funcionario] = field(default_factory=list)
    periodo: Periodo | None = None
    rascunho: Escala | None = None   # em revisão, editável
    escalas: list[Escala] = field(default_factory=list)  # confirmadas, por data de início

    def publicar(self, nova: Escala) -> list[Escala]:
        """Inclui a escala confirmada; as que têm período sobreposto são substituídas."""
        substituidas = [e for e in self.escalas
                        if e.periodo.inicio <= nova.periodo.fim and nova.periodo.inicio <= e.periodo.fim]
        self.escalas = sorted([e for e in self.escalas if e not in substituidas] + [nova],
                              key=lambda e: e.periodo.inicio)[-MAX_ESCALAS:]
        return substituidas

    def escala_de(self, inicio: date) -> Escala | None:
        return next((e for e in self.escalas if e.periodo.inicio == inicio), None)

    def classificar(self, hoje: date) -> dict[date, str]:
        """Papel de cada escala: atual, seguinte (o par que a equipe vê), anterior ou futura.

        A equipe vê sempre um par "mês atual + mês seguinte". O par só avança quando
        as DUAS coisas acontecem: o mês virou (a escala seguinte já começou) e o ADM
        confirmou uma escala nova depois dela. Então:
          * atual = a escala mais recente que já começou E já tem uma sucessora;
          * sem nenhuma assim (ex.: só há escalas futuras), a primeira que ainda
            não terminou; sem ela, a mais recente;
          * seguinte = a escala logo depois da atual.
        Antes da atual: anterior. Depois da seguinte: futura (só o ADM vê).
        """
        es = self.escalas  # já ordenadas por início
        if not es:
            return {}
        i = next((k for k in range(len(es) - 2, -1, -1) if es[k].periodo.inicio <= hoje), None)
        if i is None:
            i = next((k for k, e in enumerate(es) if e.periodo.fim >= hoje), len(es) - 1)
        papeis = {}
        for k, e in enumerate(es):
            papeis[e.periodo.inicio] = ("atual" if k == i else "seguinte" if k == i + 1
                                        else "anterior" if k < i else "futura")
        return papeis

    def escala_padrao(self, hoje: date) -> Escala | None:
        """A que abre primeiro: a atual; sem ela, a do mês seguinte; sem ela, a mais recente."""
        papeis = self.classificar(hoje)
        for papel in ("atual", "seguinte"):
            for e in self.escalas:
                if papeis[e.periodo.inicio] == papel:
                    return e
        return self.escalas[-1] if self.escalas else None

    def funcionario(self, id_: str) -> Funcionario:
        for f in self.funcionarios:
            if f.id == id_:
                return f
        raise KeyError(id_)

    def nome_em_uso(self, nome: str, ignorar_id: str | None = None) -> bool:
        return any(f.nome == nome and f.id != ignorar_id for f in self.funcionarios)


def _funcionario_para_dict(f: Funcionario) -> dict:
    return {
        "id": f.id,
        "nome": f.nome,
        "tipo": f.cargo.value,
        "disponibilidade": {f"{d.isoformat()}|{t.value}": s.value
                            for (d, t), s in sorted(f.disponibilidade.items())},
    }


def _funcionario_de_dict(item: dict) -> Funcionario:
    extras = {"id": item["id"]} if item.get("id") else {}
    f = Funcionario(nome=item["nome"], cargo=Cargo(item.get("tipo") or item["cargo"]), **extras)
    for chave, valor in item.get("disponibilidade", {}).items():
        data_str, turno = chave.split("|")
        f.definir_status(date.fromisoformat(data_str), Turno(turno), Status(valor))
    return f


def periodo_para_dict(p: Periodo) -> dict:
    return {"inicio": p.inicio.isoformat(), "fim": p.fim.isoformat()}


def periodo_de_dict(dados: dict) -> Periodo:
    return Periodo(date.fromisoformat(dados["inicio"]), date.fromisoformat(dados["fim"]))


def escala_para_dict(e: Escala) -> dict:
    def membro(f):
        return {"id": f.id, "nome": f.nome} if f else None

    return {
        "periodo": periodo_para_dict(e.periodo),
        "confirmada_em": e.confirmada_em.isoformat(timespec="minutes") if e.confirmada_em else None,
        "plantoes": [{"data": p.data.isoformat(), "turno": p.turno.value,
                      **{c.value.lower(): membro(p.equipe.get(c)) for c in Cargo},
                      "editados": sorted(c.value for c in p.editados)}
                     for p in e.plantoes],
    }


def escala_de_dict(dados: dict, funcionarios: list[Funcionario],
                   incluir_ausentes: bool = False) -> tuple[Escala, list[Funcionario]]:
    """Monta a escala ligando cada posição a um profissional da equipe, pelo id ou pelo nome.

    Quem não está na equipe vira um profissional avulso (a avaliação aponta o
    conflito). Com `incluir_ausentes`, usado na importação, ele é acrescentado
    à equipe e devolvido na lista de novos.
    """
    periodo = periodo_de_dict(dados["periodo"])
    por_id = {f.id: f for f in funcionarios}
    por_nome = {f.nome: f for f in funcionarios}
    novos: list[Funcionario] = []

    def resolver(item: dict | None, cargo: Cargo) -> Funcionario | None:
        if not item:
            return None
        nome = normalizar_nome(item["nome"])
        f = por_id.get(item.get("id")) or por_nome.get(nome)
        if f is None:
            f = Funcionario(nome, cargo, **({"id": item["id"]} if item.get("id") else {}))
            por_id[f.id] = por_nome[f.nome] = f
            if incluir_ausentes:
                funcionarios.append(f)
                novos.append(f)
        return f

    # A grade sempre cobre o período inteiro; posições fora dele são ignoradas.
    salvos = {(date.fromisoformat(i["data"]), Turno(i["turno"])): i for i in dados.get("plantoes", [])}
    plantoes = []
    for dia, turno in periodo.slots():
        item = salvos.get((dia, turno), {})
        p = Plantao(dia, turno, {c: resolver(item.get(c.value.lower()), c) for c in Cargo})
        p.editados = {Cargo(c) for c in item.get("editados", [])}
        plantoes.append(p)
    confirmada = dados.get("confirmada_em")
    return Escala(periodo, plantoes, datetime.fromisoformat(confirmada) if confirmada else None), novos


class RepositorioJSON:
    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.lock = threading.RLock()

    def carregar(self) -> EstadoApp:
        if not self.caminho.exists():
            return EstadoApp()
        with self.caminho.open(encoding="utf-8") as fp:
            dados = json.load(fp)
        funcionarios = [_funcionario_de_dict(i) for i in dados.get("funcionarios", [])]
        rascunho = escala_de_dict(dados["rascunho"], funcionarios)[0] if dados.get("rascunho") else None
        # Formato atual: lista "escalas". Formato antigo: uma única "escala".
        brutas = dados.get("escalas") or ([dados["escala"]] if dados.get("escala") else [])
        escalas = sorted((escala_de_dict(d, funcionarios)[0] for d in brutas), key=lambda e: e.periodo.inicio)
        return EstadoApp(
            funcionarios=funcionarios,
            periodo=periodo_de_dict(dados["periodo"]) if dados.get("periodo") else None,
            rascunho=rascunho,
            escalas=escalas,
        )

    def salvar(self, estado: EstadoApp) -> None:
        dados = {
            "periodo": periodo_para_dict(estado.periodo) if estado.periodo else None,
            "funcionarios": [_funcionario_para_dict(f) for f in estado.funcionarios],
            "rascunho": escala_para_dict(estado.rascunho) if estado.rascunho else None,
            "escalas": [escala_para_dict(e) for e in estado.escalas],
        }
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.caminho.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(dados, fp, indent=2, ensure_ascii=False)
            os.replace(tmp, self.caminho)
        except BaseException:
            os.unlink(tmp)
            raise
