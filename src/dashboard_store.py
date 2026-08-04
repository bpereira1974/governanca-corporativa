"""Persiste os resultados de analises de FRE processadas pelo dashboard.

Fase 1: armazenamento em um arquivo JSON local (data/dashboard_store.json).
Quando o modulo de BigQuery/CVM estiver pronto, este armazenamento pode ser
trocado por um banco de dados sem alterar a interface (load_companies /
save_company / delete_company).
"""
import json
import os
import traceback

from src.utils.logging_utils import custom_log

STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dashboard_store.json"
)


def load_companies():
    try:
        if not os.path.exists(STORE_PATH):
            return {}
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/dashboard_store/load_companies",
            severity="ERROR",
        )
        return {}


def save_company(nome, resultado):
    try:
        companies = load_companies()
        companies[nome] = resultado
        os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(companies, f, ensure_ascii=False, indent=2)
        custom_log(
            msg=f"Empresa '{nome}' salva no dashboard store",
            component="/dashboard_store/save_company",
            severity="INFO",
        )
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/dashboard_store/save_company",
            severity="CRITICAL",
        )
        raise


def delete_company(nome):
    try:
        companies = load_companies()
        if nome in companies:
            del companies[nome]
            with open(STORE_PATH, "w", encoding="utf-8") as f:
                json.dump(companies, f, ensure_ascii=False, indent=2)
            custom_log(
                msg=f"Empresa '{nome}' removida do dashboard store",
                component="/dashboard_store/delete_company",
                severity="INFO",
            )
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/dashboard_store/delete_company",
            severity="CRITICAL",
        )
        raise
