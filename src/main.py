# src/main.py
# Entrypoint: carrega a planilha, calcula notas e exibe ranking.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import traceback
from src.parser_planilha import extrair_todas_empresas
from src.scoring_engine import calcular_nota_governanca
from src.utils.logging_utils import custom_log


def rodar_avaliacao(path_planilha: str = None) -> list[dict]:
    try:
        custom_log(msg="Iniciando pipeline de avaliação de governança", component="/main/rodar_avaliacao", severity="INFO")
        empresas = extrair_todas_empresas(path_planilha)
        resultados = [calcular_nota_governanca(d) for d in empresas]
        resultados.sort(key=lambda r: r["nota_final"], reverse=True)
        custom_log(msg=f"Avaliação concluída. {len(resultados)} empresas processadas.", component="/main/rodar_avaliacao", severity="INFO")
        return resultados
    except Exception as e:
        custom_log(msg=traceback.format_exc(), component="/main/rodar_avaliacao", severity="CRITICAL")
        raise


def imprimir_resumo(resultados: list[dict]):
    print("\n" + "=" * 65)
    print("  RANKING DE GOVERNANÇA CORPORATIVA")
    print("=" * 65)
    print(f"{'#':<4} {'Empresa':<20} {'Nota Final':>10}  {'SEG':>4} {'DIR':>4} {'EST':>4} {'CON':>4} {'DIT':>4}")
    print("-" * 65)
    for i, r in enumerate(resultados, 1):
        b = r["blocos"]
        print(
            f"{i:<4} {r['empresa']:<20} {r['nota_final']:>10.1f}  "
            f"{b['segmento_listagem']['nota_ponderada']:>4.0f} "
            f"{b['direitos_acionistas']['nota_ponderada']:>4.1f} "
            f"{b['estrutura_acionaria']['nota_ponderada']:>4.0f} "
            f"{b['conselho_administracao']['nota_ponderada']:>4.0f} "
            f"{b['diretoria']['nota_ponderada']:>4.0f}"
        )
    print("=" * 65)
    print("Blocos: SEG=Segmento  DIR=Direitos  EST=Estrutura  CON=Conselho  DIT=Diretoria")
    print()


if __name__ == "__main__":
    resultados = rodar_avaliacao()
    imprimir_resumo(resultados)
