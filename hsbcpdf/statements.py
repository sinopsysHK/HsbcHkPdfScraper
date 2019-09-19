#-------------------------------------------------------------------------------------------
# PDF HSBC Account statement (Hong Kong) Scraper
#-------------------------------------------------------------------------------------------
import sys
import logging
import datetime
import json
#import matplotlib.pyplot as plt
import pandas as pd
from pdfquery.cache import FileCache
import pdfquery
import pdfminer

from .helpers.utils import *
from .helpers.accountstatement import *

logger = logging.getLogger("hsbcpdf.statements")


class Base:

    def __init__(self, pdfpath, pdf = None):
        self.pdfpath = pdfpath
        self.pdf = pdf
        if self.pdf is None:
            self.pdf = pdfquery.PDFQuery(pdfpath)
            self.pdf.load()

        self.page_height = None
        self.page_width = None
        self.account_number = None
        self.st_date = None

    def match_template(self):
        # get file pages format
        p = self.pdf.pq('LTPage[page_index="0"]')[0]
        self.page_height = p.layout.height
        self.page_width = p.layout.width

    def extract_tables(self):
        pass

    def check_consistency(self):
        pass

    def merge_all(self):
        self.statement = {
            'main_account': self.account_number,
            'statement_date': self.st_date,
            'previous_balance': {},
            'entries': []
        }

    def process(self):
        self.match_template()
        self.extract_tables()
        self.check_consistency()
        self.merge_all()
        return self

    def get_df(self):
        df = pd.DataFrame(self.statement['entries'])
        df['st_date'] = self.st_date
        df['main_account'] = self.account_number
        df['file_path'] = self.pdfpath
        return df

    def get_json(self):
        def myconverter(o):
            if isinstance(o, datetime.datetime):
                return o.strftime("%d/%m/%Y")

        return json.dumps(self.statement, default = myconverter)


class Account(Base):

    ph_acc_number = TextBox(page=1, bbox="486,700,538,712")
    ph_st_date = TextBox(page=1, bbox="394,651,538,660")
    ph_ptfsum_section = TextLabel(text="Portfolio Summary", height=10)
    ph_top_section = TextLabel(text="HSBC Premier Account Transaction History", height=10)
    # consecutive sections containing tables
    ph_sections = {
        AccountTypes.HKDSAVINGS: TextLabel(text="HKD Savings", height=9),
        AccountTypes.HKDCURRENT: TextLabel(text="HKD Current", height=9),
        AccountTypes.FCYSAVINGS: TextLabel(text="Foreign Currency Savings", height=9),
        AccountTypes.FCYCURRENT: TextLabel(text="Foreign Currency Current", height=9),
    }
    zone_types = {
        AccountTypes.HKDSAVINGS: TableZoneHkd,
        AccountTypes.HKDCURRENT: TableZoneHkd,
        AccountTypes.FCYSAVINGS: TableZoneFcy,
        AccountTypes.FCYCURRENT: TableZoneFcy,
    }
    ph_end_section = TextLabel(text="Total Relationship Balance", height=10)
    ph_fend_section = TextLabel(text="Important Notice", height=10)

    def __init__(self, pdfpath, pdf = None):
        Base.__init__(self, pdfpath, pdf)
        self.ptfsum_zone = None
        self.zones = {}

    def match_template(self):
        Base.match_template(self)

        # get statement related account number
        self.account_number = Account.ph_acc_number.query(self.pdf)

        #get statement date
        strdate = Account.ph_st_date.query(self.pdf)
        logger.info("process statement of {} on {}".format(self.account_number, strdate))
        self.st_date = datetime.datetime.strptime(strdate, '%d %B %Y')

        # get structuring sections
        ptfsum_section = Account.ph_ptfsum_section.query(self.pdf)
        if ptfsum_section is None:
            raise TemplateException(f'Portfolio summary section "{Account.ph_ptfsum_section.text}" not found in statement')

        top_section = Account.ph_top_section.query(self.pdf)
        if top_section is None:
            raise TemplateException(f'Top section "{Account.ph_top_section.text}" not found in statement')

        end_section = Account.ph_end_section.query(self.pdf)
        if end_section is None:
            # On first statement there is no Total relationship balance so fallback on Important Notice
            end_section = Account.ph_fend_section.query(self.pdf)
            if end_section is None:
                raise TemplateException(
                    f'End section "{Account.ph_end_section.text}" and "{Account.ph_fend_section.text}" not found in statement')
        if end_section.yup > 679:
            # if end section is top of page force it as bottom of previous page
            end_section.page = end_section.page - 1
            end_section.yup = 69
            end_section.ybot = 69

        sections = {}
        available_sections = [end_section]
        for k,v in Account.ph_sections.items():
            res = v.query(self.pdf, after=top_section, before=end_section)
            if res is not None:
                sections[k] = res
                available_sections.append(res)
                logger.debug(f'section [{k}] ("{v.text}"") found: {res}')
            else:
                logger.warning(f'Section [{k}] ("{v.text}"") not found in statement')
        # set ending of each sections
        ptfsum_section.next = top_section
        logger.debug(f'section Summary:{ptfsum_section}')
        self.ptfsum_zone = TableZoneSum(self.page_height, self.page_width, ptfsum_section, 'summary', self.st_date)
        self.ptfsum_zone.get_tables_format(self.pdf)
        logger.debug("proceed accounts sections...")
        for k, v in sections.items():
            next = v.get_next(available_sections)
            available_sections.remove(next)
            logger.debug(f'section {k}:{v} followed by {next}')
            self.zones[k] = Account.zone_types[k](self.page_height, self.page_width, v, k, self.st_date)
            self.zones[k].get_tables_format(self.pdf)

    def extract_tables(self):
        self.ptfsum_zone.extract_tables(self.pdfpath)
        for k, v in self.zones.items():
            if v is not None:
                v.extract_tables(self.pdfpath)

    def check_consistency(self):
        self.ptfsum_zone.check_consistency(None)
        for v in self.zones.values():
            if v is not None:
                v.check_consistency(self.ptfsum_zone.summary)

    def merge_all(self):
        Base.merge_all(self)
        for v in self.zones.values():
            for k in v.statement['previous_balance'].keys():
                self.statement['previous_balance'][k] = v.statement['previous_balance'][k]
            self.statement['entries'] = self.statement['entries'] + v.statement['entries']


class Card(Base):
    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)

    pdfpath = sys.argv[1]
    outputdir = sys.argv[2] if len(sys.argv) > 2 else ".\\outputs\\"
    st = Account(sys.argv[1])
    st.process()
    df = st.get_df()
    logger.debug(df.head())
    df.to_csv(outputdir + st.account_number + "-" + st.st_date.strftime("%Y%m") + ".csv", index=False)
