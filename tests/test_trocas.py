from datetime import date

import pytest

from escala.dominio import Cargo, Escala, Funcionario, Periodo, Plantao, Status, Turno
from escala.trocas import Posicao, TrocaInvalida, aplicar, impedimentos_da_troca, opcoes

E, S = Cargo.ENFERMEIRO, Cargo.MOTORISTA
D, N = Turno.DIA, Turno.NOITE


def _escala(grade):
    """grade: {(dia, turno): (enfermagem, socorrista)} em novembro/2026."""
    dias = sorted({d for d, _ in grade})
    periodo = Periodo(date(2026, 11, dias[0]), date(2026, 11, dias[-1]))
    plantoes = []
    for dia, turno in periodo.slots():
        enf, soc = grade.get((dia.day, turno), (None, None))
        plantoes.append(Plantao(dia, turno, {E: enf, S: soc}))
    return Escala(periodo, plantoes)


ANA, BIA, CAIO = Funcionario("ANA", E), Funcionario("BIA", E), Funcionario("CAIO", E)
LEO = Funcionario("LEO", S)
EQUIPE = [ANA, BIA, CAIO, LEO]
pos = lambda dia, turno, cargo=E: Posicao(date(2026, 11, dia), turno, cargo)
quem = lambda esc, dia, turno, cargo=E: esc.plantao(date(2026, 11, dia), turno).equipe[cargo].nome


def test_troca_entre_dois():
    esc = _escala({(2, D): (ANA, LEO), (4, D): (BIA, LEO)})
    aplicar(esc, [pos(2, D), pos(4, D)])
    assert (quem(esc, 2, D), quem(esc, 4, D)) == ("BIA", "ANA")
    assert E in esc.plantao(date(2026, 11, 2), D).editados


def test_rodizio_entre_tres():
    esc = _escala({(2, D): (ANA, LEO), (4, D): (BIA, LEO), (6, D): (CAIO, LEO)})
    aplicar(esc, [pos(2, D), pos(4, D), pos(6, D)])
    # ANA vai para o plantão de BIA, BIA para o de CAIO, CAIO para o de ANA.
    assert (quem(esc, 2, D), quem(esc, 4, D), quem(esc, 6, D)) == ("CAIO", "ANA", "BIA")


@pytest.mark.parametrize("posicoes, erro", [
    ([pos(2, D)], "2 ou 3"),
    ([pos(2, D), pos(2, D)], "diferentes"),
    ([pos(2, D), pos(2, D, S)], "mesma função"),
    ([pos(2, D), pos(3, D)], "vaga em aberto"),
    ([pos(2, D), pos(4, N)], "pessoa diferente"),
])
def test_trocas_invalidas(posicoes, erro):
    esc = _escala({(2, D): (ANA, LEO), (4, N): (ANA, LEO)})
    with pytest.raises(TrocaInvalida, match=erro):
        aplicar(esc, posicoes)


def test_bloqueia_descanso_e_ignora_indisponivel():
    # BIA trabalha a noite do dia 3; receber o DIA 4 de ANA quebraria o descanso.
    esc = _escala({(3, N): (BIA, LEO), (4, D): (ANA, LEO), (6, D): (BIA, LEO)})
    problemas = impedimentos_da_troca(EQUIPE, esc, [pos(4, D), pos(6, D)])
    assert problemas == {"BIA": ["Saindo do plantão da noite anterior"]}
    assert quem(esc, 4, D) == "ANA" and quem(esc, 6, D) == "BIA"  # simulação não altera nada

    ANA.definir_status(date(2026, 11, 6), D, Status.INDISPONIVEL)
    esc2 = _escala({(4, D): (ANA, LEO), (6, D): (BIA, LEO)})
    assert impedimentos_da_troca(EQUIPE, esc2, [pos(4, D), pos(6, D)]) == {}
    ANA.definir_status(date(2026, 11, 6), D, Status.DISPONIVEL)


def test_opcoes_mostram_colegas_e_motivos():
    esc = _escala({(3, N): (BIA, LEO), (4, D): (ANA, LEO), (6, D): (BIA, LEO), (8, D): (CAIO, LEO)})
    lista = {o["nome"]: o["plantoes"] for o in opcoes(EQUIPE, esc, [pos(4, D)])}
    assert set(lista) == {"BIA", "CAIO"}  # ANA (quem pede) e socorristas ficam fora
    bia = {(p["data"], p["turno"]): p["motivos"] for p in lista["BIA"]}
    assert bia[("2026-11-03", "NOITE")] == []  # as duas saem dos plantões originais: sem conflito
    assert bia[("2026-11-06", "DIA")] == ["BIA: Saindo do plantão da noite anterior"]
    assert lista["CAIO"][0]["motivos"] == []
