"""Troca de plantões entre colegas (SWAP de 2 ou rodízio de 3).

As posições escolhidas formam um ciclo: quem está na posição 1 vai para a 2,
quem está na 2 vai para a 3 (ou para a 1, na troca entre dois) e quem está
na última vai para a 1.

    Troca entre 2:  A(P1) ↔ B(P2)            → P1: B, P2: A
    Rodízio de 3:   A(P1) → P2, B(P2) → P3, C(P3) → P1

Bloqueiam a troca as regras de segurança: dois plantões no mesmo dia, falta
de descanso depois da noite, férias e quem saiu da equipe. "Indisponível"
não bloqueia: quem aceita a troca está abrindo mão dessa marcação.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .avaliacao import Agenda, impedimentos
from .dominio import Cargo, Escala, Funcionario, Turno

MIN_PESSOAS, MAX_PESSOAS = 2, 3
REGRAS_QUE_BLOQUEIAM = {
    "Já tem outro plantão neste dia",
    "Saindo do plantão da noite anterior",
    "Tem plantão de dia logo após esta noite",
    "De férias",
    "Não faz mais parte da equipe",
}


class TrocaInvalida(ValueError):
    pass


@dataclass(frozen=True)
class Posicao:
    data: date
    turno: Turno
    cargo: Cargo

    def __str__(self) -> str:
        dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        return f"{dias[self.data.weekday()]} {self.data:%d/%m} {self.turno.value}"


@dataclass(frozen=True)
class Movimento:
    funcionario: Funcionario
    de: Posicao
    para: Posicao


def _ocupante(escala: Escala, p: Posicao) -> Funcionario | None:
    try:
        return escala.plantao(p.data, p.turno).equipe.get(p.cargo)
    except KeyError:
        raise TrocaInvalida(f"{p} está fora do período desta escala.")


def movimentos(escala: Escala, posicoes: list[Posicao]) -> list[Movimento]:
    """Quem vai para onde, validando a forma da troca (sem alterar nada)."""
    if not MIN_PESSOAS <= len(posicoes) <= MAX_PESSOAS:
        raise TrocaInvalida("A troca precisa de 2 ou 3 plantões.")
    if len(set(posicoes)) != len(posicoes):
        raise TrocaInvalida("Escolha plantões diferentes.")
    if len({p.cargo for p in posicoes}) != 1:
        raise TrocaInvalida("Só dá para trocar plantões da mesma função (Enfermagem com Enfermagem, "
                            "Socorrista com Socorrista).")
    pessoas = [_ocupante(escala, p) for p in posicoes]
    if any(f is None for f in pessoas):
        raise TrocaInvalida("Não dá para trocar com uma vaga em aberto.")
    if len({f.id for f in pessoas}) != len(pessoas):
        raise TrocaInvalida("Cada plantão da troca precisa ser de uma pessoa diferente.")
    n = len(posicoes)
    return [Movimento(pessoas[i], posicoes[i], posicoes[(i + 1) % n]) for i in range(n)]


def aplicar(escala: Escala, posicoes: list[Posicao]) -> list[Movimento]:
    """Faz o rodízio na escala e marca as posições como alteradas."""
    movs = movimentos(escala, posicoes)
    for m in movs:
        p = escala.plantao(m.para.data, m.para.turno)
        p.equipe[m.para.cargo] = m.funcionario
        p.editados.add(m.para.cargo)
    return movs


def impedimentos_da_troca(funcionarios: list[Funcionario], escala: Escala,
                          posicoes: list[Posicao]) -> dict[str, list[str]]:
    """Regras que a troca quebraria, por nome (vazio = pode trocar). Não altera a escala."""
    movs = movimentos(escala, posicoes)
    antes = {(p.data, p.turno): (dict(p.equipe), set(p.editados)) for p in escala.plantoes
             if any((p.data, p.turno) == (m.para.data, m.para.turno) for m in movs)}
    try:
        aplicar(escala, posicoes)
        agenda = Agenda(escala.plantoes)
        equipe_ids = {f.id for f in funcionarios}
        problemas = {}
        for m in movs:
            motivos = [x for x in impedimentos(m.funcionario, m.para.data, m.para.turno, m.para.cargo,
                                               agenda, equipe_ids)
                       if x in REGRAS_QUE_BLOQUEIAM]
            if motivos:
                problemas[m.funcionario.nome] = motivos
        return problemas
    finally:
        for p in escala.plantoes:  # desfaz a simulação
            if (p.data, p.turno) in antes:
                p.equipe, p.editados = dict(antes[(p.data, p.turno)][0]), set(antes[(p.data, p.turno)][1])


def opcoes(funcionarios: list[Funcionario], escala: Escala, base: list[Posicao]) -> list[dict]:
    """Plantões de colegas que podem entrar na troca depois de `base`, agrupados por pessoa."""
    cargo = base[0].cargo
    na_troca = {f.id for f in (_ocupante(escala, p) for p in base) if f}
    por_pessoa: dict[str, dict] = {}
    for p in escala.plantoes:
        f = p.equipe.get(cargo)
        if not f or f.id in na_troca:
            continue
        pos = Posicao(p.data, p.turno, cargo)
        try:
            problemas = impedimentos_da_troca(funcionarios, escala, base + [pos])
        except TrocaInvalida as e:
            problemas = {"": [str(e)]}
        item = por_pessoa.setdefault(f.id, {"id": f.id, "nome": f.nome, "plantoes": []})
        item["plantoes"].append({
            "data": p.data.isoformat(), "turno": p.turno.value,
            "motivos": [f"{nome}: {m}" if nome else m for nome, ms in problemas.items() for m in ms],
        })
    return sorted(por_pessoa.values(), key=lambda x: x["nome"])
