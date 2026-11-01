"""Exportação da escala para PDF (fpdf 1.7).

Uma linha por dia, com os turnos DIA e NOITE lado a lado. Cada profissional
ganha a mesma cor da tela, para achar os próprios plantões de relance. O
resumo por profissional fica só no sistema: não vai para quem recebe a escala.

O PDF também carrega a escala em JSON (chave /EscalaSAMU do dicionário de
informações), o que permite reimportá-lo depois para edição.
"""
from __future__ import annotations

import base64
import json
import re

from fpdf import FPDF

from .avaliacao import ResultadoEscala
from .dominio import Turno, eh_fim_de_semana

DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

VERMELHO = (196, 30, 36)
LARANJA = (232, 100, 27)
CINZA_CLARO = (245, 246, 248)
AZUL_FDS = (232, 240, 254)
TEXTO = (33, 37, 41)
AZUL_NOITE = (27, 42, 64)

# Mesma paleta de static/css/style.css (--pc-0 … --pc-11).
PALETA = ["#3B6FD8", "#E07A1F", "#2E9E5B", "#8E5CC4", "#129C9C", "#C29A00",
          "#8B5E3C", "#D6548E", "#5B6B82", "#6B8E23", "#4446B8", "#9E2A5E"]

_CHAVE_DADOS = "EscalaSAMU"
_RE_DADOS = re.compile(rb"/" + _CHAVE_DADOS.encode() + rb" \(([A-Za-z0-9+/=]+)\)")


def _rgb(hexa: str) -> tuple[int, int, int]:
    return tuple(int(hexa[i:i + 2], 16) for i in (1, 3, 5))


def _tom_claro(rgb: tuple[int, int, int], forca: float = 0.18) -> tuple[int, int, int]:
    return tuple(round(255 - (255 - c) * forca) for c in rgb)


class _PDF(FPDF):
    dados_embutidos = ""

    def _putinfo(self):
        super()._putinfo()
        if self.dados_embutidos:
            self._out(f"/{_CHAVE_DADOS} ({self.dados_embutidos})")


def ler_dados_embutidos(pdf: bytes) -> dict | None:
    """Recupera a escala gravada por `gerar_pdf`; None se o PDF não tiver os dados."""
    achado = _RE_DADOS.search(pdf)
    return json.loads(base64.b64decode(achado.group(1))) if achado else None


def gerar_pdf(resultado: ResultadoEscala, dados: dict | None = None) -> bytes:
    pdf = _PDF()
    if dados:
        pdf.dados_embutidos = base64.b64encode(json.dumps(dados).encode()).decode("ascii")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    periodo = resultado.periodo
    cores = {fid: _rgb(PALETA[i]) for fid, i in resultado.cores.items()}

    pdf.set_fill_color(*VERMELHO)
    pdf.rect(0, 0, 210, 26, "F")
    pdf.set_fill_color(*LARANJA)
    pdf.rect(0, 26, 210, 1.5, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(10, 6)
    pdf.cell(0, 8, "SAMU 192 - ESCALA DE PLANTÃO")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(10, 14)
    pdf.cell(0, 6, f"Período: {periodo.inicio:%d/%m/%Y} a {periodo.fim:%d/%m/%Y}   |   "
                   f"Cobertura: {resultado.cobertura:.0%}")
    pdf.set_y(34)

    # Uma linha por dia: bloco DIA à esquerda, NOITE à direita (A4 = 190 mm úteis).
    larg_data, larg_nome, vao, altura = 26, 40, 4, 7
    blocos = [(Turno.DIA, "DIA", LARANJA), (Turno.NOITE, "NOITE", AZUL_NOITE)]

    def cabecalho():
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(255, 255, 255)
        y = pdf.get_y()
        pdf.set_fill_color(*TEXTO)
        pdf.cell(larg_data, altura * 2, "Data", fill=True)
        for i, (_, titulo, cor) in enumerate(blocos):
            if i:
                pdf.cell(vao, altura * 2)
            x = pdf.get_x()
            pdf.set_fill_color(*cor)
            pdf.cell(larg_nome * 2, altura, titulo, align="C", fill=True)
            pdf.set_xy(x, y + altura)
            pdf.set_fill_color(*TEXTO)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(larg_nome, altura, "Enfermagem", fill=True)
            pdf.cell(larg_nome, altura, "Condutor", fill=True)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_xy(x + larg_nome * 2, y)
        pdf.set_xy(pdf.l_margin, y + altura * 2)

    def caber(texto, largura):
        while texto and pdf.get_string_width(texto) > largura:
            texto = texto[:-2] + "."
        return texto

    def celula_pessoa(membro, fundo):
        x, y = pdf.get_x(), pdf.get_y()
        if not membro:
            pdf.set_fill_color(*fundo)
            pdf.set_text_color(*VERMELHO)
            pdf.cell(larg_nome, altura, "   VAGO", fill=True)
            return
        cor = cores.get(membro.id, TEXTO)
        pdf.set_fill_color(*_tom_claro(cor))
        pdf.set_text_color(*TEXTO)
        pdf.cell(larg_nome, altura, "   " + caber(membro.nome, larg_nome - 6), fill=True)
        pdf.set_fill_color(*cor)
        pdf.rect(x + 1, y + 1.2, 1.4, altura - 2.4, "F")

    por_dia: dict = {}
    for p in resultado.plantoes:
        por_dia.setdefault(p.data, {})[p.turno] = p

    cabecalho()
    for i, (dia, turnos) in enumerate(por_dia.items()):
        if pdf.get_y() > 280 - altura:
            pdf.add_page()
            cabecalho()
        fundo = AZUL_FDS if eh_fim_de_semana(dia) else (CINZA_CLARO if i % 2 else (255, 255, 255))
        pdf.set_font("Helvetica", "B" if eh_fim_de_semana(dia) else "", 10)
        pdf.set_fill_color(*fundo)
        pdf.set_text_color(*TEXTO)
        pdf.cell(larg_data, altura, f"{dia:%d/%m} {DIAS_SEMANA[dia.weekday()]}", fill=True)
        pdf.set_font("Helvetica", "", 10)
        for j, (turno, _, _) in enumerate(blocos):
            if j:
                pdf.cell(vao, altura)
            plantao = turnos.get(turno)
            for membro in (plantao.enfermeiro, plantao.motorista) if plantao else (None, None):
                celula_pessoa(membro, fundo)
        pdf.ln()

    return pdf.output(dest="S").encode("latin-1")
