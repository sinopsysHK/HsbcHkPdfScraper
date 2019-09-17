#-------------------------------------------------------------------------------------------
# PDF HSBC Account statement (Hong Kong) Scraper
#-------------------------------------------------------------------------------------------
from pdfquery.cache import FileCache
import pdfquery
import pdfminer
import camelot
import sys
import logging
import pandas as pd
import datetime
import json

logger = logging.getLogger("hsbcstatement")


class ScraperException(Exception):
    pass

class TemplateException(ScraperException):
    pass

class ConsistencyException(ScraperException):
    pass


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


class PdfComponent:
    __doc__ = "Generic query holder"
    def __init__(self):
        pass

    def query(self, pdf):
        pass

class TextBox(PdfComponent):
    __doc__ = "query for text in specific area given by bbox"

    def __init__(self, bbox, page=None):
        self.page = page
        self.bbox = bbox

    def query(self, pdf):
        q = ""
        if self.page is not None:
            q = f'LTPage[page_index="{self.page - 1 }"] '
        q += f'LTTextLineHorizontal:in_bbox("{self.bbox}")'
        res = pdf.pq(q)
        if len(res) > 1:
            for v in res:
                logger.debug(v.layout)
            raise TemplateException(f'Several ({len(res)}) text boxes in "{self.bbox}"" place holder')
        return res[0].layout.get_text().strip()

class TextLabel(PdfComponent):
    __doc__ = "Locate a section defined from a text label"

    def __init__(self, text, height = None):
        self.text = text
        self.height = height

    def query(self, pdf, after=None, before=None):
        res = pdf.pq(f'LTTextLineHorizontal:contains("{self.text}")')
        if self.height is not None:
            res = res.filter(lambda i: self.height + 1 > float(this.get('height', 0)) > self.height - 1)
        res = [Section(s) for s in res]
        if before is not None:
            res = [s for s in res if s < before]
        if after is not None:
            res = [s for s in res if s > after]
        if len(res) > 1:
            raise TemplateException(f'Several ({len(res)} occurence found of "{self.text}"')
        if len(res) == 0:
            logger.debug(f'no section found for text "{self.text}"' + f' with given height' if self.height is not None else '')
            return None
        return res[0]

