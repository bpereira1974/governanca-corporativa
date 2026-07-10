"""Extrai a estrutura de administracao (capitulo 7 do FRE) a partir do PDF do
Formulario de Referencia, para uso enquanto o mapeamento via CSV/BigQuery da CVM
nao esta consolidado. Usa pdfplumber (puro Python, sem dependencia de binario
externo) para extrair o texto e regex para parsear os blocos repetidos do
formulario.
"""
import re
import traceback

import pdfplumber

from utils.logging_utils import custom_log

_PAGE_FOOTER_RE = re.compile(r"P[ÁA]GINA:\s*\d+\s*de\s*\d+")
_HEADER_RE = re.compile(r"Formulário de Referência.*?Versão\s*:\s*\d+\s*\n?")

_MEMBER_START_RE = re.compile(
    r"Nome:?\s+(?P<nome>[A-ZÀ-Ü][A-ZÀ-Ü'\.\s]+?)\s+CPF:\s*(?P<cpf>[\d\.\-/]+)"
)


def _clean_text(text):
    text = _PAGE_FOOTER_RE.sub("", text)
    text = _HEADER_RE.sub("", text)
    return text


def extract_section_text(pdf_path, page_start, page_end):
    """Extrai e concatena o texto (layout preservado) de um intervalo de paginas.

    page_start/page_end sao 1-indexados e inclusivos, no numero de pagina do
    arquivo PDF (nao o numero impresso "PÁGINA: X de Y").
    """
    try:
        chunks = []
        with pdfplumber.open(pdf_path) as pdf:
            for i in range(page_start - 1, min(page_end, len(pdf.pages))):
                page_text = pdf.pages[i].extract_text(layout=True) or ""
                chunks.append(page_text)
        custom_log(
            msg=f"Extraidas paginas {page_start}-{page_end} de {pdf_path}",
            component="/fre_pdf_parser/extract_section_text",
            severity="INFO",
        )
        return _clean_text("\n".join(chunks))
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/fre_pdf_parser/extract_section_text",
            severity="CRITICAL",
        )
        raise


def _field(pattern, block, default=None):
    match = re.search(pattern, block, re.DOTALL)
    return match.group(1).strip() if match else default


def _split_member_blocks(text):
    starts = list(_MEMBER_START_RE.finditer(text))
    blocks = []
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        blocks.append((match, text[match.start():end]))
    return blocks


# pdfplumber preserva o layout fisico linha a linha: quando uma celula da
# tabela quebra em varias linhas, cada linha fisica contem fragmentos de TODAS
# as colunas daquele "andar" da linha, entao juntar tudo numa string so
# intercala palavras de colunas diferentes (ex: "Conselho de" da coluna 1 e
# "Administração" da coluna 1 ficam separadas por conteudo de outras colunas).
# Por isso o parsing abaixo ancora no INICIO DE LINHA (sem colapsar \n) e usa
# o primeiro fragmento da coluna "Órgão da Administração" pra identificar o
# orgao, em vez de tentar casar a frase completa.
_ORGAO_ROW_START_RE = re.compile(
    r"^\s*(?P<first>Conselho de|Conselho|Diretoria)\s+\d{2}/\d{2}/\d{4}",
    re.MULTILINE,
)


def _parse_orgaos(block):
    """Extrai as linhas da tabela 'Orgaos da Administracao' de um bloco de membro.

    Cada membro normalmente ocupa 1 linha nessa tabela. Identificamos o inicio
    de cada linha pelo primeiro fragmento de coluna (que sempre cabe na 1a
    linha fisica, junto com a 1a data), e desambiguamos "Conselho" (que pode
    ser "Conselho de Administração" ou "Conselho Fiscal") olhando a proxima
    linha fisica em busca de "Fiscal" vs "Administração"/"de".
    """
    section = _field(
        r"Órgãos da Administração:(.*?)(?:Condenações:|\Z)", block
    )
    if not section:
        return []

    row_matches = list(_ORGAO_ROW_START_RE.finditer(section))
    orgaos = []
    for i, m in enumerate(row_matches):
        end = row_matches[i + 1].start() if i + 1 < len(row_matches) else len(section)
        row_text = section[m.start():end]
        lines = [l for l in row_text.split("\n") if l.strip()]

        first = m.group("first")
        if first == "Diretoria":
            orgao = "Diretoria"
        elif first == "Conselho de":
            orgao = "Conselho de Administração"
        else:  # "Conselho" sozinho: olhar a 2a linha fisica
            second_line = lines[1] if len(lines) > 1 else ""
            orgao = "Conselho Fiscal" if "Fiscal" in second_line else "Conselho de Administração"

        dates = re.findall(r"\d{2}/\d{2}/\d{4}", row_text)
        eleito_pelo_controlador = _field(r"\b(Sim|Não)\b", row_text)
        cargo_hint = None
        if "C.F." in row_text or "C.F.(" in row_text:
            cargo_hint = _field(r"(C\.F\.\S*)", row_text)
        elif "Presidente do" in row_text:
            cargo_hint = "Presidente do Conselho de Administração"
        elif "Conselho de Adm" in row_text:
            cargo_hint = _field(r"(Conselho de Adm\.\s*\S*\s*\(\w+\))", row_text)
        elif "Outros Diretores" in row_text:
            cargo_hint = "Outros Diretores"
        elif "Diretor" in row_text:
            cargo_hint = _field(r"(Diretor\S*(?:\s*/\s*\S+)*)", row_text)

        orgaos.append(
            {
                "orgao": orgao,
                "cargo_eletivo_ocupado": cargo_hint,
                "data_eleicao": dates[0] if dates else None,
                "data_posse": dates[-2] if len(dates) >= 2 else None,
                "data_inicio_primeiro_mandato": dates[-1] if dates else None,
                "foi_eleito_pelo_controlador": eleito_pelo_controlador,
                "raw": " ".join(row_text.split()),
            }
        )
    return orgaos


