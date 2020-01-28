import logging
import json

from hsbcpdf.scraper import ScraperFactory

logging.basicConfig(level=logging.WARNING)
logging.getLogger('hsbcpdf').setLevel(logging.DEBUG)

st = ScraperFactory.get_scraper('mysgstatement9.pdf').process()

js = st.get_json()
df = st.get_df()

print("Statement JSON: \n%s" % str(json.dumps(js, indent=2)))