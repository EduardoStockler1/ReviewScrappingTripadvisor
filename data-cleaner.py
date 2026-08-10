import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from unidecode import unidecode

# =====================================================================
# CONFIG — ligue/desligue as limpezas opcionais aqui
# =====================================================================
CONFIG = {
    # Colunas onde faz sentido rodar a limpeza PESADA de texto livre
    # (HTML, URLs, CPF, emojis, etc.). Colunas de data/nota nao entram aqui.
    "text_columns_hints": [
        "title", "comment", "local", "category",
        "titulo", "comentario", "categoria", "review", "texto", "descricao",
    ],

    # Colunas candidatas a serem "coluna de comentario" (para filtros de
    # linha como duplicata de comentario / tamanho minimo).
    "comment_column_hints": ["comment", "comentario", "review", "texto"],

    # Opcionais (default = False, exceto indicado)
    "remove_accents": True,               # unidecode - True porque o script original ja fazia isso
    "lowercase": False,
    "remove_emojis": True,
    "remove_emoticons": True,
    "remove_mentions": True,
    "remove_hashtags": True,
    "remove_stopwords": False,
    "reduce_letter_repetition": True,
    "reduce_word_repetition": True,
    "remove_markdown": True,
    "expand_abbreviations": False,
    "normalize_slang": False,

    # Filtros de linha
    "min_comment_length": 0,              # 0 = desliga
    "drop_duplicate_comments": False,     # so roda se achar coluna de comentario
    "drop_duplicate_rows": True,
    "drop_fully_empty_columns": True,

    "placeholder_values": [
        "n/a", "na", "-", "--", "s/n", "sem resposta", "nao informado",
        "não informado", "null", "none", "undefined", ".", "..", "...",
    ],
}

ABBREVIATIONS_MAP = {
    # "vc": "voce", "pq": "porque", "tb": "tambem",
}
SLANG_MAP = {
    # "mds": "meu deus", "top": "otimo",
}

# =====================================================================
# Regex / utilitarios de baixo nivel
# =====================================================================

INVISIBLE_CHARS_RE = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad]"
)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

HTML_TAG_RE = re.compile(r"<[^>]+>")
XML_TAG_RE = re.compile(r"</?[a-zA-Z][\w:-]*(?:\s+[^<>]*)?/?>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-.\s]?\d{4}")

CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
CEP_RE = re.compile(r"\b\d{5}-?\d{3}\b")
RG_RE = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9xX]\b")

MENTION_RE = re.compile(r"(?<!\w)@\w+")
HASHTAG_RE = re.compile(r"(?<!\w)#\w+")

EMOTICON_RE = re.compile(
    r"(?::|;|=|X|x)[\-o\*']?(?:\)|\(|D|P|p|O|o|\/|\\|3|\||S|s)"
    r"|<3|\)-?:|\(-?:|\^_?\^|xD|XD"
)
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "\U0000FE0F"
    "]+"
)
GIF_IMG_PLACEHOLDER_RE = re.compile(
    r"\[?\s*(?:gif|imagem|image|photo|foto|video|attachment|anexo)\s*\]?",
    re.IGNORECASE,
)
MARKDOWN_RE = re.compile(r"(\*\*|__|`{1,3}|~~|^#{1,6}\s?)", re.MULTILINE)

REPEATED_PUNCT_RE = re.compile(r"([!?.,;:])\1{1,}")
MULTI_QUESTION_EXCLAM_RE = re.compile(r"([!?])(?:\s*[!?])+")
BACKSLASH_RE = re.compile(r"\\+(?!n|t|r)")
LITERAL_ESCAPE_RE = re.compile(r"\\[ntr]")
ISOLATED_SYMBOL_RE = re.compile(r"(?<!\w)[§¤©®™°¶†‡•·…»«¬~^`´¨]+(?!\w)")
LETTER_REPEAT_RE = re.compile(r"([a-zA-ZáéíóúâêôãõàçÁÉÍÓÚÂÊÔÃÕÀÇ])\1{2,}")
# Repeticao de palavra tolera virgula/ponto-e-virgula entre as ocorrencias
# (ex: "ruim, ruim, ruim" -> "ruim"), nao so espaco puro.
WORD_REPEAT_RE = re.compile(r"\b(\w{2,})\b(?:\s*[,;]?\s+\1\b)+", re.IGNORECASE)

# Depois do unidecode nao sobra acento, mas mantemos p/ caso remove_accents=False
SYMBOL_PATTERN = re.compile(r"[^a-zA-Z0-9\s.,;:!?()\-\"'/áéíóúâêôãõàçÁÉÍÓÚÂÊÔÃÕÀÇ]")

HTML_ENTITY_MAP = {
    "&nbsp;": " ", "&amp;": "&", "&quot;": '"', "&lt;": "<", "&gt;": ">",
    "&apos;": "'", "&#39;": "'", "&#160;": " ",
}

