"""Data e hora no fuso da equipe (padrão: America/Sao_Paulo).

Na Vercel o servidor roda em UTC: sem isto, às 21h de Tubarão o sistema já
estaria "amanhã" (e viraria o mês três horas antes). Em Docker/Kubernetes o
TZ do contêiner já é o de São Paulo, então o resultado é o mesmo.
"""
from __future__ import annotations

import os
from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        FUSO = ZoneInfo(os.environ.get("ESCALA_FUSO", "America/Sao_Paulo"))
    except ZoneInfoNotFoundError:  # sem base de fusos (pacote tzdata ausente): usa o do sistema
        FUSO = None
except ImportError:  # pragma: no cover
    FUSO = None


def agora() -> datetime:
    """Data e hora com fuso (ex.: 2026-11-15T21:30:00-03:00)."""
    return datetime.now(FUSO) if FUSO else datetime.now().astimezone()


def hoje() -> date:
    return agora().date()
