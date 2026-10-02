# coding: utf-8
import datetime
import os
import random
import re
import time
import logger
import config
import close_iframe
from typing import Dict, List, Optional, Tuple
from playwright.sync_api import (
    sync_playwright,
    Locator,
    TimeoutError,
)

class Scraper:

    # =========================================================================
    # 1) CRIAÇÃO / FECHAMENTO DO NAVEGADOR -> Playwright + Chromium + Contexto persistente
    # =========================================================================

    def __init__(self):
        self.playwright = sync_playwright().start() 
        self.__review_dumps_done = 0
        self.__total_reviews_collected = 0

        self.browser = self.playwright.chromium.launch(
            headless=config.HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context_kwargs = {
            "locale": "pt-BR",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "viewport": {
                "width": 1366, 
                "height": 900
            },
        }

        # if os.path.exists(config.STORAGE_STATE_PATH):
        #     logger.debug(f"Reaproveitando sessão salva em {config.STORAGE_STATE_PATH}")
        #     context_kwargs["storage_state"] = config.STORAGE_STATE_PATH

        self.context = self.browser.new_context(**context_kwargs)
        # self.context.clear_cookies()
        self.page = self.context.new_page() 
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        logger.debug("Fechando navegador")
        try:
            self.context.close()
        finally:
            try:
                self.browser.close()
            finally:
                self.playwright.stop()

    def save_session(self):
        # Persiste cookies/local storage atuais em disco, para reuso nas
        # próximas execuções (evita repetir o desafio anti-bot a cada run). 
        try:
            self.context.storage_state(path=config.STORAGE_STATE_PATH)
            logger.debug(f"Sessão salva em {config.STORAGE_STATE_PATH}")
        except Exception as e:
            logger.error(f"Não foi possível salvar a sessão: {e}")

    # =========================================================================
    # 2) ABRIR A PÁGINA (+ desafios anti-bot, cookies, obstáculos)
    # =========================================================================

    def open_page(self, url: str, cookies: bool = True):
        t0 = time.monotonic()
        logger.info("[TIMING] Abrindo página {}".format(url))

        self.page.goto(
            url,
            wait_until="domcontentloaded"
        )
        logger.info(f"[TIMING] goto concluído em {time.monotonic() - t0:.1f}s")

        if cookies:
            self.__handle_cookies()
            logger.info(f"[TIMING] cookies tratados em {time.monotonic() - t0:.1f}s")
            self.page.wait_for_timeout(1000)

    def __handle_cookies(self):
        cookie_button = self.page.locator(f'xpath={config.XPATHS["accept_cookies"]}')
        try:
            # Páginas com bastante anúncio/tracking de terceiros (ex.: banners
            # patrocinados) atrasam a injeção do script do OneTrust. 15s se
            # mostrou curto demais em alguns casos; damos mais margem aqui.
            cookie_button.wait_for(state="visible", timeout=30000)
            cookie_button.click(timeout=5000)

            # Não basta ter clicado: confirmamos que o botão realmente sumiu
            # do DOM antes de seguir, já que o clique pode falhar
            # silenciosamente se o layout mudar no meio do processo.
            cookie_button.wait_for(state="hidden", timeout=10000)

            logger.debug("Cookies aceitos")

        except TimeoutError:
            logger.debug("Sem popup de cookies (ou não desapareceu a tempo)")
            self.__dump_debug_snapshot("cookie_banner_issue")

    def get_page_title(self, max_wait_seconds: int = 120, poll_seconds: int = 5):
        t0 = time.monotonic()
        logger.info("[TIMING] Esperando h1 (com polling do interstitial)...")

        while time.monotonic() - t0 < max_wait_seconds:
            try:
                logger.info(f" Esperando iframe interstitial aparecer (polling a cada {poll_seconds}s)...")
                close_iframe.dump_frames_debug(self.page)
                closed = close_iframe.close_interstitial(self.page, timeout = 1)
                if closed:
                    logger.info(f"[TIMING] interstitial fechado em {time.monotonic() - t0:.1f}s")
            except Exception as e:
                logger.error(f"Erro ao tentar fechar interstitial: {e}")

            close_iframe.dump_frames_debug(self.page)

            try:
                result = self.page.locator(
                    f'xpath={config.XPATHS["place_name"]}'
                ).text_content(timeout=poll_seconds * 1000)
                logger.info(f"[TIMING] h1 obtido em {time.monotonic() - t0:.1f}s")
                return result
            except TimeoutError:
                continue

        logger.info(f"[TIMING] h1 NÃO apareceu após {time.monotonic() - t0:.1f}s (polling esgotado)")
        
        raise TimeoutError(
            f"h1 não apareceu após {max_wait_seconds}s de polling, mesmo "
            "tentando fechar o interstitial repetidamente."
        )

    # =========================================================================
    # 3) PAGINAÇÃO
    # =========================================================================

    def wait_reviews_to_load(self):
        self.page.locator(
            f'xpath={config.XPATHS["pagination_info"]}'
        ).wait_for()

    def get_review_amount(self):
        logger.debug("Obtendo quantidade de reviews no ponto turístico")
        pagination_info = self.page.locator(f'xpath={config.XPATHS["pagination_info"]}').text_content()
        pattern = re.compile(config.REGEXES["get_review_amount"])
        amount = 0
        try:
            review_amount_str = re.match(pattern, pagination_info).group(1)
            amount = int(review_amount_str.replace(".", ""))
            logger.debug(f"{amount} reviews no total")
        except Exception as e:
            logger.error("Erro ao obter a quantidade de reviews: {}".format(e))

        return amount

    def has_next_page(self):
        logger.debug("Verificando se há próxima página")

        next_button = self.page.locator(f'xpath={config.XPATHS["next_page_button"]}')

        if next_button.count() == 0:
            return False

        # O botão pode continuar presente no DOM na última página, porém
        # desabilitado. count() > 0 sozinho não é suficiente.
        aria_disabled = next_button.first.get_attribute("aria-disabled")
        class_attr = next_button.first.get_attribute("class") or ""

        if aria_disabled == "true" or "disabled" in class_attr.lower():
            return False

        return True

    def go_to_next_page(self, page_title):

        logger.info(f"{page_title} -> Indo para próxima página")

        # Pausa curta antes de navegar: evita o padrão "clique instantâneo
        # em intervalos idênticos" que é um dos sinais mais fáceis de
        # detectar em automação.
        self.__human_delay()

        self.page.locator(
            f'xpath={config.XPATHS["next_page_button"]}'
        ).click()

    def __human_delay(self):
        """Pausa curta e aleatória entre ações, pra não parecer um robô
        martelando requisições em intervalos perfeitamente regulares."""
        time.sleep(random.uniform(config.MIN_DELAY_BETWEEN_ACTIONS, config.MAX_DELAY_BETWEEN_ACTIONS))

    # =========================================================================
    # 4) EXTRAIR OS REVIEWS DA PÁGINA ATUAL
    # =========================================================================

    def scrap_page(self) -> Tuple[List[Dict], int]:
        logger.debug("Extraindo reviews da página")
        raw_reviews = self.page.locator(f'xpath={config.XPATHS["review_cards"]}').all()
        page_reviews = []

        counter = 0
        skipped = 0
        for review in raw_reviews:
            # Limite de teste: para de extrair assim que atingir o total
            # (soma de todas as páginas já processadas), mesmo no meio desta.
            if config.MAX_REVIEWS is not None and self.__total_reviews_collected >= config.MAX_REVIEWS:
                logger.info(f"Limite de {config.MAX_REVIEWS} reviews atingido. Parando a extração.")
                break

            # Em vez de assumir por posição (pop()) que o último elemento é um
            # botão, filtramos explicitamente qualquer card que contenha o
            # botão de paginação dentro dele.
            if review.locator(f'xpath={config.XPATHS["review_card_next_button"]}').count() > 0:
                continue

            new_data = self.handle_review(review)

            if new_data is not None:
                logger.info("Review extraído: {}".format(new_data))
                page_reviews.append(new_data)
                counter += 1
                self.__total_reviews_collected += 1
            else:
                skipped += 1

        logger.info(f"Encontrados {counter} reviews ({skipped} ignorados por erro de parsing). "
                    f"Total acumulado: {self.__total_reviews_collected}.")
        return page_reviews, counter

    def has_reached_review_limit(self) -> bool:
        """Usado pelo loop externo de paginação para saber se deve parar
        de chamar go_to_next_page() (limite de teste já atingido)."""
        return config.MAX_REVIEWS is not None and self.__total_reviews_collected >= config.MAX_REVIEWS

    def handle_review(self, review) -> Optional[Dict]:
        try:
            title = self.__safe_text(
                review.locator(f'xpath={config.XPATHS["review_title"]}')
            )

            comment = self.__safe_text(
                review.locator(f'xpath={config.XPATHS["review_comment"]}')
            )

            raw_date = self.get_review_date(review)
            date = self.parse_date(raw_date) if raw_date else None

            raw_rating = self.__safe_text(
                review.locator(f'xpath={config.XPATHS["review_rating"]}')
            )
            rating = self.parse_rating(raw_rating)

            local = self.get_local(review)

            category = self.get_category(review)

            if title is None or comment is None or raw_date is None:
                self.__dump_review_html_once(review, "campo_ausente")

            return {
                "title": title,
                "comment": comment,
                "date": date,
                "rating": rating,
                "local": local,
                "category": category,
            }
        except Exception as e:
            logger.error(f"Erro ao processar review, ignorando: {e}")
            return None

    def __get_date_category_raw_text(self, review: Locator) -> str:
        locator = review.locator(f'xpath={config.XPATHS["category"]}')
        if locator.count() == 0:
            return ""
        return (locator.first.text_content() or "").strip()

    def get_review_date(self, review: Locator) -> Optional[str]:
        logger.debug("Obtendo data do review")

        full_date = self.__safe_text(review.locator(f'xpath={config.XPATHS["review_date_full"]}'))
        if full_date:
            return full_date

        short_date_pattern = re.compile(config.REGEXES["short_date"], re.IGNORECASE)

        combined_text = self.__get_date_category_raw_text(review)
        if combined_text:
            date_part = combined_text.split("•")[0].strip()
            if short_date_pattern.match(date_part):
                return date_part

        candidates = review.locator(f'xpath={config.XPATHS["review_date_candidates"]}')
        for i in range(candidates.count()):
            text = (candidates.nth(i).text_content() or "").strip()
            if short_date_pattern.match(text):
                return text

        return None

    def parse_date(self, date: str) -> Optional[str]:
        logger.debug("Parseando data")
        date = date.strip()

        full_match = re.match(config.REGEXES["full_date"], date)
        if full_match:
            dia, mes_nome, ano = full_match.groups()
            mes = config.MESES_PT.get(mes_nome.lower())
            if mes is None:
                logger.error(f"Mês não reconhecido: '{mes_nome}'")
                return None
            try:
                return datetime.date(int(ano), mes, int(dia)).strftime("%d/%m/%Y")
            except ValueError as e:
                logger.error(f"Data inválida ({date}): {e}")
                return None

        short_match = re.match(config.REGEXES["short_date"], date, re.IGNORECASE)
        if short_match:
            mes_abrev, ano = short_match.groups()
            mes = config.MESES_ABREV_PT.get(mes_abrev.lower().rstrip('.'))
            if mes is None:
                logger.error(f"Mês abreviado não reconhecido: '{mes_abrev}'")
                return None
            # Sem dia disponível nesse formato — retornamos só mês/ano em vez
            # de inventar um dia (ex.: "01") que passaria uma precisão falsa.
            return f"{mes:02d}/{ano}"

        logger.error(f"Formato de data inesperado: '{date}'")
        return None

    def parse_rating(self, rating_str: Optional[str]) -> Optional[float]:
        logger.debug("Parseando avaliação do turista")

        if not rating_str:
            logger.error("Rating vazio ou ausente")
            return None

        pattern = re.compile(config.REGEXES["rating"])
        try:
            match = re.match(pattern, rating_str)
            if not match:
                raise ValueError(f"Não bateu com o padrão esperado: '{rating_str}'")
            return float(match.group(1).replace(",", "."))
        except Exception as e:
            logger.error("Erro ao parsear o rating ({}): {}".format(rating_str, e))
            return None

    def get_local(self, review: Locator) -> str:
        logger.debug("Obtendo local no turista")
        vylts_divs = review.locator(f'xpath={config.XPATHS["local"]}')
        count = vylts_divs.count()

        if count == 0:
            return ""

        first = vylts_divs.nth(0)
        span = first.locator("xpath=.//span")

        if span.count() > 0:
            return (span.first.text_content() or "").strip()

        text = (first.text_content() or "").strip()
        if "contribui" in text.lower():
            return ""
        return text

    def get_category(self, review):
        combined_text = self.__get_date_category_raw_text(review)
        if not combined_text:
            return ""

        match = re.match(config.REGEXES["get_category"], combined_text)
        return match.group(1) if match else ""

    def __safe_text(self, locator: Locator, timeout: int = 3000) -> Optional[str]:
        if locator.count() == 0:
            return None
        try:
            return locator.first.text_content(timeout=timeout)
        except TimeoutError:
            return None

    # =========================================================================
    # 5) DIAGNÓSTICO (screenshots/HTML salvos em caso de falha)
    # =========================================================================

    def __dump_debug_snapshot(self, label: str):
        try:
            os.makedirs("debug_snapshots", exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base = f"debug_snapshots/{label}_{stamp}"
            self.page.screenshot(path=f"{base}.png", full_page=True)
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(self.page.content())
            logger.error(f"Snapshot de diagnóstico salvo em {base}.png / {base}.html")
        except Exception as e:
            logger.error(f"Não foi possível salvar snapshot de diagnóstico: {e}")

    def __dump_review_html_once(self, review: Locator, label: str, max_dumps: int = 3):
        """Salva o outerHTML de um card de review específico quando um campo
        essencial vem ausente, limitado a poucas vezes por execução (o
        problema costuma ser sistemático — não precisa de milhares de
        arquivos iguais pra diagnosticar)."""
        if self.__review_dumps_done >= max_dumps:
            return
        try:
            os.makedirs("debug_snapshots", exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = f"debug_snapshots/review_{label}_{stamp}.html"
            html = review.evaluate("el => el.outerHTML")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            self.__review_dumps_done += 1
            logger.error(f"HTML do card de review salvo em {path}")
        except Exception as e:
            logger.error(f"Não foi possível salvar HTML do card de review: {e}")

    def print_element(self, element):
        element.screenshot(path=f"{os.getcwd()}/element.png")