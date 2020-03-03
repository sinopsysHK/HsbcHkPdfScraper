#-------------------------------------------------------------------------------------------
# PDF HSBC FR Account statement Scraper
#-------------------------------------------------------------------------------------------
import sys
import logging
import datetime
import json
import tempfile
import pathlib
import math

#import matplotlib.pyplot as plt
import pandas as pd
from pdfquery.cache import FileCache
import pdfquery
import pdfminer
from PyPDF2.utils import PdfReadError
import camelot
import numpy as np
import re

from hsbcpdf.helpers.utils import *
from hsbcpdf.helpers.accountstatement import *

logger = logging.getLogger("hsbcpdf.hsbcfr.statements")




class HsbcFrStatement(BaseStatement):

    st_bank = 'hsbcfr'

    _BANK_SIGNATURE = [
        TextLabel("www.hsbc.fr")
    ]

    st_type = None
    _TYPE_SIGNATURE = []

    PREVIOUS_BAL = "SOLDE DE DEBUT DE PERIODE"
    NEW_BAL = "SOLDE DE FIN DE PERIODE"

    ph_acc_number = TextBox(page=1, bbox="410,782,570,799")
    ph_st_date = TextBox(
        page=1,
        bbox="420,765,568,788",
        above=TextLabel(text="envoi n°", first=True))

    # ph_st_currency = TextBox(page=1, bbox="477,600,566,616")
    ph_head_sect = None
    ph_begin_sect = TextLabel(text="RELEVÉ DES OPÉRATIONS", height=13)
    ph_end_section = TextLabel(text="TOTAUX DES MOUVEMENTS", height=10)
    ph_end_section_bis = TextLabel(text=NEW_BAL, height=10)
    ph_new_bal_lab = TextLabel(text=NEW_BAL, height=10)
    ph_new_bal_rect = HLine(xleft=400, xright=570, hmin=1, hmax=1.5)
    ph_tab_footer = HLine(xleft=40, xright=562, hmin=0.1, hmax=3, wmin=498)
    ph_tab_columns = VLine(yup=800, ybot=0, hmin=10)
    new_bal_bbox = Bbox(xleft=415, xright=570, ytop=0, ybot=10)
    page1_tabbox = Bbox(xleft=25, xright=570, ytop=505, ybot=125)
    pagex_tabbox = Bbox(xleft=25, xright=570, ytop=700, ybot=84)
    columns = "78, 130, 413, 489"

    st_columns = []
    fl_skip_first_tab_raw = False
    fl_start_prev_balance = False
    fl_end_new_balance = False
    fl_end_sec_excluded = True
    rows_to_remove=[]

    def _find_columns(self):
        footer = self.ph_tab_footer.querys(self.pdf, page=1)
        footer = footer[-1]
        ph_head_sect = self.ph_head_sect.query(self.pdf, page=1)

        tab_vl = HLine(0, 595, 0, 0.8, 20).querys(self.pdf, page=1, before=footer, after=ph_head_sect)
        yl = sorted(list(dict.fromkeys([e.yup for e in tab_vl])), reverse=True)
        cols = VLine(yup=yl[0] + 1, ybot=yl[1] - 1, hmin=10, wmin=0, wmax=0.8).querys(self.pdf, page=1)
        xcols = sorted(list(dict.fromkeys([e.layout.x0 for e in cols])))
        self.page1_tabbox.xleft = self.pagex_tabbox.xleft = xcols[0]
        self.page1_tabbox.xright = self.pagex_tabbox.xright = xcols[-1]
        self.page1_tabbox.ybot = ybot = tab_vl[1].yup
        self.columns = ",".join(map(str, xcols[1:-1]))

    def __init__(self, pdfpath, pdf=None):
        BaseStatement.__init__(self, pdfpath, pdf)
        self.logger = logging.getLogger('hsbcpdf.societegenrale.statements.base')
        self.accounts = []
        self.old_balance = {}
        self.new_balance = {}
        self.entries = None
        self.currency = 'EUR'


    def _hackdirtypdf(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cleanpdfpath= pathlib.Path(self.tmpdir.name) / 'currentpdf.pdf'
        with self.cleanpdfpath.open('wb') as target:
            with open(self.pdfpath, 'rb') as src:
                inc = 0
                self.logger.debug("patch pdf file")
                ref = '%%EOF'
                idx = -1
                while True:
                    inc += 1
                    ccar = src.read(1)
                    if not ccar:
                        break
                    #if ord(ccar):
                    #    self.logger.debug("process(%d)  [%02x]", inc, ord(ccar))
                    if ord(ccar) == ord(ref[idx+1]):
                        idx += 1
                    else:
                        idx = -1
                    target.write(ccar)
                    if idx + 1 == len(ref):
                        break
        self.intialpath=self.pdfpath
        self.pdfpath=str(self.cleanpdfpath)



    def _find_top(self):
        # called only if pages>1
        lines = HLine(0, 595, 0, 1, 20).querys(self.pdf, page=2)
        self.pagex_tabbox.ytop = lines[0].yup

    def _extract_amount(self, debit, credit):
        if not debit and not credit:
            return None
        amount = 0.0
        if debit:
            amount -= float(debit.replace("-", "").replace(".", "").replace(",", ".").replace("*", ""))
        if credit:
            amount += float(credit.replace(".", "").replace(",", ".").replace("*", ""))
        return amount

    def _extract_date(self, strdt):
        return datetime.datetime.strptime(strdt, '%d.%m.%y')

    def _extract_entry_date(self, strdt):
        return self._extract_date(strdt)

    def extract_tables(self):
        begin_section = self.ph_begin_sect.query(self.pdf)
        footers = self.ph_tab_footer.querys(self.pdf, after=begin_section, page=1)
        for idx, f in enumerate(footers):
            self.logger.debug("footer {} at {}".format(idx, f.obj.layout))
        # table always ends with complete row and final line before footer line
        footer = footers[-1]
        end_section = self.ph_end_section.query(self.pdf)
        if not end_section:
            end_section = self.ph_end_section_bis.query(self.pdf)
            self.fl_end_sec_excluded = True

        # get columns
        self._find_columns()
        self.logger.debug("columns found: {}".format(self.columns))

        self.entries = self._extract_tables(self.account_number, begin_section, end_section, footer)

    def _extract_tables(self, account, begin_section, end_section, footer):
        entries = None
        first_bbox = Bbox(
            orig=self.page1_tabbox if begin_section.page == 1 else self.pagex_tabbox,
            ytop=begin_section.yup - 2,
            ybot=footer.ybot + 2
        )

        self.logger.debug("Table ends page {} with y={}".format(end_section.page, end_section.yup - 1 if self.fl_end_sec_excluded else end_section.ybot -2))
        if end_section.page == begin_section.page:
            first_bbox.ybot = end_section.yup - 1 if self.fl_end_sec_excluded else end_section.ybot -2
        self.logger.debug("extract first tab in {}".format(first_bbox))
        tp = None
        try:
            tp = camelot.read_pdf(
                self.pdfpath,
                pages="1",
                flavor="stream",
                table_areas=[first_bbox.to_camellot_bbox()],
                columns=[self.columns],
                strip_text='*' #,
                #row_tol=5
            )
        except PdfReadError:
            self.logger.debug("dirty PDF: try hack")
            self._hackdirtypdf()
            tp = camelot.read_pdf(
                self.pdfpath,
                pages="1",
                flavor="stream",
                table_areas=[first_bbox.to_camellot_bbox()],
                columns=[self.columns],
                strip_text='*'  # ,
                # row_tol=5
            )
        tp = tp[0].df[1 if self.fl_skip_first_tab_raw else 0:]
        self.logger.debug(f'First trunck of table: \n{tp.to_string()}')

        if end_section.page > begin_section.page:
            self._find_top()
            if end_section.page > begin_section.page + 1:
                others = camelot.read_pdf(
                    self.pdfpath,
                    pages="2-{}".format(end_section.page - 1),
                    flavor="stream",
                    table_areas=[self.pagex_tabbox.to_camellot_bbox()],
                    columns=[self.columns],
                    strip_text='*',
                    row_tol=5
                )
                for i in others:
                    tp = pd.concat([tp, i.df[1 if self.fl_skip_first_tab_raw else 0:]])
                    self.logger.debug(
                        f'Next trunck of table [{self.pagex_tabbox.ytop} - {self.pagex_tabbox.ybot}]: \n{i.df.to_string()}')

            last_tab_bbox = Bbox(orig=self.pagex_tabbox, ybot=end_section.yup - 1 if self.fl_end_sec_excluded else end_section.ybot -2)
            last_tab = camelot.read_pdf(
                self.pdfpath,
                pages=str(end_section.page),
                flavor="stream",
                table_areas=[last_tab_bbox.to_camellot_bbox()],
                columns=[self.columns],
                strip_text='*',
                row_tol=5
            )[0].df[1 if self.fl_skip_first_tab_raw else 0:]
            tp = pd.concat([tp, last_tab])
            self.logger.debug(
                f'Last trunck of table (page:{end_section.page} in {last_tab_bbox.to_camellot_bbox()}): \n{last_tab.to_string()}')

        tp.columns = self.st_columns
        for r in self.rows_to_remove:
            if 'txt' in r:
                tp = tp[~tp[r['column']].str.contains(r['txt'])]
            if 'regexp' in r:
                tp = tp[~tp[r['column']].str.match(r['regexp'])]

        tp = tp.apply(lambda x: x.str.strip())
        tp['amount'] = tp.apply(
            lambda r: self._extract_amount(r['debit'].replace(' ', ''), r['credit'].replace(' ', ''))
            , axis=1
        )
        self.logger.debug(f'full table: \n{tp.to_string()}')
        self.logger.debug(f'full concat table columns: {tp.columns}')

        # First row must contains previous balance
        if self.fl_start_prev_balance:
            if self.PREVIOUS_BAL not in tp.iloc[0]['description']:
                raise TemplateException(
                    "First line of table should be '{}' instead of {}".format(self.PREVIOUS_BAL, tp.iloc[0]['description']))
            self.old_balance[account] = tp.iloc[0]['amount']
            tp = tp[1:]

        if self.fl_end_new_balance:
            # Last Row should contain statement balance
            if self.NEW_BAL not in tp.iloc[-1]['description']:
                raise TemplateException(
                    "Last line of table should be '{}' instead of {}".format(self.NEW_BAL, tp.iloc[-1]['description']))
            last_amount = tp.iloc[-1]['amount']
            self.new_balance[account] = 0.0 if math.isnan(last_amount) else last_amount
            tp = tp[:-1]

        if tp.empty:
            self.logger.info("No entries to extract in this statement")
            entries= tp[['post_date', 'transaction_date', 'description', 'amount']]
            entries['currency'] = self.currency
            entries['account'] = account
            return

        if 'transaction_date' not in self.st_columns:
            # assume transaction_date = post date if not provided
            tp['transaction_date'] = tp['post_date']

        entries = tp[['post_date', 'transaction_date', 'description', 'amount']]
        entries['idx'] = entries.reset_index().index
        select = entries['post_date'].eq("")
        entries.loc[select, ['idx', 'post_date', 'transaction_date']] = None
        # entries.loc[select, 'idx'] = None
        entries[['idx', 'post_date', 'transaction_date', 'amount']] = entries[
            ['idx', 'post_date', 'transaction_date', 'amount']].fillna(method='ffill')
        self.logger.debug("before merge table: \n{}".format(entries.to_string()))
        entries = entries.groupby(['idx', 'post_date', 'transaction_date', 'amount'])['description'].apply(
            '\n'.join).reset_index()
        self.logger.debug("merge table: \n{}".format(entries.to_string()))
        entries['transaction_date'] = entries.apply(lambda r: r['transaction_date'] or r['post_date'], axis=1)
        entries['post_date'] = entries['post_date'].apply(self._extract_entry_date)
        entries['transaction_date'] = entries['transaction_date'].apply(self._extract_entry_date)
        entries['currency'] = self.currency
        entries['account'] = account
        entries = entries.drop('idx', axis=1)

        self.logger.debug("final table: {}".format(entries.to_string()))
        return entries

    def check_consistency(self):
        for acc in self.accounts:
            tot = self.old_balance[acc]
            tot += self.entries.loc[self.entries['account'].eq(acc)]['amount'].sum()
            if round(tot, 2) != round(self.new_balance[acc], 2):
                raise ConsistencyException(
                    "Mismatching balance on acc [{}] {}/{} ({} diff)".format(
                        acc,
                        round(tot, 2),
                        round(self.new_balance[acc], 2),
                        round(self.new_balance[acc] - tot, 2)
                    )
                )

    def merge_all(self):
        super().merge_all()
        for acc in self.accounts:
            self.statement['previous_balance'][acc] = {self.currency: self.old_balance[acc]}
            self.statement['new_balance'][acc] = {self.currency: self.new_balance[acc]}
        self.statement['entries'] = self.entries.to_dict('record')

class Account(HsbcFrStatement):

    st_type = "BANK"
    _TYPE_SIGNATURE = [ TextLabel("Votre Relevé de Compte") ]

    PREVIOUS_BAL = "SOLDE PRÉCÉDENT"
    NEW_BAL = "NOUVEAU SOLDE"
    
    ph_acc_number = TextBox(page=1, bbox="410,782,570,799")
    ph_st_date = TextBox(
        page=1,
        bbox="420,765,568,788",
        above=TextLabel(text="envoi n°",first=True))
    
    #ph_st_currency = TextBox(page=1, bbox="477,600,566,616")
    ph_begin_sect = TextLabel(text="RELEVÉ DES OPÉRATIONS", height=13)
    ph_end_section = TextLabel(text="TOTAUX DES MOUVEMENTS", height=10)
    ph_new_bal_lab = TextLabel(text=NEW_BAL, height=10)
    ph_new_bal_rect = HLine(xleft = 400, xright = 570, hmin = 1, hmax = 1.5)
    ph_tab_footer = HLine(xleft = 20, xright = 575, hmin = 0.1, hmax = 1, wmin=500)
    ph_tab_columns = VLine(yup=800, ybot=0, hmin=10)
    new_bal_bbox  = Bbox(xleft=415, xright=570, ytop=0, ybot=10)
    page1_tabbox = Bbox(xleft=25, xright=570, ytop=505, ybot=125)
    pagex_tabbox = Bbox(xleft=25, xright=570, ytop=700, ybot=84)
    columns = "78, 130, 413, 489"

    fl_start_prev_balance = True
    st_columns = ['post_date', 'transaction_date', 'description', 'debit', 'credit']
    rows_to_remove = [
        {'column': 'credit', 'txt':"suite >>>"},
        {'column': 'description', 'txt': "SOLDE AU"}
    ]

    def _find_columns(self):
        footer = HLine(0, 595, wmin=500, ymax=90).querys(self.pdf, page=1)
        footer = footer[-1]
        ph_begin_sect = TextLabel(text="SOLDE PRÉCÉDENT", height=10).query(self.pdf, page=1)

        tab_vl = HLine(0, 595, 0, 0.8, 500).querys(self.pdf, page=1, before=footer, after=ph_begin_sect)
        cols = VLine(yup=tab_vl[0].yup + 1, ybot=tab_vl[1].ybot - 1, hmin=10, wmin=0, wmax=0.8).querys(self.pdf, page=1)
        xcols = sorted(list(dict.fromkeys([e.layout.x0 for e in cols])))
        self.page1_tabbox.xleft = self.pagex_tabbox.xleft = xcols[0]
        self.page1_tabbox.xright = self.pagex_tabbox.xright = xcols[-1]
        self.page1_tabbox.ybot = ybot=tab_vl[1].yup
        self.columns = ",".join(map(str, xcols[1:-1]))

    def __init__(self, pdfpath, pdf=None):
        HsbcFrStatement.__init__(self, pdfpath, pdf)
        self.logger = logging.getLogger('hsbcpdf.societegenrale.statements.account')

    def match_template(self):
        super().match_template()

        # get statement related account number
        self.account_number = re.search("(\d[ \d]+\d)", self.ph_acc_number.query(self.pdf).strip()).group(1)

        # get statement date
        strdate = re.search("du .* au (.*)", self.ph_st_date.query(self.pdf).strip()).group(1)
        self.st_date = self._extract_date(strdate)

        # get new balance
        new_bal_lab = self.ph_new_bal_lab.query(self.pdf)
        line_up = self.ph_new_bal_rect.query(self.pdf, page=new_bal_lab.page, before=new_bal_lab)
        self.logger.debug("found upper line {}".format(line_up.ybot))
        line_bot = self.ph_new_bal_rect.querys(self.pdf, page=new_bal_lab.page, after=new_bal_lab)[0]
        self.logger.debug("found lower line {}".format(line_bot.yup))
        self.new_bal_bbox.ytop = line_up.yup
        self.new_bal_bbox.ybot = line_bot.ybot
        newbalstr = TextBox(page=new_bal_lab.page, bbox=self.new_bal_bbox).query(self.pdf)
        self.logger.info("found new balance string {}".format(newbalstr))
        self.new_balance = self._extract_amount(None, newbalstr.replace(' ', '').strip())

        self.logger.info("process card statement of {} on {} with new balance {}EUR".format(
            self.account_number,
            self.st_date,
            self.new_balance
        ))


class Card(HsbcFrStatement):

    st_type = "CARD"
    _TYPE_SIGNATURE = [ TextLabel("Votre Relevé de Carte", first=True) ]

    PREVIOUS_BAL = None
    NEW_BAL = "TOTAL FACTURE"

    ph_st_date_lab = TextLabel(text="Relevé cartes bancaires au", first=True)
    ph_pay_date_lab = TextLabel(text="TOTAL IMPUTE A VOTRE COMPTE LE", first=True)

    # ph_st_currency = TextBox(page=1, bbox="477,600,566,616")
    ph_head_sect = ph_pay_date_lab
    ph_begin_sect = TextLabel(text="CARTE N°")
    ph_end_section = TextLabel(text=NEW_BAL, height=13)
    ph_new_bal_lab = TextLabel(text=NEW_BAL, height=13)
    ph_new_bal_rect = HLine(xleft=400, xright=570, hmin=1, hmax=1.5)
    ph_tab_footer = HLine(xleft=20, xright=575, hmin=0.1, hmax=1, wmin=500)
    ph_tab_columns = VLine(yup=800, ybot=0, hmin=10)
    new_bal_bbox = Bbox(xleft=415, xright=570, ytop=0, ybot=10)
    page1_tabbox = Bbox(xleft=25, xright=570, ytop=505, ybot=125)
    pagex_tabbox = Bbox(xleft=25, xright=570, ytop=700, ybot=84)
    columns = "105, 385, 470"

    st_columns = ['post_date', 'description', 'debit', 'credit']
    fl_end_sec_excluded = False
    fl_skip_first_tab_raw = True
    rows_to_remove = [
        {'column': 'description', 'txt': "Opérations effectuées"},
        {'column': 'credit', 'txt':"suite >>>"},
        {'column': 'credit', 'regexp': r'\d/\d'}
    ]
    fl_end_new_balance = True

    def __init__(self, pdfpath, pdf=None):
        HsbcFrStatement.__init__(self, pdfpath, pdf)
        self.logger = logging.getLogger('hsbcpdf.societegenrale.statements.card')

    def _extract_entry_date(self, strdt):
        return datetime.datetime.strptime(strdt, '%d.%m.%y')

    def _extract_acc_number(self, acc_number):
        self.logger.debug("acc number [%s]", acc_number.obj.layout.get_text().strip())
        return re.search("CARTE N° (\d{4} \d\dXX XXXX \d{4})", acc_number.obj.layout.get_text().strip()).group(1)

    def match_template(self):
        super().match_template()

        # get statement date
        st_date_lab = self.ph_st_date_lab.query(self.pdf, page=1)
        check_date = re.search("(\d\d.\d\d.\d\d)$", st_date_lab.obj.layout.get_text())
        if check_date:
            self.st_date = self._extract_date(check_date.group(1))
        else:
            strdate = TextBox(
                page=1,
                bbox=Bbox(xleft=480,
                          xright=585,
                          ybot=st_date_lab.ybot - 3,
                          ytop=st_date_lab.yup + 3
                          )
            ).query(self.pdf)
            self.st_date = self._extract_date(re.search("(\d\d.\d\d.\d\d)$", strdate).group(1))


        self.logger.info("process card statement of {} on {}".format(
            self.account_number,
            self.st_date
        ))

    def extract_tables(self):
        begin_sections = self.ph_begin_sect.querys(self.pdf)
        footers = self.ph_tab_footer.querys(self.pdf, after=begin_sections[0], page=1)
        for idx, f in enumerate(footers):
            self.logger.debug("footer {} at {}".format(idx, f.obj.layout))
        # table always ends with complete row and final line before footer line
        footer = footers[-1]
        end_sections = self.ph_end_section.querys(self.pdf)
        if not end_sections:
            end_sections = self.ph_end_section_bis.querys(self.pdf)
            self.fl_end_sec_excluded = True

        if len(begin_sections) != len(end_sections):
            raise TemplateException("We should have as many total lines as credit cards")

        # get columns
        self._find_columns()
        self.logger.debug("columns found: {}".format(self.columns))

        entries = []
        for begin, end in zip(begin_sections, end_sections):
            account = self._extract_acc_number(begin)
            self.accounts.append(account)
            self.old_balance[account] = 0.0
            entries.append(
                self._extract_tables(
                    account,
                    begin,
                    end,
                    footer
                )
            )
        self.entries = pd.concat(entries)

class HsbcFrFactory(BaseFactory):
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
