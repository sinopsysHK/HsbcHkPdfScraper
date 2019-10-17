import logging
import json

from hsbcpdf import scraper

logging.basicConfig(level=logging.WARNING)
logging.getLogger('hsbcpdf').setLevel(logging.DEBUG)

st = scraper.get_statement('mystatement.pdf')

js = st.get_json()
df = st.get_df()

print("Statement JSON: \n%s" % str(json.dumps(js, indent=2)))