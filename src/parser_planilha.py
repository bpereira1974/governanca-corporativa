# src/parser_planilha.py
# Lê a planilha Template_Governança.xlsx e extrai os dados de cada empresa
# para o formato esperado pelo scoring_engine.

import traceback
import pandas as pd
from configs import config
from src.utils.logging_utils import custom_log


def _normalizar_bool(valor) -> bool:
    if pd.isna(valor):
        return False
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ("sim", "true", "1", "s")


def _normalizar_str(valor) -> str:
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def _normalizar_float(valor, default=0.0) -> float:
    try:
        if pd.isna(valor):
            return default
        return float(valor)
    except (TypeError, ValueError):
        return default


def _extrair_empresa(nome_empresa: str, df: pd.DataFrame, empresas: list) -> dict:
    try:
        if nome_empresa not in empresas:
            raise ValueError(f"Empresa '{nome_empresa}' não encontrada na planilha.")

        col = nome_empresa

        def campo(label: str):
            try:
                linha = df[df.iloc[:, 0] == label]
                if linha.empty:
                    return None
                return linha[col].values[0]
            except Exception:
                return None

        def campo_nth(label: str, n: int = 0):
            """Busca a n-ésima ocorrência de um label (0-indexed)."""
            try:
                linhas = df[df.iloc[:, 0] == label]
                if linhas.empty or n >= len(linhas):
                    return None
                return linhas.iloc[n][col]
            except Exception:
                return None

        dados = {
            "empresa": nome_empresa,

            # Segmento de Listagem
            "segmento_listagem": _normalizar_str(campo("Segmento de Listagem")),
            "comentario_segmento": _normalizar_str(campo("Comentário")),

            # Direitos dos Acionistas
            "conselho_fiscal_permanente": _normalizar_bool(campo("Conselho Fiscal permanente")),
            "conselho_fiscal_instalado": _normalizar_bool(campo("CF instalado (se CF permanente, preencher com \"N/A\"")),
            "poison_pill": _normalizar_bool(campo("Cláusula de Poison Pill")),
            "poison_pill_threshold": _normalizar_float(campo("Participação que aciona PP")),
            "limite_voto": _normalizar_bool(campo("Limitação de direito de voto ou participação")),
            "limite_dividendo": _normalizar_bool(campo("Limitação a distribuição de dividendos")),

            # Estrutura Acionária
            "natureza_estrutura": _normalizar_str(campo("Natureza da Estrutura acionária")),
            "participacao_controlador": campo("Participação do controlador no capital total"),
            "visao_controlador": _normalizar_str(campo("Visão sobre o acionista controlador (Positiva, Negativa ou Mixed)")),
            "insiders_ownership": _normalizar_float(campo("% de Insiders Ownership")),
            "potencial_conflito": _normalizar_str(campo("Potencial conflito de interesses")),
            "transacoes_partes_relacionadas": _normalizar_str(campo("Transações com partes relacionadas relevantes")),

            # Conselho de Administração
            "n_membros_conselho": int(_normalizar_float(campo("Número de membros no Conselho"), default=0)),
            "qualidade_conselho": int(_normalizar_float(campo("Avaliação da qualidade e diversidade do conselho (Nota)"), default=1)),

            # Diretoria — usa 2ª ocorrência de '% Remuneração Fixa / Total' (n=1)
            # A 1ª ocorrência (n=0) é do Conselho de Administração
            "qualidade_diretoria": int(_normalizar_float(campo("Avaliação da diversidade e qualidade da Diretoria (Nota)"), default=1)),
            "pct_rem_fixa_diretoria": _normalizar_float(campo_nth("% Remuneração Fixa / Total", n=1)),
            "transparencia_rem_variavel": _normalizar_str(campo("A Companhia é transparente ref remuneração variável de CP")),
            "praticas_contabeis_agressivas": _normalizar_str(campo("Companhia tem práticas contábeis agressivas ou é pouco transparente em relação a transações relevantes para o entendimento do negócio??")),
            "contingencias_relevantes": _normalizar_str(campo("Companhia possui número elevado de contingências tributárias e/ou cíveis")),
            "relatorio_sustentabilidade": _normalizar_str(campo("Empresa divulga Relatório de Sustentabilidade")),
        }

        custom_log(msg=f"Dados extraídos da planilha para empresa: {nome_empresa}", component="/parser/extrair_empresa", severity="INFO")
        return dados

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/parser/extrair_empresa", severity="CRITICAL")
        raise


def carregar_planilha(path: str = None) -> tuple[pd.DataFrame, list]:
    try:
        caminho = path or config.TEMPLATE_PATH
        df_raw = pd.read_excel(caminho, sheet_name="Relatório Governança", header=None)

        # Header com 'Empresa' está na linha 3 (índice 3)
        header_row_idx = None
        for i, row in df_raw.iterrows():
            if str(row.iloc[0]).strip() == "Empresa":
                header_row_idx = i
                break

        if header_row_idx is None:
            raise ValueError("Linha de cabeçalho com 'Empresa' não encontrada na planilha.")

        colunas_raw = df_raw.iloc[header_row_idx].tolist()
        empresas = [str(e).strip() for e in colunas_raw[1:] if not pd.isna(e) and str(e).strip() not in ("", "nan")]

        df = df_raw.iloc[header_row_idx:].copy()
        df.columns = [str(c).strip() if not pd.isna(c) else f"col_{i}" for i, c in enumerate(df.iloc[0])]
        df = df[1:].reset_index(drop=True)

        custom_log(msg=f"Planilha carregada. Empresas encontradas: {empresas}", component="/parser/carregar_planilha", severity="INFO")
        return df, empresas

    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/parser/carregar_planilha", severity="CRITICAL")
        raise


def extrair_todas_empresas(path: str = None) -> list[dict]:
    df, empresas = carregar_planilha(path)
    resultado = []
    for empresa in empresas:
        try:
            dados = _extrair_empresa(empresa, df, empresas)
            resultado.append(dados)
        except Exception:
            custom_log(msg=f"Falha ao extrair empresa '{empresa}' — pulando.", component="/parser/extrair_todas_empresas", severity="WARNING")
    return resultado
