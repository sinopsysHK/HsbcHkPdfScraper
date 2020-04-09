# -----------------------------------------------------------------------------
# Account statement helpers

import logging
import datetime


import camelot
import pandas as pd
import os
import json

from pdfquery.cache import FileCache
import pdfquery
import pdfminer

from .utils import *

logger = logging.getLogger("hsbcpdf.helpers.accountstatements")

class EnumSumAccountTypes:
    HKDSAVINGS = 'HKD Savings'
    HKDCURRENT = 'HKD Current'
    FCYSAVINGS = 'FCY Savings'
    FCYCURRENT = 'FCY Current'

class AccountTypes:
    HKDSAVINGS = 'HKDSavings'
    HKDCURRENT = 'HKDCurrent'
    FCYSAVINGS = 'FCYSavings'
    FCYCURRENT = 'FCYCurrent'


class TableZone:
    __doc__ = "Find table zone and columns positions"

    class Chunk:
        def __init__(self, page, yup, ybot):
            self.page = page
            self.yup = yup
            self.ybot = ybot


    def __init__(self, page_height, page_width, section, account, st_date):
        self.page_height = page_height
        self.page_width = page_width
        self.account = account
        self.st_date = st_date
        self.chunks = []
        self.columns = None
        self.table = None
        self.statement = {'previous_balance': {self.account: {}}, 'new_balance': {self.account: {}}, 'entries': []}
        begin_page = section.page
        begin_yup = section.ybot
        end_page = section.next.page
        end_ybot = section.next.yup
        top_margin = 690
        bottom_margin = 69
        if begin_page == end_page:
            self.chunks.append(TableZone.Chunk(begin_page, begin_yup, end_ybot))
        else:
            self.chunks.append(TableZone.Chunk(begin_page, begin_yup, bottom_margin))
            for i in range(end_page - begin_page -1):
                self.chunks.append(TableZone.Chunk(begin_page + i, self.page_height, bottom_margin))
            if end_ybot < top_margin:
                self.chunks.append(TableZone.Chunk(end_page, self.page_height, end_ybot))
        logger.debug("Section of account '{}' has {} chuncks".format(account, len(self.chunks)))

    def get_tables_format(self, pdf):
        logger.debug("search table hearder for account '{}'".format(self.account))
        for c in self.chunks:
            # seek table header
            # first get large light grey horizontal line
            hl = pdf.pq(
                f'LTPage[page_index="{c.page-1}"] LTLine[height="0.0"]:in_bbox("0, {c.ybot}, {self.page_width}, {c.yup}")'
            ).filter(lambda i: float(this.get('linewidth', 0)) > 10)
            if len(hl) == 0:
                raise TemplateException("could not find Horizontal line of table header (page {} in bbox 0,{}, {}, {})".format(c.page,c.ybot, self.page_width, c.yup))
            hl = hl[0].layout
            linewidth = hl.linewidth
            upper = hl.y0 + (linewidth/2) + 1
            lower = hl.y0 - (linewidth/2) - 1
            c.yup = upper
            # then search separator vertical lines in header
            logger.debug("search table hearder columns for account '{}' in page[{}] bbob[0, {}, {}, {}]".format(self.account, c.page, lower, self.page_width, upper))
            if self.columns is None:
                # do it once as table format is same in each chunks
                self.columns = []
                vls = pdf.pq(
                    f'LTPage[page_index="{c.page-1}"] LTLine[width="0.0"]:in_bbox("0, {lower}, {self.page_width}, {upper}")'
                ).filter(lambda i: float(this.get('linewidth', 0)) < 1)
                if len(vls) == 0:
                    raise TemplateException("could not find Vertical lines of table header (page {} in bbox 0,{}, {}, {})".format(c.page,c.ybot, self.page_width, c.yup))
                for vl in vls:
                    self.columns.append(vl.layout.x0)
                self.columns.sort()
                logger.debug("found these ({}) columns from hearder {}".format(len(self.columns), self.columns))

    def extract_tables(self, pdfpath):
        cols = ','.join(map(str, self.columns))
        for c in self.chunks:
            logger.debug("process table in page[{}] bbox[0,{},{},{}] with columns[{}]".format(c.page, c.ybot, self.page_width, c.yup, cols))
            tables = camelot.read_pdf(
                        pdfpath,
                        pages=str(c.page),
                        flavor="stream",
                        table_areas=[f'0, {c.yup}, {self.page_width}, {c.ybot}'],
                        columns=[cols],
                        split_text=True)
            logger.debug('found tables: {} - {}'.format(tables[0].parsing_report, tables[0].shape))
            if self.table is None:
                self.table = tables[0].df[1:]
            else:
                self.table = pd.concat([self.table, tables[0].df[1:]])
        logger.debug("the table:\n{}".format(self.table.head().to_string()))
        #camelot.plot(tables[0], kind='grid')
        #plt.show()
        self.clean_table()

    def clean_table(self):
        pass

    def extract_date(self, strdt):
        res = datetime.datetime.strptime(strdt + ' ' + str(self.st_date.year), '%d %b %Y')
        if res > self.st_date:
            res = res.replace(year=self.st_date.year - 1)
        return res

    def check_consistency(self, summary):
        new_balances = self.statement['new_balance'][self.account]
        expected_balances = summary['new_acc_balances'][self.account]
        for k,v in new_balances.items():
            if k not in expected_balances.keys():
                if round(v, 2) != 0. :
                    raise ConsistencyException(
                        "Missing non null balance in Summary for [{}({})] {}".format(
                            self.account,
                            k,
                            v
                        )
                    )
            elif round(v, 2) != round(expected_balances[k]['ccy'], 2):
                raise ConsistencyException(
                    "Mismatching balance on [{}({})] {}/{}".format(
                        self.account,
                        k,
                        v,
                        round(expected_balances[k]['ccy'], 2)
                    )
                )


