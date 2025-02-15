import logging
import json

from hsbcpdf.scraper import ScraperFactory

logging.basicConfig(level=logging.WARNING)
logging.getLogger('hsbcpdf').setLevel(logging.DEBUG)

#st = ScraperFactory.get_scraper('/mnt/share/hk/bank/SG/releves/woob/error/0382700010264536_-NdjGzLL9o0vYoXfso7MyrFJP1Q=.pdf').process()
st = ScraperFactory.get_scraper('/mnt/share/hk/bank/SG/releves/scanned/releve_00015787140_20150401.pdf').process()

js = st.get_json()
df = st.get_df()

print("Statement JSON: \n%s" % str(json.dumps(js, indent=2)))
