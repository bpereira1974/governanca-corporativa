# src/dashboard_app.py
# Dashboard interativo: upload de FRE em PDF, parsing ao vivo da estrutura
# de administracao (Conselho/Diretoria/Comites), e visualizacao das empresas
# ja processadas. Rodar com: streamlit run src/dashboard_app.py

import sys
import os
import tempfile
import traceback
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from src.fre_pdf_parser import (
    find_chapter7_page_range,
    parse_administration_structure,
    extract_company_name,
    parse_remuneracao_qualitativa,
    parse_remuneracao_valores,
    parse_remuneracao_extremos,
    parse_principais_fatores_risco,
)
from src.dashboard_store import load_companies, save_company, delete_company
from src.utils.logging_utils import custom_log


def _tempo_no_cargo(data_str):
    if not data_str:
        return "N/D"
    try:
        d, m, y = (int(p) for p in data_str.split("/"))
        inicio = date(y, m, d)
    except (ValueError, TypeError):
        return "N/D"
    dias = (date.today() - inicio).days
    if dias < 0:
        return "N/D"
    anos, resto_dias = divmod(dias, 365)
    meses = resto_dias // 30
    if anos == 0:
        return f"{meses}m"
    return f"{anos}a {meses}m" if meses else f"{anos}a"


def _processar_upload(uploaded_file, nome_empresa):
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        page_start, page_end = find_chapter7_page_range(tmp_path)
        resultado = parse_administration_structure(tmp_path, page_start, page_end)
        resultado["_meta"] = {
            "empresa": nome_empresa,
            "arquivo_original": uploaded_file.name,
            "paginas_capitulo_7": [page_start, page_end],
        }

        try:
            resultado["remuneracao"] = parse_remuneracao_qualitativa(tmp_path)
        except Exception as e:
            # a secao de remuneracao e' um bonus sobre o resultado principal
            # (composicao do Conselho/Diretoria) — se ela falhar (ex: FRE com
            # numeracao atipica), nao queremos perder o resto do processamento
            custom_log(
                msg=traceback.format_exception(e),
                component="/dashboard_app/_processar_upload",
                severity="WARNING",
            )
            resultado["remuneracao"] = None

        try:
            resultado["remuneracao_valores"] = parse_remuneracao_valores(tmp_path)
        except Exception as e:
            custom_log(
                msg=traceback.format_exception(e),
                component="/dashboard_app/_processar_upload",
                severity="WARNING",
            )
            resultado["remuneracao_valores"] = None

        try:
            resultado["remuneracao_extremos"] = parse_remuneracao_extremos(tmp_path)
        except Exception as e:
            custom_log(
                msg=traceback.format_exception(e),
                component="/dashboard_app/_processar_upload",
                severity="WARNING",
            )
            resultado["remuneracao_extremos"] = None

        try:
            resultado["fatores_risco"] = parse_principais_fatores_risco(tmp_path)
        except Exception as e:
            custom_log(
                msg=traceback.format_exception(e),
                component="/dashboard_app/_processar_upload",
                severity="WARNING",
            )
            resultado["fatores_risco"] = None

        save_company(nome_empresa, resultado)
        return resultado
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/dashboard_app/_processar_upload",
            severity="ERROR",
        )
        raise
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def _render_tabela_orgao(membros, filtro_orgao):
    linhas = []
    pessoas = []
    for m in membros:
        for o in m["orgaos"]:
            if filtro_orgao in o["orgao"]:
                linhas.append(
                    {
                        "Nome": m["nome"],
                        "Cargo": o["cargo_eletivo_ocupado"] or "—",
                        "Início 1º mandato": o["data_inicio_primeiro_mandato"] or "N/D",
                        "Tempo no cargo": _tempo_no_cargo(o["data_inicio_primeiro_mandato"]),
                    }
                )
                pessoas.append((m, o["cargo_eletivo_ocupado"]))
                break
    linhas.sort(key=lambda r: r["Nome"])
    st.dataframe(linhas, width='stretch', hide_index=True)
    _render_curriculos(pessoas)


def _render_curriculos(pessoas):
    pessoas = sorted(pessoas, key=lambda p: p[0]["nome"])
    st.markdown("**Mini currículos**")
    for membro, cargo in pessoas:
        titulo = membro["nome"]
        if cargo:
            titulo += f" — {cargo}"
        with st.expander(titulo):
            if membro.get("profissao"):
                st.caption(membro["profissao"])
            st.write(membro.get("experiencia_profissional") or "Currículo não disponível no FRE.")


_ORGAOS_REMUNERACAO_LABELS = {
    "conselho_administracao": "Conselho de Administração",
    "diretoria_estatutaria": "Diretoria Estatutária",
}


