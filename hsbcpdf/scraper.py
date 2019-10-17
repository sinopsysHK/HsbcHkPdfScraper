import logging
import os, sys
from pathlib import Path

from pdfquery.cache import FileCache
import pdfquery
import pdfminer

from hsbcpdf.helpers import utils
from hsbcpdf import statements

logger = logging.getLogger('hsbcpdf.scraper')

STATEMENTS = [
    (utils.TextLabel("Card type", first=True), statements.Card),
    (utils.TextLabel("Financial Overview"), statements.Account)
]


def get_statement(pdfpath):
    if not os.path.exists(pdfpath):
        raise utils.ScraperException(f'"{pdfpath}" file not found')
    if not os.path.isfile(pdfpath):
        raise utils.ScraperException(f'"{pdfpath}" not a file')
    pdf = pdfquery.PDFQuery(pdfpath)
    pdf.load()
    for tl, gen in STATEMENTS:
        if tl.query(pdf) is not None:
            return gen(pdfpath, pdf).process()
    logger.error("provided pdf not recognized as HSBC HK (card or account) Statement")
    raise utils.ScraperException(f'"{pdfpath}" not recognized as a HSBC HK (card or account) Statement')

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)

    logger.setLevel(logging.INFO)

    pdfpath = sys.argv[1]
    outputdir = Path(sys.argv[2] if len(sys.argv) > 2 else ".\\outputs\\")
    st = get_statement(pdfpath)
    df = st.get_df()
    logger.debug(df.head())
    df.to_csv(outputdir / f'{st.st_type}-{st.account_number}-{st.st_date.strftime("%Y%m")}.csv', index=False)
