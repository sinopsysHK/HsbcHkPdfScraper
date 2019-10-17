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
import camelot
import numpy as np
import re

from .helpers.utils import *
from .helpers.accountstatement import *

logger = logging.getLogger("hsbcpdf.statements")


class Base:

    st_type = None

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
            'type' : self.st_type,
            'main_account': self.account_number,
            'statement_date': self.st_date,
            'previous_balance': {},
            'new_balance': {},
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

    st_type = "BANK"

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
        super().__init__(pdfpath, pdf)
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
        super().merge_all()
        self.statement['new_balance'] = {
            acc: {
                ccy : vals['ccy']
                for ccy, vals in ccys.items()
            }
            for acc, ccys in self.ptfsum_zone.summary['new_acc_balances'].items()
        }

        for v in self.zones.values():
            for k in v.statement['previous_balance'].keys():
                self.statement['previous_balance'][k] = v.statement['previous_balance'][k]
            self.statement['entries'] = self.statement['entries'] + v.statement['entries']


class Card(Base):

    st_type = "CARD"

    OPENING_BAL = "OPENING BALANCE"
    PREVIOUS_BAL = "PREVIOUS BALANCE"
    CLOSING_BAL = "CLOSING BALANCE"
    STMT_BAL = "STATEMENT BALANCE"

    ph_acc_number = TextBox(page=1, bbox="325,681,561,694")
    ph_st_date = TextBox(page=1, bbox="326,633,446,649")
    ph_st_currency = TextBox(page=1, bbox="477,600,566,616")
    page1_tabbox = "60,617,570,339"
    pagex_tabbox = "60,666,570,77"
    columns = "97, 135, 477"

    def _extract_amount(self, samount):
        res = - float(samount.replace(",","").replace("CR",""))
        if "CR" in samount:
            res = -res
        return res

    def _extract_date(self, strdt):
        res = datetime.datetime.strptime(strdt + str(self.st_date.year), '%d%b%Y')
        if res > self.st_date:
            res = res.replace(year=self.st_date.year - 1)
        return res

    def __init__(self, pdfpath, pdf=None):
        Base.__init__(self, pdfpath, pdf)
        self.old_balance = None
        self.new_balance = None
        self.entries = None

    def match_template(self):
        super().match_template()

        # get statement related account number
        self.account_number = self.ph_acc_number.query(self.pdf)

        #get statement date
        strdate = self.ph_st_date.query(self.pdf)
        self.st_date = datetime.datetime.strptime(strdate, '%d %b %Y')
        self.currency = re.search('Amount +\((?P<currency>[A-Z]{3})\)$', self.ph_st_currency.query(self.pdf).strip()).group('currency')
        logger.info("process card statement of {} on {}".format(self.account_number, self.st_date))

    def extract_tables(self):
        tp = camelot.read_pdf(
            self.pdfpath,
            pages="1",
            flavor="stream",
            table_areas=[self.page1_tabbox],
            columns=[self.columns]
        )[0].df[1:]
        others = camelot.read_pdf(
            self.pdfpath,
            pages="2-end",
            flavor="stream",
            table_areas=[self.pagex_tabbox],
            columns=[self.columns]
        )
        for i in others:
            tp = pd.concat([tp, i.df[1:]])
        logger.debug(f'full table: {tp.to_string()}')
        tp = tp.apply(lambda x: x.str.strip())
        tp = pd.concat([tp, tp.iloc[:, [0, 2, 3]].shift(-1)], axis=1)[tp[3] != ""]
        tp.columns = ['post_date', 'transaction_date', 'desc', 'amount', 'nextpostD', 'nextdesc', 'nextamount']
        tp.iloc[-1]['nextdesc'] = ""
        tp['description'] = tp.apply(
            lambda row: " ".join([row.desc, row.nextdesc]) if row.post_date != "" and row.nextpostD == "" and row.nextamount == "" else row.desc,
            #concat_desc,
            axis=1
        )
        logger.debug(f'full concat table columns: {tp.columns}')
        logger.debug("full concat table: {}".format(tp[['post_date', 'desc', 'description', 'amount', 'nextpostD', 'nextdesc', 'nextamount']].to_string()))

        # First row must contains previous balance
        if tp.iloc[0]['description'] not in (self.OPENING_BAL, self.PREVIOUS_BAL):
            raise TemplateException(
                "First line of table should be '{}' instead of {}".format(self.PREVIOUS_BAL, tp.iloc[0]['description']))
        self.old_balance = self._extract_amount(tp.iloc[0]['amount'])

        # Last Row should contain statement balance
        if tp.iloc[-1]['description'] not in (self.CLOSING_BAL, self.STMT_BAL):
            raise TemplateException(
                "Last line of table should be '{}' instead of {}".format(self.STMT_BAL, tp.iloc[-1]['description']))
        self.new_balance = self._extract_amount(tp.iloc[-1]['amount'])

        self.entries = tp[['post_date', 'transaction_date', 'description', 'amount']][1:-1]
        self.entries['post_date'] = self.entries['post_date'].apply(self._extract_date)
        self.entries['transaction_date'] = self.entries['transaction_date'].apply(self._extract_date)
        self.entries['amount'] = self.entries['amount'].apply(self._extract_amount)
        self.entries['currency'] = self.currency
        self.entries['account'] = 'default'
        logger.debug("final table: {}".format(self.entries.to_string()))

    def check_consistency(self):
        tot = self.old_balance
        tot +=  self.entries['amount'].sum()
        if round(tot, 2) != round(self.new_balance, 2):
            raise ConsistencyException(
                "Mismatching balance {}/{} ({} diff)".format(
                    round(tot, 2),
                    round(self.new_balance, 2),
                    round(self.new_balance - tot, 2)
                )
            )

    def merge_all(self):
        super().merge_all()
        self.statement['previous_balance'] = {'default': {self.currency: self.old_balance}}
        self.statement['new_balance'] = {'default': {self.currency: self.new_balance}}
        self.statement['entries'] = self.entries.to_dict('record')


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