_COMITE_ROW_START_RE = re.compile(r"^\s*Outros\s+Comitês\b", re.MULTILINE)

# sinal robusto a quebra de linha/coluna de que a linha do "Comite de
# Auditoria Estatuario" esta presente: essa frase (que identifica o tipo
# "Comite de Auditoria") quebra de forma imprevisivel entre colunas vizinhas
# (a coluna "Tipo auditoria" tambem comeca com "Comite de"), entao
# detectamos pela descricao do regime regulatorio, que e' um texto fixo.
_COMITE_AUDITORIA_SIGNAL_RE = re.compile(r"Resolução\s+CVM|Estatut[áa]rio", re.IGNORECASE)

# nomes dos comites de assessoramento, conforme enumerados na secao 7.2 do FRE
# (usado para reconhecer o comite especifico quando tipo_comite = "Outros Comitês")
KNOWN_COMMITTEE_NAMES = [
    "Comitê de Pessoas e Sustentabilidade",
    "Comitê de Estratégia e Finanças",
]


def _cargo_from_text(text):
    if "Coordenador" in text:
        return "Coordenador"
    if "Secretári" in text:
        return "Secretário"
    if "Membro" in text or "(Efetivo)" in text:
        return "Membro"
    return "Outros"


def _parse_comites(block, known_committee_names=KNOWN_COMMITTEE_NAMES):
    """Parseia a tabela 'Comitês' de um bloco de membro (secao 7.4).

    A coluna 'Tipo comitê' e a coluna vizinha 'Tipo auditoria' comecam ambas
    com "Comitê de", entao a linha do Comitê de Auditoria Estatutario nao da'
    pra ancorar de forma confiavel por posicao de linha (ao contrario de
    "Outros Comitês", que e' uma frase curta que nao quebra e nao se repete
    em coluna vizinha). Por isso ela e' tratada separadamente: assumimos que,
    quando presente, ela e' sempre a 1a linha da tabela (e' assim em todos os
    membros observados no FRE da Cyrela) e a identificamos pelo texto fixo do
    regime regulatorio ("Resolução CVM", "Estatutário"), nao pelo cabecalho
    da coluna em si.
    """
    section = _field(r"Comitês:(.*?)(?:Condenações:|\Z)", block)
    if not section:
        return []

    outros_matches = list(_COMITE_ROW_START_RE.finditer(section))
    first_outros_start = outros_matches[0].start() if outros_matches else len(section)

    comites = []

    auditoria_chunk = section[:first_outros_start]
    if _COMITE_AUDITORIA_SIGNAL_RE.search(auditoria_chunk):
        dates = re.findall(r"\d{2}/\d{2}/\d{4}", auditoria_chunk)
        comites.append(
            {
                "tipo_comite": "Comitê de Auditoria",
                "comite_especifico": "Comitê de Auditoria Estatutário",
                "cargo_ocupado": _cargo_from_text(auditoria_chunk),
                "data_posse": dates[0] if dates else None,
                "data_inicio_primeiro_mandato": dates[-1] if dates else None,
                "raw": " ".join(auditoria_chunk.split()),
            }
        )

    for i, m in enumerate(outros_matches):
        end = outros_matches[i + 1].start() if i + 1 < len(outros_matches) else len(section)
        row_text = section[m.start():end]
        row_norm = " ".join(row_text.split())
        dates = re.findall(r"\d{2}/\d{2}/\d{4}", row_text)

        comite_especifico = None
        for name in known_committee_names:
            # o nome do comite fica espalhado em ate 2 palavras por linha;
            # comparamos por palavras-chave em vez da frase inteira
            keywords = name.replace("Comitê de ", "").split(" e ")
            if all(kw.strip() in row_norm for kw in keywords):
                comite_especifico = name
                break

        comites.append(
            {
                "tipo_comite": "Outros Comitês",
                "comite_especifico": comite_especifico,
                "cargo_ocupado": _cargo_from_text(row_text),
                "data_posse": dates[0] if dates else None,
                "data_inicio_primeiro_mandato": dates[-1] if dates else None,
                "raw": row_norm,
            }
        )
    return comites


