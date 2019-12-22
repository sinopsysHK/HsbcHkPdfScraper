import logging

import pdfquery
import pdfminer

logger = logging.getLogger('hsbcpdf.helpers.utils')

# -----------------------------------------------------------------------------
# Exceptions
class ScraperException(Exception):
    pass


class UnrecognizedException(ScraperException):
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

    def query(self, pdf, page=None):
        pass


class TextBox(PdfComponent):
    __doc__ = "query for text in specific area given by bbox"

    def __init__(self, bbox, page=None, bellow=None, above=None):
        self.page = page
        self.bbox = bbox
        if isinstance(bbox, str):
            self.bbox = Bbox()
            self.bbox.xleft, self.bbox.ybot, self.bbox.xright, self.bbox.ytop = map(int, bbox.split(','))
        self.bellow = bellow
        self.above = above

    def query(self, pdf, page=None):
        if self.above:
            above = self.above.query(pdf).yup if self.above else self.bbox.ybot
            self.bbox.ybot = above - 3
        if self.bellow:
            bellow = self.bellow.query(pdf).ybot if self.bellow else self.bbox.ytop
            self.bbox.ytop = bellow + 3

        q = ""
        if self.page is not None:
            q = f'LTPage[page_index="{self.page - 1 }"] '
        q += f'LTTextLineHorizontal:in_bbox("{self.bbox.to_pdfq_bbox()}")'
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

    def querys(self, pdf, after=None, before=None, page=None):
        res = pdf.pq(f'LTTextLineHorizontal:contains("{self.text}")')
        if self.height is not None:
            res = res.filter(lambda i: self.height + 1 > float(this.get('height', 0)) > self.height - 1)
        res = [Section(s) for s in res]
        if before is not None:
            res = [s for s in res if s < before]
        if after is not None:
            res = [s for s in res if s > after]
        return res

    def query(self, pdf, after=None, before=None, page=None):
        res = self.querys(pdf, after, before, page)
        if len(res) > 1 and not self.first:
            raise TemplateException(f'Several ({len(res)} occurence found of "{self.text}"')
        if len(res) == 0:
            logger.debug(f'no section found for text "{self.text}"' + f' with given height' if self.height is not None else '')
            return None
        return res[0]


class HLine(PdfComponent):
    __doc__ = "Locate a section defined from a horizontal Line"

    def __init__(self, xleft, xright, hmin=None, hmax=None, wmin=None, wmax=None, first=False):
        self.xleft = xleft
        self.xright = xright
        self.hmin = hmin
        self.hmax = hmax
        self.wmin = wmin
        self.wmax = wmax
        self.first = first

    def querys(self, pdf, after=None, before=None, page=None):
        res = pdf.pq(
            f'LTLine:in_bbox("{self.xleft}, 0, {self.xright}, {pdf.get_layout(0).height}")'
        ).filter(lambda i:
                               (self.hmin is None or float(this.get('height')) > self.hmin)
                               and (self.hmax is None or float(this.get('height')) < self.hmax)
                               and (self.wmin is None or float(this.get('width')) > self.wmin)
                               and (self.wmax is None or float(this.get('width')) < self.wmax)
                 )
        res += pdf.pq(
            (f'LTPage[page_index="{page-1}"] ' if page else '') \
            + f'LTRect:in_bbox("{self.xleft}, 0, {self.xright}, {pdf.get_layout(0).height}")'
        ).filter(lambda i:
                               (self.hmin is None or float(this.get('height')) > self.hmin)
                               and (self.hmax is None or float(this.get('height')) < self.hmax)
                               and (self.wmin is None or float(this.get('width')) > self.wmin)
                               and (self.wmax is None or float(this.get('width')) < self.wmax)
                 )

        res = [Section(s) for s in res]
        if before is not None:
            res = [s for s in res if s < before]
        if after is not None:
            res = [s for s in res if s > after]
        return res

    def query(self, pdf, after=None, before=None, page=None):
        res = self.querys(pdf, after, before, page)
        if len(res) > 1 and not self.first:
            for r in res:
                logger.debug("line p{}: {}".format(r.page, r.obj.layout.bbox))
            raise TemplateException(f'Several ({len(res)} lines matching')
        if len(res) == 0:
            logger.debug(f'no section found for line')
            return None
        return res[0]


class VLine(PdfComponent):
    __doc__ = "Locate a section defined from a horizontal Line"

    def __init__(self, yup, ybot, hmin=None, hmax=None, wmin=None, wmax=None, first=False):
        self.yup = yup
        self.ybot = ybot
        self.hmin = hmin
        self.hmax = hmax
        self.wmin = wmin
        self.wmax = wmax
        self.first = first

    def querys(self, pdf, after=None, before=None, page=None):
        res = pdf.pq(
            f'LTLine:in_bbox("0, {self.ybot}, {pdf.get_layout(0).width}, {self.yup} ")'
        ).filter(lambda i:
                               (self.hmin is None or float(this.get('height')) > self.hmin)
                               and (self.hmax is None or float(this.get('height')) < self.hmax)
                               and (self.wmin is None or float(this.get('width')) > self.wmin)
                               and (self.wmax is None or float(this.get('width')) < self.wmax)
                 )
        res += pdf.pq(
            (f'LTPage[page_index="{page-1}"] ' if page else '') \
            + f'LTRect:in_bbox("0, {self.ybot}, {pdf.get_layout(0).width}, {self.yup} ")'
        ).filter(lambda i:
                               (self.hmin is None or float(this.get('height')) > self.hmin)
                               and (self.hmax is None or float(this.get('height')) < self.hmax)
                               and (self.wmin is None or float(this.get('width')) > self.wmin)
                               and (self.wmax is None or float(this.get('width')) < self.wmax)
                 )

        return res

    def query(self, pdf, after=None, before=None, page=None):
        res = self.querys(pdf, after, before, page)
        if len(res) > 1 and not self.first:
            for r in res:
                logger.debug("line p{}: {}".format(r.page, r.obj.layout.bbox))
            raise TemplateException(f'Several ({len(res)} lines matching')
        if len(res) == 0:
            logger.debug(f'no section found for line')
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
    def __init__(self, xleft=None, xright=None, ybot=None, ytop=None, orig=None):
        if orig:
            self.xleft = orig.xleft
            self.xright = orig.xright
            self.ybot = orig.ybot
            self.ytop = orig.ytop
        if xleft:
            self.xleft = xleft
        if xright:
            self.xright = xright
        if ybot:
            self.ybot = ybot
        if ytop:
            self.ytop = ytop

    def to_camellot_bbox(self):
        return "{},{},{},{}".format(self.xleft, self.ytop, self.xright, self.ybot)

    # "420,765,568,782"
    def to_pdfq_bbox(self):
        return "{},{},{},{}".format(self.xleft, self.ybot, self.xright, self.ytop)

    def __repr__(self):
        return "[({},{}),({},{})]".format(self.xleft, self.ybot, self.xright, self.ytop)