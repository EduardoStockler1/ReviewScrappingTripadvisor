# coding: utf-8
import csv
import datetime
import os
from concurrent import futures
import traceback
from typing import Dict, List, TextIO
from logging import getLogger
import locale

import unidecode as unidecode

from beeper import beep
from config import THREADS, SAVING_THRESHOLD
from scrapper import Scrapper
from logger import init_logging, debug, info, error
from timer import Timer

timer = Timer()
logger = getLogger("scrapper")
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except:
    locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil')

def write_data_chunk(csv_writer: csv.DictWriter, data: List[Dict]):
    try:
        info("Salvando {} reviews em {}".format(
            str(len(data)), datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
        csv_writer.writerows(data)
        info("Salvamento terminado em {}".format(
            datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
    except Exception as e:
        error("Erro ao salvar os reviews: {}".format(e), "error")
        beep("exception")


def scrap_url(scrapper: Scrapper, csv_writer: csv.DictWriter, page_title: str):
    review_amount = scrapper.get_review_amount()
    info(
        "{} -> {} reviews encontrados".format(page_title, review_amount))
    reviews = []
    counter = 0
    has_next_page = True

    try:
        while has_next_page:
            scrapper.wait_reviews_to_load()
            tmp_reviews, processed = scrapper.scrap_page()
            reviews += tmp_reviews
            counter += processed

            info("{} -> {:.2f}% ({}/{})".format(page_title,
                         (counter/review_amount)*100, counter, review_amount))
            has_next_page = scrapper.has_next_page()
            info(f"Segurando {counter} reviews (vai salvar: {counter >= SAVING_THRESHOLD})")
            if counter >= SAVING_THRESHOLD:
                write_data_chunk(csv_writer, reviews)
                reviews = []
                counter = 0

            if has_next_page:
                scrapper.go_to_next_page(page_title)
    except Exception as exc:
        error("{} gerou uma exceção => {}".format(page_title, exc))
        beep("exception")

    if reviews:
        info(
            "{} -> Salvando os restantes {} reviews".format(page_title, len(reviews))
        )
        write_data_chunk(csv_writer, reviews)


def start_csv_writer(file: TextIO) -> csv.DictWriter:
    example = {
        "title": "",
        "comment": "",
        "date": "",
        "rating": "",
        "local": "",
        "category": ""
    }
    dict_to_csv_writer = csv.DictWriter(file, example.keys())
    dict_to_csv_writer.writeheader()
    return dict_to_csv_writer


def url_task(url: str, directory: str):
    info("Iniciando {}".format(url))
    url_timer = Timer()
    url_timer.start()

    # Scrapper agora é usado como context manager: garante o fechamento do
    # browser mesmo se `open_page`, `get_page_title` ou o scraping em si
    # lançarem uma exceção (ex.: bloqueio anti-bot, timeout de rede).
    with Scrapper() as scrapper:
        scrapper.open_page(url)
        page_title = scrapper.get_page_title().replace(" ", "_")
        debug("{} -> Página 1 aberta".format(page_title))
        filename = unidecode.unidecode(page_title)
        info("{} -> Abrindo o arquivo".format(filename))

        # BUG CORRIGIDO: `directory` já é um caminho absoluto completo
        # (os.getcwd() + "/reviews/{begin_time}"). O código original
        # formatava de novo como "reviews/{directory}/...", duplicando o
        # prefixo "reviews/" e resultando num caminho que nunca existia
        # (FileNotFoundError na hora de abrir o CSV).
        csv_path = os.path.join(directory, "{}.csv".format(filename))
        file = open(csv_path, "w", newline="", encoding="utf-8")
        dict_to_csv_writer = start_csv_writer(file)

        info("{} -> Iniciando o scraping".format(page_title))
        scrap_url(
            scrapper=scrapper,
            csv_writer=dict_to_csv_writer,
            page_title=page_title
        )

        info("{} -> Fechando o arquivo".format(page_title))
        file.close()

    beep("done")
    info("DONE -----> {} terminada em {} segundos".format(page_title, url_timer.stop()))


def main():
    with open("urls.txt", 'r') as urls_file:
        urls = urls_file.readlines()

    begin_time = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    directory = os.getcwd() + "/reviews/{}".format(begin_time)
    os.makedirs(directory)
    with futures.ThreadPoolExecutor(THREADS) as executor:
        debug("Dentro da threadpool")
        future_results = {url: executor.submit(
            url_task, url, directory) for url in urls}
        for url, future in future_results.items():
            debug("Checando o resultado de {}".format(url))
            try:
                future.result()
            except Exception as exc:
                error("Thread de {} gerou uma exceção:" .format(url))
                traceback.print_exception(type(exc), exc, exc.__traceback__)


if __name__ == "__main__":
    init_logging()
    main()