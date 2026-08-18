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

    aba_conselho, aba_diretoria, aba_comites = st.tabs(["Conselho de Administração", "Diretoria", "Comitês"])
    with aba_conselho:
        _render_tabela_orgao(dados["membros"], "Conselho de Administração")
    with aba_diretoria:
        _render_tabela_orgao(dados["membros"], "Diretoria")
    with aba_comites:
        if resumo["comites"]:
            st.write("Comitês identificados: " + ", ".join(resumo["comites"]))
        _render_tabela_comites(dados["membros_comites"])

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