class TableZoneHkd(TableZone):
    def clean_table(self):
        shape = self.table.shape
        logger.debug(shape)
        # get first line as the previous balance
        startidx=1
        previous_balance_tag = self.table.iloc[0,1]
        val = self.table.iloc[0, 4]
        logger.debug("value to use as a float: [{}]".format(val))
        previous_balance = float(val.replace(",", "")) if isinstance(val, str) else val
        if self.table.iloc[0, 5] == 'DR':
            previous_balance = -previous_balance
        if previous_balance_tag != "B/F BALANCE":
            # if first line is not "B/F BALANCE" likely this is the first statement or previous balance was 0
            previous_balance = 0
            startidx = 0
        self.statement['previous_balance'][self.account]['HKD'] = previous_balance

        dt = ""
        desc = ""
        new_balance = previous_balance
        for index, row in self.table.iloc[startidx:, :].iterrows():
            if row[0] != "": dt = self.extract_date(row[0])
            desc = (desc + " " if desc != "" else "") + row[1]
            credit = row[2]
            debit = row[3]
            amount = None

            logger.debug("date[{}] desc[{}] credit[{}] debit[{}]".format(dt, desc, credit, debit))
            if credit is not None and credit != "":
                amount = float(credit.replace(",", ""))
            elif debit is not None and debit != "":
                amount = -float(debit.replace(",", ""))
            else:
                continue
            new_balance += amount
            self.statement['entries'].append({
                'account': self.account,
                'post_date': dt,
                'transaction_date': dt,
                'description': desc,
                'currency': "HKD",
                'amount': amount
            })
            desc = ""
        self.statement['new_balance'][self.account]['HKD'] = new_balance
        logger.debug(self.statement)


class TableZoneFcy(TableZone):

    def clean_table(self):
        shape = self.table.shape
        logger.debug(shape)
        logger.debug('table shape: {}'.format(self.table.shape))

        dt = ""
        ccy = ""
        desc = ""
        new_balance = 0.
        for index, row in self.table.iterrows():
            # first line with new currency is previous balance
            if row[0] != ccy and row[0] != "":
                if ccy != "":
                    # record new balance of currently parsing account before moving to next
                    self.statement['new_balance'][self.account][ccy] = new_balance
                    new_balance = 0.
                ccy = row[0]
                if row[5] != "":
                    # When this is the first movement on a currency there is no previous balance
                    previous_balance_tag = row[2]
                    previous_balance = float(row[5].replace(",", ""))
                    if row[6] == 'DR':
                        previous_balance = -previous_balance
                    if previous_balance_tag != "B/F BALANCE":
                        raise TemplateException(
                            "First line should contain B/F BALANCE vs [{}]".format(previous_balance_tag))
                    self.statement['previous_balance'][self.account][ccy] = previous_balance
                    new_balance = previous_balance


            if row[1] != "": dt = self.extract_date(row[1])
            desc = (desc + " " if desc != "" else "") + row[2]
            credit = row[3]
            debit = row[4]
            amount = None

            logger.debug("ccy[{}] date[{}] desc[{}] credit[{}] debit[{}]".format(ccy, dt, desc, credit, debit))
            if credit is not None and credit != "":
                amount = float(credit.replace(",", ""))
            elif debit is not None and debit != "":
                amount = -float(debit.replace(",", ""))
            else:
                if desc == "B/F BALANCE":
                    desc = ""
                continue

            new_balance += amount
            self.statement['entries'].append({
                'post_date': dt,
                'transaction_date': dt,
                'account': self.account,
                'description': desc,
                'currency': ccy,
                'amount': amount
            })
            desc = ""
        self.statement['new_balance'][self.account][ccy] = new_balance
        logger.debug(self.statement)


