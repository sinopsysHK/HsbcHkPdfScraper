#-------------------------------------------------------------------------------------------
# PDF SocieteGenerale Account statement Scraper
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

from hsbcpdf.helpers.utils import *
from hsbcpdf.helpers.accountstatement import *

logger = logging.getLogger("hsbcpdf.societegenerale.statements")




class SocgenStatement(BaseStatement):

    st_bank = 'societegenrale'

    _BANK_SIGNATURE = [
        TextLabel("Société Générale")
    ]


class Account(SocgenStatement):

    st_type = "BANK"
    _TYPE_SIGNATURE = [ TextLabel("RELEVÉ DE COMPTE") ]
    
    PREVIOUS_BAL = "SOLDE PRÉCÉDENT"
    NEW_BAL = "NOUVEAU SOLDE"
    
    ph_acc_number = TextBox(page=1, bbox="410,782,570,799")
    ph_st_date = TextBox(page=1, bbox="420,765,568,782")
    
    #ph_st_currency = TextBox(page=1, bbox="477,600,566,616")
    ph_end_section = TextLabel(text=NEW_BAL, height=10)
    page1_tabbox = Bbox(xleft=25, xright=570, ytop=509, ybot=95)
    pagex_tabbox = Bbox(xleft=25, xright=570, ytop=700, ybot=95)
    columns = "78, 130, 413, 489"

    
    def _extract_amount(self, debit, credit):
        amount = None
        if debit:
            amount = "-" + debit.replace("-", "")
        elif credit:
            amount = credit
        else:
            return None
        return float(amount.replace(".", "").replace(",", ".").replace("*", ""))

    def _extract_date(self, strdt):
        return datetime.datetime.strptime(strdt, '%d/%m/%Y')

    def __init__(self, pdfpath, pdf=None):
        SocgenStatement.__init__(self, pdfpath, pdf)
        self.logger = logging.getLogger('hsbcpdf.societegenrale.statements.card')
        self.old_balance = None
        self.new_balance = None
        self.entries = None
        self.currency = 'EUR'

    def match_template(self):
        super().match_template()

        # get statement related account number
        self.account_number = re.search("(\d[ \d]+\d)", self.ph_acc_number.query(self.pdf).strip()).group(1)

        #get statement date
        strdate = re.search("du .* au (.*)", self.ph_st_date.query(self.pdf).strip()).group(1)
        self.st_date = datetime.datetime.strptime(strdate, '%d/%m/%Y')
        self.logger.info("process card statement of {} on {}".format(self.account_number, self.st_date))

    def extract_tables(self):
        end_section = self.ph_end_section.query(self.pdf)
        self.logger.debug("Table ends page {} with y={}".format(end_section.page, end_section.yup))
        if end_section.page == 1:
            self.page1_tabbox.ybot = end_section.ybot
        tp = camelot.read_pdf(
            self.pdfpath,
            pages="1",
            flavor="stream",
            table_areas=[self.page1_tabbox.to_camellot_bbox()],
            columns=[self.columns]
        )[0].df[1:]
        self.logger.debug(f'First trunck of table: {tp.to_string()}')

        if end_section.page > 1:
            if end_section.page > 2:
                others = camelot.read_pdf(
                    self.pdfpath,
                    pages="2-{}".format(end_section.page-1),
                    flavor="stream",
                    table_areas=[self.pagex_tabbox.to_camellot_bbox()],
                    columns=[self.columns]
                )
                for i in others:
                    tp = pd.concat([tp, i.df])
                    self.logger.debug(f'Next trunck of table: {i.df.to_string()}')

            self.pagex_tabbox.ybot = end_section.ybot
            last_tab = camelot.read_pdf(
                self.pdfpath,
                pages=str(end_section.page),
                flavor="stream",
                table_areas=[self.pagex_tabbox.to_camellot_bbox()],
                columns=[self.columns]
            )[0].df
            tp = pd.concat([tp, last_tab])
            self.logger.debug(f'Last trunck of table: {last_tab.to_string()}')

        tp.columns = ['post_date', 'transaction_date', 'description', 'debit', 'credit']

        tp = tp.apply(lambda x: x.str.strip())
        tp['amount'] = tp.apply(
            lambda r: self._extract_amount(r['debit'].replace(' ', ''), r['credit'].replace(' ', ''))
            , axis=1
        )
        self.logger.debug(f'full table: {tp.to_string()}')
        self.logger.debug(f'full concat table columns: {tp.columns}')

        # First row must contains previous balance
        if self.PREVIOUS_BAL not in tp.iloc[0]['description']:
            raise TemplateException(
                "First line of table should be '{}' instead of {}".format(self.PREVIOUS_BAL, tp.iloc[0]['description']))
        self.old_balance = tp.iloc[0]['amount']

        if self.NEW_BAL not in tp.iloc[-1]['description']:
            raise TemplateException(
                "Last line of table should be '{}' instead of {}".format(self.NEW_BAL, tp.iloc[-1]['description']))
        self.new_balance = tp.iloc[-1]['amount']

        '''
        # Last Row should contain statement balance
        if tp.iloc[-1]['description'] not in (self.CLOSING_BAL, self.STMT_BAL):
            raise TemplateException(
                "Last line of table should be '{}' instead of {}".format(self.STMT_BAL, tp.iloc[-1]['description']))
        self.new_balance = self._extract_amount(tp.iloc[-1]['amount'])
        '''

        self.entries = tp[['post_date', 'transaction_date', 'description', 'amount']][1:-2]
        self.entries['idx'] = self.entries.reset_index().index
        select = self.entries['post_date'].eq("")
        self.entries.loc[select, ['idx', 'post_date']] = None
        #self.entries.loc[select, 'idx'] = None
        self.entries[['idx', 'post_date', 'amount']] = self.entries[['idx', 'post_date', 'amount']].fillna(method='ffill')
        self.entries = self.entries.groupby(['idx', 'post_date', 'transaction_date', 'amount'])['description'].apply('\n'.join).reset_index()
        self.logger.debug("merge table: \n{}".format(self.entries.to_string()))
        self.entries['transaction_date'] = self.entries.apply(lambda r: r['transaction_date'] or r['post_date'], axis=1)
        self.entries['post_date'] = self.entries['post_date'].apply(self._extract_date)
        self.entries['transaction_date'] = self.entries['transaction_date'].apply(self._extract_date)
        self.entries['currency'] = self.currency
        self.entries['account'] = 'default'
        self.entries = self.entries.drop('idx', axis=1)

        self.logger.debug("final table: {}".format(self.entries.to_string()))

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


