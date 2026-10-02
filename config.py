# coding: utf-8

THREADS = 1

HEADLESS = False

SAVING_THRESHOLD = 150

STORAGE_STATE_PATH = "storage_state.json"

MIN_DELAY_BETWEEN_ACTIONS = 1.5
MAX_DELAY_BETWEEN_ACTIONS = 4.0

MAX_REVIEWS = 100

# XPath e regex usados em vários pontos do scrapper.py. Mantidos aqui pra não poluir a classe Scrapper.
XPATHS = {
    "accept_cookies": '//*[@id="onetrust-accept-btn-handler"]',
    "language_selector": '//span[text()="English"]',
    "lang_option": './/span[@id="menu-item-{}"]',
    "next_page_button": '//a[contains(@data-smoke-attr, "pagination-next-arrow")]',
    "pagination_info": '//div[contains(text(),"Mostrando")]', # O Tripadvisor trocou o atributo de "data-automation" pra "data-test-target" nesse h1 específico (confirmado em snapshot de 27/07/2026). Aceita os dois por segurança, caso volte a mudar ou varie entre páginas.
    "place_name": '//h1[@data-automation="mainH1" or @data-test-target="mainH1"]',
    "review_cards": '//*[@data-automation="reviewCard"]',
    "review_card_next_button": './/a[contains(@data-smoke-attr, "pagination-next-arrow")]',
    "review_title": './/h3',
    "review_comment": './/span[contains(@class, "JguWG")]',
    "review_date_full": './/div[contains(@class, "BNe1O")]',
    "review_date_candidates": './/div | .//span',
    "review_rating": './/*[local-name()="svg" and @data-automation="bubbleRatingImage"]/*[local-name()="title"]',
    "local": './/div[contains(@class, "vYLts")]',
    "category": './/div[contains(@class, "jXCrq")]',
}

# Transforma textos em dados estruturados (ex.: "out. de 2025" → {"month": 10, "year": 2025})
REGEXES = {
    "starts_with_number": r'^\d.+$',
    # Aceita nota inteira ou com casa decimal ("4 de 5 círculos" ou "4,5 de 5 círculos")
    "rating": r"^(\d+(?:[.,]\d+)?) de \d+ círculos$",
    "get_review_amount": r"^Mostrando.* de (.*) resultados$",
    # A categoria/tipo de viagem, quando vem com data embutida, é "mai. de 2026 • Solo"
    "get_category": r"^.*•\s*(.*)$",
    # Data completa antiga: "Feita em 15 de agosto de 2024"
    "full_date": r"^Feita em (\d{1,2}) de (\w+) de (\d{4})$",
    # Data curta atual, sem dia: "out. de 2025" / "out de 2025"
    "short_date": r"^(\w+)\.?\s+de\s+(\d{4})$",
}

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

MESES_ABREV_PT = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