class Section:
    def __init__(self, obj):
        self.obj = obj
        self.page = get_page(obj)
        self.yup = obj.layout.y1
        self.ybot = obj.layout.y0
        self.next = None
        self.table_areas = None

    def __ge__(self, other):
        return self.page > other.page \
               or (
                       self.page == other.page
                       and (self.ybot + ((self.yup - self.ybot)/2)) <= (other.ybot + ((other.yup - other.ybot)/2))
               )

    def __gt__(self, other):
        return self.page > other.page \
               or (
                       self.page == other.page
                       and (self.ybot + ((self.yup - self.ybot)/2)) < (other.ybot + ((other.yup - other.ybot)/2))
               )

    def get_next(self, others):
        for s in others:
            if s <= self:
                continue
            elif self.next is None:
                self.next = s
            elif s < self.next:
                self.next = s
        return self.next

    def __str__(self):
        return f'<page[{self.page}] {self.yup} <-> {self.ybot}' + (f' - page[{self.next.page}] {self.next.yup} <-> {self.next.ybot}>' if self.next is not None else '>')

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
                        columns=[cols])
            logger.debug('found tables: {} - {}'.format(tables[0].parsing_report, tables[0].shape))
            if self.table is None:
                self.table = tables[0].df[1:]
            else:
                self.table = pd.concat([self.table, tables[0].df[1:]])
        logger.debug("the table:\n{}".format(self.table.head()))
        self.clean_table()

    def clean_table(self):
        pass

    def extract_date(self, strdt):
        return datetime.datetime.strptime(strdt + ' ' + str(self.st_date.year), '%d %b %Y')

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
        previous_balance_tag = self.table.iloc[0,1]
        val = self.table.iloc[0, 4]
        logger.debug("value to use as a float: [{}]".format(val))
        previous_balance = float(val.replace(",", "")) if isinstance(val, str) else val
        if previous_balance_tag != "B/F BALANCE":
            raise TemplateException("First line should contain B/F BALANCE vs [{}]".format(previous_balance_tag))
        self.statement['previous_balance'][self.account]['HKD'] = previous_balance

        dt = ""
        desc = ""
        new_balance = previous_balance
        for index, row in self.table.iloc[1:, :].iterrows():
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
                'date': dt.strftime("%d/%m/%Y"),
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
                continue

            new_balance += amount
            self.statement['entries'].append({
                'date': dt.strftime("%d/%m/%Y"),
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



class Statement:

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

    def __init__(self, pdfpath):
        self.pdfpath = pdfpath
        self.pdf = pdfquery.PDFQuery(pdfpath)
        self.pdf.load()

        self.page_height = None
        self.page_width = None
        self.account_number = None
        self.st_date = None
        self.ptfsum_zone = None
        self.zones = {}

    def match_template(self):

        # get file pages format
        p = self.pdf.pq('LTPage[page_index="0"]')[0]
        self.page_height = p.layout.height
        self.page_width = p.layout.width

        # get statement related account number
        self.account_number = Statement.ph_acc_number.query(self.pdf)

        #get statement date
        strdate = Statement.ph_st_date.query(self.pdf)
        logger.info("process statement of {} on {}".format(self.account_number, strdate))
        self.st_date = datetime.datetime.strptime(strdate, '%d %B %Y')

        # get structuring sections
        ptfsum_section = Statement.ph_ptfsum_section.query(self.pdf)
        if ptfsum_section is None:
            raise TemplateException(f'Portfolio summary section "{Statement.ph_ptfsum_section.text}" not found in statement')

        top_section = Statement.ph_top_section.query(self.pdf)
        if top_section is None:
            raise TemplateException(f'Top section "{Statement.ph_top_section.text}" not found in statement')

        end_section = Statement.ph_end_section.query(self.pdf)
        if end_section is None:
            raise TemplateException(f'End section "{Statement.ph_end_section.text}" not found in statement')
        if end_section.yup > 679:
            # if end section is top of page force it as bottom of previous page
            end_section.page = end_section.page - 1
            end_section.yup = 69
            end_section.ybot = 69

        sections = {}
        available_sections = [end_section]
        for k,v in Statement.ph_sections.items():
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
            self.zones[k] = Statement.zone_types[k](self.page_height, self.page_width, v, k, self.st_date)
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
        self.statement = {
            'main_account': self.account_number,
            'statement_date': self.st_date.strftime('%d/%m/%Y'),
            'previous_balance': {},
            'entries': []
        }
        for v in self.zones.values():
            for k in v.statement['previous_balance'].keys():
                self.statement['previous_balance'][k] = v.statement['previous_balance'][k]
            self.statement['entries'] = self.statement['entries'] + v.statement['entries']

    def process(self):
        self.match_template()
        self.extract_tables()
        self.check_consistency()
        self.merge_all()

    def get_df(self):
        df = pd.DataFrame(self.statement['entries'])
        df['st_date'] = self.st_date.strftime("%d/%m/%Y")
        df['main_account'] = self.account_number
        df['file_path'] = self.pdfpath
        return df

    def get_json(self):
        return json.dumps(self.statement)

def get_page(obj):
    if isinstance(obj.layout, pdfminer.layout.LTPage):
          return obj.layout.pageid
    else:
          return get_page(obj.getparent())

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)

    pdfpath = sys.argv[1]
    outputdir = sys.argv[2] if len(sys.argv) > 2 else ".\\outputs\\"
    st = Statement(sys.argv[1])
    st.process()
    df = st.get_df()
    logger.debug(df.head())
    df.to_csv(outputdir + st.account_number + "-" + st.st_date.strftime("%Y%m") + ".csv", index=False)