class Card(SocgenStatement):

    st_type = "CARD"
    _TYPE_SIGNATURE = [ TextLabel("RELEVÉ CARTE", first=True) ]

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
        SocgenStatement.__init__(self, pdfpath, pdf)
        self.logger = logging.getLogger('hsbcpdf.societegenrale.statements.card')
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
        self.logger.info("process card statement of {} on {}".format(self.account_number, self.st_date))

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
        self.logger.debug(f'full table: {tp.to_string()}')
        tp = tp.apply(lambda x: x.str.strip())
        tp = pd.concat([tp, tp.iloc[:, [0, 2, 3]].shift(-1)], axis=1)[tp[3] != ""]
        tp.columns = ['post_date', 'transaction_date', 'desc', 'amount', 'nextpostD', 'nextdesc', 'nextamount']
        tp.iloc[-1]['nextdesc'] = ""
        tp['description'] = tp.apply(
            lambda row: " ".join([row.desc, row.nextdesc]) if row.post_date != "" and row.nextpostD == "" and row.nextamount == "" else row.desc,
            #concat_desc,
            axis=1
        )
        self.logger.debug(f'full concat table columns: {tp.columns}')
        self.logger.debug("full concat table: {}".format(tp[['post_date', 'desc', 'description', 'amount', 'nextpostD', 'nextdesc', 'nextamount']].to_string()))

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
        self.logger.debug("final table: {}".format(self.entries.to_string()))

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


class SocgenFactory(BaseFactory):
    _scrapers = [Account, Card]


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
