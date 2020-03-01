import logging
import os, sys
from pathlib import Path

from .helpers import utils
from .helpers import accountstatement
from .hsbchk.statements import HsbcFactory
from .societegenerale.statements import SocgenFactory
from .hsbcfr.statements import HsbcFrFactory

class ScraperFactory(accountstatement.BaseFactory):
    _factories = [ HsbcFactory, SocgenFactory, HsbcFrFactory ]

    @classmethod
    def get_scraper(cls, pdfpath):
        for f in cls._factories:
            s = f.get_scraper(pdfpath)
            if s:
                return s
        raise utils.UnrecognizedException(f'"{pdfpath}" unrecognized Statement format')


if __name__ == "__main__":
    logger = logging.getLogger('hsbcpdf.scraper')
    logging.basicConfig(level=logging.WARNING)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)

    logger.setLevel(logging.INFO)

    pdfpath = sys.argv[1]
    outputdir = Path(sys.argv[2] if len(sys.argv) > 2 else ".\\outputs\\")
    st = ScraperFactory.get_scraper(pdfpath).process()
    df = st.get_df()
    logger.debug(df.head())
    df.to_csv(outputdir / f'{st.st_type}-{st.account_number}-{st.st_date.strftime("%Y%m")}.csv', index=False)
