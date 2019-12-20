import logging

import pdfquery
import pdfminer

logger = logging.getLogger('hsbcpdf.helpers.utils')

# -----------------------------------------------------------------------------
# Exceptions
class ScraperException(Exception):
    pass


class TemplateException(ScraperException):
    pass


class ConsistencyException(ScraperException):
    pass

# -----------------------------------------------------------------------------
# PdfQuery helpers


def get_page(obj):
    if isinstance(obj.layout, pdfminer.layout.LTPage):
          return obj.layout.pageid
    else:
          return get_page(obj.getparent())


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
        elif len(res) == 0:
            raise TemplateException(f'No text boxes in "{self.bbox}"" place holder')
        logger.debug(res)
        return res[0].layout.get_text().strip()


class TextLabel(PdfComponent):
    __doc__ = "Locate a section defined from a text label"

    def __init__(self, text, height = None, first=False):
        self.text = text
        self.height = height
        self.first = first

    def querys(self, pdf, after=None, before=None):
        res = pdf.pq(f'LTTextLineHorizontal:contains("{self.text}")')
        if self.height is not None:
            res = res.filter(lambda i: self.height + 1 > float(this.get('height', 0)) > self.height - 1)
        res = [Section(s) for s in res]
        if before is not None:
            res = [s for s in res if s < before]
        if after is not None:
            res = [s for s in res if s > after]
        return res

    def query(self, pdf, after=None, before=None):
        res = self.querys(pdf, after, before)
        if len(res) > 1 and not self.first:
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


class Bbox:
    def __init__(self, xleft, xright, ybot, ytop):
        self.xleft = xleft
        self.xright = xright
        self.ybot = ybot
        self.ytop = ytop

    def to_camellot_bbox(self):
        return "{},{},{},{}".format(self.xleft, self.ytop, self.xright, self.ybot)