def parse_members(text, include_comites=False):
    """Parseia os blocos de membros da secao 7.3 (ou 7.4, se include_comites).

    Retorna uma lista de dicts, um por membro, com dados pessoais, experiencia
    profissional (texto bruto) e a lista de orgaos (ou comites) ocupados.
    """
    members = []
    for match, block in _split_member_blocks(text):
        nome = " ".join(match.group("nome").split())
        cpf = match.group("cpf").strip()

        experiencia = _field(
            r"Experiência Profissional:(.*?)(?:Órgãos da Administração:|Comitês:|\Z)",
            block,
        )
        if experiencia:
            # remove os paragrafos-padrao de declaracao (nao sao curriculo)
            experiencia = re.split(r"O\s+(?:Sr|Sra)\.[^\n]*declarou que:", experiencia)[0]
            experiencia = " ".join(experiencia.split())

        member = {
            "nome": nome,
            "cpf": cpf,
            "nacionalidade": _field(r"Nacionalidade:\s*(\S+)", block),
            "data_nascimento": _field(r"Nascimento:\s*(\d{2}/\d{2}/\d{4})", block),
            "profissao": _field(r"Profis[sã]?[ãa]?o?:?\s*(.*?)\s*Data\s*\n?\s*de\s*\n?\s*Nascimento", block),
            "experiencia_profissional": experiencia,
        }
        if include_comites:
            member["comites"] = _parse_comites(block)
        else:
            member["orgaos"] = _parse_orgaos(block)
        members.append(member)
    return members


def parse_7_1d_counts(text):
    """Parseia a tabela 7.1D de contagem de membros por orgao e genero.

    Retorna dict {orgao: {"feminino": int, "masculino": int, "total": int}}.
    """
    section = _field(
        r"7\.1D.*?Quantidade de membros por declaração de gênero(.*?)Quantidade de membros por declaração de cor",
        text,
    )
    if not section:
        return {}

    counts = {}
    for orgao_label in [
        r"Diretoria",
        r"Conselho de Administração - Efetivos",
        r"Conselho de Administração -\s*\n?\s*Suplentes",
        r"Conselho Fiscal - Efetivos",
        r"Conselho Fiscal - Suplentes",
    ]:
        m = re.search(
            rf"{orgao_label}\s+((?:\d+|Não se aplica)\s+(?:\d+|Não se aplica))", section
        )
        if m:
            nums = re.findall(r"\d+", m.group(1))
            if len(nums) >= 2:
                counts[re.sub(r"[\\\s]+", " ", orgao_label).strip()] = {
                    "feminino": int(nums[0]),
                    "masculino": int(nums[1]),
                    "total": int(nums[0]) + int(nums[1]),
                }
    return counts


def parse_administration_structure(pdf_path, page_start, page_end):
    """Funcao de conveniencia: extrai e parseia 7.1D + 7.3 + 7.4 de uma vez.

    page_start/page_end devem cobrir pelo menos as secoes 7.1 a 7.4 do FRE
    (no exemplo da Cyrela FRE 2026 v4, paginas 121-165 do arquivo).
    """
    try:
        text = extract_section_text(pdf_path, page_start, page_end)

        secao_73 = _field(
            r"7\.3 Composição e experiências profissionais(.*?)(?:7\.4 Composição dos comitês|\Z)",
            text,
        ) or ""
        secao_74 = _field(r"7\.4 Composição dos comitês(.*)", text) or ""

        result = {
            "contagem_por_orgao": parse_7_1d_counts(text),
            "membros": parse_members(secao_73, include_comites=False),
            "membros_comites": parse_members(secao_74, include_comites=True) if secao_74 else [],
        }

        n_conselho = sum(
            1 for m in result["membros"]
            for o in m["orgaos"]
            if o["orgao"] == "Conselho de Administração"
        )
        n_diretoria = sum(
            1 for m in result["membros"]
            for o in m["orgaos"]
            if o["orgao"] == "Diretoria"
        )
        comites_unicos = {
            c["comite_especifico"] or c["tipo_comite"]
            for m in result["membros_comites"]
            for c in m["comites"]
        }

        result["resumo"] = {
            "n_membros_conselho_administracao": n_conselho,
            "n_membros_diretoria": n_diretoria,
            "n_comites": len(comites_unicos),
            "comites": sorted(comites_unicos),
        }

        custom_log(
            msg=f"Estrutura de administracao parseada: {result['resumo']}",
            component="/fre_pdf_parser/parse_administration_structure",
            severity="INFO",
        )
        return result
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/fre_pdf_parser/parse_administration_structure",
            severity="CRITICAL",
        )
        raise