STOPWORDS_PT = {
    "a", "o", "as", "os", "de", "do", "da", "dos", "das", "em", "um", "uma",
    "uns", "umas", "e", "é", "ao", "aos", "à", "às", "para", "por", "com",
    "que", "se", "na", "no", "nas", "nos", "sua", "seu", "suas", "seus",
    "esse", "essa", "isso", "este", "esta", "isto", "mas", "ou", "como",
    "foi", "ser", "ter", "muito", "mais", "ja", "já", "tambem", "também",
}


def fix_mojibake(text: str) -> str:
    if any(ch in text for ch in ("Ã", "Â", "â€", "�")):
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
    return text


def normalize_invalid_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cn")


def is_only_symbols_or_numbers(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return not re.search(r"[^\W\d_]", stripped, re.UNICODE)


# =====================================================================
# Pipeline pesado de limpeza de texto livre
# =====================================================================

def clean_free_text(value, cfg):
    if pd.isna(value):
        return np.nan

    text = str(value)

    text = fix_mojibake(text)
    text = normalize_invalid_unicode(text)

    text = INVISIBLE_CHARS_RE.sub("", text)
    text = CONTROL_CHARS_RE.sub("", text)

    for entity, char in HTML_ENTITY_MAP.items():
        text = text.replace(entity, char)
    text = re.sub(r"&#\d+;", " ", text)
    text = SCRIPT_STYLE_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = XML_TAG_RE.sub(" ", text)

    if cfg["remove_markdown"]:
        text = MARKDOWN_RE.sub(" ", text)

    text = LITERAL_ESCAPE_RE.sub(" ", text)
    text = re.sub(r"[\r\n\t]+", " ", text)

    text = GIF_IMG_PLACEHOLDER_RE.sub(" ", text)

    text = URL_RE.sub(" ", text)
    text = EMAIL_RE.sub(" ", text)
    text = CNPJ_RE.sub(" ", text)
    text = CPF_RE.sub(" ", text)
    text = CEP_RE.sub(" ", text)
    text = RG_RE.sub(" ", text)
    text = PHONE_RE.sub(" ", text)

    if cfg["remove_mentions"]:
        text = MENTION_RE.sub(" ", text)
    if cfg["remove_hashtags"]:
        text = HASHTAG_RE.sub(" ", text)

    if cfg["remove_emoticons"]:
        text = EMOTICON_RE.sub(" ", text)
    if cfg["remove_emojis"]:
        text = EMOJI_RE.sub(" ", text)

    text = REPEATED_PUNCT_RE.sub(r"\1", text)
    text = MULTI_QUESTION_EXCLAM_RE.sub(lambda m: m.group(1), text)
    text = re.sub(r'"{2,}', '"', text)
    text = re.sub(r"'{2,}", "'", text)
    text = BACKSLASH_RE.sub(" ", text)
    text = ISOLATED_SYMBOL_RE.sub(" ", text)

    if cfg["reduce_letter_repetition"]:
        text = LETTER_REPEAT_RE.sub(r"\1\1", text)
    if cfg["reduce_word_repetition"]:
        text = WORD_REPEAT_RE.sub(r"\1", text)

    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)

    if cfg["expand_abbreviations"] and ABBREVIATIONS_MAP:
        for abbr, full in ABBREVIATIONS_MAP.items():
            text = re.sub(rf"\b{re.escape(abbr)}\b", full, text, flags=re.IGNORECASE)
    if cfg["normalize_slang"] and SLANG_MAP:
        for slang, norm in SLANG_MAP.items():
            text = re.sub(rf"\b{re.escape(slang)}\b", norm, text, flags=re.IGNORECASE)

    # acentos e simbolos decorativos: usa unidecode, igual ao script original
    if cfg["remove_accents"]:
        text = unidecode(text)
        text = re.sub(r"[^a-zA-Z0-9\s.,;:!?()\-\"'/]", "", text)
    else:
        text = SYMBOL_PATTERN.sub("", text)

    text = re.sub(r"\s+", " ", text).strip()

    if cfg["remove_stopwords"] and text:
        words = [w for w in text.split(" ") if w.lower() not in STOPWORDS_PT]
        text = " ".join(words)

    if cfg["lowercase"]:
        text = text.lower()

    if is_only_symbols_or_numbers(text) or text == "":
        return np.nan

    return text


