"""Extrai a estrutura de administracao (capitulo 7 do FRE) a partir do PDF do
Formulario de Referencia, para uso enquanto o mapeamento via CSV/BigQuery da CVM
nao esta consolidado. Usa pdfplumber (puro Python, sem dependencia de binario
externo) para extrair o texto e regex para parsear os blocos repetidos do
formulario.
"""
import re
import traceback

import pdfplumber

from src.utils.logging_utils import custom_log

_PAGE_FOOTER_RE = re.compile(r"P[ÁA]GINA:\s*\d+\s*de\s*\d+")
_HEADER_RE = re.compile(r"Formulário de Referência.*?Versão\s*:\s*\d+\s*\n?")

_MEMBER_START_RE = re.compile(
    r"Nome:?\s+(?P<nome>[A-ZÀ-Ü][A-ZÀ-Ü'\.\s]+?)\s+CPF:\s*(?P<cpf>[\d\.\-/]+)"
)

_COMPANY_NAME_RE = re.compile(
    r"Formulário de Referência\s*-?\s*(?:\d{2}/\d{2}/)?\d{4}\s*-\s*(.+?)\s*Versão\s*:",
    re.IGNORECASE,
)


def extract_company_name(pdf_path):
    """Extrai o nome da companhia do cabecalho repetido em todas as paginas
    do FRE (ex: "Formulário de Referência - 2026 - CYRELA BRAZIL REALTY
    S.A.EMPREEND E PART Versão : 4" -> "CYRELA BRAZIL REALTY S.A.EMPREEND E
    PART"). Retorna None se nao conseguir reconhecer o padrao (ex: PDF nao e'
    um FRE da CVM).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ""
        match = _COMPANY_NAME_RE.search(first_page_text)
        return match.group(1).strip() if match else None
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/fre_pdf_parser/extract_company_name",
            severity="ERROR",
        )
        return None


def _clean_text(text):
    text = _PAGE_FOOTER_RE.sub("", text)
    text = _HEADER_RE.sub("", text)
    return text


_CHAPTER7_START_RE = re.compile(r"7\.1\s+Principais\s+características")
# paramos no que vier primeiro: inicio do capitulo 8, ou da secao 7.5 (que
# nao nos interessa e pode ser bem longa — visto na Estapar, cuja 7.6 tem
# dezenas de paginas e inflava demais o intervalo se so' parassemos no 8.1)
_CHAPTER7_END_RE = re.compile(r"^\s*(?:8\.1\b|7\.5\s+Relações familiares)", re.MULTILINE)


def find_chapter7_page_range(pdf_path):
    """Localiza automaticamente as paginas do capitulo 7 (estrutura de
    administracao) do FRE, escaneando o texto de cada pagina por cabecalhos
    de secao ("7.1 Principais características..." / "8.1 ..."). A numeracao
    das secoes e' padronizada pelo Anexo B da Resolução CVM 80/22, entao vale
    pra qualquer companhia aberta, nao so' as ja' testadas.

    Retorna (page_start, page_end), 1-indexados e inclusivos, prontos pra
    passar direto pra extract_section_text/parse_administration_structure.
    """
    try:
        start_page = None
        end_page = None
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                lines = [l for l in text.split("\n") if l.strip()]
                # a pagina de indice tambem lista "7.1 Principais
                # características..." como item de sumario — o que distingue
                # uma pagina de CONTEUDO real e' que ela repete o cabecalho
                # da secao atual bem no topo (2a linha nao-vazia, logo apos
                # o titulo "Formulário de Referência..."), enquanto o indice
                # tem "Índice" nessa posicao
                header = lines[1] if len(lines) > 1 else ""
                if start_page is None:
                    if _CHAPTER7_START_RE.match(header.strip()):
                        start_page = i + 1
                    continue
                if _CHAPTER7_END_RE.match(header.strip()):
                    end_page = i  # a pagina anterior ja' e' a ultima do capitulo 7
                    break

        if start_page is None:
            raise ValueError(
                "Não foi possível localizar a seção 7.1 do FRE neste PDF — "
                "verifique se é de fato um Formulário de Referência da CVM"
            )
        if end_page is None:
            # nao achou o inicio do capitulo 8 (formatacao atipica); usa uma
            # janela generosa a partir do inicio do capitulo 7
            end_page = start_page + 60

        custom_log(
            msg=f"Capítulo 7 localizado nas páginas {start_page}-{end_page} de {pdf_path}",
            component="/fre_pdf_parser/find_chapter7_page_range",
            severity="INFO",
        )
        return start_page, end_page
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/fre_pdf_parser/find_chapter7_page_range",
            severity="CRITICAL",
        )
        raise


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
    r"^\s*(?P<first>Conselho de|Conselho|Diretoria e|Diretoria)\s+\d{2}/\d{2}/\d{4}",
    re.MULTILINE,
)

# palavras-chave que sinalizam onde comeca o texto da coluna "Cargo eletivo
# ocupado", em ordem de prioridade de busca
_CARGO_KEYWORDS_ORGAO = ["C.F.", "Conselho de Adm", "Outros Diretores", "Diretor"]


def _extract_cargo_eletivo(row_text):
    """Extrai o texto da coluna 'Cargo eletivo ocupado' de uma linha da
    tabela 'Orgaos da Administracao'.

    A primeira data da linha (Data da Eleição) fica logo apos o nome do
    orgao (ex: "Diretoria"), que tambem contem a palavra "Diretor" como
    prefixo — buscar a palavra-chave de cargo na linha inteira acabava
    capturando por engano o proprio nome do orgao. Por isso a busca comeca
    so' depois da 1a data. O fim do cargo e' aproximado pela proxima data
    encontrada (Data de posse), que vem logo em seguida na mesma linha
    fisica; se o cargo quebrar pra uma 2a linha (titulos compostos longos,
    ex: "Diretor Presidente / Superintendente"), so' a parte que cabe na 1a
    linha e' capturada — limitacao conhecida, ver CONTEXT.md.
    """
    first_date = re.search(r"\d{2}/\d{2}/\d{4}", row_text)
    search_text = row_text[first_date.end():] if first_date else row_text

    # "Presidente do Conselho de Administração" e "Vice Presidente Cons. de
    # Administração" sempre quebram em varias linhas fisicas (o cargo mais
    # o proprio nome do orgao de novo), entao sao reconstruidos por texto
    # fixo em vez de recorte posicional
    if "Presidente do" in search_text:
        return "Presidente do Conselho de Administração"
    if "Vice Presidente" in search_text:
        return "Vice-Presidente do Conselho de Administração"

    for keyword in _CARGO_KEYWORDS_ORGAO:
        idx = search_text.find(keyword)
        if idx == -1:
            continue
        rest = search_text[idx:]
        stop = re.search(r"\d{2}/\d{2}/\d{4}", rest)
        cargo = rest[: stop.start()] if stop else rest
        cargo = " ".join(cargo.split()).rstrip("/").strip()
        return cargo or None

    # conselheiro "regular" (nem independente, nem presidente) tem o cargo
    # "Conselho de Administração (Efetivo)" grafado por extenso, que quebra
    # em varias linhas do mesmo jeito que o proprio nome do orgao — sem dar
    # pra recortar por posicao, mas o marcador "(Efetivo)"/"(Suplente)"
    # sobrevive intacto em alguma linha da tabela
    marker = re.search(r"\((Efetivo|Suplente)\)", row_text)
    if marker:
        return f"Conselho de Administração ({marker.group(1)})"
    return None


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
        if first == "Diretoria e":
            # cargo duplo: "Diretoria e Conselho de Administração" numa so linha
            orgao = "Diretoria e Conselho de Administração"
        elif first == "Diretoria":
            orgao = "Diretoria"
        elif first == "Conselho de":
            orgao = "Conselho de Administração"
        else:  # "Conselho" sozinho: olhar a 2a linha fisica
            second_line = lines[1] if len(lines) > 1 else ""
            orgao = "Conselho Fiscal" if "Fiscal" in second_line else "Conselho de Administração"

        dates = re.findall(r"\d{2}/\d{2}/\d{4}", row_text)
        eleito_pelo_controlador = _field(r"\b(Sim|Não)\b", row_text)
        cargo_hint = _extract_cargo_eletivo(row_text)

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


# linhas genericas da tabela: "Outros Comitês" (nome do comite fica numa
# coluna a parte), um nome de comite direto na propria coluna "Tipo
# comitê" iniciando com "Comitê de X" (ex: "Comitê de Risco" no FRE do
# BTG), ou iniciando so' com "Comitê X" sem o "de" (ex: "Comitê
# Financeiro" na Estapar). Excluimos explicitamente o padrao "Comitê de
# Comitê de" (duas colunas vizinhas comecando igual), que e' o artefato da
# linha ambigua do Comite de Auditoria (ver abaixo) — sem essa exclusao, o
# comeco dessa linha seria capturado como um comite generico chamado
# "Comitê de Comitê".
_COMITE_ROW_START_RE = re.compile(
    r"^\s*(?P<tipo>(?!Comitê\s+de\s+Comitê\s+de\b)"
    r"(?:Comitê\s+de\s+\S+(?:\s+\S+)*?|Comitê\s+(?!de\b)\S+(?:\s+\S+)*?|Outros\s+Comitês))"
    r"[^\n]*?\d{2}/\d{2}/\d{4}",
    re.MULTILINE,
)

# sinal robusto a quebra de linha/coluna de que a linha do "Comite de
# Auditoria Estatutario" esta presente: quando a coluna "Tipo auditoria"
# vizinha tem texto longo, "Comitê de" e "Auditoria" quebram em linhas
# fisicas diferentes, entao nao da' pra ancorar por posicao de linha (ao
# contrario dos casos acima). Detectamos pela descricao do regime
# regulatorio, que e' um texto fixo, nao pelo cabecalho da coluna em si.
# "Estatut?ário" tolera a variante "Estatuário" (sem o 2o "t") vista no FRE
# da Estapar, alem da grafia usual "Estatutário".
_COMITE_AUDITORIA_SIGNAL_RE = re.compile(r"Resolução\s+CVM|Estatut?[áa]rio", re.IGNORECASE)

# nomes dos comites de assessoramento conhecidos quando o "Tipo comitê" e'
# generico ("Outros Comitês") e o nome real fica numa coluna a parte —
# especifico por empresa; estender conforme novos FREs forem testados
KNOWN_COMMITTEE_NAMES = [
    "Comitê de Pessoas e Sustentabilidade",  # Cyrela
    "Comitê de Estratégia e Finanças",  # Cyrela
    "Comitê Financeiro e de Investimentos",  # Estapar
    "Comitê de Inovação",  # Estapar
]

# palavras da coluna "Cargo ocupado" que, se capturadas logo apos "Comitê de",
# indicam que o nome do comite nao coube na 1a linha (ver _parse_comites)
_CARGO_KEYWORDS = {"Membro", "Outros", "Coordenador", "Secretário", "Secretária"}


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

    O Comite de Auditoria Estatutario e' tratado separadamente do resto: a
    coluna 'Tipo comitê' e a coluna vizinha 'Tipo auditoria' comecam ambas
    com "Comitê de" para essa linha especificamente, entao ela nao da' pra
    ancorar de forma confiavel por posicao de linha como as demais. Por
    isso e' identificada pelo texto fixo do regime regulatorio ("Resolução
    CVM", "Estatutário") em vez do cabecalho da coluna, buscado na secao
    inteira (nao assume posicao/ordem).
    """
    section = _field(r"Comitês:(.*?)(?:Condenações:|\Z)", block)
    if not section:
        return []

    comites = []

    auditoria_signal = _COMITE_AUDITORIA_SIGNAL_RE.search(section)
    if auditoria_signal:
        # a linha do Comite de Auditoria abrange do inicio da secao (ou do
        # fim da linha anterior) ate o proximo salto de paragrafo em branco;
        # aproximamos pegando ate 400 chars ao redor do sinal encontrado
        window_start = max(0, auditoria_signal.start() - 300)
        auditoria_chunk = section[window_start:auditoria_signal.end() + 100]
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

    row_matches = list(_COMITE_ROW_START_RE.finditer(section))
    for i, m in enumerate(row_matches):
        end = row_matches[i + 1].start() if i + 1 < len(row_matches) else len(section)
        row_text = section[m.start():end]
        row_norm = " ".join(row_text.split())
        dates = re.findall(r"\d{2}/\d{2}/\d{4}", row_text)

        tipo = " ".join(m.group("tipo").split())
        if tipo == "Outros Comitês":
            comite_especifico = None
            for name in known_committee_names:
                # o nome do comite fica espalhado em ate 2 palavras por linha;
                # comparamos por palavras-chave em vez da frase inteira
                keywords = name.replace("Comitê de ", "").split(" e ")
                if all(kw.strip() in row_norm for kw in keywords):
                    comite_especifico = name
                    break
        elif re.sub(r"^Comitê(?:\s+de)?\s*", "", tipo).strip() in _CARGO_KEYWORDS:
            # o nome do comite nao coube na 1a linha fisica (junto com a
            # coluna "Cargo ocupado") e foi empurrado pra uma linha seguinte;
            # o regex capturou por engano a palavra do cargo (ex: "Comitê de
            # Membro" em vez de "Comitê de Remuneração"). O nome real
            # costuma sobrar logo depois da ultima data e antes do marcador
            # "(Efetivo)"/"(Suplente)"/"(Coordenador)" — tudo depois disso
            # e' texto de outra coluna (ex: prazo do mandato) que vazou pra
            # dentro da mesma linha fisica e deve ser descartado
            tail = row_norm.rsplit(dates[-1], 1)[-1] if dates else row_norm
            marker = re.search(r"\((?:Efetivo|Suplente|Coordenador)\)", tail)
            name = tail[:marker.start()].strip() if marker else tail.strip()
            prefix = "Comitê de" if tipo.startswith("Comitê de") else "Comitê"
            comite_especifico = f"{prefix} {name}" if name else None
        else:
            # nome direto na propria coluna "Tipo comitê" (ex: "Comitê de Risco")
            comite_especifico = tipo

        comites.append(
            {
                "tipo_comite": tipo,
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
        secao_74 = _field(
            r"7\.4 Composição dos comitês(.*?)(?:7\.5\s+Relações familiares|\Z)", text
        ) or ""

        result = {
            "contagem_por_orgao": parse_7_1d_counts(text),
            "membros": parse_members(secao_73, include_comites=False),
            "membros_comites": parse_members(secao_74, include_comites=True) if secao_74 else [],
        }

        # usamos substring (nao igualdade exata) pois um membro pode acumular
        # os dois orgaos numa linha so (ex: "Diretoria e Conselho de
        # Administração", visto no FRE do BTG Pactual)
        n_conselho = sum(
            1 for m in result["membros"]
            for o in m["orgaos"]
            if "Conselho de Administração" in o["orgao"]
        )
        n_diretoria = sum(
            1 for m in result["membros"]
            for o in m["orgaos"]
            if "Diretoria" in o["orgao"]
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


_SECAO_8_1_START_RE = re.compile(r"8\.1\s+Pol[ií]tica")
_SECAO_8_5_START_RE = re.compile(r"^\s*8\.5\b", re.MULTILINE)


def find_remuneracao_page_range(pdf_path):
    """Localiza as paginas das secoes 8.1 (Politica de remuneração), 8.3
    (Remuneração Variável) e 8.4 (Plano de remuneração baseado em ações) do
    FRE. Mesma tecnica de find_chapter7_page_range: escaneia o cabecalho de
    secao repetido na 2a linha de cada pagina.
    """
    try:
        start_page = None
        end_page = None
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                lines = [l for l in text.split("\n") if l.strip()]
                header = lines[1] if len(lines) > 1 else ""
                if start_page is None:
                    if _SECAO_8_1_START_RE.match(header.strip()):
                        start_page = i + 1
                    continue
                if _SECAO_8_5_START_RE.match(header.strip()):
                    end_page = i
                    break

        if start_page is None:
            raise ValueError(
                "Não foi possível localizar a seção 8.1 (remuneração) neste PDF"
            )
        if end_page is None:
            end_page = start_page + 40

        custom_log(
            msg=f"Seção de remuneração localizada nas páginas {start_page}-{end_page} de {pdf_path}",
            component="/fre_pdf_parser/find_remuneracao_page_range",
            severity="INFO",
        )
        return start_page, end_page
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/fre_pdf_parser/find_remuneracao_page_range",
            severity="CRITICAL",
        )
        raise


# sinal de que a secao 8.4 nega a existencia de plano de remuneracao baseada
# em acoes — quando ha' um plano vigente, a secao descreve o desenho dele em
# vez de uma frase curta de negacao
_LONGO_PRAZO_NEGATIVO_RE = re.compile(
    r"não\s+(?:h[áa]|possui|existe)\s+plano|não\s+aplic[áa]vel", re.IGNORECASE
)

# tipos de instrumento de remuneracao de longo prazo reconhecidos por
# palavra-chave no texto da secao 8.4
_LONGO_PRAZO_TIPOS = [
    (
        "Opções de compra de ações (stock options)",
        re.compile(r"op[çc][õo]es\s+de\s+compra\s+de\s+a[çc][õo]es|stock\s*options?", re.IGNORECASE),
    ),
    (
        "Ações restritas (RSU)",
        re.compile(r"a[çc][õo]es\s+restritas|restricted\s+stock|\bRSU\b", re.IGNORECASE),
    ),
    (
        "Phantom shares / ações fantasma",
        re.compile(r"phantom|a[çc][õo]es\s+fantasmas?", re.IGNORECASE),
    ),
    ("Matching de ações", re.compile(r"matching", re.IGNORECASE)),
]

# sinal (nao definitivo) de que a remuneracao variavel de curto prazo
# menciona metas/indicadores de desempenho — a resposta completa (quais
# indicadores) normalmente exige leitura humana do texto extraido
_KPI_SIGNAL_RE = re.compile(
    r"indicador(?:es)?|metas?\s+(?:individuais|estabelecidas|corporativas)"
    r"|\bKPIs?\b|crit[ée]rios?\s+de\s+desempenho",
    re.IGNORECASE,
)


def parse_remuneracao_qualitativa(pdf_path, page_start=None, page_end=None):
    """Extrai informações qualitativas do capítulo 8 (remuneração) do FRE:

    (a) se há remuneração de longo prazo baseada em ações e de que tipo
        (seção 8.4 "Plano de remuneração baseado em ações")
    (b) sinal de que a remuneração variável de curto prazo (bônus) é
        baseada em metas/indicadores de desempenho (seção 8.1)

    Diferente da estrutura do capítulo 7 (tabelas com colunas fixas), o
    capítulo 8 é majoritariamente texto corrido, que varia bastante de
    redação entre empresas. Por isso esta função NÃO tenta produzir uma
    resposta definitiva: extrai o texto relevante e sinaliza SIM/NÃO por
    palavra-chave, mas a leitura do texto extraído pelo analista continua
    sendo necessária pra confirmar a resposta, principalmente pro item (b).
    """
    try:
        if page_start is None or page_end is None:
            page_start, page_end = find_remuneracao_page_range(pdf_path)

        text = extract_section_text(pdf_path, page_start, page_end)

        secao_81 = _field(
            r"8\.1 Política ou prática de remuneração(.*?)(?:8\.2 Remuneração total|\Z)", text
        ) or ""
        secao_84 = _field(
            r"8\.4 Plano de remuneração baseado em ações(.*?)(?:8\.5|\Z)", text
        ) or ""

        tem_plano_longo_prazo = bool(secao_84.strip()) and not _LONGO_PRAZO_NEGATIVO_RE.search(secao_84)
        tipos_detectados = (
            [nome for nome, padrao in _LONGO_PRAZO_TIPOS if padrao.search(secao_84)]
            if tem_plano_longo_prazo
            else []
        )
        sinal_kpi_curto_prazo = bool(_KPI_SIGNAL_RE.search(secao_81))

        # remove as repeticoes do cabecalho da propria secao (aparece 1x por
        # pagina) antes de exibir o texto — e' ruido, nao conteudo
        texto_81 = " ".join(re.sub(r"8\.1 Política ou prática de remuneração", "", secao_81).split())
        texto_84 = " ".join(re.sub(r"8\.4 Plano de remuneração baseado em ações", "", secao_84).split())

        resultado = {
            "remuneracao_longo_prazo": {
                "possui_plano": tem_plano_longo_prazo,
                "tipos_detectados": tipos_detectados,
                "texto_secao_8_4": texto_84,
            },
            "remuneracao_curto_prazo_kpis": {
                "sinal_metas_indicadores": sinal_kpi_curto_prazo,
                "texto_secao_8_1": texto_81,
            },
        }

        custom_log(
            msg=(
                f"Remuneração qualitativa extraída: longo prazo={tem_plano_longo_prazo} "
                f"({tipos_detectados}), sinal KPI curto prazo={sinal_kpi_curto_prazo}"
            ),
            component="/fre_pdf_parser/parse_remuneracao_qualitativa",
            severity="INFO",
        )
        return resultado
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/fre_pdf_parser/parse_remuneracao_qualitativa",
            severity="CRITICAL",
        )
        raise


# numero no formato BR: milhares separados por ponto, decimais por virgula
# (ex: "5.942.498,78"); o grupo de milhares e' opcional (ex: "10,00")
_BR_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"

_ANO_BLOCK_RE = re.compile(
    r"Remuneração total (?:prevista para o|do) Exercício Social (?:corrente\s*)?(?:em\s*)?(\d{2}/\d{2}/\d{4})"
)

# rotulo da linha -> chave do campo; a ordem das 4 colunas e' sempre
# Conselho de Administração, Diretoria Estatutária, Conselho Fiscal, Total
_LINHAS_8_2 = [
    ("n_total_membros", "Nº total de membros"),
    ("n_membros_remunerados", "Nº de membros remunerados"),
    ("salario_pro_labore", "Salário ou pró-labore"),
    ("beneficios", "Benefícios direto e indireto"),
    ("participacoes_comites", "Participações em comitês"),
    ("bonus", "Bônus"),
    ("participacao_resultados", "Participação de resultados"),
    ("participacao_reunioes", "Participação em reuniões"),
    ("comissoes", "Comissões"),
    ("pos_emprego", "Pós-emprego"),
    ("cessacao_cargo", "Cessação do cargo"),
    ("baseada_acoes", "Baseada em ações"),
    ("total_remuneracao", "Total da remuneração"),
]

_ORGAOS_8_2 = ["conselho_administracao", "diretoria_estatutaria", "conselho_fiscal", "total"]


def _br_to_float(s):
    return float(s.replace(".", "").replace(",", "."))


def _parse_linha_valores(bloco_texto, rotulo):
    r"""Busca uma linha de valores por rotulo (ex: 'Bônus') e retorna os 4
    numeros que a seguem na mesma linha fisica (Conselho, Diretoria,
    Conselho Fiscal, Total). Retorna None se o rotulo nao for encontrado ou
    nao houver 4 numeros logo em seguida (o rotulo pode aparecer sozinho em
    texto descritivo, ex: "Descrição de outras remunerações fixas"). O gap
    entre o rotulo e o 1o numero e' [^\d]*? (nao so' espaco) pois alguns
    rotulos tem texto extra antes dos valores, ex: "Baseada em ações
    (incluindo" (o "opções)" continua na linha de baixo, fora do recorte)."""
    padrao = re.compile(
        re.escape(rotulo) + r"[^\d]*?(" + _BR_NUM + r")\s+(" + _BR_NUM + r")\s+(" + _BR_NUM + r")\s+(" + _BR_NUM + r")"
    )
    m = padrao.search(bloco_texto)
    if not m:
        return None
    valores = [_br_to_float(g) for g in m.groups()]
    return dict(zip(_ORGAOS_8_2, valores))


def _parse_linhas_outros(bloco_texto):
    """A linha 'Outros' aparece 2x no bloco (uma em 'Remuneração fixa
    anual', outra em 'Remuneração variável') — retorna (outros_fixo,
    outros_variavel) na ordem em que aparecem no texto."""
    padrao = re.compile(
        r"\bOutros\s+(" + _BR_NUM + r")\s+(" + _BR_NUM + r")\s+(" + _BR_NUM + r")\s+(" + _BR_NUM + r")"
    )
    matches = list(padrao.finditer(bloco_texto))
    resultados = []
    for m in matches[:2]:
        valores = [_br_to_float(g) for g in m.groups()]
        resultados.append(dict(zip(_ORGAOS_8_2, valores)))
    while len(resultados) < 2:
        resultados.append(None)
    return resultados[0], resultados[1]


def parse_remuneracao_valores(pdf_path, page_start=None, page_end=None):
    """Extrai os valores efetivos de remuneração por órgão (seção 8.2 do
    FRE), para os últimos exercícios sociais disponíveis (normalmente 3-4
    anos, incluindo o exercício corrente previsto).

    Diferente da seção 8.1/8.4 (texto corrido), a seção 8.2 e' uma tabela
    numerica com layout consistente entre empresas (exigido pelo Ofício-
    Circular/Anual da CVM/SEP), entao a extração aqui e' posicional (mesma
    tecnica das tabelas do capítulo 7), nao uma triagem por palavra-chave.

    Retorna uma lista de dicts, um por exercício social, cada um com os
    valores brutos (R$) por órgão — fixos, variáveis (curto prazo) e
    baseados em ações (longo prazo) — e a contagem de membros, prontos pra
    quem for calcular % de composição ou valor per capita (dividir pelo nº
    de membros remunerados, nao pelo total, pra media mais precisa).
    """
    try:
        if page_start is None or page_end is None:
            page_start, page_end = find_remuneracao_page_range(pdf_path)

        text = extract_section_text(pdf_path, page_start, page_end)

        secao_82 = _field(
            r"8\.2 Remuneração total por órgão(.*?)(?:8\.3 Remuneração Variável|\Z)", text
        ) or ""

        blocos_ano = list(_ANO_BLOCK_RE.finditer(secao_82))
        exercicios = []
        for i, m in enumerate(blocos_ano):
            fim = blocos_ano[i + 1].start() if i + 1 < len(blocos_ano) else len(secao_82)
            bloco = secao_82[m.start():fim]

            por_orgao = {orgao: {} for orgao in _ORGAOS_8_2}
            for campo, rotulo in _LINHAS_8_2:
                linha = _parse_linha_valores(bloco, rotulo)
                if linha:
                    for orgao in _ORGAOS_8_2:
                        por_orgao[orgao][campo] = linha[orgao]

            outros_fixo, outros_variavel = _parse_linhas_outros(bloco)
            for orgao in _ORGAOS_8_2:
                por_orgao[orgao]["outros_fixo"] = outros_fixo[orgao] if outros_fixo else None
                por_orgao[orgao]["outros_variavel"] = outros_variavel[orgao] if outros_variavel else None

            exercicios.append({"data_referencia": m.group(1), **por_orgao})

        custom_log(
            msg=f"Remuneração por órgão extraída para {len(exercicios)} exercício(s) sociais de {pdf_path}",
            component="/fre_pdf_parser/parse_remuneracao_valores",
            severity="INFO",
        )
        return exercicios
    except Exception as e:
        custom_log(
            msg=traceback.format_exception(e),
            component="/fre_pdf_parser/parse_remuneracao_valores",
            severity="CRITICAL",
        )
        raise
