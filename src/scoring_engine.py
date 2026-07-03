# src/scoring_engine.py
# Motor de scoring de governança corporativa
# Recebe um dict com os campos da empresa e retorna a nota consolidada por bloco.

import traceback
from configs import config
from src.utils.logging_utils import custom_log


def calcular_segmento_listagem(dados: dict) -> dict:
    """Calcula nota do bloco Segmento de Listagem (max: 10)."""
    try:
        segmento = dados.get("segmento_listagem", "")
        nota_base = config.NOTAS_SEGMENTO.get(segmento, 0)

        # Mitigadores de tag along inferidos do campo 'comentario_segmento'
        comentario = str(dados.get("comentario_segmento", "") or "").lower()
        tag_along_pn = "80%" in comentario and "pn" in comentario
        tag_along_on = "100%" in comentario and "on" in comentario
        duas_classes_pn = "2 classes" in comentario and "pn" in comentario

        if duas_classes_pn:
            nota_base = 6
        elif tag_along_pn and tag_along_on:
            nota_base = 7
        elif tag_along_pn or tag_along_on:
            nota_base = 6

        # peso = 10, max = 10 → nota bruta = nota ponderada
        custom_log(
            msg=f"Segmento de listagem: {segmento} -> nota {nota_base}/10",
            component="/scoring/segmento_listagem",
            severity="INFO",
        )
        return {"nota_bruta": nota_base, "nota_ponderada": nota_base, "max_bruta": 10}

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/scoring/segmento_listagem", severity="CRITICAL")
        raise


def calcular_direitos_acionistas(dados: dict) -> dict:
    """Calcula nota do bloco Direitos e Proteções dos Acionistas (max: 10)."""
    try:
        cf_permanente = dados.get("conselho_fiscal_permanente", False)
        cf_instalado = dados.get("conselho_fiscal_instalado", False)

        if cf_permanente:
            nota = config.NOTAS_CONSELHO_FISCAL["permanente"]
        elif cf_instalado:
            nota = config.NOTAS_CONSELHO_FISCAL["instalado"]
        else:
            nota = config.NOTAS_CONSELHO_FISCAL["nao_instalado"]

        if dados.get("poison_pill", False):
            nota += config.PENALIDADES_DIREITOS["poison_pill"]
            threshold = dados.get("poison_pill_threshold", 1.0)
            if threshold <= 0.20:
                nota += config.PENALIDADES_DIREITOS["poison_pill_threshold_baixo"]

        if dados.get("limite_voto", False):
            nota += config.PENALIDADES_DIREITOS["limite_voto"]

        if dados.get("limite_dividendo", False):
            nota += config.PENALIDADES_DIREITOS["limite_dividendo"]

        nota = max(nota, 0)

        custom_log(msg=f"Direitos acionistas -> nota {nota}/10", component="/scoring/direitos_acionistas", severity="INFO")
        return {"nota_bruta": nota, "nota_ponderada": nota, "max_bruta": 10}

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/scoring/direitos_acionistas", severity="CRITICAL")
        raise