def _linha_composicao(orgao_dados):
    # .get(..., 0.0) em vez de indexacao direta: um rotulo pode nao ter
    # sido reconhecido pro parser (ex: layout de tabela atipico numa
    # empresa nova) sem que isso quebre o calculo dos demais campos
    g = lambda campo: orgao_dados.get(campo) or 0.0
    fixo = g("salario_pro_labore") + g("beneficios") + g("participacoes_comites") + g("outros_fixo")
    variavel_curto = (
        g("bonus") + g("participacao_resultados") + g("participacao_reunioes") + g("comissoes") + g("outros_variavel")
    )
    variavel_longo = g("baseada_acoes")
    total = orgao_dados.get("total_remuneracao")
    n_remunerados = orgao_dados.get("n_membros_remunerados")
    per_capita = (total / n_remunerados) if total and n_remunerados else None
    return fixo, variavel_curto, variavel_longo, total, n_remunerados, per_capita


def _render_remuneracao_valores(exercicios):
    if not exercicios:
        st.info(
            "Não foi possível localizar/extrair a tabela de valores de remuneração "
            "(seção 8.2) deste FRE."
        )
        return

    for chave_orgao, label_orgao in _ORGAOS_REMUNERACAO_LABELS.items():
        st.markdown(f"**{label_orgao}**")
        linhas_pct = []
        linhas_valores = []
        for ex in exercicios:
            orgao_dados = ex.get(chave_orgao)
            if not orgao_dados:
                continue
            fixo, var_curto, var_longo, total, n_remunerados, per_capita = _linha_composicao(orgao_dados)
            ano = ex["data_referencia"]
            if total:
                linhas_pct.append(
                    {
                        "Exercício": ano,
                        "Fixa": f"{fixo / total:.1%}",
                        "Variável curto prazo": f"{var_curto / total:.1%}",
                        "Variável longo prazo (ações)": f"{var_longo / total:.1%}",
                    }
                )
            linhas_valores.append(
                {
                    "Exercício": ano,
                    "Fixa (R$)": fixo,
                    "Variável curto prazo (R$)": var_curto,
                    "Variável longo prazo (R$)": var_longo,
                    "Total (R$)": total,
                    "Nº remunerados": n_remunerados,
                    "Per capita (R$)": round(per_capita, 2) if per_capita else None,
                }
            )
        if linhas_pct:
            st.caption("(a) Composição % da remuneração total")
            st.dataframe(linhas_pct, width="stretch", hide_index=True)
        if linhas_valores:
            st.caption("(b) Valores efetivos (R$) e per capita")
            st.dataframe(linhas_valores, width="stretch", hide_index=True)


def _render_remuneracao_extremos(extremos):
    if not extremos:
        st.info(
            "Não foi possível localizar/extrair a tabela de maior/menor/média "
            "remuneração (seção 8.15) deste FRE."
        )
        return

    for chave_orgao, label_orgao in _ORGAOS_REMUNERACAO_LABELS.items():
        anos = extremos.get(chave_orgao)
        if not anos:
            continue
        st.markdown(f"**{label_orgao}**")
        linhas = [
            {
                "Exercício": a["ano"],
                "Maior remuneração (R$)": a["maior"],
                "Menor remuneração (R$)": a["menor"],
                "Média (R$)": a["media"],
                "Razão maior/menor": a["razao_maior_menor"],
                "Nº remunerados": a["n_membros_remunerados"],
            }
            for a in anos
        ]
        st.dataframe(linhas, width="stretch", hide_index=True)


def _render_fatores_risco(fatores_risco):
    st.markdown("### 5 principais fatores de risco")
    st.caption(
        "Extraído diretamente da seção 4.2 do FRE (a própria Companhia escolhe e ordena "
        "esses 5 dentre a lista mais ampla da seção 4.1)."
    )
    if not fatores_risco:
        st.info(
            "Não foi possível localizar/extrair a seção 4.2 (principais fatores de risco) "
            "deste FRE."
        )
    else:
        for item in fatores_risco:
            st.markdown(f"**{item['numero']}.** {item['descricao']}")

    st.divider()
    st.markdown("### Contingências (processos judiciais/administrativos)")
    st.info(
        "Ainda não implementado — pendente de um FRE com contingências relevantes "
        "reportadas (a Cyrela, única testada até agora, não tinha nenhuma na data-base "
        "deste documento) para validar a estrutura real antes de escrever a extração."
    )


def _render_remuneracao(remuneracao, remuneracao_valores, remuneracao_extremos):
    st.markdown("### Valores quantitativos")
    _render_remuneracao_valores(remuneracao_valores)

    st.divider()
    st.markdown("### Maior x menor remuneração individual")
    st.caption(
        "Razão maior/menor como indicador de dispersão da remuneração dentro do órgão "
        "(seção 8.15 do FRE)."
    )
    _render_remuneracao_extremos(remuneracao_extremos)

    st.divider()
    st.markdown("### Aspectos qualitativos")

    if not remuneracao:
        st.info(
            "Não foi possível localizar/extrair a seção de remuneração (capítulo 8) "
            "deste FRE — empresa processada antes dessa funcionalidade existir, ou "
            "o PDF tem uma numeração de seção atípica."
        )
        return

    st.caption(
        "Extração automática por palavra-chave a partir de texto corrido — "
        "confira o texto original antes de usar como resposta final."
    )

    longo = remuneracao["remuneracao_longo_prazo"]
    curto = remuneracao["remuneracao_curto_prazo_kpis"]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**(a) Remuneração de longo prazo**")
        if longo["possui_plano"]:
            tipos = ", ".join(longo["tipos_detectados"]) or "tipo não identificado por palavra-chave"
            st.success(f"SIM — indícios de plano vigente ({tipos})")
        else:
            st.error("NÃO — texto indica que não há plano vigente")
        with st.expander("Ver texto extraído (seção 8.4)"):
            st.write(longo["texto_secao_8_4"] or "Seção não encontrada.")

    with col2:
        st.markdown("**(b) Metas/indicadores na remuneração variável de curto prazo**")
        if curto["sinal_metas_indicadores"]:
            st.success("SIM — o texto menciona metas/indicadores de desempenho")
        else:
            st.warning("A CONFIRMAR — nenhuma palavra-chave de meta/indicador encontrada")
        with st.expander("Ver texto extraído (seção 8.1)"):
            st.write(curto["texto_secao_8_1"] or "Seção não encontrada.")