class TableZoneSum(TableZone):
    map_type = {
        EnumSumAccountTypes.HKDSAVINGS: AccountTypes.HKDSAVINGS,
        EnumSumAccountTypes.HKDCURRENT: AccountTypes.HKDCURRENT,
        EnumSumAccountTypes.FCYSAVINGS: AccountTypes.FCYSAVINGS,
        EnumSumAccountTypes.FCYCURRENT: AccountTypes.FCYCURRENT
    }

    def __init__(self, page_height, page_width, section, account, st_date):
        super().__init__(page_height, page_width, section, account, st_date)
        self.summary = {'total_balance_hkd': None, 'new_acc_balances': {}}

    def extract_amount(self, stramount, dr):
        logger.debug("string to  convert to float:[{}]".format(stramount))
        amount = stramount if isinstance(stramount, float) else float(stramount.replace(",", ""))
        if dr == 'DR':
            amount = - amount
        return amount

    def clean_table(self):
        shape = self.table.shape
        logger.debug(shape)

        acc_bal = self.summary['new_acc_balances']
        logger.debug('table shape: {}'.format(self.table.shape))

        acc = ""
        total = 0.
        expected_total = .0
        # skip first 2 lines that are header part and account narrative
        for index, row in self.table[2:].iterrows():
            logger.debug("process row ({}): <{}>".format(index, row))
            if row[0] is not None and row[0] != "":
                if row[0] == 'Total':
                    self.summary['total_balance_hkd'] = self.extract_amount(row[6], row[7])
                    continue
                elif row[0] not in TableZoneSum.map_type.keys():
                    raise TemplateException("Summary contains an unknow Account type [{}]".format(row[0]))
                else:
                    acc = TableZoneSum.map_type[row[0]]

            ccy = row[2]
            amount = self.extract_amount(row[4], row[5])
            amounthkd = self.extract_amount(row[6], row[7])

            logger.debug("account[{}] ccy[{}] balance[{}] balancehkd[{}]".format(acc, ccy, amount, amounthkd))
            expected_total += amounthkd
            if acc not in acc_bal.keys():
                acc_bal[acc] = {ccy: {'ccy': amount, 'hkd':amounthkd} }
            else:
                acc_bal[acc][ccy] = {'ccy': amount, 'hkd':amounthkd}

        logger.debug("Statement summary: {}".format(self.summary))

    def check_consistency(self, summary):
        # self.summary = {'total_balance_hkd': None, 'new_acc_balances': {}}
        total = self.summary['total_balance_hkd']
        new_bal = self.summary['new_acc_balances']
        amount = 0.
        for v in new_bal.values():
            for vccy in v.values():
                amount += vccy['hkd']

        if round(amount, 2) != round(total, 2):
            raise ConsistencyException("Mismatching Summary balance on {}/{}".format(round(amount, 2), round(total, 2)))

class BaseFactory:

    _scrapers = []

    @classmethod
    def get_scraper(cls, pdfpath, pdf=None):
        if not os.path.exists(pdfpath):
            raise ScraperException(f'"{pdfpath}" file not found')
        if not os.path.isfile(pdfpath):
            raise ScraperException(f'"{pdfpath}" not a file')
        pdf = pdfquery.PDFQuery(pdfpath)
        pdf.load()

        for s in cls._scrapers:
            if s.probe_bank(pdf) and s.probe_type(pdf):
                logger.debug("pdf file matches {}.{}".format(s.st_bank, s.st_type))
                return s(pdfpath, pdf)


class BaseStatement:

    _BANK_SIGNATURE = []
    _TYPE_SIGNATURE = []

    st_bank = None
    st_type = None

    @classmethod
    def probe_bank(cls, pdf):
        for elem in cls._BANK_SIGNATURE:
            if len(elem.querys(pdf)) == 0:
                logger.debug("pdf file does not matches bank {}".format(cls.st_bank))
                return False
        logger.debug("pdf file matches bank {}".format(cls.st_bank))
        return True

    @classmethod
    def probe_type(cls, pdf):
        for elem in cls._TYPE_SIGNATURE:
            if len(elem.querys(pdf)) == 0:
                logger.debug("pdf file does not matches type {}".format(cls.st_type))
                return False
        logger.debug("pdf file matches type {}".format(cls.st_type))
        return True

    def __init__(self, pdfpath, pdf = None):
        self.logger = logging.getLogger("hsbcpdf.helpers.basestatement")
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
        self.logger.debug("page format: WxH = {}x{}".format(
            self.page_width,
            self.page_height
        ))

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