def calcular_estrutura_acionaria(dados: dict) -> dict:
    """Calcula nota do bloco Estrutura Acionária (max: 20)."""
    try:
        # (A) Natureza — case-insensitive
        natureza = dados.get("natureza_estrutura", "").lower().strip()
        nota_a = config.NOTAS_NATUREZA_ESTRUTURA.get(natureza, 0)

        # (B) Participação do controlador
        # Corporation/sem controlador (nan/N/A) → 3pts (neutro/positivo)
        participacao_raw = dados.get("participacao_controlador")
        is_sem_controlador = (
            participacao_raw is None
            or str(participacao_raw).strip().upper() in ("NAN", "N/A", "")
        )
        if is_sem_controlador:
            nota_b = config.NOTAS_PARTICIPACAO_CONTROLADOR["sem_controlador"]
        elif float(participacao_raw) >= 0.40:
            nota_b = config.NOTAS_PARTICIPACAO_CONTROLADOR["acima_40"]
        else:
            nota_b = config.NOTAS_PARTICIPACAO_CONTROLADOR["abaixo_40"]

        # (C) Visão sobre o controlador
        # N/A (corporation) → 3pts (neutro)
        visao = dados.get("visao_controlador", "")
        if visao.upper() in ("N/A", "NAN", ""):
            nota_c = 3
        else:
            nota_c = config.NOTAS_VISAO_CONTROLADOR.get(visao, 0)

        # (D) Insiders' ownership
        insiders = float(dados.get("insiders_ownership", 0.0) or 0.0)
        if insiders >= 0.10:
            nota_d = config.NOTAS_INSIDERS["acima_10"]
        elif insiders >= 0.05:
            nota_d = config.NOTAS_INSIDERS["entre_5_10"]
        else:
            nota_d = config.NOTAS_INSIDERS["abaixo_5"]

        # (E) Potencial conflito
        conflito = dados.get("potencial_conflito", "Alto")
        nota_e = config.NOTAS_CONFLITO.get(conflito, 0)

        # (F) Partes relacionadas
        partes_rel = dados.get("transacoes_partes_relacionadas", "Sim")
        nota_f = config.NOTAS_PARTES_RELACIONADAS.get(partes_rel, 0)

        nota_bruta = nota_a + nota_b + nota_c + nota_d + nota_e + nota_f
        # max = 4+3+6+3+2+2 = 20 = peso do bloco → sem normalização
        custom_log(
            msg=f"Estrutura acionária -> {nota_bruta}/20 (A={nota_a} B={nota_b} C={nota_c} D={nota_d} E={nota_e} F={nota_f})",
            component="/scoring/estrutura_acionaria",
            severity="INFO",
        )
        return {
            "nota_bruta": nota_bruta,
            "nota_ponderada": nota_bruta,
            "max_bruta": 20,
            "detalhes": {"natureza": nota_a, "participacao": nota_b, "visao": nota_c, "insiders": nota_d, "conflito": nota_e, "partes_relacionadas": nota_f},
        }

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/scoring/estrutura_acionaria", severity="CRITICAL")
        raise


def calcular_conselho_administracao(dados: dict) -> dict:
    """Calcula nota do bloco Conselho de Administração (max: 30)."""
    try:
        # (A) Estrutura: número de membros → nota 1/2/3 → 2/6/10 pts fixos
        n_membros = int(dados.get("n_membros_conselho", 0))
        nota_estrutura_rank = config.NOTA_ESTRUTURA_POR_MEMBROS.get(n_membros, config.NOTA_ESTRUTURA_DEFAULT)
        nota_a = config.NOTAS_ESTRUTURA_CONSELHO_PTS[nota_estrutura_rank]

        # (B) Qualidade e diversidade (nota subjetiva 1–5) → 4/8/12/16/20 pts
        qualidade = int(dados.get("qualidade_conselho", 1))
        nota_b = config.NOTAS_QUALIDADE_CONSELHO.get(qualidade, 4)

        nota_bruta = nota_a + nota_b  # max = 10 + 20 = 30 = peso do bloco
        custom_log(
            msg=f"Conselho -> {nota_bruta}/30 (estrutura={nota_a} qualidade={nota_b})",
            component="/scoring/conselho_administracao",
            severity="INFO",
        )
        return {
            "nota_bruta": nota_bruta,
            "nota_ponderada": nota_bruta,
            "max_bruta": 30,
            "detalhes": {"estrutura": nota_a, "qualidade_diversidade": nota_b},
        }

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/scoring/conselho_administracao", severity="CRITICAL")
        raise