def clean_light_text(value):
    """Limpeza minima para colunas que NAO sao texto livre (ex: id, url de
    origem, nome de autor): so tira invisiveis/controle e espacos nas
    pontas/multiplos, sem mexer no conteudo."""
    if pd.isna(value):
        return np.nan
    text = str(value)
    text = fix_mojibake(text)
    text = INVISIBLE_CHARS_RE.sub("", text)
    text = CONTROL_CHARS_RE.sub("", text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text != "" else np.nan


def extract_rating(value):
    if pd.isna(value):
        return value
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return np.nan
    return match.group().replace(",", ".")


# =====================================================================
# Limpeza do DataFrame
# =====================================================================

def clean_dataframe(df: pd.DataFrame, cfg=CONFIG) -> pd.DataFrame:
    df = df.copy()

    all_text_cols = [
        c for c in df.columns
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])
    ]
    heavy_cols = [
        c for c in all_text_cols
        if any(hint in c.lower() for hint in cfg["text_columns_hints"])
    ]
    light_cols = [c for c in all_text_cols if c not in heavy_cols]

    # limpeza leve em tudo que e texto mas nao e "texto livre"
    for col in light_cols:
        df[col] = df[col].apply(clean_light_text)

    # limpeza pesada nas colunas de texto livre (comentario, titulo, etc.)
    for col in heavy_cols:
        df[col] = df[col].apply(lambda v: clean_free_text(v, cfg))

    # placeholders tipo "N/A", "-", "sem resposta" -> NaN, em qualquer coluna de texto
    placeholders_lower = {p.lower() for p in cfg["placeholder_values"]}
    for col in all_text_cols:
        df[col] = df[col].apply(
            lambda v: np.nan if (isinstance(v, str) and v.strip().lower() in placeholders_lower) else v
        )

    if cfg["drop_fully_empty_columns"]:
        df = df.dropna(axis=1, how="all")

    # coluna de nota/rating: extrai o primeiro numero antes de converter
    numeric_cols = [c for c in df.columns if any(k in c.lower() for k in ["rating", "score", "stars", "nota"])]
    for col in numeric_cols:
        if col in df.columns and (df[col].dtype == object or pd.api.types.is_string_dtype(df[col])):
            df[col] = df[col].apply(extract_rating)
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # coluna de data
    date_cols = [c for c in df.columns if "date" in c.lower() or "data" in c.lower()]
    for col in date_cols:
        try:
            # dayfirst=True: as datas vem no formato DD/MM/AAAA. Sem isso,
            # pandas assume o formato americano (MM/DD/AAAA) por padrao e
            # inverte dia/mes silenciosamente pra qualquer dia <= 12.
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
        except Exception:
            pass

    # coluna de comentario, para filtros de linha
    comment_column = next(
        (c for c in df.columns if any(h in c.lower() for h in cfg["comment_column_hints"])),
        None,
    )
    if comment_column is not None:
        if cfg["min_comment_length"] > 0:
            df = df[
                df[comment_column].isna()
                | (df[comment_column].astype(str).str.len() >= cfg["min_comment_length"])
            ]
        if cfg["drop_duplicate_comments"]:
            df = df.drop_duplicates(subset=[comment_column], keep="first")

    # linhas totalmente vazias
    df = df.dropna(axis=0, how="all")

    # linhas duplicadas (todas as colunas)
    if cfg["drop_duplicate_rows"]:
        df = df.drop_duplicates()

    df = df.reset_index(drop=True)
    return df


# =====================================================================
# Descoberta de arquivo + main (igual ao script original)
# =====================================================================

def find_latest_review_csv(reviews_dir: Path) -> Path:
    """Encontra o CSV mais recente dentro de reviews/<pasta_mais_recente>/,
    evitando precisar editar o caminho manualmente a cada nova coleta."""
    if not reviews_dir.exists():
        print(f"Diretório de reviews não encontrado: {reviews_dir}")
        sys.exit(1)

    subdirs = [d for d in reviews_dir.iterdir() if d.is_dir()]
    if not subdirs:
        print(f"Nenhuma subpasta de coleta encontrada em: {reviews_dir}")
        sys.exit(1)

    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)

    csv_files = list(latest_dir.glob("*.csv"))
    if not csv_files:
        print(f"Nenhum CSV encontrado em: {latest_dir}")
        sys.exit(1)

    # Se houver mais de um CSV na pasta mais recente, pega o mais recente também.
    return max(csv_files, key=lambda f: f.stat().st_mtime)


def main():
    base_dir = Path.cwd()
    reviews_dir = base_dir / "reviews"

    input_path = find_latest_review_csv(reviews_dir)
    print(f"Usando arquivo mais recente: {input_path}")

    dest_dir = input_path.parent.parent / "reviews cleaned"
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        df = pd.read_csv(input_path)
    except UnicodeDecodeError:
        df = pd.read_csv(input_path, encoding="latin1")

    print(f"Linhas antes da limpeza: {len(df)}")
    cleaned = clean_dataframe(df, CONFIG)
    print(f"Linhas depois da limpeza: {len(cleaned)}")

    stem = input_path.stem
    cleaned_csv_path = dest_dir / f"{stem}-cleaned.csv"
    cleaned_xlsx_path = dest_dir / f"{stem}-cleaned.xlsx"

    cleaned.to_csv(cleaned_csv_path, index=False)
    try:
        cleaned.to_excel(cleaned_xlsx_path, index=False)
    except Exception:
        with pd.ExcelWriter(cleaned_xlsx_path) as writer:
            cleaned.to_excel(writer, index=False)

    print(f"Saved cleaned CSV: {cleaned_csv_path}")
    print(f"Saved cleaned Excel: {cleaned_xlsx_path}")


if __name__ == "__main__":
    main()