def _render_tabela_comites(membros_comites):
    linhas = []
    for m in membros_comites:
        for c in m["comites"]:
            linhas.append(
                {
                    "Comitê": c["comite_especifico"] or c["tipo_comite"],
                    "Nome": m["nome"],
                    "Cargo": c["cargo_ocupado"],
                    "No comitê desde": c["data_inicio_primeiro_mandato"] or "N/D",
                }
            )
    linhas.sort(key=lambda r: (r["Comitê"], r["Nome"]))
    st.dataframe(linhas, width='stretch', hide_index=True)


def main():
    st.set_page_config(page_title="Dashboard de Governança Corporativa", layout="wide")
    st.title("Dashboard de Governança Corporativa")
    st.caption("Composição do Conselho de Administração, Diretoria e Comitês, extraída direto do Formulário de Referência (CVM)")

    companies = load_companies()

    with st.sidebar:
        st.header("Empresas analisadas")
        if companies:
            nomes = sorted(companies.keys())
            selecionada = st.radio("Selecione uma empresa", nomes, label_visibility="collapsed")
        else:
            st.info("Nenhuma empresa processada ainda.")
            selecionada = None

        st.divider()
        st.header("Adicionar nova empresa")
        uploaded_file = st.file_uploader("PDF do Formulário de Referência (FRE)", type=["pdf"])

        nome_sugerido = ""
        if uploaded_file is not None:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path_sugestao = tmp.name
            nome_sugerido = extract_company_name(tmp_path_sugestao) or ""
            os.remove(tmp_path_sugestao)

        nome_empresa = st.text_input("Nome da empresa", value=nome_sugerido)

        if st.button("Processar FRE", disabled=uploaded_file is None or not nome_empresa.strip()):
            with st.spinner(f"Localizando e processando o capítulo 7 do FRE de {nome_empresa}..."):
                try:
                    _processar_upload(uploaded_file, nome_empresa.strip())
                    st.success(f"{nome_empresa} processada com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(
                        "Não foi possível processar este PDF. Verifique se é de fato "
                        "um Formulário de Referência da CVM. Detalhe técnico: "
                        f"{e}"
                    )

        if selecionada:
            st.divider()
            if st.button(f"Remover '{selecionada}'", type="secondary"):
                delete_company(selecionada)
                st.rerun()

    if not selecionada:
        st.info("Envie o PDF de um Formulário de Referência na barra lateral para começar.")
        return

    dados = companies[selecionada]
    resumo = dados["resumo"]

    st.header(selecionada)
    col1, col2, col3 = st.columns(3)
    col1.metric("Conselho de Administração", resumo["n_membros_conselho_administracao"])
    col2.metric("Diretoria", resumo["n_membros_diretoria"])
    col3.metric("Comitês de assessoramento", resumo["n_comites"])

    aba_conselho, aba_diretoria, aba_comites, aba_remuneracao, aba_riscos = st.tabs(
        ["Conselho de Administração", "Diretoria", "Comitês", "Remuneração", "Fatores de Risco"]
    )
    with aba_conselho:
        _render_tabela_orgao(dados["membros"], "Conselho de Administração")
    with aba_diretoria:
        _render_tabela_orgao(dados["membros"], "Diretoria")
    with aba_comites:
        if resumo["comites"]:
            st.write("Comitês identificados: " + ", ".join(resumo["comites"]))
        _render_tabela_comites(dados["membros_comites"])
    with aba_remuneracao:
        _render_remuneracao(
            dados.get("remuneracao"),
            dados.get("remuneracao_valores"),
            dados.get("remuneracao_extremos"),
        )
    with aba_riscos:
        _render_fatores_risco(dados.get("fatores_risco"))

    if len(companies) > 1:
        st.divider()
        st.subheader("Visão geral — todas as empresas")
        visao_geral = [
            {
                "Empresa": nome,
                "Conselho": c["resumo"]["n_membros_conselho_administracao"],
                "Diretoria": c["resumo"]["n_membros_diretoria"],
                "Comitês": c["resumo"]["n_comites"],
            }
            for nome, c in companies.items()
        ]
        st.dataframe(visao_geral, width='stretch', hide_index=True)


if __name__ == "__main__":
    main()