def calcular_diretoria(dados: dict) -> dict:
    """Calcula nota do bloco Diretoria (max: 20)."""
    try:
        # (A) Qualidade e diversidade (nota subjetiva 1–5) → 2/4/6/8/10 pts
        qualidade = int(dados.get("qualidade_diretoria", 1))
        nota_a = config.NOTAS_QUALIDADE_DIRETORIA.get(qualidade, 2)

        # (B) % Remuneração Fixa da Diretoria (< 50% → 2pts)
        # ATENÇÃO: usar 2ª ocorrência na planilha (parser usa campo_nth n=1)
        pct_rem_fixa = float(dados.get("pct_rem_fixa_diretoria", 1.0) or 1.0)
        nota_b = config.NOTAS_REM_FIXA["abaixo_50"] if pct_rem_fixa < 0.50 else config.NOTAS_REM_FIXA["acima_50"]

        # (C) Transparência remuneração variável CP
        transparencia = dados.get("transparencia_rem_variavel", "Não")
        nota_c = config.NOTAS_TRANSPARENCIA_REM.get(transparencia, 0)

        # (D) Práticas contábeis agressivas
        praticas = dados.get("praticas_contabeis_agressivas", "Não")
        nota_d = config.NOTAS_PRATICAS_CONTABEIS.get(praticas, 0)

        # (E) Contingências relevantes
        contingencias = dados.get("contingencias_relevantes", "Não")
        nota_e = config.NOTAS_CONTINGENCIAS.get(contingencias, 0)

        # (F) Relatório de sustentabilidade
        sustentabilidade = dados.get("relatorio_sustentabilidade", "Não")
        nota_f = config.NOTAS_SUSTENTABILIDADE.get(sustentabilidade, 0)

        nota_bruta = nota_a + nota_b + nota_c + nota_d + nota_e + nota_f
        # max = 10+2+2+2+2+2 = 20 = peso do bloco → sem normalização
        custom_log(
            msg=f"Diretoria -> {nota_bruta}/20 (A={nota_a} B={nota_b} C={nota_c} D={nota_d} E={nota_e} F={nota_f})",
            component="/scoring/diretoria",
            severity="INFO",
        )
        return {
            "nota_bruta": nota_bruta,
            "nota_ponderada": nota_bruta,
            "max_bruta": 20,
            "detalhes": {"qualidade": nota_a, "rem_fixa": nota_b, "transparencia_rem": nota_c, "praticas_contabeis": nota_d, "contingencias": nota_e, "sustentabilidade": nota_f},
        }

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/scoring/diretoria", severity="CRITICAL")
        raise


def calcular_nota_governanca(dados: dict) -> dict:
    """
    Calcula a nota consolidada de governança corporativa (0–100).

    Args:
        dados: dict com todos os campos da empresa.

    Returns:
        dict com nota_final, detalhamento por bloco e empresa.
    """
    try:
        empresa = dados.get("empresa", "N/A")
        custom_log(msg=f"Iniciando cálculo de governança para: {empresa}", component="/scoring/calcular_nota_governanca", severity="INFO")

        blocos = {
            "segmento_listagem": calcular_segmento_listagem(dados),
            "direitos_acionistas": calcular_direitos_acionistas(dados),
            "estrutura_acionaria": calcular_estrutura_acionaria(dados),
            "conselho_administracao": calcular_conselho_administracao(dados),
            "diretoria": calcular_diretoria(dados),
        }

        nota_final = sum(b["nota_ponderada"] for b in blocos.values())

        resultado = {
            "empresa": empresa,
            "nota_final": round(nota_final, 1),
            "blocos": {
                nome: {
                    "nota_bruta": b["nota_bruta"],
                    "max_bruta": b["max_bruta"],
                    "nota_ponderada": round(b["nota_ponderada"], 2),
                    "peso_bloco": config.PESOS_BLOCOS[nome],
                    **({"detalhes": b["detalhes"]} if "detalhes" in b else {}),
                }
                for nome, b in blocos.items()
            },
        }

        custom_log(msg=f"Nota final de governança para {empresa}: {nota_final:.1f}/100", component="/scoring/calcular_nota_governanca", severity="INFO")
        return resultado

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/scoring/calcular_nota_governanca", severity="CRITICAL")
        raise
